# Madam Flasher QR

A local web app for showing student images. A staff member scans a printed QR coupon with a webcam, or types the
student's **Backup No.** (the `id` column). The app looks the student up in the Excel file and shows that
student's image full-screen in Chrome.

The repository also holds the whole **event pipeline** that produces the images and the coupons (see
[Event pipeline](#event-pipeline-step-by-step) below).

How it looks:

- **The Chrome window is the display.** It shows only the student's image on black: no camera, text, errors or
  cursor. This is what the audience sees.
- **The controls float on top** in a small, always-on-top **control panel**. You can drag it anywhere, including
  to another monitor. It holds the camera, the Backup No. box, the result messages, a small preview of what's on
  the display, and a Clear button.

```
+--------------------------------------------------------------+
|                                                              |
|                    student image (Chrome)    +-------------+ |
|                                              | camera      | |
|                                              | [ Backup No]| |
|                                              | result      | |
|                                              | on display  | |
|                                              +-------------+ |
|                                               floating panel |
+--------------------------------------------------------------+
```

The panel uses Chrome's *Document Picture-in-Picture*: the same always-on-top window as a popped-out video. If
that is unavailable, it opens as a small normal popup window instead.

Everything runs on this computer. The server listens on `127.0.0.1` only, the QR library is vendored
(no CDN), and no student data leaves the machine. The source Excel file and the images are only read, never
written.

## Requirements

- Windows 10/11 with **Google Chrome**
- **Python 3.11 or newer** (tested on 3.13) from python.org, with "Add python.exe to PATH" ticked
- A webcam (a Logitech webcam is preferred automatically; any camera works)

## Quick start

1. Edit `config.yaml` so the paths point to this machine's files (see below).
2. From the project folder, run:

   ```bat
   python app.py
   ```

   It will:
   - create `.venv` if it is missing,
   - install the pinned packages from `requirements.txt` (only on first run or when the file changes),
   - start the server and print the student and image counts, including the list of students with no image,
   - open the display as a chromeless, full-screen Chrome window (on the monitor set by
     `display.window_position`).
3. **Click the display** (or press `C`) to open the floating control panel. Chrome only lets a window open after a
   click, so this step is needed once per start.
4. Allow camera access when Chrome asks. The choice is remembered.

To stop the server, press `Ctrl+C` or close the console window.

Options:

```bat
python app.py --no-browser          REM start the server without opening any windows
python app.py --config D:\other.yaml
```

`app.py` works with any Python 3.11+ on PATH. If it is not already running inside `.venv`, it re-runs itself
with `.venv`'s Python. In an IDE (e.g. IntelliJ/PyCharm), you can set the project interpreter to
`.venv\Scripts\python.exe` and run `app.py` directly.

### Display window keys

| Action | Key / mouse |
|---|---|
| Open the control panel (if closed) | Click, `C`, `Enter` or `Space` |
| Toggle full screen | Double-click or `F` |
| Close the control panel | Its window's close button. Click the display to bring it back. |

Before the panel is first opened, the display shows an **Open control panel** button. After that, the display
stays pure black/image. The button reappears only while you move the mouse with the panel closed.

### Projector setups

- **Mirrored or single screen**: the floating panel sits on top of the image. Drag it to a corner, and remember
  that the audience can see it too.
- **Extended desktop** (Windows key + P → *Extend*): set `display.window_position` to a point on the projector so
  the image opens there. For a projector to the right of a 1920-pixel-wide laptop screen, use `'1920,0'`. Then
  drag the floating panel onto the laptop screen, so only staff see it.
- To move the display by hand: press `F` to leave full screen, drag the window, then press `F` again.
- The display window uses its own Chrome profile (`output/chrome-display-profile`), so it never mixes with your
  normal Chrome windows.
- The operator UI also works as a normal page at <http://127.0.0.1:8000/>, if you prefer a separate full window.

## Configuration (`config.yaml`)

`config.yaml` is the only file that should change when you move to another computer. `config.example.yaml` is
a reference copy. Use **single quotes** around Windows paths. Relative paths are resolved from the folder that
contains the config file.

| Key | Meaning |
|---|---|
| `paths.excel_file` | Student workbook (`Program, year_of_study, student_id, name, id`; other columns are ignored). Written by `step2_make_coupons.py` (default `./output/student_db.xlsx`) |
| `paths.images_dir` | Folder of `<metric_no>.png` images (matched case-insensitively): the InDesign exports, same as `pipeline.yaml` `outputs.indesign_images_dir` |
| `paths.output_dir` | Where the scan log, QR codes, PDF and PPTX are written |
| `paths.default_image` | Image shown when a student has no `<metric_no>.png` (e.g. `'D:\book\default_bg.png'`); `null` = show nothing |
| `excel.sheet` | Sheet name, or `null` for the first sheet |
| `excel.columns.*` | Column names, if the headers in the Excel file differ |
| `server.host` / `server.port` | Host must be `127.0.0.1`; any other host is refused |
| `display.show_name_caption` | `true` shows the name under the image on the display (debugging only; default is image only) |
| `display.window_position` | Where the display window opens, e.g. `'1920,0'` for a second monitor; `null` = main screen |
| `display.fullscreen` | Open the display window full screen (default `true`) |
| `scanner.camera_label_contains` | Preferred camera label text, e.g. `"Logi"` |
| `scanner.debounce_seconds` | Repeated scans of the same QR within this window are ignored |

You can also point to a different config with `--config PATH` or the `MADAM_CONFIG` environment variable.

## Using the app

In the **control panel**:

- **Scan**: hold the coupon's QR in the dashed box.
- **Backup No.**: type the number and press Enter. Leading zeros are ignored (`001` = `1`). The input box keeps focus, so you can type the next number right away.
- A scan or Backup No. does **not** go on screen right away. Its image waits in the **Next (waiting)** preview,
  next to *On display* in the floating panel (below it on the full page), with the student's name, so you can check it first.
  - **N** (or *Show*): put the waiting image on the audience screen.
  - **B** (or *Default image*): show the default image (`paths.default_image`) instead. This works for the waiting
    image, or, if nothing is waiting, it replaces the wrong image that is already on screen.
  - A new scan replaces the waiting one. N and B also work on the display window.
- The image on screen stays until you show the next one (there is no countdown). **Esc** or **Clear display**
  blanks the audience screen and drops the waiting image.
- N and B are shortcuts even while the Backup No. box has focus, so that box takes numbers only. Metric numbers
  come from the QR scan.
- The *Last result* card shows:
  - **Press N to show** (blue): found, waiting in *Next*
  - **On screen** (green) / **Default image on screen** (amber): after N / B
  - **Not found** (red): no student has this number or metric no.
  - **Image missing** (amber): the student exists but has no PNG. The name is shown so staff can act.
    If `paths.default_image` exists, the default image waits in *Next* instead (press N to show it).

Errors are shown **only** in the control panel. The display keeps showing what it had (or black), so the
audience never sees "not found".

Every attempt is appended to `output/scan_log.csv` (`timestamp, input, matched_by, metric_no, result`).
If the same coupon is held in front of the camera, it is logged only once.

### Input rules

1. Trim whitespace and convert to uppercase.
2. All digits means it is an `id` (compared as an integer).
3. Anything else is a `metric_no`.
4. A QR that holds a URL or a prefix (e.g. `https://…/BS25110208`, `ID:7`) uses its last token.

### Data reloads

The Excel file is read from a temporary copy, so it can stay **open in Excel** while the app runs. Save the
workbook and the app reloads it on the next scan. The image folder is re-scanned whenever it changes. To force
a reload:

```bat
curl -X POST http://127.0.0.1:8000/api/reload
```

If a reload fails (for example, a duplicate `id` was introduced), the app keeps the previous data. The error is
shown in `/api/health` and in the toolbar.

### API

| Endpoint | Description |
|---|---|
| `POST /api/lookup {"code": "..."}` | Returns `result` (`success`, `not_found`, `image_missing`, `invalid`), `matched_by` (`qr`/`id`), `student`, `image_url` |
| `GET /api/image/{metric_no}` | Serves a PNG from `images_dir` only (`^[A-Za-z0-9_-]+$`) |
| `GET /api/health` | Counts, students with a missing image, images with no student, warnings |
| `GET /api/display/state` | What the display is showing now |
| `GET /api/display/events` | Server-sent events stream of display changes (used by both windows) |
| `POST /api/display/confirm` | Show the waiting (next) image — shortcut N |
| `POST /api/display/default` | Show the default image instead of the waiting one (or of the current one) — shortcut B |
| `POST /api/display/clear` | Blank the display |
| `POST /api/reload` | Reloads the Excel file and the images now |

## Event pipeline (step by step)

All inputs and outputs are named in **`pipeline.yaml`** (what lives in the OneDrive `Question` folder, which
two Excel files must be there, and where each step writes). Edit that file for a new event or year.

```
OneDrive\Question\                          (pipeline.yaml: question)
  photos uploaded through Microsoft Forms
  complete_database.xlsx                    everyone eligible -> one coupon each
  MAJLIS ANUGERAH DEKAN ... (1-170).xlsx    Forms responses, incl. "Will you be attending the ceremony?"
        |
        |  Step 1: step1_clean_images.py    rename, align faces, remove background (GPU)
        v
D:\book\new_name\                           (outputs.clean_images_dir)
  <MATRIC>.png, yearbook_datamerge.csv      the CSV's `id` = coupon Backup No.
        |
        |  InDesign Data Merge (manual), export one image per student
        v
OneDrive\MAD 2026\data_student\<MATRIC>.png (outputs.indesign_images_dir = config.yaml images_dir)
        |
        |  Step 2: step2_make_coupons.py    eligible list + attendance + CSV ids
        v
output\student_db.xlsx                      (config.yaml excel_file) read by the app
output\coupons.pdf, qr_test.pptx, qr\       coupons with the attendance status
        |
        |  python app.py                    scan coupons at the ceremony
```

**Step 1: clean images.** Needs the image packages (MediaPipe, rembg on the GPU), which are in the conda env
`madam-flasher-qr` (or `pip install -r requirements-images.txt`):

```bat
conda activate madam-flasher-qr
python step1_clean_images.py                         REM all photos, ~2 minutes on the GPU
python step1_clean_images.py --only BS23110116       REM redo one student (CSV not rewritten)
```

The portraits and `yearbook_datamerge.csv` are saved in `D:\book\new_name`, as before; review the ATTENTION list
and `reports\contact_sheet_NN.jpg`. Details, including fixing flagged photos: [docs/yearbook.md](docs/yearbook.md).

**Step 2: student database and coupons.** Uses the project `.venv` (the same as the app):

```bat
.venv\Scripts\python step2_make_coupons.py                          REM database + all coupons
.venv\Scripts\python step2_make_coupons.py --attendance confirmed   REM coupons for confirmed students only
.venv\Scripts\python step2_make_coupons.py --db-only                REM database only
```

It builds `output\student_db.xlsx` with one row per eligible student:

- **id, name, program, year** come from `yearbook_datamerge.csv` when the student has a portrait (so the Backup No.
  matches InDesign). Other eligible students get ids after the CSV's last id, their name from the eligible list,
  the program translated with `students.program_names` and the year from the matric intake year.
- **attendance** is the student's latest answer to *Will you be attending the ceremony?*: **CONFIRMED**,
  **NOT ATTENDING**, or **NO RESPONSE** (never answered). Students who answer "No" skip the matric question,
  so they are matched by the matric in their email address or by name.

Anything to check (confirmed but no portrait, portraits not yet exported from InDesign, responses that match no
student, students not on the eligible list) is printed and saved in `output\student_attention.txt`.

Because the CSV ids follow the sort order, a full step 1 run with new students shifts ids: re-run step 2 and reprint.

Other tools: `tools\rename_form_uploads.py` (rename-only copy of the uploads, [docs](docs/rename_form_uploads.md))
and `tools\round_canvas.py` (the round gold frame for InDesign).

## Generating coupons

`step2_make_coupons.py` runs this for you. To regenerate coupons from the existing database only:

```bat
.venv\Scripts\python generate_coupons.py                  REM all students
.venv\Scripts\python generate_coupons.py --limit 5        REM quick test
.venv\Scripts\python generate_coupons.py --program "MARINE SCIENCES"
.venv\Scripts\python generate_coupons.py --rows 4         REM 8 larger coupons per page
.venv\Scripts\python generate_coupons.py --attendance confirmed no-response
```

The script writes these files to `output_dir`:

- `qr/<metric_no>.png`: one QR per student (payload = `metric_no`, error correction M, 4-module quiet zone)
- `coupons.pdf`: A4, 12 coupons per page (2 columns × `--rows`, default 6) with dashed cut lines. Each coupon
  has the QR, a large **ID (Backup No.)**, the name, matric no., program and year, and under the QR an
  **Attendance** section with the date of the responses export: a filled green **CONFIRMED**, a red outlined
  **NOT ATTENDING** or a grey outlined **NO RESPONSE**. The text shrinks to fit when there are more rows.
- `qr_test.pptx`: one large QR per slide on white, with the `id`, matric no., name, program and year small in the corner. Open it in PowerPoint
  and hold the webcam up to the screen to test without printing.

Print `coupons.pdf` at **100% / Actual size** (not "fit to page") so the QR codes stay crisp.

## Setting up a new machine

1. Install Python 3.11+ and Chrome.
2. Copy this project folder (no `.venv` or `output` needed).
3. Edit the three paths in `config.yaml`.
4. Run `python app.py`. Check the console for the student and image counts.

## Finding the webcam

- The **Camera** drop-down at the top lists every camera Chrome can see. Your choice is remembered in this browser.
- With no saved choice, the app picks the first camera whose name contains `scanner.camera_label_contains`,
  otherwise the default camera.
- To see camera names, open `chrome://settings/content/camera` or Windows Device Manager → *Cameras*.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Camera error: Permission denied" | Click the camera icon in Chrome's address bar → Allow, then reload. Also check Windows *Settings → Privacy → Camera*. |
| "Camera error: Could not start video source" | Another app (Teams, Zoom, the Camera app) is using the webcam. Close it and reload. |
| Camera API unavailable | Open the page as `http://127.0.0.1:8000` or `http://localhost:8000`. Other addresses are not a secure context. |
| QR not detected | Improve the lighting, hold the coupon 15–30 cm away and steady, avoid glare. Use the Backup No. if needed. |
| Server will not start: duplicate id / metric_no | Fix the duplicates the console lists in the Excel file. |
| `Excel file not found` / `Config file not found` | Check the paths in `config.yaml` (single quotes, correct drive letter). |
| Port 8000 already in use | Another copy of the app is probably still running (close its console), or change `server.port` in `config.yaml`. |
| Display stays black | The dot at the top right of the control panel should be green (live link). Press F5 in the display window. Only successful lookups reach the display. |
| Control panel does not appear | Click the display once (Chrome needs a click before it opens a window). Chrome 116+ is needed for the always-on-top panel; older versions get a normal popup, so allow popups for `127.0.0.1`. |
| Control panel hidden behind the display | Only the popup fallback can do this. Update Chrome to get the always-on-top panel. |
| Display opens on the wrong monitor | Set `display.window_position` (see above), or drag it there and press `F` for full screen. |
| Many "Image missing" | The console lists every student with no `<metric_no>.png` and every image with no student. |

## Development

```bat
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

Layout:

```
config.yaml, config.example.yaml, requirements.txt, requirements-dev.txt
pipeline.yaml          event inputs/outputs (Question folder, Excel files, image folders), portrait settings
requirements-images.txt  step 1 packages (MediaPipe, rembg GPU)
app.py                 launcher: sets up .venv, starts the server, opens Chrome
step1_clean_images.py  step 1: Forms photos -> clean portraits + InDesign Data Merge CSV
step2_make_coupons.py  step 2: student database (eligible + attendance + CSV ids) -> coupons
generate_coupons.py    QR codes, coupons.pdf, qr_test.pptx from the student database
pipeline/settings.py   loads pipeline.yaml
pipeline/students.py   builds the student database, attendance matching
pipeline/yearbook/     portrait pipeline (moved from D:\book\python_code\yearbook): naming, landmarks,
                       align, background, report, run; models/ (MediaPipe face models)
tools/                 rename_form_uploads.py, round_canvas.py (moved from D:\book\python_code)
docs/                  yearbook.md, rename_form_uploads.md
app/main.py            FastAPI app and server entry point
app/display.py         shared display state (what the audience sees, auto-expiry)
app/data.py            config, Excel loading, input classification, image matching
app/static/            index.html/app.js/style.css (operator UI; ?embed=1 = compact floating panel),
                       display.html/js/css (image display + opens the floating panel),
                       vendor/jsQR.js (1.4.0, Apache-2.0)
tests/                 pytest unit and API tests
```

QR decoding uses Chrome's `BarcodeDetector` when the platform supports QR codes. Otherwise it uses the vendored
jsQR. Chrome on Windows generally uses jsQR.
