# Tool to analyze bluebook practice tests

Disclaimer: this is entirely written by claude - I don't typically vibe-code things, but wanted this tool and don't have the time to make it myself.

I wanted to analyze how much time I spent on different question types.

And now onto the llm-written description:

# Usage

Extract the time spent on each question from a screen recording of a Bluebook practice SAT.

The script reads two labels off the screen with OCR:

- `Question N of M` in the bottom bar
- `Section X, Module Y: Math` in the top bar

It then tracks when the question changes and times each visit using the **video timestamps**. The on-screen timer is not used.

## Requirements

- Python 3 with `opencv`, `numpy`, `pytesseract`
- The `tesseract` binary
- For `--select-regions` only: an OpenCV build with GUI support (`opencv-python`, not `opencv-python-headless`)

### pip

```sh
pip install opencv-python pytesseract numpy
# plus tesseract: brew install tesseract / apt install tesseract-ocr
```

### Nix

```nix
py = pkgs.python3.withPackages (ps: with ps; [
  (opencv4.override { enableGtk3 = true; })  # GUI build, needed for --select-regions
  numpy
  pytesseract
]);
```

## Quick start

```sh
# 1. First time: pick the two crop boxes (saved to regions.json)
python sat_question_times.py recording.mp4 --select-regions

# 2. Later runs reuse regions.json
python sat_question_times.py recording.mp4
```

## Picking the regions

`--select-regions` walks you through three steps:

1. **Scrub** with the slider to a frame where a question is on screen, then press Enter.
2. **Bottom box:** drag a box around `Question N of M`, then press Enter.
3. **Top box:** drag a box around `Section X, Module Y: ...`, then press Enter. Keep the timer out of this box.

The script OCRs both boxes on that frame and prints what it read, so you know immediately whether they work. Tight boxes give cleaner OCR.

Regions are saved as **fractions of the frame size**, so `regions.json` can be reused for other recordings with the same layout, even at a different resolution.

## Options

| Option | Default | What it does |
|---|---|---|
| `video` | (required) | Path to the screen recording. |
| `--select-regions` | off | Open the graphical picker and save the boxes, then run the scan. |
| `--regions PATH` | `regions.json` | Where the boxes are saved or loaded. |
| `--sample-fps N` | `2` | Frames sampled per second. Raise it if short visits get missed. |
| `--confirm N` | `2` | Consecutive samples a new question must appear in before it counts. Raise it if OCR noise splits questions. |
| `--out PATH` | `question_times.csv` | CSV with every individual visit. |
| `--always-ocr` | off | OCR the bottom bar on every sample instead of only when it changes. Slower, but useful to check whether change detection is missing questions. |
| `--debug-crops` | off | Save `debug_top.png` and `debug_bottom.png` from the first frame, to check what the OCR sees. |
| `--top-frac F` | `0.12` | Fallback only (no regions file): height of the top bar as a fraction of the frame. |
| `--bottom-frac F` | `0.12` | Fallback only (no regions file): height of the bottom bar as a fraction of the frame. |

## Output

**Terminal:** a per-module table of total time and number of visits for each question, with a module total.

```
Module                                 Q     Time  Visits
---------------------------------------------------------
Section 2, Module 1: Math           1/22    1:12.5       1
Section 2, Module 1: Math           2/22    0:48.0       2
...
                                  total   31:40.5
```

**CSV** (`question_times.csv`): one row per visit, with columns `module, question, of, start_s, end_s, duration_s`. A question you revisit has one row per visit, and the terminal table sums them.

## How it works

1. Video frames are sampled at `--sample-fps`.
2. Each region is cropped, upscaled, thresholded, and read with Tesseract.
3. The bottom box is only re-OCR'd when it visibly changes. The top box is re-read when the question changes and every ~10 s.
4. A new `(module, question, total)` state must be seen `--confirm` times in a row, and is dated from the first of those samples.
5. Consecutive states become visits. Time is `end - start` in video seconds.

## Notes and limitations

- **Review screen:** if the bottom bar still shows the last question number there, that time is credited to that question.
- **Failed OCR reads** are skipped and the previous state is held.
- **Module label:** if it can't be read, the last known module is carried forward. If it has never been read, the module shows as `Unknown module`.
- **Selector troubleshooting:**
  - The picker needs a GUI-capable OpenCV.
  - On Wayland with the pip `opencv-python` wheel, it runs through XWayland. If it fails to open, try `QT_QPA_PLATFORM=xcb python sat_question_times.py recording.mp4 --select-regions`.
  - You can also write `regions.json` by hand and verify it with `--debug-crops`:

    ```json
    {
      "bottom": [0.42, 0.93, 0.16, 0.05],
      "top":    [0.30, 0.01, 0.40, 0.05]
    }
    ```

    Each box is `[x, y, width, height]` as fractions of the frame.
