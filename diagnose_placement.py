"""
PLACEMENT DIAGNOSTIC — find out why a partial line is not being caught.

No guessing. This records YOUR actual recitation, sends it through the real
engine, and prints every candidate placement with its score, so we can see
exactly which offset was chosen, what the true offset should have been, and
what the numbers look like at each.

    conda activate quran_teacher
    cd C:\\Users\\user\\Quran_Teacher_v2
    python diagnose_placement.py

The engine must already be running (python run.py in another window), or this
will start its own model, which is slower.
"""

import os
import sys
import time
import wave
import io

import requests

SAMPLE_RATE = 16000
ENGINE = os.getenv('MUAALEM_ENGINE', 'http://127.0.0.1:8000')
SURA = int(os.getenv('DIAG_SURA', '1'))
AYA = int(os.getenv('DIAG_AYA', '5'))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from word_map import build_word_spans          # noqa: E402
from app import edit_ops, predict, MOSHAF_KW   # noqa: E402


def record(seconds, prompt):
    import numpy as np
    import sounddevice as sd
    print(f"\n  {prompt}")
    for i in range(3, 0, -1):
        print(f"    {i}...", end='\r', flush=True)
        time.sleep(1)
    print("    RECITE NOW!         ")
    rec = sd.rec(int(SAMPLE_RATE * seconds), samplerate=SAMPLE_RATE,
                 channels=1, dtype='float32')
    sd.wait()
    a = np.squeeze(rec).astype('float32')
    peak = float(np.max(np.abs(a))) or 1.0
    a = a / peak
    print(f"    captured {len(a)/SAMPLE_RATE:.1f}s "
          f"rms={float((a**2).mean()**0.5):.3f}")
    return a


def to_wav(audio):
    import numpy as np
    pcm = (np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes()
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def main():
    from quran_transcript import Aya, quran_phonetizer, MoshafAttributes

    moshaf = MoshafAttributes(**MOSHAF_KW)
    uthmani = Aya(SURA, AYA).get().uthmani
    phonemes, spans = build_word_spans(uthmani, moshaf, quran_phonetizer)
    words = uthmani.split()

    print("=" * 74)
    print("  PLACEMENT DIAGNOSTIC")
    print("=" * 74)
    print(f"\n  ayah {SURA}:{AYA}   {uthmani}")
    print(f"  reference phonemes ({len(phonemes)}): {phonemes}\n")
    for i, w in enumerate(words):
        a, b = spans[i]
        print(f"    word {i}  {w:<14} span=({a},{b})  {phonemes[a:b]}")

    try:
        requests.get(f"{ENGINE}/health", timeout=3)
    except Exception:
        print(f"\n  Engine not reachable at {ENGINE}.")
        print("  Start it first:  python run.py   (in another window)")
        return 1

    n_words = len(words)
    half = max(1, n_words // 2)

    trials = [
        (f"LAST words (say: {' '.join(words[half:])})", half, n_words - 1),
        (f"FIRST words (say: {' '.join(words[:half])})", 0, half - 1),
    ]

    for label, w_from, w_to in trials:
        audio = record(7, label)
        raw = to_wav(audio)
        heard = predict(raw)
        if not heard:
            print("    engine returned nothing")
            continue

        true_a = spans[w_from][0]
        true_b = spans[w_to][1]
        expected = phonemes[true_a:true_b]

        print(f"\n    heard    : {heard}")
        print(f"    expected : {expected}")
        print(f"    true span: ({true_a},{true_b})")

        n = len(heard)
        span_len = int(n * 1.3) + 6

        print(f"\n    {'offset':>7} {'word':<14} {'rate':>7}  segment")
        print("    " + "-" * 64)
        rows = []
        for i, (a, _b) in enumerate(spans):
            seg = phonemes[a:a + span_len]
            if len(seg) < n * 0.4:
                rows.append((a, i, None, seg))
                continue
            _ops, dist = edit_ops(seg, heard)
            rows.append((a, i, dist / n, seg))

        best = None
        for a, i, rate, seg in rows:
            mark = ''
            if a == true_a:
                mark = '   <-- TRUE POSITION'
            if rate is None:
                print(f"    {a:>7} {words[i]:<14} {'--':>7}  "
                      f"(too short){mark}")
                continue
            if best is None or rate < best[1]:
                best = (a, rate, i)
            print(f"    {a:>7} {words[i]:<14} {rate:>7.3f}  "
                  f"{seg[:26]}{mark}")

        if best:
            a, rate, i = best
            correct = (a == true_a)
            print(f"\n    CHOSEN   : offset {a} (word {i} = {words[i]}) "
                  f"rate={rate:.3f}")
            print(f"    CORRECT? : {'YES' if correct else 'NO'}")
            true_rate = next((r for aa, _i, r, _s in rows
                              if aa == true_a and r is not None), None)
            if true_rate is not None:
                print(f"    rate at the TRUE position: {true_rate:.3f}")
                if not correct:
                    print(f"    -> the wrong offset scored "
                          f"{true_rate - rate:.3f} better")
            print(f"\n    thresholds: needs <= "
                  f"{__import__('app').authoritative_rate_for(n):.3f} "
                  f"to overwrite,  <= {__import__('app').CHUNK_MAX_RATE} "
                  f"to place at all")

    print("\n" + "=" * 74)
    print("""  READING THIS
    * If CHOSEN matches the TRUE POSITION but the rate is above the
      'needs <=' threshold, the placement is fine and the threshold is
      simply too strict -- raise PARTIAL_SHORT_RATE.
    * If CHOSEN is a different offset, placement itself is wrong, and the
      rate at the true position tells us by how much.
    * If the rate at the true position is very high (say >0.4), the engine
      transcribed something quite different from the reference, and no
      threshold will help -- that is a phonetics mismatch, not a search bug.""")
    print("=" * 74)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
