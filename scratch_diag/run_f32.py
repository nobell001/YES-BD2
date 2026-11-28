import os, sys, unittest
sys.path.insert(0, os.getcwd())
import openvino
orig = openvino.Core.compile_model
def compile_f32(self, model, device_name=None, config=None, *a, **k):
    config = dict(config or {})
    config.setdefault("INFERENCE_PRECISION_HINT", "f32")
    return orig(self, model, device_name or "CPU", config, *a, **k)
openvino.Core.compile_model = compile_f32
unittest.main(module=None, argv=["unittest"] + sys.argv[1:])
