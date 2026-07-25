"""
STEP 1 — Prove the pipeline end to end.

Records you reciting one ayah, runs it through the Muaalem model, and prints
the predicted phonemes against the reference phonemes.

Nothing is built on top of this until it demonstrably works.

Run:
    conda run -n quran_teacher python test_muaalem.py
"""

import sys
import time

SAMPLE_RATE = 16000
RECORD_SECONDS = 8

# Al-Fatihah 1:4  -- مَالِكِ يَوْمِ الدِّينِ
# The ayah where kasra vs fatha on مالك is the classic learner error.
SURA = 1
AYA = 4


def main():
    import numpy as np
    import torch

    try:
        import sounddevice as sd
    except ImportError:
        print("Missing sounddevice. Install with:")
        print("  conda run -n quran_teacher pip install sounddevice")
        sys.exit(1)

    from quran_transcript import Aya, quran_phonetizer, MoshafAttributes
    from quran_muaalem import Muaalem

    print("=" * 70)
    print("  MUAALEM PIPELINE TEST")
    print("=" * 70)

    # ---- 1. reference text ----
    aya = Aya(SURA, AYA)
    uthmani = aya.get().uthmani
    print(f"\n[1] Reference text ({SURA}:{AYA})")
    print(f"    {uthmani}")

    # ---- 2. recitation rules ----
    moshaf = MoshafAttributes(
        rewaya="hafs",
        madd_monfasel_len=2,
        madd_mottasel_len=4,
        madd_mottasel_waqf=4,
        madd_aared_len=2,
    )

    # ---- 3. phonetize the reference ----
    ref = quran_phonetizer(uthmani, moshaf, remove_spaces=True)
    print(f"\n[2] Reference phonemes (what CORRECT sounds like)")
    print(f"    {ref.phonemes}")

    # ---- 4. load model ----
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\n[3] Loading model on {device}...")
    muaalem = Muaalem(device=device)
    print("    ready")

    # ---- 5. record ----
    print(f"\n[4] Recording {RECORD_SECONDS}s.")
    print("    Recite this ayah. Try it CORRECTLY first, then run again")
    print("    with a deliberate mistake and compare.")
    input("\n    Press ENTER to start...")
    for i in range(3, 0, -1):
        print(f"      {i}...", end="\r", flush=True)
        time.sleep(1)
    print("      RECITE NOW!      ")

    rec = sd.rec(int(SAMPLE_RATE * RECORD_SECONDS),
                 samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    wave = np.squeeze(rec).astype("float32")
    peak = float(np.max(np.abs(wave))) or 1.0
    wave = wave / peak
    rms = float(np.sqrt(np.mean(wave ** 2)))
    print(f"      captured, rms={rms:.4f}")
    if rms < 0.01:
        print("      WARNING: very quiet")

    # ---- 6. run the model ----
    print("\n[5] Analyzing...")
    outs = muaalem([wave], [ref], sampling_rate=SAMPLE_RATE)
    out = outs[0]

    print(f"\n[6] RESULT")
    print(f"    reference : {ref.phonemes}")
    print(f"    you said  : {out.phonemes.text}")
    print(f"    match     : {'YES' if out.phonemes.text == ref.phonemes else 'NO -- differences found'}")

    # ---- 7. per-phoneme sifat, first few ----
    print(f"\n[7] Sifat for the first 8 phonemes")
    for sifa in out.sifat[:8]:
        grp = getattr(sifa, "phonemes_group", "?")
        bits = []
        for attr in ("hams_or_jahr", "shidda_or_rakhawa",
                     "tafkheem_or_taqeeq", "ghonna"):
            unit = getattr(sifa, attr, None)
            if unit is not None:
                bits.append(f"{attr}={getattr(unit, 'text', unit)}")
        print(f"    {grp:8s}  " + "  ".join(bits))

    print("\n" + "=" * 70)
    print("""  If the two phoneme strings differ where you made a mistake, the
  pipeline works and we build the app on top of it.

  Note: madd length shows up as REPEATED symbols. A 6-count madd is six
  alif symbols; holding it for 2 gives two. That is why length errors are
  visible here when they were invisible to every earlier approach.""")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"\nFAILED: {exc}")
