"""Feasibility test: export the quran-muaalem model to ONNX (for on-device use)."""
import os, time, numpy as np, torch
from transformers import AutoFeatureExtractor
from quran_muaalem.modeling.modeling_multi_level_ctc import Wav2Vec2BertForMultilevelCTC

MODEL = "obadx/muaalem-model-v3_2"
print("loading feature extractor + model (may take a minute)...", flush=True)
fe = AutoFeatureExtractor.from_pretrained(MODEL)
model = Wav2Vec2BertForMultilevelCTC.from_pretrained(MODEL).eval()

audio = np.zeros(int(16000 * 2), dtype=np.float32)           # 2s dummy
feat = fe(audio, sampling_rate=16000, return_tensors="pt")
inf, am = feat["input_features"], feat["attention_mask"]
print("input_features", tuple(inf.shape), "attention_mask", tuple(am.shape), flush=True)

with torch.no_grad():
    out = model(inf, am, return_dict=False)
if isinstance(out, dict):
    d = out
elif isinstance(out, (list, tuple)) and out and isinstance(out[0], dict):
    d = out[0]
else:
    d = dict(out)
levels = list(d.keys())
print("output levels:", levels, flush=True)

class Wrap(torch.nn.Module):
    def __init__(self, m, levels):
        super().__init__(); self.m = m; self.levels = levels
    def forward(self, input_features, attention_mask):
        o = self.m(input_features, attention_mask, return_dict=False)
        o = o if isinstance(o, dict) else (o[0] if isinstance(o, (list, tuple)) else dict(o))
        return tuple(o[l] for l in self.levels)

wrap = Wrap(model, levels)
onames = [f"logits_{l}" for l in levels]
dyn = {"input_features": {0: "b", 1: "t"}, "attention_mask": {0: "b", 1: "t"}}
for n in onames:
    dyn[n] = {0: "b", 1: "t"}

print("exporting to ONNX...", flush=True)
t0 = time.time()
torch.onnx.export(
    wrap, (inf, am), "muaalem.onnx",
    input_names=["input_features", "attention_mask"], output_names=onames,
    dynamic_axes=dyn, opset_version=17, do_constant_folding=True,
)
print(f"EXPORT OK in {time.time()-t0:.0f}s", flush=True)
print("onnx size MB:", round(os.path.getsize("muaalem.onnx") / 1e6, 1), flush=True)

# quick runtime sanity check
import onnxruntime as ort
sess = ort.InferenceSession("muaalem.onnx", providers=["CPUExecutionProvider"])
res = sess.run(None, {"input_features": inf.numpy(), "attention_mask": am.numpy()})
print("onnxruntime ran OK; output shapes:", [r.shape for r in res], flush=True)
