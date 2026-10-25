# Yearbook Portrait Pipeline

Renames student photos from Microsoft Forms, then aligns and standardizes them with **MediaPipe**, so that every
portrait has its **eyes and mouth at the same coordinates**. The results can go straight into an InDesign photo grid.
Originals are never modified.

> **Moved into this repository (25 Oct 2026).** `run_yearbook.py` is now `step1_clean_images.py`; `config.toml`
> is now the `yearbook:` section of `pipeline.yaml` (input/output paths are under `question:` and `outputs:`);
> `yb/` is now `pipeline/yearbook/` and the models are in `pipeline/yearbook/models/`. Background removal is
> **on by default** (the old `--remove-bg`); `--keep-bg` skips it. The copy in `D:\book\python_code` is no longer used.

```
Input photos -> filename validation & renaming -> face detection -> landmarks
  -> eye-level rotation -> scale normalization -> reference-point alignment
  -> standardized crop -> quality checks -> export + reports
```

> **For AI agents:** read this file first. Always finish a run by relaying the **ATTENTION** list to the user
> (missing files, duplicates, wrong-account submissions, photos to review). The user wants that list every time.

## 1. Install (once)
```
pip install -r requirements-images.txt        (or use the conda env: conda activate madam-flasher-qr)
```
The models are already in `pipeline\yearbook\models\`: `face_landmarker.task` (478 landmarks plus irises) and
`blaze_face_short_range.tflite` (detection confidence). To download them again:
```
https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite
```
Tested with Python 3.13, mediapipe 1.1.1 and opencv 5.0.

## 2. Configure (`pipeline.yaml`)
Everything is set in one file. Paths are in `question:` (photo folder, Forms responses Excel) and `outputs:`
(`clean_images_dir`, `corrections_dir`); the rest is under `yearbook:`:
| Section | What it controls |
|---|---|
| `naming` | `responses` (names from the Forms Excel) or `filename` mode; name pattern; matric regex |
| `template` | output size and dpi, **eye-midpoint x/y**, **interocular distance**, **mouth_y**, mouth weight |
| `crop` | fill for missing borders, head/shoulder margin checks |
| `quality` | thresholds for confidence, pose (yaw/pitch/roll), blur, upscaling, closed eyes, mouth tolerance |
| `export` | png (default) or jpg, contact-sheet layout, Data Merge CSV encoding (name: `outputs.datamerge_csv`) |
| `background` | GPU background removal: on/off, model, transparent or solid colour |

Default template: **900 × 1125 px (4:5, 3 × 3.75 in at 300 dpi)**, eye midpoint at (450, 480),
interocular distance 172 px, mouth at y = 662. To change the framing, edit these numbers. For a larger head, raise
`interocular` and move `mouth_y` to about `eye_center_y + 1.06 × interocular`.

## 3. Run
```
cd C:\Users\balan\IdeaProjects\madam_flasher_qr
conda activate madam-flasher-qr
python step1_clean_images.py                           # whole folder
python step1_clean_images.py --only BS23110116 "LAU ZI" # reprocess selected photos (writes *_partial_* reports)
python step1_clean_images.py --settings other.yaml     # another event or year
python step1_clean_images.py --output-dir D:\tmp\test   # write somewhere else, e.g. to compare
```
148 photos take about 2 minutes with background removal on the GPU (about 30 seconds without).

## 4. Output (`output_dir`, default `D:\book\new_name`)
```
<MATRIC>.png             final portrait for every student (one per student, latest submission);
                         name set by [naming] pattern, currently "{matric}"
yearbook_datamerge.csv   InDesign Data Merge file (see below)
reports/                 (no needs_review folder: problems are listed in report.csv / attention.txt only;
                          older duplicate submissions and photos with no face are not exported)
  report.csv            status, original -> new name, pose, rotation, scale, mouth offset, padding, sharpness, warnings
  attention.txt         the ATTENTION list
  contact_sheet_NN.jpg  thumbnails with guides: cyan = target eye line and eye points, magenta = target mouth;
                        border green = ok, orange = review, red = fail (problem photos come first)
  manual_landmarks.csv  correction sheet for flagged photos (see section 5)
corrections/    put replacement photos here
```
Exports are **PNG**, sRGB (any embedded colour profile is converted), with an sRGB ICC profile at 300 dpi.
iPhone HEIC files are supported, including ones saved with a `.jpeg` extension.

### Data Merge CSV (`yearbook_datamerge.csv`)
The columns are exactly these, in this order:

| Program | year_of_study | student_id | name | id | quote | @photo_path |
|---|---|---|---|---|---|---|
| AQUACULTURE | Year 2 | BS25110295 | DARLINDA GINIHIM ASHTY ATAH | 1 | Life goal: ... | D:\book\new_name\BS25110295.png |

- There is **one row per student**. If a student submitted more than once, the latest submission (by Forms
  completion time) is used.
- Rows are sorted by **Program**, then **year_of_study**, then name. **id** is a unique sequence number
  (1, 2, 3, …) given after sorting. It is also the coupon **Backup No.** (step 2). A new student shifts the ids
  of everyone sorted after them, so after a full step 1 run, re-run step 2 and reprint the coupons.
- The **@** in `@photo_path` is required: it tells InDesign that the field holds an image path. The value is
  the full Windows path to the PNG in `output_dir`. If you move the folder, re-run the pipeline so the paths are
  rewritten.
- The **quote** has line breaks removed, because InDesign fields can't contain them.
- The file is saved as **UTF-16** so that special characters such as ‘ and accents import correctly into InDesign.
  Excel also opens it. To change the encoding, edit `datamerge_encoding` in pipeline.yaml.
- Photos flagged for review are still included, so that no student is missing from the layout. Their warnings are in
  `reports/report.csv` (status = review) and `reports/attention.txt`.
- `--only` runs don't rewrite this CSV. Run the whole folder to refresh it.

### InDesign
1. Make the template with a 4:5 image frame, set *Frame Fitting Options → Fit Content Proportionally*,
   and add text frames for the other fields.
2. Go to *Window → Utilities → Data Merge → Select Data Source* and choose `yearbook_datamerge.csv`.
3. Drag the fields in, then *Create Merged Document* (multiple records per page for a grid).

The eyes will line up across every row without any manual repositioning.

### Background removal (GPU)
On by default (`enabled: true` under `yearbook: background:` in pipeline.yaml); `mode` is `"transparent"` (the
user's choice). To skip it for one run:
```
python step1_clean_images.py --keep-bg
```
- It uses **rembg** with the `birefnet-portrait` model on the **NVIDIA GPU** (RTX 4070 Ti) through onnxruntime CUDA.
  The CUDA and cuDNN libraries come from pip wheels, so no separate CUDA install is needed. The model (~1 GB)
  downloads to `%USERPROFILE%\.u2net` on the first run. If no GPU is found, it falls back to the CPU (slower).
  The run log shows `on GPU` or `on CPU`.
- It runs **after** alignment, so the eye and mouth positions stay the same.
- `mode: 'color'` puts the person on a solid `color` (default white). `mode: 'transparent'` writes a PNG with alpha.
- If removal fails for a photo, the photo is flagged as `review`.
- Install: included in `requirements-images.txt` (do not also install the CPU `onnxruntime`).

## 5. Alignment method
- Landmarks: the iris centres (468/473) give the eye positions. The mouth centre is the mean of the inner lips
  (13, 14) and the mouth corners (61, 291).
- A **similarity transform only** is used (rotation + uniform scale + translation), so faces are never stretched.
  - Rotation makes the eye line horizontal.
  - Scale = `scale_eye^(1-w) · scale_mouth^w` with `w = mouth_weight` (0.3), clamped to ±10% of the eye-only
    scale. This moves the mouth towards `mouth_y` while keeping each person's real proportions.
  - Translation puts the eye midpoint exactly on the target point.
- Large downscales are resampled with INTER_AREA first, then warped with Lanczos.
- When a photo doesn't reach the portrait edge, the border pixels are extended (`fill = "replicate"`). If more than
  15% of the portrait is filled this way, the photo is flagged.

## 6. Quality checks (flag = status "review" in report.csv)
| Check | Meaning |
|---|---|
| no face / >1 face / low confidence | detection problem |
| yaw > 20°, pitch > 22°, roll > 25° | side-facing, looking up/down, strongly tilted |
| eyes may be closed | blink blendshape > 0.55 |
| upscaled > 1.6× | low-resolution source |
| sharpness < 6 | very blurry face |
| tightly cropped / head cut off | photo doesn't cover the frame or the hair area |
| little room above head / below chin | framing |
| duplicate matric, name conflict, bad matric format | naming |
| submitted from another account | the Forms account name differs from the typed name; confirm it's the right person |
| file name has another matric | the uploaded file name's matric differs from the typed one |
`flag_low_resolution` and `flag_tight_crop` are set to **false** (the user's choice): those photos are processed as well as
possible and logged as `[info]` instead of being flagged.
Smaller issues, such as a slight upscale, a small border fill or a mouth offset, are logged as `[info]` in report.csv only.

## 7. Fixing flagged photos, then re-running
Choose one of these per photo, then run again (or use `--only <matric>`):
1. **Better photo:** save it in `corrections/` named with the *new* name, e.g. `BS23110116.jpg`.
   It replaces the original for that student. The original file stays untouched.
2. **Accept as is:** in `reports/manual_landmarks.csv`, set `accept` to `yes` for that row. The photo is then no
   longer flagged.
3. **Wrong landmarks:** enter `left_eye_x/y`, `right_eye_x/y` (and optionally `mouth_x/y`), measured in pixels on
   the upright original photo. Detection is then skipped for that photo.

Each run replaces that student's earlier output.

## 8. Code layout
```
step1_clean_images.py          CLI entry point (prints the ATTENTION list)
pipeline.yaml                  all settings
pipeline/settings.py           loads pipeline.yaml and builds the settings dict for the modules below
pipeline/yearbook/naming.py    Forms-response mapping, renaming, duplicate/conflict/wrong-account checks
pipeline/yearbook/imageio.py   EXIF orientation, colour profile -> sRGB, HEIC, export
pipeline/yearbook/landmarks.py MediaPipe Face Landmarker + Face Detector, pose, blink
pipeline/yearbook/align.py     similarity transform, warp/crop, geometric quality checks
pipeline/yearbook/background.py GPU background removal (rembg)
pipeline/yearbook/report.py    CSV report, manual-correction sheet, contact sheets
pipeline/yearbook/run.py       orchestration, export to output_dir, Data Merge CSV
```
The simpler rename-only script is `tools/rename_form_uploads.py` (see `docs/rename_form_uploads.md`).
