import pandas as pd

import generate_coupons as gc
from app.data import Student


def test_read_attendance_and_pdf_with_status(tmp_path):
    db = tmp_path / "student_db.xlsx"
    pd.DataFrame({"Program": ["AQUACULTURE"] * 3, "year_of_study": [2, 3, 4],
                  "student_id": ["BS25110001", "bs24110002", "BS23110003"], "name": ["A", "B", "C"],
                  "id": [1, 2, 3], "attendance": ["CONFIRMED", "NOT ATTENDING", "NO RESPONSE"],
                  "attendance_as_of": ["25 Oct 2026"] * 3}).to_excel(db, index=False)
    att = gc.read_attendance(db)
    assert att["BS24110002"] == ("NOT ATTENDING", "25 Oct 2026")

    students = [Student(i + 1, m, n, "AQUACULTURE", 2)
                for i, (m, n) in enumerate([("BS25110001", "A"), ("BS24110002", "B"), ("BS23110003", "C")])]
    qr = gc.write_qr_pngs(students, tmp_path / "qr")
    pdf = tmp_path / "coupons.pdf"
    gc.write_pdf(students, qr, pdf, attendance=att)
    assert pdf.read_bytes().startswith(b"%PDF") and pdf.stat().st_size > 2000


def test_read_attendance_without_column(tmp_path):
    db = tmp_path / "old.xlsx"
    pd.DataFrame({"student_id": ["BS25110001"], "id": [1]}).to_excel(db, index=False)
    assert gc.read_attendance(db) == {}
