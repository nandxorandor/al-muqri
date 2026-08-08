import json, glob, numpy as np, librosa, onnxruntime as ort, difflib
from quran_muaalem.modeling.multi_level_tokenizer import MultiLevelTokenizer
tok=MultiLevelTokenizer("obadx/muaalem-model-v3_2"); id2v=tok.id_to_vocab["phonemes"]
d=json.load(open("mobile/www/quran_targets.json",encoding="utf-8"))
TARGET={}
for k,v in d["pages"].items():
    s=k.split(":")[0]
    for a in v["ayat"]: TARGET[s+":"+str(a["aya"])]=a
sess=ort.InferenceSession("mobile/www/model/muaalem.onnx",providers=["CPUExecutionProvider"])
onames=[o.name for o in sess.get_outputs()]; N=64000
def dec(ph):
    ids=ph.argmax(-1); out=[];prev=0
    for i in ids:
        i=int(i)
        if i==0: prev=0; continue
        if i==prev: continue
        out.append(i);prev=i
    return "".join(id2v[i] for i in out)
def heard_for(mp3):
    au,_=librosa.load(mp3,sr=16000,mono=True); au=au.astype(np.float32)
    tot=min(len(au),N*4); h=""
    for off in range(0,tot,N):
        seg=au[off:off+N]; a=np.zeros(N,dtype=np.float32); a[:len(seg)]=seg
        ph=sess.run(None,{"audio":a})[onames.index("logits_phonemes")][0]
        vf=max(1,min(ph.shape[0],round(len(seg)*ph.shape[0]/N)))
        h+=dec(ph[:vf])
    return h
# test surah 114 (An-Nas)
for mp3 in sorted(glob.glob("reference_audio/husary/114*.mp3")):
    fn=mp3.replace("\\","/").split("/")[-1][:6]; s=str(int(fn[:3])); a=str(int(fn[3:]))
    key=s+":"+a
    if key not in TARGET: print(key,"NO TARGET"); continue
    tgt=TARGET[key]["phonemes"]; h=heard_for(mp3)
    sim=difflib.SequenceMatcher(None,tgt,h).ratio()
    print(f"{key} sim={sim:.0%}  tgt={tgt}  heard={h}")
