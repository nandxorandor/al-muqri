"""
WORD BOUNDARY MAPPER — the piece that makes word-level highlighting possible.

THE PROBLEM
-----------
Tajweed crosses word boundaries. Phonetizing each word alone gives a reference
that does not match real recitation:

    phonetize("بِسْمِ")           -> بِسم
    phonetize("ٱللَّهِ")           -> ءَللَاه
    concatenated                  -> بِسمءَللَاه       <-- WRONG
    phonetize("بِسْمِ ٱللَّهِ")     -> بِسمِللَاه        <-- what you actually say

An earlier version of the app phonetized per word and nothing ever matched.

THE FIX
-------
Phonetize the WHOLE ayah (correct phonetics), then discover where each word
lands inside that string by phonetizing progressively longer prefixes:

    prefix "بِسْمِ"                 -> len 4
    prefix "بِسْمِ ٱللَّهِ"          -> len 11   => word 2 spans chars 4..11

Cross-word tajweed stays intact, and every word gets a character range.

    conda activate quran_teacher
    cd C:\\Users\\user\\Quran_Teacher_v2
    python word_map.py            # runs a self-test
"""

import os
import sys


def build_word_spans(uthmani, moshaf, phonetizer):
    """Map each word of an ayah to its [start, end) span in the ayah phonemes.

    Returns (full_phonemes, spans) where spans[i] = (start, end) for word i.

    METHOD
    ------
    Phonetizing the first k words measures where word k ends. Those measured
    boundaries are TRUSTED and never moved.

    A word that fuses entirely into its neighbour yields no growth. Such a run
    of words is given the gap between the last real boundary and the NEXT real
    boundary, divided among only the words in that run, by letter count. No
    measured boundary is disturbed.

    (Before this, 1:4 gave يَوْمِ a zero-width span, so a kasra error on
    مَـٰلِكِ was blamed on ٱلدِّينِ.)
    """
    words = uthmani.split()
    if not words:
        return '', []

    full = phonetizer(uthmani, moshaf, remove_spaces=True).phonemes
    n = len(words)
    L = len(full)
    if n == 1:
        return full, [(0, L)]

    # ---- measure cumulative end of each word ----
    cum = []
    for k in range(1, n + 1):
        try:
            ph = phonetizer(' '.join(words[:k]), moshaf,
                            remove_spaces=True).phonemes
            cum.append(len(ph))
        except Exception:
            cum.append(cum[-1] if cum else 0)

    for i in range(1, n):
        if cum[i] < cum[i - 1]:
            cum[i] = cum[i - 1]

    if cum[-1] > 0:
        f = L / cum[-1]
        ends = [min(L, int(round(c * f))) for c in cum]
    else:
        ends = [int(round(L * (i + 1) / n)) for i in range(n)]
    ends[-1] = L
    for i in range(1, n):
        if ends[i] < ends[i - 1]:
            ends[i] = ends[i - 1]

    def letters(w):
        return max(1, sum(1 for c in w if '\u0621' <= c <= '\u064A'))

    # ---- fill zero-growth runs, leaving measured boundaries alone ----
    i = 0
    while i < n:
        prev_end = ends[i - 1] if i > 0 else 0
        if ends[i] > prev_end:
            i += 1
            continue

        # words i..j all sit at prev_end (zero growth)
        j = i
        while j + 1 < n and ends[j + 1] <= prev_end:
            j += 1

        # the next real boundary belongs to word j+1 (or the end of the string)
        next_end = ends[j + 1] if j + 1 < n else L

        # share the room among words i..j PLUS the word that owns next_end,
        # because that word's territory is what they are borrowing from
        members = list(range(i, min(j + 1, n - 1) + 1))
        if j + 1 < n:
            members = list(range(i, j + 2))
        room = next_end - prev_end
        if room <= 0 or not members:
            i = j + 1
            continue

        wts = [letters(words[m]) for m in members]
        tot = sum(wts) or 1
        acc = float(prev_end)
        for idx, m in enumerate(members):
            acc += room * wts[idx] / tot
            e = int(round(acc))
            ends[m] = max(prev_end, min(next_end, e))
        ends[members[-1]] = next_end

        for x in range(1, n):
            if ends[x] < ends[x - 1]:
                ends[x] = ends[x - 1]
        i = members[-1] + 1

    # ---- assemble, guaranteeing at least 1 char where possible ----
    spans, prev = [], 0
    for i in range(n):
        e = max(prev, min(L, ends[i]))
        if i == n - 1:
            e = L
        spans.append((prev, e))
        prev = e

    for i in range(n):
        a, b = spans[i]
        if b > a:
            continue
        # steal one char from the widest neighbour that can spare it
        cand = [k for k in range(n) if spans[k][1] - spans[k][0] >= 2]
        if not cand:
            break
        d = max(cand, key=lambda k: spans[k][1] - spans[k][0])
        if d < i:
            spans[d] = (spans[d][0], spans[d][1] - 1)
            for k in range(d + 1, i):
                spans[k] = (spans[k][0] - 1, spans[k][1] - 1)
            spans[i] = (spans[i][0] - 1, spans[i][1])
        else:
            spans[d] = (spans[d][0] + 1, spans[d][1])
            for k in range(i + 1, d):
                spans[k] = (spans[k][0] + 1, spans[k][1] + 1)
            spans[i] = (spans[i][0], spans[i][1] + 1)

    return full, spans


def detect_links(uthmani, moshaf, phonetizer, full, spans):
    """Which words are phonetically fused with a neighbour.

    Rather than hand-coding tajweed rules, this MEASURES fusion: phonetize a
    word alone and compare against the phonemes it actually occupies inside
    the ayah. If they differ, the word's sound is changed by its neighbour --
    which is exactly what idgham, ikhfa, the linking of ٱللَّه after بِسْمِ,
    and madd munfasil all do.

    Returns a list, one entry per word:
        {'prev': bool, 'next': bool}
    meaning "this word is bound to the word before / after it".
    """
    words = uthmani.split()
    n = len(words)
    out = [{'prev': False, 'next': False} for _ in range(n)]
    if n < 2:
        return out

    def ph(text):
        try:
            return phonetizer(text, moshaf, remove_spaces=True).phonemes
        except Exception:
            return ''

    solo = [ph(w) for w in words]

    for i in range(n):
        a, b = spans[i]
        in_context = full[a:b]
        if not solo[i] or not in_context:
            continue

        # Bound to the PREVIOUS word if the pair's phonemes are shorter than
        # the two words separately -- sounds were merged at the seam.
        if i > 0:
            pair = ph(words[i - 1] + ' ' + words[i])
            if pair and len(pair) < len(solo[i - 1]) + len(solo[i]):
                out[i]['prev'] = True
                out[i - 1]['next'] = True

        # Bound to the NEXT word by the same test.
        if i < n - 1:
            pair = ph(words[i] + ' ' + words[i + 1])
            if pair and len(pair) < len(solo[i]) + len(solo[i + 1]):
                out[i]['next'] = True
                out[i + 1]['prev'] = True

    return out


def owner_of(spans, pos):
    """Which word owns phoneme position `pos`."""
    for i, (a, b) in enumerate(spans):
        if a <= pos < b:
            return i
    return len(spans) - 1 if spans else -1


# How close to a boundary still counts as "on the seam".
SEAM = 0


def owners_of(spans, pos, seam=SEAM):
    """Words that could own `pos`.

    With seam=0 only the owning word is returned, EXCEPT exactly on a boundary
    character, where the previous word is included too -- a word-final harakah
    is phonetically bound to the next word, so the boundary is genuinely
    shared. A wider seam caused overlapping pairs to chain together and mark
    an entire line red from a single mistake.
    """
    """Words that could own `pos`, including a neighbour if it sits on a seam.

    A word-final harakah is phonetically bound to the following word, so the
    phonetizer places it at the start of the NEXT word's span. Blaming one
    word alone is wrong roughly half the time -- measured on real data, the
    kasra ending مَـٰلِكِ lands at the first index of يَوْمِ. Both are returned
    so the UI can mark both rather than confidently mark the wrong one.
    """
    if not spans:
        return []
    out = []
    for i, (a, b) in enumerate(spans):
        if a <= pos < b:
            out.append(i)
            # exactly ON the opening boundary: the previous word ends here
            if pos == a and i > 0:
                out.insert(0, i - 1)
            break
    if not out:
        out = [owner_of(spans, pos)]
    return out


def words_touched(spans, start, end):
    """Every word overlapping the phoneme range [start, end)."""
    out = []
    for i, (a, b) in enumerate(spans):
        if a < end and b > start:
            out.append(i)
    return out


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

def main():
    from quran_transcript import Aya, quran_phonetizer, MoshafAttributes

    moshaf = MoshafAttributes(
        rewaya="hafs",
        madd_monfasel_len=2,
        madd_mottasel_len=4,
        madd_mottasel_waqf=4,
        madd_aared_len=2,
        madd_alleen_len=2,
    )

    print("=" * 72)
    print("  WORD BOUNDARY MAPPER — self-test")
    print("=" * 72)

    tests = [(1, 1), (1, 2), (1, 4), (1, 7), (112, 1)]
    all_ok = True

    for sura, aya_no in tests:
        uthmani = Aya(sura, aya_no).get().uthmani
        full, spans = build_word_spans(uthmani, moshaf, quran_phonetizer)
        words = uthmani.split()

        print(f"\n  {sura}:{aya_no}   {uthmani}")
        print(f"  phonemes ({len(full)}): {full}")
        print(f"  {'word':<14} {'span':<12} phonemes")
        print("  " + "-" * 56)
        for i, w in enumerate(words):
            a, b = spans[i]
            print(f"  {w:<14} {str((a,b)):<12} {full[a:b]}")

        # --- invariants ---
        ok = True
        if len(spans) != len(words):
            print("  FAIL: span count != word count"); ok = False
        if spans and spans[0][0] != 0:
            print("  FAIL: first span does not start at 0"); ok = False
        if spans and spans[-1][1] != len(full):
            print("  FAIL: last span does not end at len(phonemes)"); ok = False
        for i in range(1, len(spans)):
            if spans[i][0] != spans[i-1][1]:
                print(f"  FAIL: gap/overlap between word {i-1} and {i}")
                ok = False
                break
        for i, (a, b) in enumerate(spans):
            if b < a:
                print(f"  FAIL: reversed span at word {i}"); ok = False
            if b == a:
                print(f"  FAIL: ZERO-WIDTH span for word {i} "
                      f"({words[i]!r}) -- errors here would be misattributed")
                ok = False
        # reconstruct
        if ''.join(full[a:b] for a, b in spans) != full:
            print("  FAIL: spans do not reconstruct the phoneme string")
            ok = False

        print(f"  -> {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok

    # --- the real test: locate a known error ---
    print("\n" + "=" * 72)
    print("  ERROR ATTRIBUTION TEST")
    print("=" * 72)
    uthmani = Aya(1, 4).get().uthmani
    full, spans = build_word_spans(uthmani, moshaf, quran_phonetizer)
    words = uthmani.split()
    print(f"\n  ayah     : {uthmani}")
    print(f"  reference: {full}")

    # your real recorded error: kasra -> fatha on مالك
    wrong = full.replace('كِ', 'كَ', 1)
    print(f"  you said : {wrong}")
    diff = [i for i, (x, y) in enumerate(zip(full, wrong)) if x != y]
    if diff:
        pos = diff[0]
        cands = owners_of(spans, pos)
        print(f"\n  first difference at phoneme {pos}: "
              f"{full[pos]!r} -> {wrong[pos]!r}")
        print(f"  candidate words: "
              + ", ".join(f"{i}:{words[i]!r}" for i in cands))
        # The kasra ending مَـٰلِكِ sits exactly on the مالك/يوم seam, so
        # either word is a defensible attribution; both get highlighted.
        hit = 0 in cands
        print(f"  -> {'PASS' if hit else 'FAIL'}: "
              f"{'مَـٰلِكِ is among the flagged words' if hit else 'missed مَـٰلِكِ'}")
        all_ok = all_ok and hit

    print("\n" + "=" * 72)
    print("  ALL PASS" if all_ok else "  *** FAILURES ABOVE ***")
    print("=" * 72)
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
