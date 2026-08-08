"""Sanity: compare int8-4s vs fp32-4s phoneme decode on a husary clip, and
print the decoded phonemes so we can eyeball correctness."""
import numpy as np, librosa, onnxruntime as ort, glob
from quran_muaalem.modeling.multi_level_tokenizer import MultiLevelTokenizer

tok = MultiLevelTokenizer("obadx/muaalem-model-v3_2")
id2v = tok.id_to_vocab["phonemes"]

def decode(logits):
    ids = logits.argmax(-1)
    out, prev = [], 0
    for i in ids:
        i = int(i)
        if i == 0: prev = 0; continue
        if i == prev: continue
        out.append(i); prev = i
    return "".join(id2v[i] for i in out)

# pick a short-ish husary file (ayah 1:1 basmala ~ within 4s)
cands = sorted(glob.glob("reference_audio/husary/00100*.mp3"))
mp3 = cands[0] if cands else sorted(glob.glob("reference_audio/husary/*.mp3"))[0]
audio, _ = librosa.load(mp3, sr=16000, mono=True)
pad = np.zeros(64000, dtype=np.float32)
pad[:min(len(audio), 64000)] = audio[:64000]
print("clip:", mp3, "len(s):", round(len(audio)/16000, 2))

def run(path):
    s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    names = [o.name for o in s.get_outputs()]
    r = s.run(None, {"audio": pad})
    return r[names.index("logits_phonemes")][0]

fp = run("_build4s/muaalem_raw_4s.onnx")
q8 = run("_build4s/muaalem_4s.int8.onnx")
h_fp = decode(fp); h_q8 = decode(q8)
print("fp32 heard:", h_fp)
print("int8 heard:", h_q8)
# frame-level argmax agreement
agree = (fp.argmax(-1) == q8.argmax(-1)).mean()
print("frame argmax agreement: {:.1%}".format(agree))
print("decoded-string match:", h_fp == h_q8)
