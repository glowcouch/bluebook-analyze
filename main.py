#!/usr/bin/env python3
"""
Extract time spent per question from a screen recording of a Bluebook practice SAT.

Reads the "Question N of M" label from the bottom bar and the
"Section X, Module Y: Subject" label from the top bar via OCR, then tracks
when the question changes. Time comes from the video timestamps, not the
on-screen timer.

Setup:
    pip install opencv-python pytesseract numpy
    # plus the tesseract binary:  brew install tesseract  /  apt install tesseract-ocr

Usage:
    python sat_question_times.py recording.mp4 --select-regions   # first time: pick crop boxes
    python sat_question_times.py recording.mp4                    # reuses saved regions.json
    python sat_question_times.py recording.mp4 --sample-fps 2 --out times.csv

Regions are saved as fractions of the frame size, so regions.json can be reused
for other recordings at the same layout/aspect ratio (any resolution).
Needs a GUI-capable OpenCV (opencv-python, not opencv-python-headless) for --select-regions.
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import OrderedDict

import cv2
import numpy as np
import pytesseract

QUESTION_RE = re.compile(r"Q\w{4,9}\s*(\d{1,2})\s*of\s*(\d{1,2})", re.IGNORECASE)
MODULE_RE = re.compile(r"Section\s*(\d)\s*[,.]?\s*Module\s*(\d)", re.IGNORECASE)


def preprocess(img):
    """Grayscale, upscale, normalise to dark-text-on-light, then Otsu threshold."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    if gray.mean() < 127:
        gray = cv2.bitwise_not(gray)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def ocr(img):
    return pytesseract.image_to_string(preprocess(img), config="--psm 6")


def parse_question(text):
    m = QUESTION_RE.search(text)
    if not m:
        return None
    n, total = int(m.group(1)), int(m.group(2))
    if 1 <= n <= total <= 99:
        return n, total
    return None


def parse_module(text):
    m = MODULE_RE.search(text)
    if not m:
        return None
    label = f"Section {m.group(1)}, Module {m.group(2)}"
    low = text.lower()
    if "math" in low:
        label += ": Math"
    elif "reading" in low:
        label += ": Reading and Writing"
    return label


def crop(frame, region):
    """Crop using a region given as fractions [x, y, w, h] of the frame."""
    h, w = frame.shape[:2]
    x, y, rw, rh = region
    x0, y0 = int(x * w), int(y * h)
    return frame[y0 : y0 + max(1, int(rh * h)), x0 : x0 + max(1, int(rw * w))]


def fit_for_display(frame, max_w=1400, max_h=800):
    h, w = frame.shape[:2]
    scale = min(1.0, max_w / w, max_h / h)
    if scale < 1.0:
        return cv2.resize(
            frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
        ), scale
    return frame.copy(), 1.0


def close_windows():
    cv2.destroyAllWindows()
    for _ in range(5):  # lets macOS actually close the window
        cv2.waitKey(1)


def pick_frame(path):
    """Scrub through the video with a slider and return the chosen frame."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        sys.exit(f"Could not open {path}")
    n = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) - 1)
    win = "Scrub to a frame showing a question, then press Enter (Esc to quit)"
    cv2.namedWindow(win)
    cv2.createTrackbar("frame", win, 0, n, lambda v: None)

    last_pos, shown = -1, None
    frame = None
    while True:
        pos = cv2.getTrackbarPos("frame", win)
        if pos != last_pos:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ok, f = cap.read()
            if ok:
                frame = f
                shown, _ = fit_for_display(f)
            last_pos = pos
        if shown is not None:
            cv2.imshow(win, shown)
        key = cv2.waitKey(30) & 0xFF
        if key in (13, 10, 32) and frame is not None:
            break
        if key in (27, ord("q")):
            close_windows()
            sys.exit("Cancelled.")
    close_windows()
    cap.release()
    return frame


def select_regions(path, out_path):
    """Let the user drag boxes for the bottom and top labels; save as fractions."""
    frame = pick_frame(path)
    disp, scale = fit_for_display(frame)
    dh, dw = disp.shape[:2]
    H, W = frame.shape[:2]

    prompts = [
        (
            "bottom",
            'Drag a box around "Question N of M" (bottom bar), then press Enter',
        ),
        (
            "top",
            'Drag a box around "Section X, Module Y: ..." (top bar, avoid the timer), then press Enter',
        ),
    ]
    regions = {}
    for name, prompt in prompts:
        shown = disp.copy()
        for r in regions.values():  # show what was already chosen
            x, y, w, h = r
            cv2.rectangle(
                shown,
                (int(x * dw), int(y * dh)),
                (int((x + w) * dw), int((y + h) * dh)),
                (0, 200, 0),
                2,
            )
        x, y, w, h = cv2.selectROI(prompt, shown, showCrosshair=False)
        close_windows()
        if w == 0 or h == 0:
            sys.exit("Selection cancelled.")
        regions[name] = [x / dw, y / dh, w / dw, h / dh]

    with open(out_path, "w") as f:
        json.dump(regions, f, indent=2)
    print(f"Saved regions to {out_path}")

    # Quick sanity check so you know straight away whether OCR can read the boxes.
    q = parse_question(ocr(crop(frame, regions["bottom"])))
    m = parse_module(ocr(crop(frame, regions["top"])))
    print(
        f"  bottom bar read as: {f'Question {q[0]} of {q[1]}' if q else 'NOTHING (try a tighter or wider box)'}"
    )
    print(f"  top bar read as:    {m or 'NOTHING (try a tighter or wider box)'}")
    return regions


def load_regions(path, top_frac, bottom_frac):
    if os.path.exists(path):
        with open(path) as f:
            r = json.load(f)
        print(f"Using regions from {path}", file=sys.stderr)
        return r
    print(
        f"No {path} found; falling back to full-width bars (run with --select-regions to pick boxes).",
        file=sys.stderr,
    )
    return {"top": [0, 0, 1, top_frac], "bottom": [0, 1 - bottom_frac, 1, bottom_frac]}


def scan_video(path, sample_fps, regions, debug_crops):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        sys.exit(f"Could not open {path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, round(video_fps / sample_fps))

    samples = []  # (time_s, (module, q, total) or None)
    module = None
    last_small = None
    last_q = None
    last_top_t = -1e9
    idx = -1
    dumped = False

    while cap.grab():
        idx += 1
        if idx % step:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            continue
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        bottom = crop(frame, regions["bottom"])
        top = crop(frame, regions["top"])

        if debug_crops and not dumped:
            cv2.imwrite("debug_top.png", top)
            cv2.imwrite("debug_bottom.png", bottom)
            dumped = True

        # Only re-OCR the bottom bar when it visibly changed (or last read failed).
        small = cv2.resize(cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY), (64, 8)).astype(
            int
        )
        changed = last_small is None or np.abs(small - last_small).mean() > 2.0
        if changed:
            q = parse_question(ocr(bottom))
            if q is not None:
                last_small = small
            last_q = q

        # Re-read the module label when the question changes, and every ~10 s.
        if (changed and last_q is not None) or t - last_top_t > 10:
            label = parse_module(ocr(top))
            if label:
                module = label
            last_top_t = t

        if last_q is None:
            samples.append((t, None))
        else:
            samples.append((t, (module or "Unknown module", last_q[0], last_q[1])))

        if total_frames and idx % (step * 200) == 0:
            print(f"  {idx / total_frames:5.1%} scanned", file=sys.stderr)

    cap.release()
    return samples


def build_segments(samples, confirm=2):
    """
    Turn noisy per-sample readings into (state, start, end) visits.
    A new state must be seen `confirm` samples in a row to be accepted, and it
    is dated from the first of those samples.
    """
    segs = []
    cur = cur_start = cur_last_seen = None
    cand = cand_start = None
    cand_n = 0
    interval = None

    prev_t = None
    for t, state in samples:
        if prev_t is not None and interval is None and t > prev_t:
            interval = t - prev_t
        prev_t = t

        if state is None:
            continue

        if cur is None:
            if state == cand:
                cand_n += 1
            else:
                cand, cand_start, cand_n = state, t, 1
            if cand_n >= confirm:
                cur, cur_start, cur_last_seen = cand, cand_start, t
                cand = None
            continue

        if state == cur:
            cur_last_seen = t
            cand = None
            continue

        if state == cand:
            cand_n += 1
        else:
            cand, cand_start, cand_n = state, t, 1
        if cand_n >= confirm:
            segs.append((cur, cur_start, cand_start))
            cur, cur_start, cur_last_seen = cand, cand_start, t
            cand = None

    if cur is not None:
        segs.append((cur, cur_start, cur_last_seen + (interval or 0)))
    return segs


def fmt(sec):
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:04.1f}"


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("video")
    ap.add_argument(
        "--sample-fps",
        type=float,
        default=2.0,
        help="frames per second to sample (default 2)",
    )
    ap.add_argument(
        "--select-regions",
        action="store_true",
        help="graphically pick the crop boxes and save them",
    )
    ap.add_argument(
        "--regions",
        default="regions.json",
        help="where regions are saved/loaded (default regions.json)",
    )
    ap.add_argument(
        "--top-frac",
        type=float,
        default=0.12,
        help="fallback if no regions file: top bar height fraction",
    )
    ap.add_argument(
        "--bottom-frac",
        type=float,
        default=0.12,
        help="fallback if no regions file: bottom bar height fraction",
    )
    ap.add_argument(
        "--confirm",
        type=int,
        default=2,
        help="consecutive samples needed to accept a change",
    )
    ap.add_argument("--out", default="question_times.csv", help="CSV of every visit")
    ap.add_argument(
        "--debug-crops",
        action="store_true",
        help="save debug_top.png / debug_bottom.png from the first frame",
    )
    args = ap.parse_args()

    if args.select_regions:
        regions = select_regions(args.video, args.regions)
    else:
        regions = load_regions(args.regions, args.top_frac, args.bottom_frac)

    samples = scan_video(args.video, args.sample_fps, regions, args.debug_crops)
    segs = build_segments(samples, args.confirm)
    if not segs:
        sys.exit(
            "No questions detected. Try --debug-crops and adjust --top-frac / --bottom-frac."
        )

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["module", "question", "of", "start_s", "end_s", "duration_s"])
        for (mod, q, total), start, end in segs:
            w.writerow(
                [mod, q, total, f"{start:.2f}", f"{end:.2f}", f"{end - start:.2f}"]
            )

    totals = OrderedDict()
    for (mod, q, total), start, end in segs:
        key = (mod, q, total)
        d = totals.setdefault(key, [0.0, 0])
        d[0] += end - start
        d[1] += 1

    print(f"\n{'Module':<34}{'Q':>6}{'Time':>9}{'Visits':>8}")
    print("-" * 57)
    last_mod = None
    mod_total = 0.0
    for (mod, q, total), (secs, visits) in sorted(
        totals.items(), key=lambda kv: (kv[0][0], kv[0][1])
    ):
        if mod != last_mod and last_mod is not None:
            print(f"{'':<34}{'total':>6}{fmt(mod_total):>9}\n")
            mod_total = 0.0
        last_mod = mod
        mod_total += secs
        print(f"{mod:<34}{f'{q}/{total}':>6}{fmt(secs):>9}{visits:>8}")
    print(f"{'':<34}{'total':>6}{fmt(mod_total):>9}")
    print(f"\nPer-visit detail written to {args.out}")


if __name__ == "__main__":
    main()
