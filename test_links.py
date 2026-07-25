"""
Check the link detector against real ayat.

It should find fusions WITHOUT any hand-coded tajweed rules -- purely by
measuring whether phonetizing two words together is shorter than phonetizing
them apart. Known cases to look for:

    1:1  بِسْمِ + ٱللَّهِ      -> linked (the ٱ of ٱللَّه elides)
    1:7  وَلَا + ٱلضَّآلِّينَ  -> linked (madd, and the لا merges)
    1:2  ٱلْحَمْدُ + لِلَّهِ    -> linked

    python test_links.py
"""

from quran_transcript import Aya, quran_phonetizer, MoshafAttributes
from word_map import build_word_spans, detect_links

moshaf = MoshafAttributes(
    rewaya="hafs",
    madd_monfasel_len=2,
    madd_mottasel_len=4,
    madd_mottasel_waqf=4,
    madd_aared_len=2,
    madd_alleen_len=2,
)

TESTS = [(1, 1), (1, 2), (1, 4), (1, 7), (112, 1)]

print("=" * 70)
print("  LINK DETECTION — which words are phonetically fused")
print("=" * 70)

for sura, aya in TESTS:
    uthmani = Aya(sura, aya).get().uthmani
    full, spans = build_word_spans(uthmani, moshaf, quran_phonetizer)
    links = detect_links(uthmani, moshaf, quran_phonetizer, full, spans)
    words = uthmani.split()

    print(f"\n  {sura}:{aya}  {uthmani}")
    for i, w in enumerate(words):
        L = links[i] if i < len(links) else {}
        marks = []
        if L.get('prev'):
            marks.append('←linked to previous')
        if L.get('next'):
            marks.append('linked to next→')
        print(f"    {w:<16} {'  '.join(marks) if marks else '—'}")

    pairs = [f"{words[i]}+{words[i+1]}"
             for i in range(len(words) - 1)
             if i + 1 < len(links) and links[i].get('next')]
    print(f"    suggested pairs: {pairs if pairs else 'none'}")

print("\n" + "=" * 70)
print("""  Read this as: any word marked 'linked' will show a small arrow when
  selected, offering to include the neighbour it fuses with. Tapping is
  optional -- reciting the selection alone still works.""")
print("=" * 70)
