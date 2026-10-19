"""Generate QR coupons for every student.

Outputs (in paths.output_dir from config.yaml):
  qr/<metric_no>.png   individual QR codes (payload = metric_no, no prefix)
  coupons.pdf          A4 printable sheet, 8 coupons per page, with cut borders
  qr_test.pptx         one large QR per slide, for scanning from a screen during testing

Usage:
  python generate_coupons.py [--config PATH] [--limit N] [--program NAME]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas as pdf_canvas

from app.data import DataError, Student, load_config, read_students

QR_BORDER = 4  # quiet zone in modules (spec minimum)


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

COLS, ROWS = 2, 4
MARGIN = 10 * mm


def _draw_coupon(c: pdf_canvas.Canvas, s: Student, qr_png: Path, x: float, y: float, w: float, h: float) -> None:
    # cut border
    c.setDash(4, 3)
    c.setLineWidth(0.6)
    c.setStrokeGray(0.55)
    c.rect(x, y, w, h)
    c.setDash()

    pad = 4 * mm
    qr_size = min(h - 2 * pad, w * 0.48)
    c.drawImage(ImageReader(str(qr_png)), x + pad, y + (h - qr_size) / 2, qr_size, qr_size)

    tx = x + pad + qr_size + 3 * mm
    tw = x + w - pad - tx
    top = y + h - pad

    c.setFillGray(0.35)
    c.setFont("Helvetica", 9)
    c.drawString(tx, top - 9, "Backup No.")
    c.setFillGray(0)
    id_text = str(s.id)
    size = 40
    while size > 16 and c.stringWidth(id_text, "Helvetica-Bold", size) > tw:
        size -= 2
    c.setFont("Helvetica-Bold", size)
    c.drawString(tx, top - 9 - size * 0.95, id_text)

    ty = top - 9 - size * 0.95 - 7 * mm
    name_size = 9.5
    lines = simpleSplit(s.name, "Helvetica-Bold", name_size, tw)
    while len(lines) > 3 and name_size > 7:
        name_size -= 0.5
        lines = simpleSplit(s.name, "Helvetica-Bold", name_size, tw)
    c.setFont("Helvetica-Bold", name_size)
    for line in lines[:3]:
        c.drawString(tx, ty, line)
        ty -= name_size * 1.2

    c.setFont("Helvetica", 8)
    c.setFillGray(0.25)
    ty -= 1 * mm
    for line in simpleSplit(s.program, "Helvetica", 8, tw)[:2]:
        c.drawString(tx, ty, line)
        ty -= 9.6
    c.drawString(tx, ty, f"Year {s.year}")
    c.setFillGray(0.5)
    c.setFont("Helvetica", 6.5)
    c.drawString(tx, y + pad - 1, s.metric_no)
    c.setFillGray(0)


def write_pdf(students: list[Student], qr_pngs: dict[str, Path], path: Path) -> None:
    page_w, page_h = A4
    cw = (page_w - 2 * MARGIN) / COLS
    ch = (page_h - 2 * MARGIN) / ROWS
    c = pdf_canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Student QR coupons")
    per_page = COLS * ROWS
    for i, s in enumerate(students):
        if i and i % per_page == 0:
            c.showPage()
        slot = i % per_page
        col, row = slot % COLS, slot // COLS
        x = MARGIN + col * cw
        y = page_h - MARGIN - (row + 1) * ch
        _draw_coupon(c, s, qr_pngs[s.metric_no], x, y, cw, ch)
    c.save()


# ------------------------------------------------------------------------------ PPTX

def write_pptx(students: list[Student], qr_pngs: dict[str, Path], path: Path) -> None:
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
        tb = slide.shapes.add_textbox(prs.slide_width - Inches(1.6), prs.slide_height - Inches(0.6),
                                      Inches(1.4), Inches(0.4))
        p = tb.text_frame.paragraphs[0]
        p.text = str(s.id)
        p.font.size = Pt(14)
        p.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    prs.save(str(path))


# ------------------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="path to config.yaml")
    ap.add_argument("--limit", type=int, help="only the first N students (after --program filter)")
    ap.add_argument("--program", help="only students of this program (case-insensitive, exact name)")
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
    write_pdf(students, qr_pngs, out / "coupons.pdf")
    write_pptx(students, qr_pngs, out / "qr_test.pptx")
    print(f"Generated {len(students)} coupon(s):")
    print(f"  {out / 'qr'}\\<metric_no>.png")
    print(f"  {out / 'coupons.pdf'}")
    print(f"  {out / 'qr_test.pptx'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
