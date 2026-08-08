"""Re-export the folded raw-audio -> logits model at a 4-second window (64000
samples). Static export (dynamic unfold fails on the legacy exporter). Feature
extraction (SeamlessM4T fbank) folded via matmul-DFT so no fft op is needed.
Verified to match HF fbank to ~7e-5 in the original session."""
import numpy as np, torch, time, os
from transformers import AutoFeatureExtractor
from quran_muaalem.modeling.modeling_multi_level_ctc import Wav2Vec2BertForMultilevelCTC

M = "obadx/muaalem-model-v3_2"
FIXED = 64000          # 4s @ 16kHz (app pads/truncates a selection to this)
OUT = "muaalem_raw_4s.onnx"

fe = AutoFeatureExtractor.from_pretrained(M)
model = Wav2Vec2BertForMultilevelCTC.from_pretrained(M).eval()
win = torch.tensor(np.asarray(fe.window), dtype=torch.float32)
mel = torch.tensor(np.asarray(fe.mel_filters), dtype=torch.float32)     # [257,80]
# precomputed real DFT (512-pt) as matmul -> ONNX-friendly (no fft op)
n = np.arange(512)[:, None]; k = np.arange(257)[None, :]
cosm = torch.tensor(np.cos(2*np.pi*n*k/512), dtype=torch.float32)       # [512,257]
sinm = torch.tensor(-np.sin(2*np.pi*n*k/512), dtype=torch.float32)
MEL_FLOOR = 1.192092955078125e-07

with torch.no_grad():
    out = model(torch.zeros(1, 99, 160), torch.ones(1, 99, dtype=torch.long), return_dict=True)
LEVELS = list(out.logits.keys())   # {level: [B,T,C]} dict lives under .logits

class Full(torch.nn.Module):
    def __init__(s):
        super().__init__(); s.m = model
        s.register_buffer("win", win); s.register_buffer("mel", mel)
        s.register_buffer("cosm", cosm); s.register_buffer("sinm", sinm)
    def forward(s, audio):                      # audio: [T] float32 (-1..1)
        x = audio * 32768.0
        fr = x.unfold(0, 400, 160)
        fr = fr - fr.mean(dim=1, keepdim=True)
        pre = torch.cat([(fr[:, :1]*0.03), (fr[:, 1:] - 0.97*fr[:, :-1])], dim=1)
        w = pre * s.win
        w = torch.nn.functional.pad(w, (0, 112))
        re = w @ s.cosm; im = w @ s.sinm
        power = re*re + im*im
        mspec = power @ s.mel
        lm = torch.log(torch.clamp(mspec, min=MEL_FLOOR))
        lm = (lm - lm.mean(0)) / torch.sqrt(lm.var(0, unbiased=True) + 1e-7)
        pad = (lm.shape[0] % 2)
        lm = torch.nn.functional.pad(lm, (0, 0, 0, pad))
        feats = lm.reshape(1, lm.shape[0]//2, 160)
        am = torch.ones(1, feats.shape[1], dtype=torch.long)
        o = s.m(feats, am, return_dict=False)
        d = o[0] if isinstance(o, (list, tuple)) else o   # length-1 tuple -> dict
        return tuple(d[l] for l in LEVELS)

full = Full().eval()
dummy = torch.zeros(FIXED, dtype=torch.float32)
onames = [f"logits_{l}" for l in LEVELS]
print("exporting static", FIXED, "->", OUT, flush=True)
t0 = time.time()
torch.onnx.export(
    full, (dummy,), OUT,
    input_names=["audio"], output_names=onames,
    opset_version=17, do_constant_folding=True, dynamo=False)  # legacy exporter
sz = os.path.getsize(OUT) + (os.path.getsize(OUT+".data") if os.path.exists(OUT+".data") else 0)
print("EXPORT OK", round(time.time()-t0), "s; MB:", round(sz/1e6, 1), flush=True)
print("LEVELS:", LEVELS, flush=True)

# sanity: run once and print phoneme-logits shape
import onnxruntime as ort
s = ort.InferenceSession(OUT, providers=["CPUExecutionProvider"])
r = s.run(None, {"audio": dummy.numpy()})
names = [o.name for o in s.get_outputs()]
ph = r[names.index("logits_phonemes")]
print("phoneme logits shape:", ph.shape, flush=True)
