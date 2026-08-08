"""Pre-generate Husary word-timing JSONs for all 114 surahs from the QUL API,
so word-level Listen works offline for any downloaded chapter. Output per surah:
mobile/www/audio/husary_timings/SSS.json = { "<aya>": [{word_idx,start_ms,end_ms}, ...], ... }"""
import os, json, time, requests

API = "https://qul.tarteel.ai/api/v1/audio/ayah_segments/20"
OUT = r"mobile\www\audio\husary_timings"
os.makedirs(OUT, exist_ok=True)

def fetch_surah(sura):
    ayat = {}
    frm = 1
    while True:
        r = requests.get(API, params={"surah": sura, "from": frm}, timeout=20)
        r.raise_for_status()
        segs = r.json().get("segments") or {}
        if not segs:
            break
        mx = 0
        for key, entry in segs.items():
            aya = int(key.split(":")[1]); mx = max(mx, aya)
            out = []
            for raw in entry.get("segments") or []:
                if not isinstance(raw, (list, tuple)) or len(raw) not in (3, 4):
                    continue
                if len(raw) == 4:
                    wi, _wid, s, e = raw
                else:
                    wi, s, e = raw
                try:
                    wi, s, e = int(wi), int(s), int(e)
                except (TypeError, ValueError):
                    continue
                if wi < 0 or s < 0 or e <= s:
                    continue
                out.append({"word_idx": wi, "start_ms": s, "end_ms": e})
            if out:
                ayat[aya] = sorted(out, key=lambda x: x["word_idx"])
        if mx < frm:            # no forward progress -> done
            break
        frm = mx + 1
    return ayat

total = 0
for sura in range(1, 115):
    try:
        ayat = fetch_surah(sura)
    except Exception as ex:
        print(f"sura {sura} FAIL: {ex}", flush=True); continue
    json.dump({str(a): ayat[a] for a in sorted(ayat)},
              open(os.path.join(OUT, f"{sura:03d}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    total += len(ayat)
    if sura % 10 == 0 or sura in (1, 114):
        print(f"sura {sura}: {len(ayat)} ayat", flush=True)
    time.sleep(0.05)

sz = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
print(f"DONE. {total} ayat total; timings size {sz/1e6:.2f} MB", flush=True)
