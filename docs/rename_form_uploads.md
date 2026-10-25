# Rename Microsoft Forms photo uploads (Majlis Anugerah Dekan)

Instructions for a person or AI agent repeating this job.

> **Moved into this repository (25 Oct 2026):** this script is `tools/rename_form_uploads.py`, the yearbook
> pipeline is `step1_clean_images.py` with its settings in `pipeline.yaml` (see `docs/yearbook.md`), and
> `round_canvas.py` is `tools/round_canvas.py`. The copies in `D:\book\python_code` are no longer used.

## Problem
Students upload photos through Microsoft Forms. The files arrive in OneDrive with messy names
(for example `fb60d0e3-..._RACHEL RURAN ROGER.jpg`), so it isn't clear who sent each one.
The "Modified by" detail exists only in OneDrive online, not on the local PC, and getting it through
Microsoft Graph device-code sign-in failed: the code timed out after 2 minutes. **Don't use that route.**

## Solution
Use the **Forms responses Excel** (Forms → Responses → Open in Excel). The photo column holds a
SharePoint link per response, and the link ends with the uploaded file name. Match that name to the local file.

## Inputs (defaults in the script)
| Item | Path |
|---|---|
| Uploaded photos | `C:\Users\balan\OneDrive - ums.edu.my\Question` |
| Responses Excel | `...\Question\MAJLIS ANUGERAH DEKAN & APRESIASI MAHASISWA SESSION 2025_2026(1-170).xlsx` |
| Output folder | `C:\Users\balan\OneDrive\Desktop\new_name` |

Columns used (matched by header prefix): `Email`, `Name`, `FULL NAME`, `MATRIC NUMBER`,
`PROGRAMME`, `Please Upload a Photo`.

## Run
```
pip install openpyxl
python tools\rename_form_uploads.py
# or with other paths:
python tools\rename_form_uploads.py "<photo folder>" "<responses.xlsx>" "<output folder>"
```
On Windows with Git Bash, set `PYTHONIOENCODING=utf-8` if printing fails on special characters.

## Rules
- **Non-destructive:** copy the files, never rename or move the originals. Output goes to a separate folder.
- New name: `<MATRIC>_<FULL NAME>.<ext>`. Use the typed full name, or the Forms account name if that is blank.
  Repeat submissions get ` (2)`, ` (3)`.
- `File_Name_Mapping.xlsx` goes in the output folder. Sheet **Mapping** has original name, new name,
  submitter name and email, matric, programme and status, with problem rows highlighted yellow.
  Sheet **Attention** lists the issues.

## Attention report (the user wants this, so always relay it)
At the end the script prints an **ATTENTION** list. Report every item to the user plainly:
- An upload is listed in the responses but missing from the folder → re-download it from the link.
- A file is in the folder but has no matching response → probably an older or replaced upload, so it isn't copied.
- Matric number is missing or unusual (expected format: 2 letters + 8 digits, e.g. BS25110295).
- Duplicate submissions.

## 2025/2026 run result (for reference)
149 uploads, 148 copied. Missing: `BS23110222_WONG YI ROU.JPG`. Unmatched in folder:
`BS25110012.jpeg`, `BS25110012_NG WEI JUN -.jpeg`, `BS25110108_PUTRI ALYATASHA BINT.jpg`.

## Converted portraits with background removal (Python + GPU)
When the user asks for "converted" photos, rename-only is not enough. Run the yearbook pipeline in
`step1_clean_images.py` (full details in `docs/yearbook.md`). It renames from the same responses Excel,
aligns every face (eyes and mouth at the same position), **removes the background on the GPU**, and saves
PNGs plus an InDesign Data Merge CSV to **`D:\book\new_name`**.

The user's current choices (already set in `pipeline.yaml`, section `yearbook:`):
- **Transparent background:** `mode: 'transparent'`. Each output is an RGBA PNG, and the area outside the person
  has alpha 0. Contact sheets show the transparent areas on a grey checkerboard.
- **Matric-only file names:** `pattern: '{matric}'`, e.g. `BS23110058.png`, not
  `BS23110058_AMIRATUL FAZIRAH BINTI AMIU.png`. Replacement photos in `corrections\` are named the same way
  (e.g. `BS23110058.jpg`). This applies to the yearbook pipeline only; the rename-only script above still writes
  `<MATRIC>_<FULL NAME>`.

Background removal uses **rembg** with the `birefnet-portrait` model on the NVIDIA RTX 4070 Ti through
onnxruntime CUDA (CUDA/cuDNN come from pip wheels, no separate CUDA install). It runs after alignment and gives
a transparent background (`yearbook: background:` in `pipeline.yaml`: `mode`, `color` for `mode: 'color'`, `alpha_matting`).
The ~1 GB model downloads to `%USERPROFILE%\.u2net` on the first run.

Install once:
```
pip install -r requirements-images.txt     # already done in the conda env "madam-flasher-qr"
```
Run (background removal is on by default):
```
cd C:\Users\balan\IdeaProjects\madam_flasher_qr
conda activate madam-flasher-qr
python step1_clean_images.py
```
Check the log says `background removal: birefnet-portrait on GPU`. If it says `on CPU`, the GPU packages are
not working.

**Photos in another folder** (for example `C:\Users\balan\Downloads\Question\Question`): copy `pipeline.yaml`
to a scratch location, change only `question: dir`, and run with `--settings <copy>`. Write `responses_xlsx` as a
full path to the Forms Excel in OneDrive (relative names are looked up in `question: dir`) and keep
`clean_images_dir: 'D:\book\new_name'`. Responses whose photo isn't in that folder
are listed in ATTENTION as missing; that is expected when the folder holds only some of the uploads.

Always relay the ATTENTION list at the end (missing photos, unmatched files, duplicates, wrong-account
submissions, and photos flagged for review such as side-facing, tilted or blurry faces). The full list is saved in
`D:\book\new_name\reports\attention.txt`, with thumbnails in `reports\contact_sheet_NN.jpg`.

### Placing portraits in `D:\book\canvas.png` (gold frame)
Portraits are 900 × 1125 px (4:5). The frame opening in canvas.png (1654 × 951 px) is x 121–556, y 105–763
(435 × 658 px, about 2:3), which is taller than 4:5. Don't make the portraits 2:3: tested on 25 Oct 2026, it
needed fill or left a hard cut-off edge at the bottom of 24 of 92 photos, because most phone photos stop at the chest.
Instead, fit the portrait to the frame's **width** and align it to the **bottom** of the opening. In canvas pixels
the photo box is x 121–556, y 219–763 (435 × 544). The transparent background lets the canvas show through as headroom.

**Round frame (the user's choice for the InDesign merge):** `D:\book\canvas_round.png` is a copy of canvas.png with
the rectangle replaced by a glowing double gold ring. It was made by `tools/round_canvas.py`
(`python tools\round_canvas.py D:\book\canvas.png D:\book\canvas_round.png`); canvas.png itself is unchanged.
Ring centre (339, 434), outer line radius 236 px, inner line radius 223 px. Photo circle: diameter **436 px**,
centred at (339, 434), i.e. box x 121–557, y 216–652 in canvas pixels (26.4% of the canvas width).
In InDesign, draw an **ellipse frame** (hold Shift for a circle) there and set **Fit Content → Fill Frame
Proportionally**, centred. The face lands in the upper-middle of the circle and the circle clips the shoulders, so
photos that stop at the chest show no hard edge.

### 2025/2026 full OneDrive run (25 Oct 2026, current output)
Input: the OneDrive `Question` folder (151 files). 149 photo uploads = 146 unique students, because 3 students
submitted twice (BS23110140, BS24110185, BS25110108) and only the latest submission is used.
`BS23110222_WONG YI ROU.JPG` is missing from the folder, so **145 transparent `<MATRIC>.png`** files plus 145 Data Merge rows.
The other 3 files in the folder match no response. Use the full folder, not the Downloads subset, for the final output.

### 2025/2026 Downloads-folder run (25 Oct 2026, for reference)
Input: `C:\Users\balan\Downloads\Question\Question` (97 files, a subset of the 151 in OneDrive).
94 photos processed on the GPU in about 65 s: 87 ok, 7 review, 0 failed. 92 portraits written to `D:\book\new_name`
as transparent `<MATRIC>.png`. 55 responses had no photo in that folder.
