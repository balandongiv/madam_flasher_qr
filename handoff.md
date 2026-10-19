

# Final plan

## Goal
Build a local web app. A person scans a printed QR coupon with a webcam, or types the student's `id` number as a backup. The app looks up the student and displays that student's image full-screen in Chrome.

## Step 0: Inspect the data first (do not assume)
- Open `D:\book\db_student.xlsx`. Report the sheet name, header row and row count. Columns: `Program, year_of_study, metric_no, name, id`.
- Sample rows:
  ```
  AKUAKULTUR | 1 | BS25110208 | SYAHANAZ BINTI SUDI @ SUDUN | 1
  AKUAKULTUR | 1 | BS25110221 | RUTHMARY JOSEPH            | 2
  AKUAKULTUR | 1 | BS25110238 | SITI ZULAIKHA BINTI ROSLI  | 3
  ```
- **Verify `id` is unique across the entire file** and that `metric_no` is unique. If either has duplicates, **stop and report** before building anything.
- Check `D:\book\unique_bg` for PNGs named `<metric_no>.png` (example: `BS25110208.png`).
- Report data problems:
    - students with no image
    - images with no student
    - blank cells
    - `id` or `metric_no` read with the wrong type (for example `id` as float `1.0`, or `metric_no` with whitespace)
    - names with special characters (`@`, `/`)

## Configuration: `config.yaml`
All machine-specific values live here. Use single quotes for Windows paths. No hardcoded paths in code. Also ship `config.example.yaml`.

```yaml
paths:
  excel_file: 'D:\book\db_student.xlsx'
  images_dir: 'D:\book\unique_bg'
  output_dir: './output'
excel:
  sheet: null                  # null = first sheet
  columns:
    program: Program
    year: year_of_study
    metric: metric_no
    name: name
    id: id
server:
  host: 127.0.0.1
  port: 8000
display:
  show_seconds: 15             # auto-return to scan screen; 0 = stay until next scan
  show_name_caption: false
scanner:
  camera_label_contains: "Logi"   # prefer the Logitech webcam, else default camera
  debounce_seconds: 3
```

## Lookup rules
- **QR payload = `metric_no` exactly** (for example `BS25110208`). The generator writes it with no prefix.
- **Backup entry = `id` integer** typed into a large input box, submitted with Enter.
- Classification of input:
    1. Trim whitespace and uppercase.
    2. If it is all digits, treat it as `id`. Strip leading zeros and compare as an integer.
    3. Otherwise treat it as `metric_no`.
    4. If a QR contains a URL or prefix, extract the last token and apply the same rules.
- Image filename match is case-insensitive.
- On-screen states, each with a clear message:
    - **Success**: image shown
    - **Not found**
    - **Student found but image missing**: show the student's name so staff can act
- Debounce repeated scans of the same code for `debounce_seconds`.
- Append every attempt to `output/scan_log.csv` (`timestamp, input, matched_by[qr|id], metric_no, result`).

## Architecture
- **Backend:** Python 3.11+, FastAPI and uvicorn.
    - Load the Excel with pandas/openpyxl, reading a **temporary copy** so it works while Excel has the file open (Excel locks files on Windows).
    - Reload automatically when the file's modified time changes, and provide `POST /api/reload`.
    - Cast `id` to int and `metric_no` to a stripped string.
- **Frontend:** a single page in Chrome.
    - `localhost` is a secure context, so `getUserMedia` works.
    - Scan in the browser with the Logitech webcam: the `BarcodeDetector` API, with a vendored `jsQR` or `zxing-js` fallback.
    - Camera selector, with the choice remembered.
    - A manual `id` box, always focused, numeric keypad friendly. Refocus it after every result.
- **Display:** full-screen, image contained and centred on a dark background. Auto-return after `show_seconds`. Esc returns to the scanner. A fullscreen button.
- **API:**
    - `POST /api/lookup {code}` returns the record, the match type and `image_url`.
    - `GET /api/image/{metric_no}`
        - Serve only a file that exists directly in `images_dir`.
        - Validate against `^[A-Za-z0-9_-]+$` to prevent path traversal.
    - `GET /api/health` returns counts and missing-image list.

## Generator script: `generate_coupons.py`
Uses `qrcode`, `Pillow`, `reportlab` and `python-pptx`. Options: `--limit N`, `--program NAME`.

1. **Individual QR PNGs:** `output/qr/<metric_no>.png` (error correction M or higher, quiet zone of at least 4 modules).
2. **Printable coupon sheet:** `output/coupons.pdf`, A4, several coupons per page. Each coupon shows:
    - the QR code
    - the **`id` printed large and clearly** as the backup number, labelled "Backup No."
    - name, program and year
    - cut borders
3. **Test deck:** `output/qr_test.pptx`, one QR per slide, large and centred on a white background, with the `id` shown small in a corner. This is for scanning from the screen with the webcam during development. Support `--limit N` for a quick test.

## Project layout
```
project/
  config.yaml, config.example.yaml, requirements.txt, README.md
  generate_coupons.py
  app/ (main.py, data.py, static/index.html, static/app.js, static/style.css, static/vendor/)
  tests/
  run.bat    # create venv if missing, install requirements, start server, open Chrome at the URL
```
Only `config.yaml` should change when moving to another computer. The README covers new-machine setup, finding the webcam, regenerating coupons and troubleshooting.

## Acceptance tests (the agent must run these and report results)
1. Startup reports the student count and the number of images matched, and lists students with a missing image.
2. Scanning a QR from `qr_test.pptx` with the Logitech webcam shows the correct image in about 1 second.
3. Typing `1` shows the image for `BS25110208`. Typing `001` gives the same result.
4. Typing an unknown number and an unknown metric number each show "not found". A student without an image shows "image missing". Nothing crashes.
5. Repeat-scanning the same QR does not flicker or double-log.
6. The app works while the Excel file is open in Excel.
7. Changing paths in `config.yaml` changes behaviour with no code edits.
8. Unit tests cover:
    - input classification (id vs metric)
    - leading-zero ids
    - case-insensitive image matching
    - path-traversal rejection
    - float or string `id` values from Excel
    - duplicate-id detection

## Constraints
- Bind to 127.0.0.1 only. No student data sent to external services.
- Vendor all JS libraries locally, with no CDN, so it works offline.
- Never modify or overwrite the source Excel or the images.
- Keep dependencies minimal and pinned.

---

## Remaining questions (defaults are set if you don't answer)
- Each  `id` is unique across all programs.
- Only for debugging,the student's name appear on screen with the image,but by default is image only.

create also the `requirements.txt` with pinned versions for all dependencies, including FastAPI, uvicorn, pandas, openpyxl, qrcode, Pillow, reportlab, python-pptx, and any JS libraries used for QR scanning.

update also the readme.md with setup instructions, how to run the server, and how to generate coupons.
