"""Discover every test module like the Build, list native DLLs loaded, then run only the affinity tests."""
import os, sys, unittest
sys.path.insert(0, os.getcwd())
if "--f32" in sys.argv:
    import openvino
    orig = openvino.Core.compile_model
    def compile_f32(self, model, device_name=None, config=None, *a, **k):
        config = dict(config or {})
        config.setdefault("INFERENCE_PRECISION_HINT", "f32")
        return orig(self, model, device_name or "CPU", config, *a, **k)
    openvino.Core.compile_model = compile_f32
suite = unittest.TestLoader().discover("tests")
import psutil
paths = sorted({m.path for m in psutil.Process().memory_maps()} if hasattr(psutil.Process(), "memory_maps") else [])
for p in paths:
    low = p.lower()
    if low.endswith(".dll") and any(k in low for k in ("tbb", "omp", "openvino", "onnx", "dnnl", "mkl", "opencv", "cv2", "torch", "numpy", "openblas")):
        print("DLL", p)
print("env", {k: v for k, v in os.environ.items() if any(s in k for s in ("OMP", "OV_", "ONEDNN", "DNNL", "TBB", "MKL", "OPENBLAS"))})
def flat(s):
    for t in s:
        if isinstance(t, unittest.TestSuite):
            yield from flat(t)
        else:
            yield t
picked = unittest.TestSuite([t for t in flat(suite) if "test_affinity_talk" in t.id()])
print("running", picked.countTestCases(), flush=True)
r = unittest.TextTestRunner(verbosity=1).run(picked)
sys.exit(0 if r.wasSuccessful() else 1)
