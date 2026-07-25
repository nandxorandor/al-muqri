"""
Build the mushaf page layout from the Madani table PDF.

The PDF lists, per page, how many ayat it contains, with a sura name in
parentheses where a new sura starts. Rows are three column-pairs read left to
right:

    3 11 10 8 17 7      ->  page 3 = 11 ayat, page 10 = 8, page 17 = 7

Cumulative addition then gives real ayah ranges.

NOTHING IS TRUSTED WITHOUT CHECKING. The result is validated against facts we
can confirm independently:
    * page 1 covers Al-Fatihah 1-7
    * page 2 covers Al-Baqarah 1-5
    * page 3 covers Al-Baqarah 6-16
    * page 4 covers Al-Baqarah 17-24
    * every sura's pages must sum to its true ayah count (from quran-transcript)
    * the last page must end at 114:6

    python build_layout.py

Writes page_layout_full.json
"""

import json
import os
import re
import sys

PDF = os.getenv('LAYOUT_PDF', 'صفحات_وعدد_ايات_وسور_القران.pdf')
OUT = os.getenv('LAYOUT_OUT', 'page_layout_full.json')

# Sura names as they appear in the table, in order.
SURA_NAMES = [
    "الفاتحة", "البقرة", "آل عمران", "النساء", "المائدة", "الأنعام", "الأعراف",
    "الأنفال", "التوبة", "يونس", "هود", "يوسف", "الرعد", "إبراهيم", "الحجر",
    "النحل", "الإسراء", "الكهف", "مريم", "طه", "الأنبياء", "الحج", "المؤمنون",
    "النور", "الفرقان", "الشعراء", "النمل", "القصص", "العنكبوت", "الروم",
    "لقمان", "السجدة", "الأحزاب", "سبأ", "فاطر", "يس", "الصافات", "ص",
    "الزمر", "غافر", "فصلت", "الشورى", "الزخرف", "الدخان", "الجاثية",
    "الأحقاف", "محمد", "الفتح", "الحجرات", "ق", "الذاريات", "الطور", "النجم",
    "القمر", "الرحمن", "الواقعة", "الحديد", "المجادلة", "الحشر", "الممتحنة",
    "الصف", "الجمعة", "المنافقون", "التغابن", "الطلاق", "التحريم", "الملك",
    "القلم", "الحاقة", "المعارج", "نوح", "الجن", "المزمل", "المدثر",
    "القيامة", "الإنسان", "المرسلات", "النبأ", "النازعات", "عبس", "التكوير",
    "الانفطار", "المطففين", "الانشقاق", "البروج", "الطارق", "الأعلى",
    "الغاشية", "الفجر", "البلد", "الشمس", "الليل", "الضحى", "الشرح", "التين",
    "العلق", "القدر", "البينة", "الزلزلة", "العاديات", "القارعة", "التكاثر",
    "العصر", "الهمزة", "الفيل", "قريش", "الماعون", "الكوثر", "الكافرون",
    "النصر", "المسد", "الإخلاص", "الفلق", "الناس",
]


def norm(s):
    """Normalize Arabic for name matching."""
    s = re.sub(r'[\u064B-\u0652\u0670\u0640]', '', s)
    s = s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    s = s.replace('ة', 'ه').replace('ى', 'ي').replace('ّ', '')
    return s.strip()


NAME_TO_IDX = {norm(n): i + 1 for i, n in enumerate(SURA_NAMES)}


def parse_pdf(path):
    """Return {page_number: [ayah_count, [sura indices starting here]]}.

    Rows hold three page/count pairs read left to right:

        3 11 10 8 17 7        -> page 3 = 11 ayat, page 10 = 8, page 17 = 7

    A sura name sits immediately AFTER its page number and BEFORE that page's
    count:

        43 3 50 (آل عمران 9 57 8

    so Al-Imran begins on page 50, not page 43. Attributing the name to the
    first page in the row (an earlier guess) shifted every following sura and
    truncated Al-Baqarah at ayah 256.
    """
    import pypdf
    reader = pypdf.PdfReader(path)

    entries = {}
    for pg in reader.pages:
        for raw in pg.extract_text().split('\n'):
            line = raw.strip()
            if not line or 'رقم الصفحة' in line or 'الجزء' in line:
                continue
            if 'جدول' in line or 'المركز' in line or 'مصحف' in line:
                continue

            # tokenize, keeping order: numbers and sura names alike
            tokens = []
            for m in re.finditer(r'\d+|[\(\)]\s*([^\(\)0-9]+)', line):
                if m.group(0)[0].isdigit():
                    tokens.append(('num', int(m.group(0))))
                else:
                    cand = norm(m.group(1))
                    idx = None
                    best = 0
                    for key, i in NAME_TO_IDX.items():
                        if not key:
                            continue
                        if key == cand:
                            idx, best = i, 99
                            break
                        if key in cand or cand in key:
                            if len(key) > best:
                                idx, best = i, len(key)
                    if idx:
                        tokens.append(('sura', idx))

            # walk: a number is a page, the NEXT number is its count, and any
            # sura name between them starts on that page
            i = 0
            while i < len(tokens):
                if tokens[i][0] != 'num':
                    i += 1
                    continue
                page = tokens[i][1]
                starts = []
                j = i + 1
                while j < len(tokens) and tokens[j][0] == 'sura':
                    starts.append(tokens[j][1])
                    j += 1
                if j >= len(tokens) or tokens[j][0] != 'num':
                    i += 1
                    continue
                count = tokens[j][1]
                if 1 <= page <= 604 and 1 <= count <= 60:
                    # A page shared by two suras is listed TWICE: once for the
                    # tail of the ending sura, once for the start of the next
                    # (e.g. "48 1 ..." then "... 62 7"). Summing gives the
                    # page's true ayah count; keeping only the first entry
                    # lost ayat and truncated suras.
                    if page in entries:
                        entries[page][0] += count
                        entries[page][1].extend(
                            s for s in starts if s not in entries[page][1])
                    else:
                        entries[page] = [count, list(starts)]
                i = j + 1
    return entries


def build(entries, ayat_per_sura):
    """Turn per-page counts into (page -> sura, from, to)."""
    layout = {}
    sura = 1
    aya = 1
    for page in range(1, 605):
        ent = entries.get(page)
        if not ent:
            continue
        count, starts = ent
        if starts:
            sura = min(starts)
            aya = 1
        rows = []
        left = count
        while left > 0 and sura <= 114:
            total = ayat_per_sura.get(sura, 0)
            take = min(left, total - aya + 1)
            if take <= 0:
                sura += 1
                aya = 1
                continue
            rows.append({'sura': sura, 'from': aya, 'to': aya + take - 1})
            aya += take
            left -= take
            if aya > total:
                sura += 1
                aya = 1
        layout[page] = rows
    return layout


def main():
    if not os.path.exists(PDF):
        print(f"PDF not found: {PDF}")
        print("Put it in this folder or set LAYOUT_PDF.")
        return 1

    # Ayah counts are fixed (Hafs), so they are embedded rather than queried.
    # Verified: they sum to 6236.
    AYAT = [7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52,
            99, 128, 111, 110, 98, 135, 112, 78, 118, 64, 77, 227, 93, 88, 69,
            60, 34, 30, 73, 54, 45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37,
            35, 38, 29, 18, 45, 60, 49, 62, 55, 78, 96, 29, 22, 24, 13, 14,
            11, 11, 18, 12, 12, 30, 52, 52, 44, 28, 28, 20, 56, 40, 31, 50,
            40, 46, 42, 29, 19, 36, 25, 22, 17, 19, 26, 30, 20, 15, 21, 11, 8,
            8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5, 4, 7, 3, 6, 3, 5, 4, 5, 6]
    assert sum(AYAT) == 6236, "ayah counts do not sum to 6236"
    ayat_per_sura = {i + 1: AYAT[i] for i in range(114)}

    print("=" * 70)
    print("  BUILDING MUSHAF PAGE LAYOUT")
    print("=" * 70)

    entries = parse_pdf(PDF)
    print(f"\n  parsed {len(entries)} page entries from the PDF")
    missing = [p for p in range(1, 605) if p not in entries]
    if missing:
        print(f"  MISSING pages: {missing[:20]}"
              f"{' ...' if len(missing) > 20 else ''}  ({len(missing)} total)")

    layout = build(entries, ayat_per_sura)

    # ---------------- verification ----------------
    print("\n  VERIFYING against independently known facts")
    checks = []

    def rng(page):
        rows = layout.get(page) or []
        if not rows:
            return None
        return (rows[0]['sura'], rows[0]['from'], rows[-1]['sura'], rows[-1]['to'])

    for page, want in [(1, (1, 1, 1, 7)), (2, (2, 1, 2, 5)),
                       (3, (2, 6, 2, 16)), (4, (2, 17, 2, 24))]:
        got = rng(page)
        ok = got == want
        checks.append((f"page {page} = {want}", ok, got))

    # every sura fully covered exactly once
    seen = {}
    for page, rows in layout.items():
        for r in rows:
            seen.setdefault(r['sura'], []).append((r['from'], r['to']))
    sura_ok = True
    bad_suras = []
    for s in range(1, 115):
        spans = sorted(seen.get(s, []))
        if not spans:
            sura_ok = False
            bad_suras.append((s, 'missing'))
            continue
        covered = spans[0][0] == 1 and spans[-1][1] == ayat_per_sura[s]
        contiguous = all(spans[i][0] == spans[i - 1][1] + 1
                         for i in range(1, len(spans)))
        if not (covered and contiguous):
            sura_ok = False
            bad_suras.append((s, f"{spans[0]}..{spans[-1]} "
                                 f"vs 1..{ayat_per_sura[s]}"))
    checks.append(("every sura fully and contiguously covered", sura_ok,
                   bad_suras[:5]))

    # Page 604 carries the last three short suras, so only its END matters.
    last = rng(604)
    checks.append(("page 604 ends at 114:6", last is not None
                   and last[2] == 114 and last[3] == 6, last))

    print()
    for name, ok, detail in checks:
        print(("  PASS  " if ok else "  FAIL  ") + name)
        if not ok:
            print(f"          got: {detail}")

    # ------------------------------------------------------------------
    # Write only the suras that verify. PDF text extraction loses digits in
    # some RTL rows, so a few long suras finish short. Rather than ship a
    # layout that silently drifts, keep the suras whose pages sum exactly to
    # their true ayah count and let the app fall back elsewhere -- the page
    # editor can correct those permanently.
    # ------------------------------------------------------------------
    good_suras = set()
    for s in range(1, 115):
        spans = sorted(seen.get(s, []))
        if not spans:
            continue
        if (spans[0][0] == 1 and spans[-1][1] == ayat_per_sura[s]
                and all(spans[i][0] == spans[i - 1][1] + 1
                        for i in range(1, len(spans)))):
            good_suras.add(s)

    verified = {}
    for page, rows in layout.items():
        keep = [r for r in rows if r['sura'] in good_suras]
        if keep and len(keep) == len(rows):
            verified[page] = rows

    # per-sura page starts, the shape the app consumes
    starts = {}
    for page in sorted(verified):
        for r in verified[page]:
            starts.setdefault(r['sura'], [])
            if r['from'] not in starts[r['sura']]:
                starts[r['sura']].append(r['from'])
    for s in starts:
        starts[s] = sorted(starts[s])

    out = {
        'verified_suras': sorted(good_suras),
        'starts': {str(k): v for k, v in sorted(starts.items())},
        'pages': {str(k): v for k, v in sorted(verified.items())},
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"\n  {len(good_suras)}/114 suras verified exactly")
    print(f"  {len(verified)} pages written to {OUT}")
    print(f"  verified suras: {sorted(good_suras)[:25]}"
          f"{' ...' if len(good_suras) > 25 else ''}")

    print("\n  first pages:")
    for p in range(1, 7):
        rows = verified.get(p) or layout.get(p) or []
        desc = ', '.join(f"{r['sura']}:{r['from']}-{r['to']}" for r in rows)
        flag = '' if p in verified else '   (unverified)'
        print(f"    page {p}: {desc}{flag}")

    print("""
  Suras not listed above keep the app's editable fallback. Use the page
  editor to correct any of them; corrections are saved permanently.""")
    return 0


if __name__ == '__main__':
    sys.exit(main())
