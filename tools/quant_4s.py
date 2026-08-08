"""Mobile-compatible dynamic int8: quantize ONLY MatMul ops (-> MatMulInteger,
which onnxruntime-android supports), leaving Conv as fp32 (avoids ConvInteger,
which android does NOT implement). Still excludes the folded fbank DFT/mel
matmuls (cosm/sinm/mel) to keep feature extraction exact."""
import onnx, time, os
from onnxruntime.quantization import quantize_dynamic, QuantType

SRC = "_build4s/muaalem_raw_4s.onnx"
DST = "_build4s/muaalem_4s.int8.onnx"

m = onnx.load(SRC, load_external_data=False)
fb = {"cosm", "sinm", "mel"}
exclude = [n.name for n in m.graph.node
           if n.op_type in ("MatMul", "Gemm") and any(i in fb for i in n.input)]
print("excluding fbank matmuls:", exclude, flush=True)

t0 = time.time()
quantize_dynamic(
    SRC, DST,
    weight_type=QuantType.QInt8,
    op_types_to_quantize=["MatMul"],   # <- only MatMul; Conv stays fp32
    nodes_to_exclude=exclude,
)
sz = os.path.getsize(DST) + (os.path.getsize(DST+".data") if os.path.exists(DST+".data") else 0)
print("quantized in", round(time.time()-t0), "s; MB:", round(sz/1e6, 1), flush=True)

# report op types so we can confirm there is NO ConvInteger, only MatMulInteger
q = onnx.load(DST, load_external_data=False)
from collections import Counter
c = Counter(n.op_type for n in q.graph.node)
print("has ConvInteger:", c.get("ConvInteger", 0),
      " MatMulInteger:", c.get("MatMulInteger", 0),
      " Conv:", c.get("Conv", 0), flush=True)
