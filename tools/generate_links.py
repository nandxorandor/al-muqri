"""Add per-word tajweed 'links' to mobile quran_data.json.
Optimized: memoize phonetizations (common words repeat) and reuse the phoneme
spans already in quran_targets.json (skip build_word_spans)."""
import json, sys, os, time
from functools import lru_cache
sys.path.insert(0, os.getcwd())
from quran_transcript import Aya, quran_phonetizer, MoshafAttributes
from word_map import detect_links

M = MoshafAttributes(rewaya="hafs", madd_monfasel_len=2, madd_mottasel_len=4,
                     madd_mottasel_waqf=4, madd_aared_len=2, madd_alleen_len=2)
BAS = Aya(1, 1).get().uthmani

# reuse full-phoneme + spans already computed for judging
TGT = {}
td = json.load(open("mobile/www/quran_targets.json", encoding="utf-8"))
for k, v in td["pages"].items():
    s = k.split(":")[0]
    for a in v["ayat"]:
        TGT[f'{s}:{a["aya"]}'] = (a["phonemes"], a["spans"])

@lru_cache(maxsize=None)
def _ph(text):
    return quran_phonetizer(text, M, remove_spaces=True)
def cached_phonetizer(text, moshaf=None, remove_spaces=True):
    return _ph(text)

d = json.load(open("mobile/www/quran_data.json", encoding="utf-8"))
cache = {}
def links_for(sura, aya, is_bas, disp):
    key = (sura, aya, bool(is_bas))
    if key in cache: return cache[key]
    none = [{"prev": False, "next": False} for _ in disp]
    try:
        t = TGT.get(f"{sura}:{aya}")
        uthmani = BAS if (is_bas or aya == 0) else Aya(sura, aya).get().uthmani
        words = uthmani.split()
        if not t or len(words) != len(disp) or len(t[1]) != len(disp):
            res = none
        else:
            res = detect_links(uthmani, M, cached_phonetizer, t[0], t[1])
            if len(res) != len(disp): res = none
    except Exception:
        res = none
    cache[key] = res
    return res

t0 = time.time(); cnt = linked = 0; seen = set()
for k, page in d["pages"].items():
    sura = int(k.split(":")[0])
    for a in page["ayat"]:
        L = links_for(sura, a["aya"], a.get("is_basmalah"), a["words"])
        a["links"] = L
        cnt += 1; linked += sum(1 for x in L if x.get("prev") or x.get("next"))
    if sura not in seen:
        seen.add(sura)
        if sura % 20 == 0:
            print(f"...surah {sura}  ({int(time.time()-t0)}s, cache {_ph.cache_info().currsize})", flush=True)

json.dump(d, open("mobile/www/quran_data.json", "w", encoding="utf-8"),
          ensure_ascii=False, separators=(",", ":"))
print(f"DONE. ayat={cnt} linked_words={linked} time={int(time.time()-t0)}s", flush=True)
