"""
AL-MUQRI (المقرئ) — word-level live recitation checker.

DESIGN
------
Uses ONLY the /predict endpoint of the muaalem engine: audio -> Quran Phonetic
Script. That endpoint returned 200 on every chunk in testing.

It does NOT use /correct-recitation, whose Tasmeea search tries to locate a
chunk anywhere in the Quran. That search produced "No results found" on short
chunks and placed audio on the wrong page. We already know which page is open
and roughly where the reciter is, so searching the whole Quran throws away
information we already have.

Matching runs against the CURRENT AYAH's phonemes, using word spans from
word_map.py (verified on real text: every word gets an accurate span,
cross-word tajweed preserved, errors mapped to the owning word and to both
words when the error lands on a shared boundary).

    python run.py
"""

import io
import os
import json
import wave
import threading
import traceback

import requests
from flask import Flask, request, jsonify, Response, send_file, url_for

from word_map import build_word_spans, owners_of, detect_links

app = Flask(__name__)

SAMPLE_RATE = 16000
ENGINE = os.getenv('MUAALEM_ENGINE', 'http://127.0.0.1:8000')
VERBOSE = os.getenv('VERBOSE', '1') != '0'

# QUL's Husary ayah-by-ayah resource supplies the MP3 URL and professionally
# prepared word timings. Each opened page is cached locally in the background,
# then served from this app so previously visited pages work without internet.
QUL_API = os.getenv('QUL_API', 'https://qul.tarteel.ai/api/v1').rstrip('/')
QUL_HUSARY_RECITATION = int(os.getenv('QUL_HUSARY_RECITATION', '20'))
QUL_AUDIO_HOST = 'audio-cdn.tarteel.ai'
APP_DIR = os.path.dirname(os.path.abspath(__file__))
REFERENCE_AUDIO_DIR = os.getenv(
    'REFERENCE_AUDIO_DIR', os.path.join(APP_DIR, 'reference_audio', 'husary'))

# Clean, independently-recorded single-word audio (harakat-perfect, no cross-word
# tajweed merging) used by "Pronunciation mode". Files: <src>/<SSS>/SSS_AAA_WWW.opus
# with 1-based word numbers.
WORD_AUDIO_ROOT = os.path.join(APP_DIR, 'reference_audio')
WORD_AUDIO_SRC = os.getenv('WORD_AUDIO_SRC', 'mujawwad')

# How wrong a word may be before it is called an error.
WORD_BAD_RATE = float(os.getenv('WORD_BAD_RATE', '0.30'))

# A single wrong harakah is a real error even though it is a tiny fraction of
# a word. Measured: kasra->fatha on مَـٰلِكِ is 1 bad phoneme out of 7 = 0.14,
# which slipped under any sensible rate threshold. Vowel substitutions are
# therefore flagged on their own.
HARAKAT = set('\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652\u0670')

# Madd length is encoded as REPEATED symbols in the Quran Phonetic Script, so
# holding a 4-count madd for 2 shows up as deleted repeats -- a small fraction
# of a long word, invisible to a rate threshold. Since madd length is one of
# the errors this tool exists to catch, repeated-symbol changes are flagged on
# their own. These are the characters QPS repeats for elongation.
MADD_CHARS = set('\u0627\u06E6\u06E5\u064A\u0648')
# A chunk worse than this is not trusted to place at all.
CHUNK_MAX_RATE = float(os.getenv('CHUNK_MAX_RATE', '0.60'))
# If a single chunk marks more than this fraction of the words it touched as
# bad, the chunk was almost certainly placed wrong or the audio was unclear.
# Trusting it would paint a whole line red from one misplacement.
MAX_BAD_FRACTION = float(os.getenv('MAX_BAD_FRACTION', '0.6'))

# A chunk covering at least this share of an ayah's words, AND matching well,
# is treated as a deliberate RE-RECITATION of that line: it overwrites every
# word it touched in both directions, so re-reading a line can clear old reds.
# Short mid-flow chunks stay conservative so overlaps do not flicker.
REREAD_COVERAGE = float(os.getenv('REREAD_COVERAGE', '0.55'))
REREAD_MAX_RATE = float(os.getenv('REREAD_MAX_RATE', '0.32'))

# A chunk may reassess just the words it covered, even a small group in the
# middle of a line. Confidence has to scale with length: a short chunk could
# plausibly fit in several places, so it must match more cleanly than a long
# one before it is trusted to overwrite anything.
PARTIAL_MIN_PHONEMES = int(os.getenv('PARTIAL_MIN_PHONEMES', '10'))
PARTIAL_BASE_RATE = float(os.getenv('PARTIAL_BASE_RATE', '0.38'))
PARTIAL_SHORT_RATE = float(os.getenv('PARTIAL_SHORT_RATE', '0.30'))


def authoritative_rate_for(n_phonemes):
    """How clean a match must be for a chunk of this length to be trusted.

    Long chunks are inherently unambiguous, so the ordinary threshold applies.
    Short ones tighten toward PARTIAL_SHORT_RATE.
    """
    if n_phonemes >= 40:
        return PARTIAL_BASE_RATE
    if n_phonemes <= PARTIAL_MIN_PHONEMES:
        return PARTIAL_SHORT_RATE
    span = 40 - PARTIAL_MIN_PHONEMES
    t = (n_phonemes - PARTIAL_MIN_PHONEMES) / span
    return PARTIAL_SHORT_RATE + t * (PARTIAL_BASE_RATE - PARTIAL_SHORT_RATE)

_AARED = int(os.getenv('MADD_AARED', '2'))
MOSHAF_KW = dict(
    rewaya="hafs",
    madd_monfasel_len=int(os.getenv('MADD_MONFASEL', '2')),
    madd_mottasel_len=int(os.getenv('MADD_MOTTASEL', '4')),
    madd_mottasel_waqf=int(os.getenv('MADD_MOTTASEL_WAQF', '4')),
    madd_aared_len=_AARED,
    madd_alleen_len=int(os.getenv('MADD_ALLEEN', str(_AARED))),
)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

_moshaf = None
_page = None
_page_lock = threading.Lock()
_husary_audio_cache = {}
_husary_audio_lock = threading.Lock()
_reference_audio_locks = {}
_reference_audio_locks_guard = threading.Lock()
_reference_prefetch_lock = threading.Lock()
_reference_prefetch_ticket = 0

# Building a page phonetizes every prefix and every word pair, which is the
# slow part. Cache per ayah so switching pages back and forth is instant.
_ayah_cache = {}
_basmalah_entry = None
PAGE_SIZE = int(os.getenv('PAGE_SIZE', '8'))

# ---------------------------------------------------------------------------
# Mushaf page boundaries.
#
# quran-transcript carries no page metadata (verified), so boundaries come
# from page_layout_full.json, which is
# generated once by build_layout_docx.py and used as-is.
#
# Stored as: sura -> [first ayah of each page]
# ---------------------------------------------------------------------------

FULL_LAYOUT_FILE = os.getenv('FULL_LAYOUT', 'page_layout_full.json')

# Fallback only if the layout file is missing entirely.
DEFAULT_STARTS = {1: [1], 2: [1, 6, 17, 25]}

_layout = None


def load_layout():
    """Page boundaries from page_layout_full.json.

    Generated by build_layout_docx.py from the mushaf page table, and used
    as-is: there is no in-app editing, so a user cannot introduce mistakes.
    Only suras that verified against their true ayah counts are present; any
    others fall back to fixed-size pages.
    """
    global _layout
    if _layout is not None:
        return _layout
    data = {}
    try:
        if os.path.exists(FULL_LAYOUT_FILE):
            with open(FULL_LAYOUT_FILE, encoding='utf-8') as f:
                raw = json.load(f)
            starts = raw.get('starts') or {}
            data = {int(k): [int(x) for x in v] for k, v in starts.items()}
            print(f"  [layout] {len(data)} suras from {FULL_LAYOUT_FILE}")
        else:
            print(f"  [layout] {FULL_LAYOUT_FILE} not found -- "
                  f"using fixed-size pages")
    except Exception:
        print(f"  [layout] could not read {FULL_LAYOUT_FILE}")
        print(traceback.format_exc())
    merged = {int(k): list(v) for k, v in DEFAULT_STARTS.items()}
    merged.update(data)
    _layout = merged
    return _layout


_page_lookup = None


def load_page_index():
    """Map (sura, aya) -> real Mushaf page number, from page_layout_full.json."""
    global _page_lookup
    if _page_lookup is not None:
        return _page_lookup
    idx = {}
    try:
        if os.path.exists(FULL_LAYOUT_FILE):
            with open(FULL_LAYOUT_FILE, encoding='utf-8') as f:
                raw = json.load(f)
            for pno, entries in (raw.get('pages') or {}).items():
                for e in entries:
                    s, a, b = int(e['sura']), int(e['from']), int(e['to'])
                    for aya in range(a, b + 1):
                        idx[(s, aya)] = int(pno)
    except Exception:
        pass
    _page_lookup = idx
    return _page_lookup


def mushaf_page_for(sura, aya):
    return load_page_index().get((int(sura), int(aya)))


def sura_pages(sura, n_ayat):
    """Page ranges for a sura: [(start_aya, end_aya), ...]."""
    starts = list(load_layout().get(sura) or [])
    starts = sorted({int(s) for s in starts if 1 <= int(s) <= n_ayat})
    if not starts:
        starts = list(range(1, n_ayat + 1, PAGE_SIZE))
    if starts[0] != 1:
        starts.insert(0, 1)
    # extend with fixed-size pages past the last known boundary
    while starts[-1] + PAGE_SIZE <= n_ayat:
        starts.append(starts[-1] + PAGE_SIZE)
    pages = []
    for i, a in enumerate(starts):
        b = (starts[i + 1] - 1) if i + 1 < len(starts) else n_ayat
        if a <= b:
            pages.append((a, b))
    return pages


def get_moshaf():
    global _moshaf
    if _moshaf is None:
        from quran_transcript import MoshafAttributes
        _moshaf = MoshafAttributes(**MOSHAF_KW)
    return _moshaf


def build_basmalah():
    """A selectable, unnumbered Basmalah with Husary's exact 1:1 audio."""
    global _basmalah_entry
    if _basmalah_entry is not None:
        return _basmalah_entry

    from quran_transcript import Aya, quran_phonetizer
    uthmani = Aya(1, 1).get().uthmani
    phonemes, spans = build_word_spans(uthmani, get_moshaf(), quran_phonetizer)
    links = detect_links(uthmani, get_moshaf(), quran_phonetizer,
                         phonemes, spans)
    _basmalah_entry = {
        'aya': 0,
        'uthmani': uthmani,
        'words': uthmani.split(),
        'phonemes': phonemes,
        'spans': spans,
        'links': links,
        'is_basmalah': True,
        'audio_sura': 1,
        'audio_aya': 1,
    }
    return _basmalah_entry


def build_page(sura, start_aya, end_aya):
    """Phonetize every ayah on the page once, with per-word spans."""
    from quran_transcript import Aya, quran_phonetizer

    moshaf = get_moshaf()
    ayat = []
    # The Basmalah appears before the first ayah of every surah except
    # Al-Fatihah (where it is ayah 1) and At-Tawbah (where it is absent).
    if start_aya == 1 and sura not in (1, 9):
        try:
            ayat.append(build_basmalah())
        except Exception:
            print('  [basmalah] failed to build')
            print(traceback.format_exc())
    for n in range(start_aya, end_aya + 1):
        cached = _ayah_cache.get((sura, n))
        if cached is not None:
            ayat.append(cached)
            continue
        try:
            uthmani = Aya(sura, n).get().uthmani
        except Exception:
            continue
        try:
            phonemes, spans = build_word_spans(uthmani, moshaf, quran_phonetizer)
        except Exception:
            print(traceback.format_exc())
            continue
        try:
            links = detect_links(uthmani, moshaf, quran_phonetizer,
                                 phonemes, spans)
        except Exception:
            # Previously this failed silently, so a single phonetizer error
            # meant no arrows appeared anywhere on the page with no clue why.
            print(f"  [links] FAILED for {sura}:{n}")
            print(traceback.format_exc())
            links = [{'prev': False, 'next': False} for _ in uthmani.split()]
        if VERBOSE:
            n_links = sum(1 for L in links if L.get('prev') or L.get('next'))
            print(f"  [links] {sura}:{n}  {n_links}/{len(links)} words linked")
        entry = {
            'aya': n,
            'uthmani': uthmani,
            'words': uthmani.split(),
            'phonemes': phonemes,
            'spans': spans,
            'links': links,
        }
        _ayah_cache[(sura, n)] = entry
        ayat.append(entry)
    return {'sura': sura, 'start_aya': start_aya, 'end_aya': end_aya,
            'ayat': ayat}


def page_for_client(page):
    return {
        'sura': page['sura'],
        'start_aya': page['start_aya'],
        'end_aya': page['end_aya'],
        'ayat': [{'aya': a['aya'], 'uthmani': a['uthmani'],
                  'words': a['words'], 'n_phonemes': len(a['phonemes']),
                  'links': a.get('links', []),
                  'is_basmalah': a.get('is_basmalah', False)}
                 for a in page['ayat']],
    }


def reference_audio_paths(sura, aya):
    """Paths for one locally cached Husary ayah."""
    stem = f'{sura:03d}{aya:03d}'
    return (os.path.join(REFERENCE_AUDIO_DIR, f'{stem}.json'),
            os.path.join(REFERENCE_AUDIO_DIR, f'{stem}.mp3'))


def load_cached_husary_audio(sura, aya):
    metadata_path, _audio_path = reference_audio_paths(sura, aya)
    try:
        with open(metadata_path, encoding='utf-8') as source:
            data = json.load(source)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get('audio_url') or not data.get('segments'):
        return None
    return data


def write_husary_metadata(sura, aya, data):
    os.makedirs(REFERENCE_AUDIO_DIR, exist_ok=True)
    metadata_path, _audio_path = reference_audio_paths(sura, aya)
    temp_path = f'{metadata_path}.part'
    with open(temp_path, 'w', encoding='utf-8') as destination:
        json.dump(data, destination, ensure_ascii=False, separators=(',', ':'))
    os.replace(temp_path, metadata_path)


def husary_audio_for_ayah(sura, aya):
    """Return QUL Husary audio and normalized word timings for one ayah."""
    key = (sura, aya)
    with _husary_audio_lock:
        cached = _husary_audio_cache.get(key)
    if cached is not None:
        return cached

    cached = load_cached_husary_audio(sura, aya)
    if cached is not None:
        with _husary_audio_lock:
            _husary_audio_cache[key] = cached
        return cached

    response = requests.get(
        f"{QUL_API}/audio/ayah_segments/{QUL_HUSARY_RECITATION}",
        params={'surah': sura, 'from': aya}, timeout=12)
    response.raise_for_status()
    entry = (response.json().get('segments') or {}).get(f'{sura}:{aya}')
    if not entry:
        raise ValueError('QUL returned no timing data for this ayah')

    audio_url = entry.get('audio_url') or ''
    if not audio_url.startswith(f'https://{QUL_AUDIO_HOST}/'):
        raise ValueError('QUL returned an unexpected audio host')

    segments = []
    for raw in entry.get('segments') or []:
        # Current QUL API: [word_index, word_id, start_ms, end_ms].
        # Its documented export format may omit word_id:
        # [word_index, start_ms, end_ms]. Support both safely.
        if not isinstance(raw, (list, tuple)) or len(raw) not in (3, 4):
            continue
        if len(raw) == 4:
            word_idx, _word_id, start_ms, end_ms = raw
        else:
            word_idx, start_ms, end_ms = raw
        try:
            word_idx, start_ms, end_ms = map(int, (word_idx, start_ms, end_ms))
        except (TypeError, ValueError):
            continue
        if word_idx < 0 or start_ms < 0 or end_ms <= start_ms:
            continue
        segments.append({'word_idx': word_idx,
                         'start_ms': start_ms, 'end_ms': end_ms})

    if not segments:
        raise ValueError('QUL returned no usable word timings for this ayah')

    result = {'audio_url': audio_url,
              'segments': sorted(segments, key=lambda s: s['word_idx'])}
    write_husary_metadata(sura, aya, result)
    with _husary_audio_lock:
        _husary_audio_cache[key] = result
    return result


def audio_lock_for(sura, aya):
    key = (sura, aya)
    with _reference_audio_locks_guard:
        return _reference_audio_locks.setdefault(key, threading.Lock())


def cache_husary_audio(sura, aya):
    """Download one ayah once, keeping a complete MP3 or no MP3 at all."""
    data = husary_audio_for_ayah(sura, aya)
    _metadata_path, audio_path = reference_audio_paths(sura, aya)
    if os.path.isfile(audio_path) and os.path.getsize(audio_path) > 1024:
        return data

    with audio_lock_for(sura, aya):
        if os.path.isfile(audio_path) and os.path.getsize(audio_path) > 1024:
            return data
        os.makedirs(REFERENCE_AUDIO_DIR, exist_ok=True)
        temp_path = f'{audio_path}.part'
        try:
            response = requests.get(data['audio_url'], stream=True, timeout=30)
            response.raise_for_status()
            with open(temp_path, 'wb') as destination:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        destination.write(chunk)
            if not os.path.isfile(temp_path) or os.path.getsize(temp_path) <= 1024:
                raise ValueError('reference audio download was incomplete')
            os.replace(temp_path, audio_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
    return data


def prefetch_reference_audio(sources, ticket):
    """Cache only the latest opened page, stopping if the user moves on."""
    for sura, aya in sources:
        with _reference_prefetch_lock:
            if ticket != _reference_prefetch_ticket:
                return
        try:
            cache_husary_audio(sura, aya)
            if VERBOSE:
                print(f'  [reference audio] cached {sura}:{aya}')
        except (OSError, requests.RequestException, ValueError) as exc:
            print(f'  [reference audio] cache paused at {sura}:{aya}: {exc}')
            return


def schedule_reference_audio(page):
    """Start a background cache job for exactly the page the user opened."""
    global _reference_prefetch_ticket
    sources = []
    for entry in page['ayat']:
        source = (entry.get('audio_sura', page['sura']),
                  entry.get('audio_aya', entry['aya']))
        if source not in sources:
            sources.append(source)
    if not sources:
        return
    with _reference_prefetch_lock:
        _reference_prefetch_ticket += 1
        ticket = _reference_prefetch_ticket
    threading.Thread(target=prefetch_reference_audio,
                     args=(sources, ticket), daemon=True).start()

# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def edit_ops(a, b):
    """Edit ops turning a into b, plus the distance."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        ai = a[i - 1]
        row, prow = dp[i], dp[i - 1]
        for j in range(1, m + 1):
            row[j] = (prow[j - 1] if ai == b[j - 1]
                      else 1 + min(prow[j], row[j - 1], prow[j - 1]))
    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        if (i > 0 and j > 0 and a[i - 1] == b[j - 1]
                and dp[i][j] == dp[i - 1][j - 1]):
            ops.append(('match', i - 1, j - 1)); i -= 1; j -= 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            ops.append(('replace', i - 1, j - 1)); i -= 1; j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(('delete', i - 1, j)); i -= 1
        else:
            ops.append(('insert', i, j - 1)); j -= 1
    ops.reverse()
    return ops, dp[n][m]


def scan_ayah(ref, heard, spans=None, stride=1):
    """Best offset for `heard` inside `ref`, restricted to WORD BOUNDARIES.

    The comparison window ENDS at a word boundary too. Previously it was a
    fixed int(n*1.3)+6 characters, so a 16-phoneme chunk was compared against
    26 characters of reference -- ten of them belonging to the next word.
    That guaranteed a large edit distance even for a perfect recitation:
    reciting إِيَّاكَ نَعْبُدُ scored 0.562 at its own true offset 0.

    Now each candidate start is paired with every plausible word-boundary END,
    so a two-word chunk is compared against exactly two words.

    Returns (start, rate, alternatives).
    """
    n = len(heard)
    if not ref or n < 3:
        return None, 1.0, []

    if spans:
        bounds = sorted({0} | {a for a, _b in spans} | {b for _a, b in spans})
        bounds = [x for x in bounds if x <= len(ref)]
        starts = [a for a, _b in spans if a < len(ref)] or [0]
    else:
        bounds = list(range(0, len(ref) + 1, max(1, stride)))
        starts = list(range(0, max(1, len(ref) - int(n * 0.5)), stride))

    scored = []
    for start in starts:
        # candidate ends: any boundary giving a segment of plausible length
        for end in bounds:
            seg_len = end - start
            if seg_len < n * 0.55 or seg_len > n * 1.7 + 6:
                continue
            seg = ref[start:end]
            if not seg:
                continue
            _ops, dist = edit_ops(seg, heard)
            scored.append((start, dist / max(n, len(seg))))
        # always include a length-matched fallback in case no boundary fits
        seg = ref[start:start + n]
        if len(seg) >= n * 0.5:
            _ops, dist = edit_ops(seg, heard)
            scored.append((start, dist / max(n, len(seg))))

    if not scored:
        return None, 1.0, []

    # keep the best score per start offset
    best_per_start = {}
    for s, r in scored:
        if s not in best_per_start or r < best_per_start[s]:
            best_per_start[s] = r

    ranked = sorted(best_per_start.items(), key=lambda x: x[1])
    best_start, best_rate = ranked[0]
    NEAR = float(os.getenv('SCAN_NEAR', '0.12'))
    alts = [(s, r) for s, r in ranked[1:] if r <= best_rate + NEAR]
    return best_start, best_rate, alts


def locate_on_page(ayat, heard, cursor_ayah, cursor_pos):
    """Where on the page does `heard` belong? Returns (ayah_idx, start, rate).

    Going BACK is treated as a first-class case, both across lines and within
    a line:

      * across lines -- every ayah on the page is scanned, so a skipped or
        earlier line can be re-read at any time
      * within a line -- offsets BEFORE the cursor are considered on equal
        footing, and an earlier offset wins whenever it is a reasonable match.
        Repeated phrases (إِيَّاكَ ... وَإِيَّاكَ) otherwise pull a re-read of
        the line's opening toward the later occurrence, so the first words
        never got marked.
    """
    scored = []
    for k, ayah in enumerate(ayat):
        start, rate, alts = scan_ayah(ayah['phonemes'], heard,
                                      spans=ayah.get('spans'))
        if start is None:
            continue

        options = [(start, rate)] + list(alts)

        # Prefer an EARLIER offset only when it matches essentially as well.
        # A wide margin here dragged good placements backward, so the earlier
        # position must be close to the best, not merely tolerable.
        BACK_MARGIN = float(os.getenv('BACK_MARGIN', '0.06'))
        viable = [(s, r) for s, r in options
                  if r <= rate + BACK_MARGIN and r <= CHUNK_MAX_RATE]
        if viable:
            viable.sort(key=lambda x: x[0])
            start, rate = viable[0]

        scored.append((rate, k, start))

    if not scored:
        return None, None, 1.0

    scored.sort(key=lambda r: r[0])
    best_rate = scored[0][0]

    TIE = 0.08
    tied = [c for c in scored if c[0] <= best_rate + TIE]

    def nearness(c):
        _rate, k, start = c
        if k == cursor_ayah:
            return (0, abs(start - cursor_pos))
        if k == cursor_ayah + 1:
            return (1, start)
        return (2, abs(k - cursor_ayah) * 1000 + start)

    tied.sort(key=nearness)
    rate, k, start = tied[0]
    return k, start, rate


def score_words(ayah, heard, start):
    """Per-word accuracy for one chunk placed at `start` in the ayah.

    The comparison window ENDS at the word boundary that best fits the heard
    length. A fixed overshoot window previously ran past where the recitation
    actually stopped: the extra reference characters had no counterpart in the
    audio, counted as deletions, and were blamed on words the reciter never
    said. (Measured: re-reading words 4..6 correctly turned 4 and 5 green but
    marked 6, 7 and 8 red.)
    """
    ref = ayah['phonemes']
    spans = ayah['spans']
    n = len(heard)

    # choose the end boundary whose segment length is closest to the audio
    ends = sorted({b for _a, b in spans if b > start} | {len(ref)})
    best_end, best_gap = None, None
    for e in ends:
        seg_len = e - start
        if seg_len < n * 0.5:
            continue
        gap = abs(seg_len - n)
        if best_gap is None or gap < best_gap:
            best_gap, best_end = gap, e
    if best_end is None:
        best_end = min(len(ref), start + n)

    seg = ref[start:best_end]
    ops, _d = edit_ops(seg, heard)

    tally = {}
    for op, i, j in ops:
        pos = start + i
        for w in owners_of(spans, pos):
            t = tally.setdefault(w, {'ok': 0, 'bad': 0, 'exp': '', 'got': '',
                                     'vowel': False, 'madd': 0})
            if op == 'match':
                t['ok'] += 1
            else:
                t['bad'] += 1
                e_ch = seg[i] if i < len(seg) else ''
                g_ch = heard[j] if j < len(heard) else ''
                if op in ('replace', 'delete') and e_ch:
                    t['exp'] += e_ch
                if op in ('replace', 'insert') and g_ch:
                    t['got'] += g_ch
                if op == 'replace' and (e_ch in HARAKAT or g_ch in HARAKAT):
                    t['vowel'] = True
                if op in ('delete', 'insert') and (e_ch or g_ch) in MADD_CHARS:
                    t['madd'] += 1

    out = []
    for w, t in tally.items():
        total = t['ok'] + t['bad']
        if total < 2:
            continue
        # a word the chunk barely touched is not evidence
        a, b = spans[w] if w < len(spans) else (0, 0)
        covered = min(b, best_end) - max(a, start)
        if covered < (b - a) * 0.5:
            continue
        rate = t['bad'] / total
        madd_off = t['madd'] >= 1
        bad = rate > WORD_BAD_RATE or t['vowel'] or madd_off
        if not bad:
            kind = 'ok'
        elif rate > WORD_BAD_RATE:
            kind = 'shape'
        elif t['vowel']:
            kind = 'vowel'
        else:
            kind = 'madd'
        out.append({
            'word_idx': w,
            'bad_rate': round(rate, 3),
            'status': 'bad' if bad else 'good',
            'kind': kind,
            'expected': t['exp'][:14],
            'heard': t['got'][:14],
        })
    return out


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class Session:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.ayah_idx = 0
        self.pos = 0
        self.state = {}      # "aya:word" -> good|bad
        self.errors = []
        self.chunks = 0

    def apply(self, page, heard):
        with self.lock:
            ayat = page['ayat']
            if not ayat:
                return {'skipped': True, 'reason': 'empty page'}

            k, start, rate = locate_on_page(
                ayat, heard, self.ayah_idx, self.pos)
            if k is None:
                return {'skipped': True, 'reason': 'no placement'}
            d = k - self.ayah_idx

            if rate > CHUNK_MAX_RATE:
                return {'skipped': True, 'reason': 'unclear',
                        'rate': round(rate, 3)}

            ayah = ayat[k]
            words = score_words(ayah, heard, start)
            aya_no = ayah['aya']

            # Should this chunk be trusted to REASSESS the words it covered?
            #
            # Previously this required covering most of the ayah, so a small
            # group in the middle of a line could never clear its own reds.
            # Now any chunk qualifies if it matched cleanly enough for its
            # length -- and it only ever overwrites the words it touched.
            n_words_ayah = max(1, len(ayah['spans']))
            covered = len({w['word_idx'] for w in words})
            need = authoritative_rate_for(len(heard))
            authoritative = rate <= need
            full_line = covered / n_words_ayah >= REREAD_COVERAGE

            # If nearly every word looks bad, the chunk was probably placed
            # wrong rather than every word being mispronounced. Previously the
            # whole chunk was discarded, which left entire ayat uncoloured.
            # Now the good words are still recorded; only the bad marks are
            # withheld, so progress is visible and nothing is falsely blamed.
            n_bad = sum(1 for w in words if w['status'] == 'bad')
            distrust_bad = (bool(words) and n_bad > 2
                            and (n_bad / len(words)) > MAX_BAD_FRACTION
                            and not authoritative)

            if authoritative:
                # Drop previous errors ONLY for the words this chunk covered.
                # Re-reading three words must not silently clear the rest of
                # the line.
                touched = {w['word_idx'] for w in words}
                self.errors = [e for e in self.errors
                               if not (e['aya'] == aya_no
                                       and e['word_idx'] in touched)]

            for w in words:
                if distrust_bad and w['status'] == 'bad':
                    continue
                key = f"{aya_no}:{w['word_idx']}"
                # Normally a good word is never downgraded, so overlapping
                # chunks cannot make it flicker. A re-read overrides that in
                # BOTH directions -- that is what lets old reds clear.
                if (not authoritative
                        and self.state.get(key) == 'good'
                        and w['status'] == 'bad'):
                    continue
                self.state[key] = w['status']
                if w['status'] == 'bad':
                    self.errors.append({
                        'aya': aya_no,
                        'word_idx': w['word_idx'],
                        'word': (ayah['words'][w['word_idx']]
                                 if w['word_idx'] < len(ayah['words']) else ''),
                        'expected': w['expected'],
                        'heard': w['heard'],
                        'bad_rate': w['bad_rate'],
                        'kind': w.get('kind', 'shape'),
                    })

            self.ayah_idx = k
            self.pos = min(len(ayah['phonemes']), start + len(heard))
            if self.pos >= len(ayah['phonemes']) - 2 and k + 1 < len(ayat):
                self.ayah_idx = k + 1
                self.pos = 0
            self.chunks += 1

            return {'skipped': False, 'aya': aya_no, 'start': start,
                    'rate': round(rate, 3), 'words': words,
                    'reread': authoritative,
                    'full_line': full_line,
                    'need_rate': round(need, 3),
                    'coverage': round(covered / n_words_ayah, 2)}

    def snapshot(self):
        with self.lock:
            return {'state': dict(self.state), 'errors': self.errors[-40:],
                    'n_errors': len(self.errors), 'chunks': self.chunks,
                    'ayah_idx': self.ayah_idx, 'pos': self.pos}


session = Session()


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def read_wav(raw):
    import numpy as np
    with wave.open(io.BytesIO(raw), 'rb') as w:
        nch, width, fr, nfr = (w.getnchannels(), w.getsampwidth(),
                               w.getframerate(), w.getnframes())
        frames = w.readframes(nfr)
    if width != 2 or not frames:
        return None, 0, 0
    a = np.frombuffer(frames, dtype='<i2').astype('float32') / 32768.0
    if nch > 1:
        a = a.reshape(-1, nch).mean(axis=1)
    dur = len(a) / fr
    rms = float((a ** 2).mean() ** 0.5) if len(a) else 0.0
    return a, dur, rms


_PREDICT_FIELD = os.getenv('PREDICT_FIELD')          # cached once discovered


def _extract(d):
    """Pull the phoneme string out of whatever shape the engine returns."""
    if isinstance(d, str):
        return d or None
    if isinstance(d, dict):
        for k in ('phonemes', 'text', 'prediction', 'predicted_phonemes',
                  'output', 'result'):
            got = _extract(d.get(k))
            if got:
                return got
        return None
    if isinstance(d, list) and d:
        return _extract(d[0])
    return None


def predict(raw):
    """Audio -> phonemes via the engine's /predict.

    The engine rejected `file` with:
        {"detail":[{"type":"missing","loc":["body","request"], ...}]}
    so its field is named `request`, not `file`. Rather than hard-code a
    guess, the correct field name is discovered on first use and cached --
    the 422 body names the expected field, so we read it from there.
    """
    global _PREDICT_FIELD

    candidates = ([_PREDICT_FIELD] if _PREDICT_FIELD
                  else ['request', 'file', 'audio', 'audio_file', 'wav'])

    last = None
    for field in candidates:
        if not field:
            continue
        try:
            r = requests.post(f"{ENGINE}/predict",
                              files={field: ('c.wav', raw, 'audio/wav')},
                              timeout=60)
        except Exception as exc:
            raise
        last = r
        if r.status_code == 200:
            if _PREDICT_FIELD != field:
                _PREDICT_FIELD = field
                if VERBOSE:
                    print(f"  [predict] using field name {field!r}")
            try:
                return _extract(r.json())
            except Exception:
                txt = (r.text or '').strip()
                return txt or None

        # A 422 tells us exactly which field it wanted -- use it next time.
        if r.status_code == 422 and not _PREDICT_FIELD:
            try:
                det = r.json().get('detail') or []
                for item in det:
                    loc = item.get('loc') or []
                    if len(loc) >= 2 and loc[0] == 'body':
                        want = loc[1]
                        if want and want not in candidates:
                            candidates.append(want)
                        if want:
                            _PREDICT_FIELD = None   # verify by trying it
                            r2 = requests.post(
                                f"{ENGINE}/predict",
                                files={want: ('c.wav', raw, 'audio/wav')},
                                timeout=60)
                            if r2.status_code == 200:
                                _PREDICT_FIELD = want
                                if VERBOSE:
                                    print(f"  [predict] discovered field "
                                          f"{want!r}")
                                try:
                                    return _extract(r2.json())
                                except Exception:
                                    return (r2.text or '').strip() or None
            except Exception:
                pass

    if VERBOSE and last is not None:
        print(f"  [predict] http {last.status_code}: {last.text[:200]}")
        print("  [predict] no field name worked. Inspect the schema at "
              f"{ENGINE}/docs")
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, 'index.html'), encoding='utf-8') as f:
        return Response(f.read(), mimetype='text/html')


@app.route('/fonts/<path:fname>')
def fonts(fname):
    """Serve locally-bundled fonts so the mushaf renders offline."""
    fname = os.path.basename(fname)   # no path traversal
    path = os.path.join(APP_DIR, 'fonts', fname)
    if not os.path.isfile(path):
        return jsonify({'error': 'font not found'}), 404
    mt = ('font/woff2' if fname.endswith('.woff2')
          else 'font/otf' if fname.endswith('.otf')
          else 'font/ttf' if fname.endswith('.ttf') else None)
    return send_file(path, mimetype=mt, max_age=31536000, conditional=True)


@app.route('/health')
def health():
    ok = False
    try:
        ok = requests.get(f"{ENGINE}/health", timeout=3).status_code == 200
    except Exception:
        pass
    return jsonify({'engine': ok, 'engine_url': ENGINE})


@app.route('/reference_audio_status')
def reference_audio_status():
    if _page is None:
        return jsonify({'error': 'no page'}), 400
    try:
        aya = int(request.args.get('aya', ''))
    except (TypeError, ValueError):
        return jsonify({'error': 'bad ayah'}), 400
    entry = next((item for item in _page['ayat'] if item['aya'] == aya), None)
    if entry is None:
        return jsonify({'error': 'unknown ayah'}), 400
    source_sura = entry.get('audio_sura', _page['sura'])
    source_aya = entry.get('audio_aya', aya)
    metadata = load_cached_husary_audio(source_sura, source_aya)
    _metadata_path, audio_path = reference_audio_paths(source_sura, source_aya)
    cached = bool(metadata and os.path.isfile(audio_path)
                  and os.path.getsize(audio_path) > 1024)
    return jsonify({'cached': cached})


@app.route('/reference_audio')
def reference_audio():
    if _page is None:
        return jsonify({'error': 'no page'}), 400
    try:
        aya = int(request.args.get('aya', ''))
    except (TypeError, ValueError):
        return jsonify({'error': 'bad ayah'}), 400
    entry = next((item for item in _page['ayat'] if item['aya'] == aya), None)
    if entry is None:
        return jsonify({'error': 'unknown ayah'}), 400
    source_sura = entry.get('audio_sura', _page['sura'])
    source_aya = entry.get('audio_aya', aya)
    try:
        data = cache_husary_audio(source_sura, source_aya)
        return jsonify({'audio_url': url_for('reference_audio_file',
                                             sura=source_sura, aya=source_aya),
                        'segments': data['segments'], 'cached': True})
    except (OSError, requests.RequestException, ValueError) as exc:
        print(f"  [reference audio] {exc}")
        return jsonify({'error': 'reference audio unavailable'}), 502


@app.route('/reference_audio_file/<int:sura>/<int:aya>.mp3')
def reference_audio_file(sura, aya):
    _metadata_path, audio_path = reference_audio_paths(sura, aya)
    if not os.path.isfile(audio_path):
        return jsonify({'error': 'reference audio not cached'}), 404
    return send_file(audio_path, mimetype='audio/mpeg', conditional=True,
                     max_age=31536000)


@app.route('/word_audio/<int:sura>/<int:aya>/<int:word>.opus')
def word_audio(sura, aya, word):
    """Serve one clean, single-word recording (1-based word number)."""
    path = os.path.join(WORD_AUDIO_ROOT, WORD_AUDIO_SRC, f"{sura:03d}",
                        f"{sura:03d}_{aya:03d}_{word:03d}.opus")
    if not os.path.isfile(path):
        return jsonify({'error': 'word audio not found'}), 404
    return send_file(path, mimetype='audio/ogg', conditional=True,
                     max_age=31536000)


@app.route('/word_audio_list')
def word_audio_list():
    """Which word numbers have a clean recording for this sura+ayah."""
    try:
        sura = int(request.args.get('sura'))
        aya = int(request.args.get('aya'))
    except Exception:
        return jsonify({'error': 'bad params'}), 400
    d = os.path.join(WORD_AUDIO_ROOT, WORD_AUDIO_SRC, f"{sura:03d}")
    prefix = f"{sura:03d}_{aya:03d}_"
    words = []
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.startswith(prefix) and fn.endswith('.opus'):
                try:
                    words.append(int(fn[len(prefix):-len('.opus')]))
                except Exception:
                    pass
    words.sort()
    return jsonify({'source': WORD_AUDIO_SRC, 'sura': sura, 'aya': aya,
                    'words': words})


@app.route('/sura_info/<int:sura>')
def sura_info(sura):
    from quran_transcript import Aya
    n = 0
    for i in range(1, 300):
        try:
            Aya(sura, i).get()
            n = i
        except Exception:
            break
    ranges = sura_pages(sura, n)
    return jsonify({'sura': sura, 'ayat': n,
                    'page_size': PAGE_SIZE,
                    'pages': len(ranges),
                    'ranges': [{'from': a, 'to': b,
                                'page': mushaf_page_for(sura, a)}
                               for a, b in ranges],
                    'starts': load_layout().get(sura, [])})


@app.route('/page', methods=['POST'])
def set_page():
    global _page
    d = request.get_json(silent=True) or {}
    try:
        sura = int(d.get('sura', 1))
        start = int(d.get('start_aya', 1))
        end = int(d.get('end_aya', 1))
        # A whole long surah at once is what made tracking crawl: every chunk
        # is scanned against every ayah on the page.
        max_end = start + int(os.getenv('MAX_PAGE_AYAT', '20')) - 1
        if end > max_end:
            end = max_end
        with _page_lock:
            _page = build_page(sura, start, end)
            session.reset()
            schedule_reference_audio(_page)
        return jsonify({'ok': True, 'page': page_for_client(_page)})
    except Exception as exc:
        print(traceback.format_exc())
        return jsonify({'error': str(exc)}), 500


@app.route('/reset', methods=['POST'])
def reset():
    session.reset()
    return jsonify({'ok': True, **session.snapshot()})


@app.route('/state')
def state():
    return jsonify(session.snapshot())


@app.route('/chunk', methods=['POST'])
def chunk():
    if _page is None:
        return jsonify({'error': 'no page'}), 400
    blob = request.files.get('audio')
    if blob is None:
        return jsonify({'error': 'no audio'}), 400

    raw = blob.read()
    audio, dur, rms = read_wav(raw)
    if audio is None or dur < 0.8:
        return jsonify({'skipped': True, 'reason': 'short',
                        **session.snapshot()})
    if rms < 0.006:
        return jsonify({'skipped': True, 'reason': 'silence',
                        **session.snapshot()})

    try:
        heard = predict(raw)
    except Exception as exc:
        return jsonify({'error': f'engine unreachable: {exc}'}), 502
    if not heard:
        return jsonify({'skipped': True, 'reason': 'nothing heard',
                        **session.snapshot()})

    res = session.apply(_page, heard)

    if VERBOSE:
        if res.get('skipped'):
            print(f"  [{dur:.1f}s] {heard[:52]}")
            print(f"        skipped: {res.get('reason')} {res.get('rate', '')}")
        else:
            bad = [w for w in res.get('words', []) if w['status'] == 'bad']
            if res.get('reread'):
                tag = ' RE-READ(line)' if res.get('full_line') else ' RE-READ(part)'
            else:
                tag = (f" NOT-AUTHORITATIVE need<={res.get('need_rate')} "
                       f"-> nothing overwritten")
            print(f"  [{dur:.1f}s] aya {res['aya']} @{res['start']} "
                  f"rate={res['rate']} n_ph={len(heard)} "
                  f"cov={res.get('coverage')} {len(bad)} bad{tag}")
            print(f"        heard: {heard[:60]}")
            for w in bad[:4]:
                print(f"          word {w['word_idx']}: "
                      f"{w['expected']} -> {w['heard']}")

    return jsonify({'heard': heard, **res, **session.snapshot()})



def judge_word(ref, heard, pass_rate):
    """Compare one word's phonemes. Returns (passed, kind, expected, heard_bits).

    A rate threshold alone cannot catch the two errors this tool exists for:
    a single swapped vowel in a 7-phoneme word scores 0.14, and a shortened
    madd scores about the same. Both slip under any sensible cutoff, so they
    are detected explicitly -- the same rules live mode uses.
    """
    if not ref:
        return False, 'shape', '', heard
    ops, dist = edit_ops(ref, heard)
    rate = dist / max(len(ref), len(heard), 1)

    exp_s = got_s = ''
    vowel = False
    madd = 0
    for op, i, j in ops:
        if op == 'match':
            continue
        e_ch = ref[i] if i < len(ref) else ''
        g_ch = heard[j] if j < len(heard) else ''
        if e_ch:
            exp_s += e_ch
        if g_ch:
            got_s += g_ch
        if op == 'replace' and (e_ch in HARAKAT or g_ch in HARAKAT):
            vowel = True
        if op in ('delete', 'insert') and (e_ch or g_ch) in MADD_CHARS:
            madd += 1

    bad = rate > pass_rate or vowel or madd >= 1
    # A badly wrong word usually also differs in some harakah, so check the
    # overall rate FIRST -- otherwise a completely different word gets
    # reported as a mere vowel slip.
    if not bad:
        kind = 'ok'
    elif rate > pass_rate:
        kind = 'shape'
    elif vowel:
        kind = 'vowel'
    elif madd:
        kind = 'madd'
    else:
        kind = 'shape'
    return (not bad), kind, exp_s[:14], got_s[:14]


@app.route('/selection', methods=['POST'])
def selection():
    """Judge a user-selected run of words.

    The reciter tells us exactly which words they are about to say, so there
    is NO placement problem -- the thing that made single words fail in live
    mode and caused whole ayat to be skipped when a chunk could not be placed.

    Words are phonetized as a contiguous span of the ayah, so cross-word
    tajweed at the internal seams is preserved.
    """
    if _page is None:
        return jsonify({'error': 'no page'}), 400

    # A selection may span multiple ayat. Preferred input is a JSON `spans`
    # list of {aya, from, to}; the legacy single-ayah form is still accepted.
    spans_raw = request.form.get('spans')
    spans = []
    try:
        if spans_raw:
            for sp in json.loads(spans_raw):
                spans.append((int(sp['aya']), int(sp['from']), int(sp['to'])))
        else:
            spans.append((int(request.form.get('aya')),
                          int(request.form.get('word_from')),
                          int(request.form.get('word_to'))))
    except Exception:
        return jsonify({'error': 'bad params'}), 400
    if not spans:
        return jsonify({'error': 'empty selection'}), 400

    blob = request.files.get('audio')
    if blob is None:
        return jsonify({'error': 'no audio'}), 400
    raw = blob.read()
    audio, dur, rms = read_wav(raw)
    if audio is None or dur < 0.3:
        return jsonify({'ok': False, 'reason': 'too short'})
    if rms < 0.006:
        return jsonify({'ok': False, 'reason': 'silence'})

    # One combined phoneme string across the selected spans + an owner map
    # telling us, per phoneme, which (aya, word) it belongs to.
    combined = ''
    owner_map = []          # (aya, word) or None, per phoneme char
    order = []              # (aya, word) in selection order
    words_text = {}         # (aya, word) -> display word
    for aya_no, w_from, w_to in spans:
        ayah = next((a for a in _page['ayat'] if a['aya'] == aya_no), None)
        if ayah is None:
            continue
        n_words = len(ayah['spans'])
        w_from = max(0, min(w_from, n_words - 1))
        w_to = max(w_from, min(w_to, n_words - 1))
        a = ayah['spans'][w_from][0]
        b = ayah['spans'][w_to][1]
        combined += ayah['phonemes'][a:b]
        for pos in range(a, b):
            owners = [w for w in owners_of(ayah['spans'], pos)
                      if w_from <= w <= w_to]
            owner_map.append((aya_no, owners[0]) if owners else None)
        for w in range(w_from, w_to + 1):
            key = (aya_no, w)
            words_text[key] = ayah['words'][w]
            order.append(key)

    if not combined or not order:
        return jsonify({'ok': False, 'reason': 'empty selection'})

    try:
        heard = predict(raw)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502
    if not heard:
        return jsonify({'ok': False, 'reason': 'nothing heard'})

    pass_rate = float(os.getenv('SELECT_PASS_RATE', '0.34'))
    passed, kind, exp_s, got_s = judge_word(combined, heard, pass_rate)

    # per-word detail so each selected word can be coloured
    ops, _dist = edit_ops(combined, heard)
    tally = {}
    for op, i, j in ops:
        owner = owner_map[i] if 0 <= i < len(owner_map) else None
        if owner is None:
            continue
        t = tally.setdefault(owner, {'ok': 0, 'bad': 0, 'exp': '', 'got': '',
                                     'vowel': False, 'madd': 0})
        if op == 'match':
            t['ok'] += 1
        else:
            t['bad'] += 1
            e_ch = combined[i] if i < len(combined) else ''
            g_ch = heard[j] if j < len(heard) else ''
            if e_ch:
                t['exp'] += e_ch
            if g_ch:
                t['got'] += g_ch
            if op == 'replace' and (e_ch in HARAKAT or g_ch in HARAKAT):
                t['vowel'] = True
            if op in ('delete', 'insert') and (e_ch or g_ch) in MADD_CHARS:
                t['madd'] += 1

    results = []
    with session.lock:
        for key in order:
            aya_no, w = key
            t = tally.get(key)
            skey = f"{aya_no}:{w}"
            if not t or (t['ok'] + t['bad']) < 2:
                results.append({'aya': aya_no, 'word_idx': w,
                                'status': 'unknown'})
                continue
            rate = t['bad'] / (t['ok'] + t['bad'])
            bad = rate > pass_rate or t['vowel'] or t['madd'] >= 1
            if not bad:
                k = 'ok'
            elif rate > pass_rate:
                k = 'shape'
            elif t['vowel']:
                k = 'vowel'
            else:
                k = 'madd'
            session.state[skey] = 'bad' if bad else 'good'
            session.errors = [e for e in session.errors
                              if not (e['aya'] == aya_no
                                      and e['word_idx'] == w)]
            if bad:
                session.errors.append({
                    'aya': aya_no, 'word_idx': w,
                    'word': words_text[key],
                    'expected': t['exp'][:14], 'heard': t['got'][:14],
                    'bad_rate': round(rate, 3), 'kind': k,
                })
            results.append({'aya': aya_no, 'word_idx': w,
                            'status': 'bad' if bad else 'good',
                            'kind': k, 'expected': t['exp'][:14],
                            'heard': t['got'][:14]})

    if VERBOSE:
        nbad = sum(1 for r in results if r.get('status') == 'bad')
        print(f"  [select] {len(order)} words / {len(spans)} span(s), "
              f"{nbad} bad")
        print(f"           want  {combined}")
        print(f"           heard {heard}")

    return jsonify({'ok': True, 'passed': passed, 'kind': kind,
                    'expected': combined, 'heard': heard,
                    'words': results, **session.snapshot()})


@app.route('/word_mode', methods=['POST'])
def word_mode():
    """Word-at-a-time practice.

    In live mode a chunk must be PLACED on the page, and a single word is
    usually too short to place reliably -- that is why reciting one word at a
    time did not work. Here the expected word is known in advance, so no
    placement is needed: we diff directly against that word's phonemes.
    """
    if _page is None:
        return jsonify({'error': 'no page'}), 400
    try:
        aya_no = int(request.form.get('aya'))
        widx = int(request.form.get('word_idx'))
    except Exception:
        return jsonify({'error': 'bad params'}), 400

    blob = request.files.get('audio')
    if blob is None:
        return jsonify({'error': 'no audio'}), 400

    ayah = next((a for a in _page['ayat'] if a['aya'] == aya_no), None)
    if ayah is None or widx >= len(ayah['spans']):
        return jsonify({'error': 'unknown word'}), 400

    raw = blob.read()
    audio, dur, rms = read_wav(raw)
    if audio is None or dur < 0.3:
        return jsonify({'ok': False, 'reason': 'too short'})
    if rms < 0.006:
        return jsonify({'ok': False, 'reason': 'silence'})

    try:
        heard = predict(raw)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502
    if not heard:
        return jsonify({'ok': False, 'reason': 'nothing heard'})

    a, b = ayah['spans'][widx]
    target = ayah['phonemes'][a:b]
    wide = ayah['phonemes'][max(0, a - 2):min(len(ayah['phonemes']), b + 2)]

    pass_rate = float(os.getenv('WORD_PASS_RATE', '0.34'))
    passed, kind, exp_s, got_s = judge_word(target, heard, pass_rate)
    if not passed:
        # a word said alone may carry linking sounds from its neighbours
        p2, k2, e2, g2 = judge_word(wide, heard, pass_rate)
        if p2:
            passed, kind, exp_s, got_s = p2, k2, e2, g2
    best = 0.0 if passed else 1.0

    key = f"{aya_no}:{widx}"
    with session.lock:
        session.state[key] = 'good' if passed else 'bad'
        session.errors = [e for e in session.errors
                          if not (e['aya'] == aya_no and e['word_idx'] == widx)]
        if not passed:
            session.errors.append({
                'aya': aya_no, 'word_idx': widx,
                'word': ayah['words'][widx],
                'expected': exp_s[:14], 'heard': got_s[:14],
                'bad_rate': round(best, 3), 'kind': kind,
            })

    if VERBOSE:
        print(f"  [word] {ayah['words'][widx]}  want {target!r} "
              f"heard {heard!r} rate={best:.2f} "
              f"-> {'PASS' if passed else kind}")

    return jsonify({'ok': True, 'passed': passed, 'rate': round(best, 3),
                    'expected': target, 'heard': heard, 'kind': kind,
                    **session.snapshot()})


@app.route('/retry', methods=['POST'])
def retry():
    """Re-check a single word the reciter tapped.

    Matching one word alone is easier than placing a chunk on the page: the
    reference is known exactly, so we only diff against that word's phonemes.
    """
    if _page is None:
        return jsonify({'error': 'no page'}), 400
    try:
        aya_no = int(request.form.get('aya'))
        widx = int(request.form.get('word_idx'))
    except Exception:
        return jsonify({'error': 'bad params'}), 400

    blob = request.files.get('audio')
    if blob is None:
        return jsonify({'error': 'no audio'}), 400

    ayah = next((a for a in _page['ayat'] if a['aya'] == aya_no), None)
    if ayah is None or widx >= len(ayah['spans']):
        return jsonify({'error': 'unknown word'}), 400

    raw = blob.read()
    audio, dur, rms = read_wav(raw)
    if audio is None or dur < 0.35:
        return jsonify({'ok': False, 'reason': 'too short'})
    if rms < 0.006:
        return jsonify({'ok': False, 'reason': 'silence'})

    try:
        heard = predict(raw)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502
    if not heard:
        return jsonify({'ok': False, 'reason': 'nothing heard'})

    a, b = ayah['spans'][widx]
    target = ayah['phonemes'][a:b]
    wide = ayah['phonemes'][max(0, a - 2):min(len(ayah['phonemes']), b + 2)]

    pass_rate = float(os.getenv('RETRY_PASS_RATE', '0.34'))
    passed, kind, exp_s, got_s = judge_word(target, heard, pass_rate)
    if not passed:
        p2, k2, e2, g2 = judge_word(wide, heard, pass_rate)
        if p2:
            passed, kind, exp_s, got_s = p2, k2, e2, g2
    best = 0.0 if passed else 1.0

    key = f"{aya_no}:{widx}"
    with session.lock:
        if passed:
            session.state[key] = 'good'
            session.errors = [e for e in session.errors
                              if not (e['aya'] == aya_no
                                      and e['word_idx'] == widx)]
        else:
            session.state[key] = 'bad'

    if VERBOSE:
        print(f"  [retry] {ayah['words'][widx]}  expected {target!r} "
              f"heard {heard!r}  rate={best:.2f} -> "
              f"{'PASS' if passed else 'again'}")

    return jsonify({'ok': True, 'passed': passed,
                    'rate': round(best, 3),
                    'expected': exp_s or target, 'heard': got_s or heard,
                    'kind': kind, **session.snapshot()})


def ensure_cert():
    """Create (once) a PERSISTENT self-signed certificate under ./certs.

    Flask's built-in 'adhoc' cert is regenerated on every restart, so a browser
    can never remember the exception -- the "not private" warning returns each
    launch. A stable cert on disk lets each browser accept it ONCE and stay
    quiet after that. Covers localhost, 127.0.0.1 and this laptop's LAN IP.

    Returns (cert_path, key_path), or None if it can't be built.
    """
    import datetime
    import ipaddress
    import socket

    cert_dir = os.path.join(APP_DIR, 'certs')
    cert_path = os.path.join(cert_dir, 'cert.pem')
    key_path = os.path.join(cert_dir, 'key.pem')
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except Exception:
        return None

    def _lan_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        except Exception:
            return None
        finally:
            s.close()

    alt = [x509.DNSName('localhost'),
           x509.IPAddress(ipaddress.IPv4Address('127.0.0.1'))]
    ip = _lan_ip()
    if ip:
        try:
            alt.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
        except Exception:
            pass

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Al-Muqri')])
    now = datetime.datetime.utcnow()
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .sign(key, hashes.SHA256()))

    os.makedirs(cert_dir, exist_ok=True)
    with open(key_path, 'wb') as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
    with open(cert_path, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f"  [tls] created persistent certificate in {cert_dir}")
    return cert_path, key_path


if __name__ == '__main__':
    port = int(os.getenv('PORT', '7070'))
    # 0.0.0.0 makes the app reachable from other PCs on your home Wi-Fi.
    # Set HOST=127.0.0.1 to keep it laptop-only.
    host = os.getenv('HOST', '0.0.0.0')
    # Browsers only allow the microphone over HTTPS (or on localhost). To let
    # the mic work on OTHER home PCs, launch with HTTPS=1 -- Flask then serves
    # a self-signed certificate (each browser shows a one-time warning to
    # accept). Without it the page still loads but recording is blocked.
    ssl_context = None
    if os.getenv('HTTPS', '0').lower() not in ('0', '', 'false', 'no'):
        try:
            import cryptography  # noqa: F401  -- cert building needs this
            # Prefer a persistent cert (exception sticks); fall back to adhoc.
            ssl_context = ensure_cert() or 'adhoc'
        except Exception:
            print("  [warn] HTTPS=1 but the 'cryptography' package is missing; "
                  "serving plain HTTP (mic will NOT work on other PCs).\n"
                  "         Fix with:  pip install cryptography")
    scheme = 'https' if ssl_context else 'http'
    print(f"  UI on {scheme}://{host}:{port}   engine {ENGINE}")
    app.run(host=host, port=port, threaded=True, ssl_context=ssl_context)
