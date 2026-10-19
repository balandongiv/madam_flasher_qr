import sys
from pathlib import Path

import openpyxl
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HEADER = ["Program", "year_of_study", "metric_no", "name", "id"]
ROWS = [
    ["AKUAKULTUR", 1, "BS25110208", "SYAHANAZ BINTI SUDI @ SUDUN", 1],
    ["AKUAKULTUR", 1, "BS25110221", "RUTHMARY JOSEPH", 2.0],          # float id from Excel
    ["AKUAKULTUR", 1, " bs25110238 ", "SITI ZULAIKHA BINTI ROSLI", "3"],  # string id, messy metric
    ["GEOLOGI", 3, "BS24110174", "PREWIN DER GURU A/L SIVAKUMAR", 4],  # no image
]


def write_xlsx(path: Path, rows, header=HEADER):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)


def write_png(path: Path):
    Image.new("RGB", (4, 4), "red").save(path)


@pytest.fixture
def env(tmp_path):
    excel = tmp_path / "students.xlsx"
    write_xlsx(excel, ROWS)
    images = tmp_path / "images"
    images.mkdir()
    write_png(images / "BS25110208.png")
    write_png(images / "bs25110221.PNG")       # different case
    write_png(images / "BS25110238.png")
    write_png(images / "BI99999999.png")       # orphan
    (tmp_path / "secret.png").write_bytes(b"outside")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "paths:\n"
        f"  excel_file: '{excel}'\n"
        f"  images_dir: '{images}'\n"
        "  output_dir: './out'\n"
        "server: {host: 127.0.0.1, port: 8000}\n"
        "display: {show_name_caption: false}\n"
        "scanner: {camera_label_contains: 'Logi', debounce_seconds: 3}\n",
        encoding="utf-8",
    )
    return {"dir": tmp_path, "excel": excel, "images": images, "config": cfg}
