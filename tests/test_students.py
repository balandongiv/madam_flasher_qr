from datetime import datetime

import openpyxl
import pandas as pd

from pipeline.students import (CONFIRMED, NO_RESPONSE, NOT_ATTENDING, Response, build, match_attendance,
                               norm_name, read_eligible, year_from_matric)

AS_OF = datetime(2026, 10, 25)
CFG = {"program_names": {"AKUAKULTUR": "AQUACULTURE", "GEOLOGI": "GEOLOGY"},
       "year_of_study": {"session_start": 2026, "max_year": 4}}


def resp(row, name="", email="", matric="", attending=True, completed="2026-10-15 09:00:00"):
    return Response(row, name, email, matric, attending, completed)


def test_norm_name_ignores_punctuation_and_trailing_dash():
    assert norm_name("SHAMA A/P SURESH KUMAR") == norm_name("shama ap suresh  kumar -")


def test_year_from_matric():
    assert year_from_matric("BS25110295", 2026, 4) == 2
    assert year_from_matric("BS23110116", 2026, 4) == 4
    assert year_from_matric("BS21110561", 2026, 4) == 4      # capped
    assert year_from_matric("XX", 2026, 4) is None


def test_match_attendance_by_matric_email_and_name():
    known = {"BS25110001": "ALI BIN ABU", "BS24110002": "SHAMA A/P SURESH", "BS23110003": "TAN AH KOW"}
    responses = [
        resp(2, "ALI BIN ABU", matric="bs25 110001"),                              # typed matric, messy
        resp(3, "SOMEONE", email="x_bs24110002@iluv.ums.edu.my", attending=False),  # matric in email
        resp(4, "TAN AH KOW -", email="tan_bs23@iluv.ums.edu.my", attending=False),  # name only
        resp(5, "NOBODY KNOWN", email="n@x", attending=False),                     # unmatched
        resp(6, "ALI BIN ABU", matric="BS25110001", attending=None),               # blank answer ignored
    ]
    got, notes = match_attendance(responses, known)
    assert {m: a for m, (a, _) in got.items()} == {"BS25110001": True, "BS24110002": False, "BS23110003": False}
    assert len(notes) == 1 and "row 5" in notes[0]


def test_match_attendance_latest_answer_wins():
    known = {"BS23110240": "AMITHRAA A/P YOGESWARAN"}
    responses = [resp(2, "AMITHRAA A/P YOGESWARAN", attending=False, completed="2026-10-15 10:00:00"),
                 resp(3, "AMITHRAA", matric="BS23110240", attending=True, completed="2026-10-18 10:00:00")]
    got, _ = match_attendance(responses, known)
    assert got["BS23110240"][0] is True


def test_build_ids_programs_years_and_status():
    eligible = pd.DataFrame({"matric": ["BS25110001", "BS23110003", "BS24110002", "BS22110009"],
                             "name": ["ALI BIN ABU", "TAN AH KOW", "SHAMA", "ZED"],
                             "program": ["AKUAKULTUR", "GEOLOGI", "AKUAKULTUR", "FIZIK INDUSTRI"]})
    datamerge = pd.DataFrame({"matric": ["BS25110001", "BS25110169"], "name": ["ALI ABU", "NATASYA"],
                              "program": ["AQUACULTURE", "INDUSTRIAL CHEMISTRY"], "year": [2.0, 2.0], "id": [2, 1]})
    attendance = {"BS25110001": (True, ""), "BS24110002": (False, "")}
    df, notes = build(eligible, datamerge, attendance, CFG, indesign_images={"BS25110001"},
                      clean_images={"BS25110001", "BS25110169"}, as_of=AS_OF)
    by = df.set_index("student_id")
    # CSV students keep their CSV id/name/program; others continue after the last CSV id, sorted
    assert by.loc["BS25110001", ["id", "name", "Program"]].tolist() == [2, "ALI ABU", "AQUACULTURE"]
    assert by.loc["BS24110002", ["id", "Program", "year_of_study"]].tolist() == [3, "AQUACULTURE", 3]
    assert by.loc["BS22110009", ["id", "Program"]].tolist() == [4, "FIZIK INDUSTRI"]   # unmapped: kept
    assert by.loc["BS23110003", ["id", "Program", "year_of_study"]].tolist() == [5, "GEOLOGY", 4]
    assert by.loc["BS25110001", "attendance"] == CONFIRMED
    assert by.loc["BS24110002", "attendance"] == NOT_ATTENDING
    assert by.loc["BS23110003", "attendance"] == NO_RESPONSE
    assert df.id.tolist() == [1, 2, 3, 4, 5] and df.id.is_unique
    assert by.loc["BS25110169", "eligible"] == "no"
    joined = "\n".join(notes)
    assert "FIZIK INDUSTRI" in joined and "BS25110169" in joined and "no InDesign image" in joined


def test_read_eligible_two_sheets_header_row_2(tmp_path):
    path = tmp_path / "eligible.xlsx"
    wb = openpyxl.Workbook()
    for i, title in enumerate(["SEMESTER I", "SEMESTER II"]):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title
        ws.append([f"{title} 2025/2026"])
        ws.append(["Bil", "Program", "Nama Pelajar", "No. Pelajar"])
        ws.append([1, "Akuakultur", "ALI BIN ABU", " bs25110001 "])
        ws.append([2, "GEOLOGI", f"STUDENT {i}", f"BS2311000{i}"])
    wb.save(path)
    spec = {"sheets": ["SEMESTER I", "SEMESTER II"], "header_row": 2,
            "columns": {"matric": "No. Pelajar", "name": "Nama Pelajar", "program": "Program"}}
    df = read_eligible(path, spec)
    assert sorted(df.matric) == ["BS23110000", "BS23110001", "BS25110001"]      # duplicate across sheets once
    assert df.set_index("matric").loc["BS25110001", "program"] == "AKUAKULTUR"
