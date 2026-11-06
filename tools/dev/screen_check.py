"""Screen library check: what every screen recognizer says about real frames.

Leo 2026-11-05 「你要測試 反覆驗證 改動之前 能不能更穩定 還是又自廢武功」 and
「像之前學校1樓 3樓 就是你設計錯誤」: before a recognizer is added, loosened or
replaced, run it over a library of real game frames whose screen is known.
Its own frames must be recognized; no frame of another screen may be taken
for it.  ``compare`` lists the frames that were right before a change and
are wrong after it: one such frame is enough to hold the change back.

The library lives outside the repository (frames show player names):
``<library>/raw/<file>`` plus ``<library>/labels.json`` mapping each file to
its true screen.  ``<library>/index.json`` lists where each frame came from
(``repo:`` = a path in this repository), so ``build`` can lay out raw/ again
in a fresh session; a frame's name is the start of its SHA-1.  Screen names follow ``SCREENS`` below; anything else is
written as ``other:<what it is>``.

    build    copy the frames named in <library>/index.json into <library>/raw
    run      classify every frame, write results JSON
    sheet    contact sheets (numbered thumbnails) to check labels by eye
    report   per screen: frames, right, missed, misread (needs labels)
    compare  frames right in the old results and wrong in the new

Usage (Linux, from the repo root):
    QT_QPA_PLATFORM=offscreen PYTHONPATH=tools/linux_tests/shims:. \\
        ~/.cache/bd2-linux-venv/bin/python tools/dev/screen_check.py run LIB OUT.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

# What the shared classifier (Navigator.classify) can answer today.  A frame
# of any other screen must come back "unknown": taking it for one of these
# is a misread.
SCREENS = (
    "home",
    "card_menu",
    "sandbox",
    "area_map",
    "sandbox_map",
    "merchant_dialog",
    "shop",
    "cooking",
    "loading",
)


def load_frame(path: Path) -> np.ndarray:
    frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"unreadable frame: {path}")
    return frame


def cmd_build(args) -> None:
    import hashlib
    import shutil

    library = Path(args.library)
    raw = library / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    missing = []
    for entry in json.loads((library / "index.json").read_text(encoding="utf-8")):
        source = entry["source"]
        path = root / source[5:] if source.startswith("repo:") else Path(source)
        target = raw / entry["file"]
        if target.exists():
            continue
        if not path.exists() or hashlib.sha1(path.read_bytes()).hexdigest()[:12] != Path(entry["file"]).stem:
            missing.append(source)
            continue
        shutil.copyfile(path, target)
    print(f"{len(list(raw.iterdir()))} frames in {raw}; missing or changed: {len(missing)}")
    for source in missing:
        print(f"  {source}")


def _ocr_engine():
    import src  # noqa: F401  (installs the app's v6 recognizer)
    from ok.feature.Box import Box, sort_boxes
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr

    engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True, use_npu=False)

    def ocr(frame=None, threshold=0.2, box=None, match=None, target_height=0, **kwargs):
        """ok-script's onnx read, as the app does it: the box cut out, the
        picture shrunk by ``target_height`` against the whole frame
        (ok.feature.FeatureSet.resize_image), boxes mapped back to the frame,
        then filtered by ``match``."""
        from ok.feature.Box import find_boxes_by_name
        from ok.feature.FeatureSet import resize_image

        image = frame if frame is not None else kwargs.get("image")
        frame_height = image.shape[0]
        offset_x = offset_y = 0
        if box is not None:
            if isinstance(box, str):
                raise ValueError(f"named box not supported here: {box}")
            offset_x, offset_y = box.x, box.y
            image = image[box.y : box.y + box.height, box.x : box.x + box.width]
        image, scale = resize_image(image, frame_height, target_height)
        lines = engine.ocr(image)[0] or []
        boxes = []
        for pos, (text, confidence) in lines:
            width = round(pos[2][0] - pos[0][0])
            height = round(pos[2][1] - pos[0][1])
            if width > 0 and height > 0 and confidence >= threshold:
                boxes.append(
                    Box(
                        round(pos[0][0] / scale) + offset_x,
                        round(pos[0][1] / scale) + offset_y,
                        round(width / scale),
                        round(height / scale),
                        confidence,
                        text.strip(),
                    )
                )
        if match is not None:
            boxes = find_boxes_by_name(boxes, match)
        return sort_boxes(boxes)

    return ocr


def classifiers():
    """name -> fn(frame) -> answer, for every recognizer the check covers."""
    from src.tasks.map_trade.navigator import Navigator
    from src.tasks.map_trade.vision import Vision

    task = SimpleNamespace(
        config={"跑图跑商识图阈值": 0.72},  # the tasks' default (MapCollection, Bargain)
        ocr=_ocr_engine(),
        sleep=lambda *_a: None,
        info_set=lambda *_a: None,
        log_info=lambda *_a, **_k: None,
        log_debug=lambda *_a, **_k: None,
    )
    vision = Vision(task)
    navigator = Navigator(task, vision)

    def classify(frame):
        vision.capture = lambda: frame
        return navigator._classify_frame(frame).value

    def home(frame):
        vision.capture = lambda: frame
        passed, hits, brightness, gacha = navigator._home_confirmation_signals(frame)
        return {"home": bool(passed), "left_hits": hits, "p95": round(float(brightness)), "gacha": gacha}

    def where(frame):
        """classify, with a page under a popup answered "unknown"."""
        vision.capture = lambda: frame
        state = navigator._classify_frame(frame)
        return "unknown" if navigator.page_covered(frame, state) else state.value

    return {"classify": classify, "where": where, "home_signals": home}


def cmd_run(args) -> None:
    library = Path(args.library)
    files = sorted(p.name for p in (library / "raw").iterdir())
    if args.only:
        files = [f for f in files if f in set(args.only.split(","))]
    checks = classifiers()
    results = {}
    for number, name in enumerate(files, 1):
        frame = load_frame(library / "raw" / name)
        row = {}
        for check, fn in checks.items():
            try:
                row[check] = fn(frame)
            except Exception as error:  # a crash is a result too
                row[check] = f"error: {type(error).__name__}: {error}"
        results[name] = row
        print(f"{number}/{len(files)} {name} {row.get('classify')}", flush=True)
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_sheet(args) -> None:
    library = Path(args.library)
    names = json.loads(Path(args.files).read_text(encoding="utf-8")) if args.files else sorted(
        p.name for p in (library / "raw").iterdir()
    )
    per, cols, tw, th = args.per_sheet, 5, 384, 216
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(names), per):
        chunk = names[start : start + per]
        rows = (len(chunk) + cols - 1) // cols
        sheet = np.full((rows * (th + 24), cols * tw, 3), 255, np.uint8)
        for i, name in enumerate(chunk):
            thumb = cv2.resize(load_frame(library / "raw" / name), (tw, th), interpolation=cv2.INTER_AREA)
            y, x = (i // cols) * (th + 24), (i % cols) * tw
            sheet[y + 24 : y + 24 + th, x : x + tw] = thumb
            cv2.putText(sheet, str(start + i), (x + 4, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 200), 2)
        cv2.imwrite(str(out / f"sheet_{start:04d}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])
    (out / "order.json").write_text(json.dumps(names, ensure_ascii=False, indent=0), encoding="utf-8")


# Library labels that are not one of SCREENS but that a recognizer may
# fairly put in a broader group.  The first answer is the one wanted; the
# others are accepted.  Anything not listed must come back "unknown".
ACCEPT = {
    "collection": ("card_menu",),  # 游戏卡珍藏集
    "quick_switch": ("card_menu", "unknown"),  # P bar over a field
    "square": ("sandbox", "unknown"),  # 广场: a field with its own HUD
    "pvp_hub": ("sandbox", "unknown"),
    "field_quickbar": ("sandbox", "card_menu", "unknown"),
    "field_hud_hidden": ("unknown", "sandbox"),  # HUD gone (key held)
    "home_dimmed": ("unknown",),  # a popup over home: not safe to press home
}
# Frames that are not a whole game screen (crops, composites, the desktop).
SKIP = {"junk"}


def accepted(label: str) -> tuple[str, ...]:
    if label in SCREENS:
        return (label,)
    return ACCEPT.get(label, ("unknown",))


def expected(label: str) -> str:
    return accepted(label)[0]


def cmd_report(args) -> None:
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    table = {}
    misreads = []
    missed = []
    for name, label in labels.items():
        if name not in results or label in SKIP:
            continue
        got = results[name].get(args.check)
        ok = accepted(label)
        group = label if label in SCREENS or label in ACCEPT else "other"
        row = table.setdefault(group, {"frames": 0, "right": 0, "missed": 0, "misread": 0})
        row["frames"] += 1
        if got in ok:
            row["right"] += 1
        elif got == "unknown":
            row["missed"] += 1
            missed.append((name, label))
        else:
            row["misread"] += 1
            misreads.append((name, label, got))
    for screen in sorted(table):
        row = table[screen]
        print(
            f"{screen:16} frames {row['frames']:4}  right {row['right']:4}"
            f"  missed {row['missed']:4}  misread {row['misread']:4}"
        )
    print(f"misread (taken for another screen): {len(misreads)}")
    for name, label, got in misreads:
        print(f"  {name}: is {label}, read as {got}")
    if args.verbose:
        print(f"missed (came back unknown): {len(missed)}")
        for name, label in missed:
            print(f"  {name}: is {label}")


def cmd_compare(args) -> None:
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    old = json.loads(Path(args.old).read_text(encoding="utf-8"))
    new = json.loads(Path(args.new).read_text(encoding="utf-8"))
    worse, better = [], []
    for name, label in labels.items():
        if name not in old or name not in new or label in SKIP:
            continue
        ok = accepted(label)
        was, now = old[name].get(args.check) in ok, new[name].get(args.check) in ok
        if was and not now:
            worse.append((name, label, new[name].get(args.check)))
        elif now and not was:
            better.append((name, label, old[name].get(args.check)))
    print(f"right before, wrong now: {len(worse)}")
    for name, label, got in worse:
        print(f"  {name}: is {label}, now read as {got}")
    print(f"wrong before, right now: {len(better)}")
    sys.exit(1 if worse else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    build = sub.add_parser("build")
    build.add_argument("library")
    build.set_defaults(fn=cmd_build)
    run = sub.add_parser("run")
    run.add_argument("library")
    run.add_argument("out")
    run.add_argument("--only", default="")
    run.set_defaults(fn=cmd_run)
    sheet = sub.add_parser("sheet")
    sheet.add_argument("library")
    sheet.add_argument("out_dir")
    sheet.add_argument("--files", default="", help="JSON list of file names, in sheet order")
    sheet.add_argument("--per-sheet", type=int, default=30)
    sheet.set_defaults(fn=cmd_sheet)
    report = sub.add_parser("report")
    report.add_argument("labels")
    report.add_argument("results")
    report.add_argument("--check", default="classify", help="which answer to score (classify, where)")
    report.add_argument("-v", "--verbose", action="store_true", help="also list missed frames")
    report.set_defaults(fn=cmd_report)
    compare = sub.add_parser("compare")
    compare.add_argument("labels")
    compare.add_argument("old")
    compare.add_argument("new")
    compare.add_argument("--check", default="classify", help="which answer to score (classify, where)")
    compare.set_defaults(fn=cmd_compare)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
