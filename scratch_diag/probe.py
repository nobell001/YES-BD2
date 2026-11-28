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
variants = [
    ("caps plain", {}, ["-c", CAPS]),
    ("build prefix", {}, ["-m", "unittest", "tests.test_about_page", "tests.test_about_tab_layout", "tests.test_absorb_only_card", "tests.test_accounts", "tests.test_affinity_bank", T]),
    ("build prefix, f32 hint", {}, ["scratch_diag/run_f32.py", "tests.test_about_page", "tests.test_about_tab_layout", "tests.test_absorb_only_card", "tests.test_accounts", "tests.test_affinity_bank", T]),
    ("build prefix, ISA<=AVX512_CORE_BF16 (no AMX)", {"ONEDNN_MAX_CPU_ISA": "AVX512_CORE_BF16"}, ["-m", "unittest", "tests.test_about_page", "tests.test_about_tab_layout", "tests.test_absorb_only_card", "tests.test_accounts", "tests.test_affinity_bank", T]),
    ("build prefix again", {}, ["-m", "unittest", "tests.test_about_page", "tests.test_about_tab_layout", "tests.test_absorb_only_card", "tests.test_accounts", "tests.test_affinity_bank", T]),
    ("build prefix, f32 hint again", {}, ["scratch_diag/run_f32.py", "tests.test_about_page", "tests.test_about_tab_layout", "tests.test_absorb_only_card", "tests.test_accounts", "tests.test_affinity_bank", T]),
]
results = []
for label, extra, args in variants:
    env = dict(os.environ, **extra)
    cmd = [sys.executable, "-X", "faulthandler"] + args
    print(f"\n===== {label}: {extra}", flush=True)
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout + p.stderr).strip().splitlines()
    keep = [l for l in out if l.startswith("caps") or "fatal exception" in l or l.startswith("Ran ") or l in ("OK",) or l.startswith("FAILED") or "Error" in l][-8:]
    print("\n".join(keep))
    results.append((label, f"0x{p.returncode & 0xFFFFFFFF:08X}"))
print("\n===== SUMMARY")
for label, code in results:
    print(f"{code}  {label}")
