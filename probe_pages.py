"""
Does quran-transcript know the mushaf page numbers?

The standard Madani mushaf has 604 fixed pages -- Al-Baqarah's first page ends
at ayah 5, the next runs 6-16, and so on. Before hardcoding those boundaries,
check whether the library already carries them.

    conda activate quran_teacher
    cd C:\\Users\\user\\Quran_Teacher_v2
    python probe_pages.py
"""

import inspect

from quran_transcript import Aya


def main():
    a = Aya(2, 1)
    got = a.get()

    print("=" * 70)
    print("  WHAT DOES quran-transcript EXPOSE PER AYAH?")
    print("=" * 70)

    print("\n[1] attributes on Aya(2,1).get()")
    fields = [f for f in dir(got) if not f.startswith('_')]
    for f in fields:
        try:
            v = getattr(got, f)
        except Exception as exc:
            print(f"    {f:24s} <error: {exc}>")
            continue
        if callable(v):
            continue
        s = str(v)
        if len(s) > 60:
            s = s[:60] + '...'
        print(f"    {f:24s} {s}")

    print("\n[2] attributes on Aya(2,1) itself")
    for f in [x for x in dir(a) if not x.startswith('_')]:
        try:
            v = getattr(a, f)
        except Exception:
            continue
        if callable(v):
            print(f"    {f:24s} (method)")
        else:
            s = str(v)
            print(f"    {f:24s} {s[:60]}")

    print("\n[3] anything that looks page-related")
    hits = [f for f in fields if 'page' in f.lower() or 'safha' in f.lower()
            or 'juz' in f.lower() or 'hizb' in f.lower()]
    print(f"    {hits if hits else 'none found on the ayah object'}")

    print("\n[4] page numbers for the first ayat of Al-Baqarah")
    print("    (the standard mushaf ends page 2 at ayah 5,")
    print("     page 3 at ayah 16, page 4 at ayah 24)")
    for n in (1, 5, 6, 16, 17, 24, 25):
        try:
            g = Aya(2, n).get()
        except Exception as exc:
            print(f"    2:{n:<3} <error {exc}>")
            continue
        page = None
        for cand in ('page', 'page_number', 'safha', 'mushaf_page'):
            if hasattr(g, cand):
                page = getattr(g, cand)
                break
        print(f"    2:{n:<3} page={page}")

    print("\n[5] module-level helpers")
    import quran_transcript as qt
    names = [n for n in dir(qt) if not n.startswith('_')]
    print(f"    {names}")

    print("\n" + "=" * 70)
    print("""  If a page field exists, the app can use the real mushaf layout directly.
  If not, the boundaries have to come from a table of 604 page starts.""")
    print("=" * 70)


if __name__ == '__main__':
    main()
