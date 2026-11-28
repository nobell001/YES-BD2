"""Scratch diagnostic (never merge): why OpenVINO OCR dies with 0xC000001D in the Build test step."""
import ctypes, os, subprocess, sys

k32 = ctypes.windll.kernel32
k32.GetEnabledXStateFeatures.restype = ctypes.c_uint64
x = k32.GetEnabledXStateFeatures()
print(f"GetEnabledXStateFeatures = 0x{x:X}  AMX_TILECFG(17)={(x >> 17) & 1} AMX_TILEDATA(18)={(x >> 18) & 1}")
print("NUMBER_OF_PROCESSORS", os.environ.get("NUMBER_OF_PROCESSORS"))
if len(sys.argv) > 1 and sys.argv[1] == "probe-only":
    import openvino as ov
    c = ov.Core()
    print("caps", c.get_property("CPU", "OPTIMIZATION_CAPABILITIES"), "default", c.get_property("CPU", "INFERENCE_PRECISION_HINT"))
    sys.exit(0)

CAPS = "import openvino as ov; c=ov.Core(); print('caps', c.get_property('CPU','OPTIMIZATION_CAPABILITIES'), c.get_property('CPU','INFERENCE_PRECISION_HINT'))"
QT_CAPS = "from PySide6.QtWidgets import QApplication; import qfluentwidgets; a=QApplication([]); " + CAPS
T = "tests.test_affinity_talk"
D = ["-m", "unittest", "discover", "-s", "tests", "-k", "test_affinity_talk"]
variants = [
    ("caps plain", {}, ["-c", CAPS]),
    ("discover -k affinity (like Build)", {}, D),
    ("discover + DLL list", {}, ["scratch_diag/disc_dlls.py"]),
    ("discover + DLL list, f32 hint", {}, ["scratch_diag/disc_dlls.py", "--f32"]),
    ("discover -k affinity, ISA<=AVX512_CORE_VNNI", {"ONEDNN_MAX_CPU_ISA": "AVX512_CORE_VNNI"}, D),
    ("discover -k affinity, ISA<=AVX2", {"ONEDNN_MAX_CPU_ISA": "AVX2"}, D),
    ("discover -k affinity again", {}, D),
]
results = []
for label, extra, args in variants:
    env = dict(os.environ, **extra)
    cmd = [sys.executable, "-X", "faulthandler"] + args
    print(f"\n===== {label}: {extra}", flush=True)
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout + p.stderr).strip().splitlines()
    keep = [l for l in out if l.startswith("caps") or l.startswith("DLL") or l.startswith("env") or l.startswith("running") or "fatal exception" in l or l.startswith("Ran ") or l in ("OK",) or l.startswith("FAILED") or "Error" in l][-40:]
    print("\n".join(keep))
    results.append((label, f"0x{p.returncode & 0xFFFFFFFF:08X}"))
print("\n===== SUMMARY")
for label, code in results:
    print(f"{code}  {label}")
