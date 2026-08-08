"""Concatenate per-word mujawwad opus into ONE file per surah + a word-timing
JSON (Husary-style), so word-by-word audio ships as ~114 files instead of 77k
(APKs cap at 65535 zip entries). Re-encodes to 24kbps mono opus to shrink size.
Word durations read from the Ogg granule position (fast, no per-file ffprobe)."""
import os, glob, json, struct, subprocess, sys

FFMPEG = r"C:\ffmpeg-8.1.1-essentials_build\bin\ffmpeg.exe"
SRC = r"reference_audio\mujawwad"
OUT = r"mobile\www\audio\wbw"
os.makedirs(OUT, exist_ok=True)

def opus_duration_ms(path):
    # last OggS page granulepos is total samples @48kHz -> ms = gp/48
    with open(path, "rb") as f:
        f.seek(0, 2); size = f.tell()
        tail = min(size, 65536); f.seek(size - tail); data = f.read()
    idx = data.rfind(b"OggS")
    if idx < 0 or idx + 14 > len(data): return 0.0
    gp = struct.unpack("<q", data[idx + 6:idx + 14])[0]
    return max(0.0, gp / 48.0)

total_out = 0
for sura in range(1, 115):
    sdir = os.path.join(SRC, f"{sura:03d}")
    files = glob.glob(os.path.join(sdir, f"{sura:03d}_*.opus"))
    if not files: continue
    def key(p):
        b = os.path.basename(p)[:-5].split("_"); return (int(b[1]), int(b[2]))
    files.sort(key=key)
    segments = []; t = 0.0; lines = []
    for p in files:
        b = os.path.basename(p)[:-5].split("_"); aya = int(b[1]); word = int(b[2])
        dur = opus_duration_ms(p)
        segments.append({"aya": aya, "word_idx": word - 1,
                         "start_ms": int(t), "end_ms": int(t + dur)})
        t += dur
        lines.append("file '" + os.path.abspath(p).replace("\\", "/") + "'")
    lp = os.path.join(OUT, f"{sura:03d}.txt")
    open(lp, "w", encoding="utf-8").write("\n".join(lines))
    outp = os.path.join(OUT, f"{sura:03d}.opus")
    r = subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", lp,
                        "-c:a", "libopus", "-b:a", "24k", "-ac", "1", outp],
                       capture_output=True, text=True)
    os.remove(lp)
    if r.returncode != 0 or not os.path.exists(outp):
        print(f"SURA {sura} FFMPEG FAIL: {r.stderr[-300:]}", flush=True); continue
    json.dump({"segments": segments},
              open(os.path.join(OUT, f"{sura:03d}.json"), "w", encoding="utf-8"))
    total_out += os.path.getsize(outp)
    if sura % 10 == 0 or sura in (1, 114):
        print(f"sura {sura}: {len(files)} words, {int(t)}ms", flush=True)

print(f"DONE. total wbw audio MB: {total_out/1e6:.1f}", flush=True)
