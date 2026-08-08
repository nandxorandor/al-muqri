/* Al-Muqri on-device engine logic (ported from app.py, verified vs Python).
   Handles: CTC decode of phoneme logits, edit-ops diff, per-word judging.
   Model inference (onnxruntime-web) is wired separately in index.html. */
(function (global) {
  "use strict";

  const HARAKAT = new Set("ًٌٍَُِّْٰ".split(""));
  const MADD    = new Set("اۦۥيو".split(""));
  const PASS_RATE = 0.34;

  let VOCAB = null;                 // id -> phoneme symbol
  function setVocab(v) { VOCAB = v; }

  // Map already-CTC-collapsed phoneme ids (from the native runtime) to symbols.
  function phonemesFromIds(ids) {
    let out = "";
    for (const id of ids) out += (VOCAB && VOCAB[id]) ? VOCAB[id] : "";
    return out;
  }

  // CTC decode: argmax per frame -> collapse repeats -> drop blank(0) -> symbols
  function decodePhonemes(logits, frames, classes) {
    // logits: Float32Array length frames*classes (row-major)
    let out = "", prev = 0;
    for (let t = 0; t < frames; t++) {
      let best = 0, bestv = -Infinity, base = t * classes;
      for (let c = 0; c < classes; c++) {
        const v = logits[base + c];
        if (v > bestv) { bestv = v; best = c; }
      }
      if (best === 0) { prev = 0; continue; }   // blank
      if (best === prev) continue;              // collapse consecutive
      out += VOCAB ? VOCAB[best] : "";
      prev = best;
    }
    return out;
  }

  // Levenshtein edit ops (match/replace/delete/insert), same backtrace as Python
  function editOps(a, b) {
    const n = a.length, m = b.length;
    const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
    for (let i = 0; i <= n; i++) dp[i][0] = i;
    for (let j = 0; j <= m; j++) dp[0][j] = j;
    for (let i = 1; i <= n; i++) {
      const ai = a[i - 1];
      for (let j = 1; j <= m; j++) {
        dp[i][j] = ai === b[j - 1] ? dp[i - 1][j - 1]
          : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
      }
    }
    const ops = []; let i = n, j = m;
    while (i > 0 || j > 0) {
      if (i > 0 && j > 0 && a[i - 1] === b[j - 1] && dp[i][j] === dp[i - 1][j - 1]) {
        ops.push(["match", i - 1, j - 1]); i--; j--;
      } else if (i > 0 && j > 0 && dp[i][j] === dp[i - 1][j - 1] + 1) {
        ops.push(["replace", i - 1, j - 1]); i--; j--;
      } else if (i > 0 && dp[i][j] === dp[i - 1][j] + 1) {
        ops.push(["delete", i - 1, j]); i--;
      } else {
        ops.push(["insert", i, j - 1]); j--;
      }
    }
    ops.reverse();
    return ops;
  }

  function ownersOf(spans, pos) {
    const out = [];
    for (let i = 0; i < spans.length; i++) {
      const a = spans[i][0], b = spans[i][1];
      if (a <= pos && pos < b) {
        out.push(i);
        if (pos === a && i > 0) out.unshift(i - 1);
        return out;
      }
    }
    return out; // (fallback owner omitted; matches when spans are contiguous)
  }

  // Judge a selection [wFrom..wTo] of one ayah. Mirrors app.py /selection.
  //   phonemes: full ayah phoneme string;  spans: [[a,b],...] per word
  //   heard: decoded phoneme string of the recitation
  function judgeSelection(phonemes, spans, heard, wFrom, wTo) {
    wFrom = Math.max(0, Math.min(wFrom, spans.length - 1));
    wTo   = Math.max(wFrom, Math.min(wTo, spans.length - 1));
    const a = spans[wFrom][0], b = spans[wTo][1];
    const target = phonemes.slice(a, b);
    const ops = editOps(target, heard);
    const tally = {};
    for (const [op, ii, jj] of ops) {
      const pos = a + ii;
      for (const w of ownersOf(spans, pos)) {
        if (w < wFrom || w > wTo) continue;
        const t = tally[w] || (tally[w] = { ok: 0, bad: 0, exp: "", got: "", vowel: false, madd: 0 });
        if (op === "match") { t.ok++; }
        else {
          t.bad++;
          const e = ii < target.length ? target[ii] : "";
          const g = jj < heard.length ? heard[jj] : "";
          if (e) t.exp += e;
          if (g) t.got += g;
          if (op === "replace" && (HARAKAT.has(e) || HARAKAT.has(g))) t.vowel = true;
          if ((op === "delete" || op === "insert") && (MADD.has(e) || MADD.has(g))) t.madd++;
        }
      }
    }
    const results = [];
    for (let w = wFrom; w <= wTo; w++) {
      const t = tally[w];
      if (!t || (t.ok + t.bad) < 2) { results.push({ word_idx: w, status: "unknown" }); continue; }
      const rate = t.bad / (t.ok + t.bad);
      const bad = rate > PASS_RATE || t.vowel || t.madd >= 1;
      let k = "ok";
      if (bad) k = rate > PASS_RATE ? "shape" : (t.vowel ? "vowel" : "madd");
      results.push({ word_idx: w, status: bad ? "bad" : "good", kind: k,
                     expected: t.exp.slice(0, 14), heard: t.got.slice(0, 14) });
    }
    return results;
  }

  // Live (continuous) judging: align a phrase's heard phonemes to the page's
  // concatenated target starting at `fromPos`, judge only the words the
  // alignment fully passed, and report how far we consumed so the next phrase
  // resumes there. `spans` are page-absolute [a,b] per word.
  function judgeLive(phon, spans, heard, fromPos) {
    const slack = 12;
    const to = Math.min(phon.length, fromPos + heard.length + slack);
    const target = phon.slice(fromPos, to);
    const ops = editOps(target, heard);
    let lastMatchAbs = fromPos;
    const tally = {};
    for (const [op, ii, jj] of ops) {
      const pos = fromPos + ii;
      if (op === "match") lastMatchAbs = Math.max(lastMatchAbs, pos + 1);
      for (const w of ownersOf(spans, pos)) {
        const t = tally[w] || (tally[w] = { ok: 0, bad: 0, exp: "", got: "", vowel: false, madd: 0 });
        if (op === "match") { t.ok++; }
        else {
          t.bad++;
          const e = ii < target.length ? target[ii] : "";
          const g = jj < heard.length ? heard[jj] : "";
          if (e) t.exp += e;
          if (g) t.got += g;
          if (op === "replace" && (HARAKAT.has(e) || HARAKAT.has(g))) t.vowel = true;
          if ((op === "delete" || op === "insert") && (MADD.has(e) || MADD.has(g))) t.madd++;
        }
      }
    }
    const results = [];
    let consumed = fromPos;
    for (let w = 0; w < spans.length; w++) {
      const a = spans[w][0], b = spans[w][1];
      if (b > lastMatchAbs) break;      // alignment hasn't reached this word yet
      if (a < fromPos) continue;        // judged in an earlier phrase
      const t = tally[w];
      if (!t || (t.ok + t.bad) < 2) { consumed = b; continue; }
      const rate = t.bad / (t.ok + t.bad);
      const bad = rate > PASS_RATE || t.vowel || t.madd >= 1;
      let k = "ok";
      if (bad) k = rate > PASS_RATE ? "shape" : (t.vowel ? "vowel" : "madd");
      results.push({ word: w, status: bad ? "bad" : "good", kind: k,
                     expected: t.exp.slice(0, 14), heard: t.got.slice(0, 14) });
      consumed = b;
    }
    return { results, consumed };
  }

  // Placement judging (free "read anywhere" live mode): align the heard phrase
  // to the BEST-matching region anywhere in the page's concatenated target
  // (semi-global: leading/trailing target is free), then judge the words that
  // region covers. Mirrors the PC behaviour where you can recite any part.
  function judgePlacement(phon, spans, heard) {
    const n = phon.length, m = heard.length;
    if (!m || !n) return { results: [], start: -1, end: -1 };
    const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
    const bt = Array.from({ length: n + 1 }, () => new Uint8Array(m + 1)); // 0 diag,1 del-target,2 ins-heard
    for (let i = 0; i <= n; i++) dp[i][0] = 0;          // may start anywhere for free
    for (let j = 1; j <= m; j++) { dp[0][j] = j; bt[0][j] = 2; }
    for (let i = 1; i <= n; i++) {
      const pi = phon[i - 1];
      for (let j = 1; j <= m; j++) {
        let best = dp[i - 1][j - 1] + (pi === heard[j - 1] ? 0 : 1), b = 0;
        const cu = dp[i - 1][j] + 1; if (cu < best) { best = cu; b = 1; }
        const cl = dp[i][j - 1] + 1; if (cl < best) { best = cl; b = 2; }
        dp[i][j] = best; bt[i][j] = b;
      }
    }
    let iEnd = 0, bestc = Infinity;
    for (let i = 0; i <= n; i++) if (dp[i][m] < bestc) { bestc = dp[i][m]; iEnd = i; }
    let i = iEnd, j = m; const ops = [];
    while (j > 0) {
      const b = bt[i][j];
      if (b === 0) { ops.push([pheq(phon, heard, i, j) ? "match" : "replace", i - 1, j - 1]); i--; j--; }
      else if (b === 1) { ops.push(["delete", i - 1, j]); i--; }
      else { ops.push(["insert", i, j - 1]); j--; }
    }
    ops.reverse();
    const start = i;
    const tally = {};
    for (const [op, ii, jj] of ops) {
      for (const w of ownersOf(spans, ii)) {
        const t = tally[w] || (tally[w] = { ok: 0, bad: 0, exp: "", got: "", vowel: false, madd: 0 });
        if (op === "match") { t.ok++; }
        else {
          t.bad++;
          const e = ii < phon.length ? phon[ii] : "";
          const g = jj < heard.length ? heard[jj] : "";
          if (e) t.exp += e;
          if (g) t.got += g;
          if (op === "replace" && (HARAKAT.has(e) || HARAKAT.has(g))) t.vowel = true;
          if ((op === "delete" || op === "insert") && (MADD.has(e) || MADD.has(g))) t.madd++;
        }
      }
    }
    const results = [];
    for (let w = 0; w < spans.length; w++) {
      const a = spans[w][0], b = spans[w][1];
      if (b <= start || a >= iEnd) continue;      // word not in the recited region
      const t = tally[w];
      if (!t || (t.ok + t.bad) < 2) continue;
      const rate = t.bad / (t.ok + t.bad);
      const bad = rate > PASS_RATE || t.vowel || t.madd >= 1;
      let k = "ok";
      if (bad) k = rate > PASS_RATE ? "shape" : (t.vowel ? "vowel" : "madd");
      results.push({ word: w, status: bad ? "bad" : "good", kind: k,
                     expected: t.exp.slice(0, 14), heard: t.got.slice(0, 14) });
    }
    return { results, start, end: iEnd };
  }
  function pheq(phon, heard, i, j) { return phon[i - 1] === heard[j - 1]; }

  global.MuqriEngine = { setVocab, decodePhonemes, phonemesFromIds, editOps, ownersOf, judgeSelection, judgeLive, judgePlacement, PASS_RATE };
})(window);
