"""Generate QR coupons for every student in the student database (config.yaml paths.excel_file).

Normally run through step2_make_coupons.py, which builds that database first. If the database has an
`attendance` column (CONFIRMED / NOT ATTENDING / NO RESPONSE), each coupon shows it under the QR.

Outputs (in paths.output_dir from config.yaml):
  qr/<metric_no>.png   individual QR codes (payload = metric_no, no prefix)
  coupons.pdf          A4 printable sheet, 12 coupons per page (2 x --rows), with cut borders
  qr_test.pptx         one large QR per slide, for scanning from a screen during testing

Usage:
  python generate_coupons.py [--config PATH] [--limit N] [--program NAME] [--rows 3-7]
                             [--attendance confirmed not-attending no-response]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import qrcode
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas as pdf_canvas

from app.data import DataError, Student, load_config, normalize_metric, read_students
from pipeline.settings import readable_copy

QR_BORDER = 4  # quiet zone in modules (spec minimum)
ATTENDANCE_CHOICES = {"confirmed": "CONFIRMED", "not-attending": "NOT ATTENDING", "no-response": "NO RESPONSE"}
# status -> (fill RGB or None, text/stroke RGB); filled = confirmed, outlined = not confirmed
STATUS_STYLE = {
    "CONFIRMED": ((0.10, 0.47, 0.24), (1, 1, 1)),
    "NOT ATTENDING": (None, (0.75, 0.13, 0.13)),
    "NO RESPONSE": (None, (0.42, 0.42, 0.42)),
}


def read_attendance(excel: Path) -> dict[str, tuple[str, str]]:
    """{metric_no: (status, as-of date)} from the database's attendance columns; {} if it has none."""
    with readable_copy(excel) as tmp:
        df = pd.read_excel(tmp, dtype=str)
    if "attendance" not in df.columns:
        return {}
    as_of = df["attendance_as_of"] if "attendance_as_of" in df.columns else pd.Series("", index=df.index)
    return {normalize_metric(m): (str(a).strip().upper(), "" if pd.isna(d) else str(d))
            for m, a, d in zip(df["student_id"], df["attendance"], as_of) if normalize_metric(m)}


def make_qr(payload: str, box_size: int = 12):
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box_size, border=QR_BORDER)
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")


def write_qr_pngs(students: list[Student], qr_dir: Path) -> dict[str, Path]:
    qr_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for s in students:
        p = qr_dir / f"{s.metric_no}.png"
        make_qr(s.metric_no).save(p)
        out[s.metric_no] = p
    return out


# ------------------------------------------------------------------------------ PDF

COLS, ROWS = 2, 6  # 12 coupons per A4 page; override rows with --rows
MARGIN = 10 * mm


def _draw_status(c: pdf_canvas.Canvas, status: str, as_of: str, x: float, top: float, w: float) -> float:
    """Attendance section under the QR: small grey label, then a pill. Returns its height."""
    label = "ATTENDANCE" + (f" (AS OF {as_of.upper()})" if as_of else "")
    size = 5.5
    while size > 4 and c.stringWidth(label, "Helvetica", size) > w:
        size -= 0.25
    c.setFillGray(0.45)
    c.setFont("Helvetica", size)
    c.drawString(x, top - size * 0.72, label)
    pill_h, py = 5.2 * mm, top - size * 0.72 - 1.2 * mm - 5.2 * mm
    fill, ink = STATUS_STYLE.get(status, (None, (0.42, 0.42, 0.42)))
    c.setLineWidth(1)
    c.setStrokeColorRGB(*(fill or ink))
    if fill:
        c.setFillColorRGB(*fill)
    c.roundRect(x, py, w, pill_h, pill_h / 2, stroke=1, fill=1 if fill else 0)
    text_size = 8
    while text_size > 5.5 and c.stringWidth(status, "Helvetica-Bold", text_size) > w - 3 * mm:
        text_size -= 0.25
    c.setFillColorRGB(*ink)
    c.setFont("Helvetica-Bold", text_size)
    c.drawCentredString(x + w / 2, py + (pill_h - text_size * 0.72) / 2, status)
    c.setFillGray(0)
    c.setStrokeGray(0)
    return top - py


STATUS_BLOCK = 5.5 * 0.72 + 1.2 * mm + 5.2 * mm   # height of _draw_status (label + gap + pill)


def _draw_coupon(c: pdf_canvas.Canvas, s: Student, qr_png: Path, x: float, y: float, w: float, h: float,
                 status: tuple[str, str] | None = None) -> None:
    # cut border
    c.setDash(4, 3)
    c.setLineWidth(0.6)
    c.setStrokeGray(0.55)
    c.rect(x, y, w, h)
    c.setDash()

    pad = 3.5 * mm
    gap = 1.8 * mm                                    # between the QR and the attendance section
    extra = STATUS_BLOCK + gap if status else 0
    qr_size = min(h - 2 * pad - extra, w * 0.5)
    qr_y = y + (h - qr_size - extra) / 2 + extra      # QR + status block centred vertically
    c.drawImage(ImageReader(str(qr_png)), x + pad, qr_y, qr_size, qr_size)
    if status:
        _draw_status(c, status[0], status[1], x + pad, qr_y - gap, qr_size)

    tx = x + pad + qr_size + 4 * mm
    tw = x + w - pad - tx

    def layout(k: float) -> list[tuple[str, float, float, str, float]]:
        """Text rows at scale k: (font, size, gray, line, space after)."""
        def fit(text: str, font: str, size: float, max_lines: int, min_size: float) -> tuple[float, list[str]]:
            lines = simpleSplit(text, font, size, tw)
            while len(lines) > max_lines and size > min_size:
                size -= 0.5
                lines = simpleSplit(text, font, size, tw)
            return size, lines[:max_lines]

        # each field is a small grey label above its value
        rows: list[tuple[str, float, float, str, float]] = []

        def field(title: str, font: str, size: float, lines: list[str], after: float = 3.2 * mm) -> None:
            rows.append(("Helvetica", max(7 * k, 5.5), 0.45, title.upper(), 1.2 * mm * k))
            for i, line in enumerate(lines):
                rows.append((font, size, 0, line, after * k if i == len(lines) - 1 else size * 0.25))

        id_text = str(s.id)
        id_size = 44 * k
        while id_size > 16 and c.stringWidth(id_text, "Helvetica-Bold", id_size) > tw:
            id_size -= 2
        field("ID (Backup No.)", "Helvetica-Bold", id_size, [id_text])
        name_size, name_lines = fit(s.name, "Helvetica-Bold", 11.5 * k, 3, 7)
        field("Name", "Helvetica-Bold", name_size, name_lines)
        field("Matric No.", "Helvetica-Bold", 10.5 * k, [s.metric_no])
        prog_size, prog_lines = fit(s.program, "Helvetica", 10 * k, 2, 6.5)
        field("Program", "Helvetica", prog_size, prog_lines)
        field("Year", "Helvetica", 10 * k, [f"Year {s.year}"], after=0)
        return rows

    # cap height ~0.72 of the font size; shrink until the block fits, then centre it vertically
    def height(rows: list[tuple[str, float, float, str, float]]) -> float:
        return sum(size * 0.72 + after for _, size, _, _, after in rows)

    k = 1.0
    rows = layout(k)
    while height(rows) > h - 2 * pad and k > 0.5:
        k -= 0.02
        rows = layout(k)
    ty = y + (h + height(rows)) / 2
    for font, size, gray, text, after in rows:
        ty -= size * 0.72
        c.setFillGray(gray)
        c.setFont(font, size)
        c.drawString(tx, ty, text)
        ty -= after
    c.setFillGray(0)


def write_pdf(students: list[Student], qr_pngs: dict[str, Path], path: Path, rows: int = ROWS,
              attendance: dict[str, tuple[str, str]] | None = None) -> None:
    page_w, page_h = A4
    cw = (page_w - 2 * MARGIN) / COLS
    ch = (page_h - 2 * MARGIN) / rows
    c = pdf_canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Student QR coupons")
    per_page = COLS * rows
    for i, s in enumerate(students):
        if i and i % per_page == 0:
            c.showPage()
        slot = i % per_page
        col, row = slot % COLS, slot // COLS
        x = MARGIN + col * cw
        y = page_h - MARGIN - (row + 1) * ch
        _draw_coupon(c, s, qr_pngs[s.metric_no], x, y, cw, ch, (attendance or {}).get(s.metric_no))
    c.save()


# ------------------------------------------------------------------------------ PPTX

def write_pptx(students: list[Student], qr_pngs: dict[str, Path], path: Path,
               attendance: dict[str, tuple[str, str]] | None = None) -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    size = Inches(6.5)
    for s in students:
        slide = prs.slides.add_slide(blank)
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        slide.shapes.add_picture(str(qr_pngs[s.metric_no]),
                                 (prs.slide_width - size) // 2, (prs.slide_height - size) // 2, size, size)
        tb = slide.shapes.add_textbox(prs.slide_width - Inches(3.6), prs.slide_height - Inches(1.1),
                                      Inches(3.4), Inches(0.9))
        tf = tb.text_frame
        tf.word_wrap = True
        lines = [f"ID {s.id}  ·  {s.metric_no}", s.name, f"{s.program}, Year {s.year}"]
        if s.metric_no in (attendance or {}):
            lines.append(attendance[s.metric_no][0])
        for i, text in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = text
            p.font.size = Pt(12)
            p.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    prs.save(str(path))


# ------------------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="path to config.yaml")
    ap.add_argument("--limit", type=int, help="only the first N students (after --program filter)")
    ap.add_argument("--program", help="only students of this program (case-insensitive, exact name)")
    ap.add_argument("--rows", type=int, default=ROWS, choices=range(3, 8), metavar="3-7",
                    help=f"coupon rows per A4 page, 2 columns each (default {ROWS})")
    ap.add_argument("--attendance", nargs="+", choices=sorted(ATTENDANCE_CHOICES),
                    help="only students with this attendance status, e.g. --attendance confirmed")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    try:
        students, report = read_students(cfg.excel_file, cfg.sheet, cfg.columns)
    except DataError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    for w in report.warnings:
        print(f"WARNING {w}")

    students.sort(key=lambda s: s.id)
    attendance = read_attendance(cfg.excel_file)
    if args.attendance:
        if not attendance:
            print("ERROR: the student database has no attendance column (run step2_make_coupons.py)", file=sys.stderr)
            return 1
        want_status = {ATTENDANCE_CHOICES[a] for a in args.attendance}
        students = [s for s in students if attendance.get(s.metric_no, ("",))[0] in want_status]
    if args.program:
        want = args.program.strip().upper()
        students = [s for s in students if s.program.strip().upper() == want]
        if not students:
            print(f"ERROR: no students in program {args.program!r}", file=sys.stderr)
            return 1
    if args.limit is not None:
        students = students[: max(args.limit, 0)]
    if not students:
        print("Nothing to generate.")
        return 0

    out = cfg.output_dir
    out.mkdir(parents=True, exist_ok=True)
    qr_pngs = write_qr_pngs(students, out / "qr")
    write_pdf(students, qr_pngs, out / "coupons.pdf", args.rows, attendance)
    write_pptx(students, qr_pngs, out / "qr_test.pptx", attendance)
    print(f"Generated {len(students)} coupon(s):")
    print(f"  {out / 'qr'}\\<metric_no>.png")
    print(f"  {out / 'coupons.pdf'}")
    print(f"  {out / 'qr_test.pptx'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
