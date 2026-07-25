"""
Build the mushaf page layout from the DOCX.

Unlike the PDF table (which listed ayah COUNTS in interleaved RTL columns and
lost digits during extraction), this document states every range explicitly:

    صفحة رقم 4 من القرآن الكريم - سورة البقرة - الآيات من 17- 24

so no counting, no inference, no column-order guessing. Each line gives the
page, the sura, and the exact first and last ayah.

    python build_layout_docx.py

Writes page_layout_full.json
"""

import json
import os
import re
import sys

DOCX = os.getenv('LAYOUT_DOCX',
                 'أرقام_صفحات_المصحف_وآيات_كل_صفحة_والسورة_التي_تقابلها.docx')
OUT = os.getenv('LAYOUT_OUT', 'page_layout_full.json')

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

AYAT = [7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99,
        128, 111, 110, 98, 135, 112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34,
        30, 73, 54, 45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37, 35, 38, 29,
        18, 45, 60, 49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12,
        12, 30, 52, 52, 44, 28, 28, 20, 56, 40, 31, 50, 40, 46, 42, 29, 19,
        36, 25, 22, 17, 19, 26, 30, 20, 15, 21, 11, 8, 8, 19, 5, 8, 8, 11, 11,
        8, 3, 9, 5, 4, 7, 3, 6, 3, 5, 4, 5, 6]
AYAT_PER_SURA = {i + 1: AYAT[i] for i in range(114)}


def norm(s):
    s = re.sub(r'[\u064B-\u0652\u0670\u0640]', '', s)
    s = s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    s = s.replace('ة', 'ه').replace('ى', 'ي')
    return ' '.join(s.split())


NAME_TO_IDX = {norm(n): i + 1 for i, n in enumerate(SURA_NAMES)}


def sura_index(text):
    c = norm(text)
    if c in NAME_TO_IDX:
        return NAME_TO_IDX[c]
    best, blen = None, 0
    for key, idx in NAME_TO_IDX.items():
        if key and key in c and len(key) > blen:
            best, blen = idx, len(key)
    return best


LINE = re.compile(
    r'صفحة\s*رقم\s*(\d+).*?سورة\s+(.+?)\s*-\s*الآيات\s*من\s*(\d+)\s*-\s*(\d+)')


def parse(path):
    import docx
    doc = docx.Document(path)
    rows = []
    bad = []
    for p in doc.paragraphs:
        t = ' '.join(p.text.split())
        if not t or 'صفحة' not in t:
            continue
        m = LINE.search(t)
        if not m:
            if 'الآيات' in t:
                bad.append(t[:90])
            continue
        page = int(m.group(1))
        sidx = sura_index(m.group(2))
        a, b = int(m.group(3)), int(m.group(4))
        if sidx is None:
            bad.append(f"unknown sura in: {t[:80]}")
            continue
        rows.append({'page': page, 'sura': sidx, 'from': a, 'to': b})
    return rows, bad


def main():
    if not os.path.exists(DOCX):
        print(f"DOCX not found: {DOCX}")
        return 1

    print("=" * 72)
    print("  BUILDING MUSHAF PAGE LAYOUT (from DOCX)")
    print("=" * 72)

    rows, bad = parse(DOCX)
    print(f"\n  parsed {len(rows)} page/sura entries")
    if bad:
        print(f"  {len(bad)} lines could not be parsed:")
        for b in bad[:5]:
            print(f"      {b}")

    pages = {}
    for r in rows:
        pages.setdefault(r['page'], []).append(
            {'sura': r['sura'], 'from': r['from'], 'to': r['to']})
    for p in pages:
        pages[p].sort(key=lambda x: (x['sura'], x['from']))

    print(f"  covering {len(pages)} distinct pages")

    # ---------------- verification ----------------
    print("\n  VERIFYING")
    checks = []

    def rng(page):
        rs = pages.get(page) or []
        return None if not rs else (rs[0]['sura'], rs[0]['from'],
                                    rs[-1]['sura'], rs[-1]['to'])

    for page, want in [(1, (1, 1, 1, 7)), (2, (2, 1, 2, 5)),
                       (3, (2, 6, 2, 16)), (4, (2, 17, 2, 24)),
                       (5, (2, 25, 2, 29))]:
        got = rng(page)
        checks.append((f"page {page} = {want}", got == want, got))

    missing = [p for p in range(1, 605) if p not in pages]
    checks.append(("all 604 pages present", not missing,
                   f"{len(missing)} missing: {missing[:10]}"))

    # every sura covered contiguously and completely
    seen = {}
    for p in sorted(pages):
        for r in pages[p]:
            seen.setdefault(r['sura'], []).append((r['from'], r['to']))
    bad_suras = []
    for s in range(1, 115):
        spans = sorted(seen.get(s, []))
        if not spans:
            bad_suras.append((s, 'missing'))
            continue
        if spans[0][0] != 1 or spans[-1][1] != AYAT_PER_SURA[s]:
            bad_suras.append((s, f"{spans[0][0]}..{spans[-1][1]} "
                                 f"vs 1..{AYAT_PER_SURA[s]}"))
            continue
        gaps = [i for i in range(1, len(spans))
                if spans[i][0] != spans[i - 1][1] + 1]
        if gaps:
            bad_suras.append((s, f"gap near ayah {spans[gaps[0]][0]}"))
    checks.append(("every sura complete and contiguous", not bad_suras,
                   bad_suras[:6]))

    total = sum(r['to'] - r['from'] + 1 for p in pages for r in pages[p])
    checks.append(("total ayat = 6236", total == 6236, total))

    print()
    all_ok = True
    for name, ok, detail in checks:
        all_ok = all_ok and ok
        print(("  PASS  " if ok else "  FAIL  ") + name)
        if not ok:
            print(f"          got: {detail}")

    if not all_ok:
        print("\n  Verification failed -- writing only what verifies.")

    good = {s for s in range(1, 115)
            if s not in {x[0] for x in bad_suras}}

    starts = {}
    for p in sorted(pages):
        for r in pages[p]:
            if r['sura'] not in good:
                continue
            starts.setdefault(r['sura'], [])
            if r['from'] not in starts[r['sura']]:
                starts[r['sura']].append(r['from'])
    for s in starts:
        starts[s] = sorted(starts[s])

    out = {
        'source': 'docx explicit ranges',
        'verified_suras': sorted(good),
        'starts': {str(k): v for k, v in sorted(starts.items())},
        'pages': {str(k): v for k, v in sorted(pages.items())},
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"\n  {len(good)}/114 suras verified")
    print(f"  wrote {OUT}")
    print("\n  first pages of Al-Baqarah:")
    for p in range(2, 9):
        rs = pages.get(p) or []
        print(f"    page {p}: " +
              ', '.join(f"{r['sura']}:{r['from']}-{r['to']}" for r in rs))
    return 0


if __name__ == '__main__':
    sys.exit(main())
