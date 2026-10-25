"""Step 2a: build the student database the coupons and the app use.

One row per student on the eligible list (plus anyone in the yearbook CSV who is not on it), with:
  - id, program, year, name from the yearbook Data Merge CSV when the student is in it (matches InDesign),
    otherwise from the eligible list, with ids continuing after the CSV's last id;
  - attendance from the latest Forms answer to "Will you be attending the ceremony?".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .settings import Settings, readable_copy

CONFIRMED, NOT_ATTENDING, NO_RESPONSE = "CONFIRMED", "NOT ATTENDING", "NO RESPONSE"
MATRIC_RE = re.compile(r"[A-Z]{2}\d{8}")
# Column order of the student database; the first five are what the app reads (config.yaml excel.columns).
DB_COLUMNS = ["Program", "year_of_study", "student_id", "name", "id",
              "attendance", "attendance_as_of", "eligible", "yearbook_photo", "indesign_image"]


@dataclass
class Response:
    row: int                      # Excel row number, for messages
    name: str
    email: str
    matric: str                   # typed matric; "" when the student answered "No" (Forms skips the question)
    attending: bool | None        # None = question left blank
    completed: Any


def norm_matric(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper() if not _blank(value) else ""


def norm_name(value: Any) -> str:
    """Compare names without punctuation: 'SHAMA A/P SURESH KUMAR -' -> 'SHAMA AP SURESH KUMAR'."""
    s = re.sub(r"[^A-Z ]", "", str(value or "").upper())
    return " ".join(s.split())


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and v != v) or str(v).strip() == ""


def _find(header: list[str], prefix: str, exact: bool = False) -> str:
    for h in header:
        h2 = str(h or "").strip()
        if (h2 == prefix) if exact else h2.startswith(prefix):
            return h
    raise ValueError(f'Column starting with "{prefix}" not found (columns: {", ".join(map(str, header))})')


# --------------------------------------------------------------------------- readers

def read_eligible(path: Path, spec: dict[str, Any]) -> pd.DataFrame:
    """Eligible list -> DataFrame[matric, name, program]; a student on several sheets appears once."""
    cols = spec["columns"]
    frames = []
    with readable_copy(path) as tmp:
        for sheet in spec["sheets"]:
            df = pd.read_excel(tmp, sheet_name=sheet, header=int(spec.get("header_row", 1)) - 1, dtype=str)
            frames.append(pd.DataFrame({
                "matric": df[cols["matric"]].map(norm_matric),
                "name": df[cols["name"]].fillna("").str.strip().str.upper(),
                "program": df[cols["program"]].fillna("").str.strip().str.upper(),
            }))
    df = pd.concat(frames, ignore_index=True)
    df = df[df.matric.str.fullmatch(MATRIC_RE.pattern)]
    return df.drop_duplicates("matric").reset_index(drop=True)


def read_responses(path: Path, columns: dict[str, str]) -> tuple[list[Response], datetime]:
    """Forms responses -> list of Response, plus the export file's modified time ("status as of")."""
    with readable_copy(path) as tmp:
        df = pd.read_excel(tmp, dtype=object)
    header = list(df.columns)
    c = {k: _find(header, columns[k], exact=(k == "form_name"))
         for k in ("email", "form_name", "full_name", "matric", "attendance", "completed")}
    out = []
    for i, r in df.iterrows():
        ans = "" if _blank(r[c["attendance"]]) else str(r[c["attendance"]]).strip().lower()
        out.append(Response(
            row=int(i) + 2,
            name=str(r[c["full_name"]] if not _blank(r[c["full_name"]]) else r[c["form_name"]] or "").strip(),
            email=str(r[c["email"]] or "").strip(),
            matric=norm_matric(r[c["matric"]]),
            attending=True if ans.startswith("yes") else False if ans.startswith("no") else None,
            completed=r[c["completed"]],
        ))
    return out, datetime.fromtimestamp(path.stat().st_mtime)


def read_datamerge(path: Path, encoding: str = "utf-16") -> pd.DataFrame:
    """Yearbook Data Merge CSV -> DataFrame[matric, name, program, year, id]. Missing file = empty."""
    if not path.is_file():
        return pd.DataFrame(columns=["matric", "name", "program", "year", "id"])
    df = pd.read_csv(path, encoding=encoding, dtype=str)
    out = pd.DataFrame({
        "matric": df["student_id"].map(norm_matric),
        "name": df["name"].fillna("").str.strip(),
        "program": df["Program"].fillna("").str.strip().str.upper(),
        "year": df["year_of_study"].str.extract(r"(\d+)")[0].astype(float),
        "id": pd.to_numeric(df["id"], errors="raise").astype(int),
    })
    for col in ("matric", "id"):
        dup = out[out[col].duplicated(keep=False)][col].unique()
        if len(dup):
            raise ValueError(f"{path.name}: duplicate {col}: {', '.join(map(str, dup))}")
    return out


# --------------------------------------------------------------------------- logic

def match_attendance(responses: list[Response], known: dict[str, str]) -> tuple[dict[str, tuple[bool, Any]], list[str]]:
    """Return ({matric: (attending, completed)}, notes). The latest answered response per student wins.

    `known` maps matric -> name for every student we can match to. A response is matched by its typed matric,
    else a matric in the email address, else the name.
    """
    by_name: dict[str, list[str]] = {}
    for m, n in known.items():
        by_name.setdefault(norm_name(n), []).append(m)
    latest: dict[str, tuple[bool, Any]] = {}
    notes = []
    for r in responses:
        if r.attending is None:
            continue
        email_m = MATRIC_RE.search(r.email.upper())
        cands = by_name.get(norm_name(r.name), [])
        if norm_matric(r.matric):
            matric = norm_matric(r.matric)
        elif email_m:
            matric = email_m.group()
        elif len(cands) == 1:
            matric = cands[0]
        else:
            why = "several students have this name" if cands else "no matric number and the name matches no student"
            notes.append(f'Response row {r.row} ({r.name}, {r.email}, answered '
                         f'{"Yes" if r.attending else "No"}): {why} - not counted.')
            continue
        prev = latest.get(matric)
        if prev is None or str(r.completed or "") >= str(prev[1] or ""):
            latest[matric] = (r.attending, r.completed)
    return latest, notes


def year_from_matric(matric: str, session_start: int, max_year: int) -> int | None:
    m = re.match(r"[A-Z]{2}(\d{2})", matric)
    if not m:
        return None
    return max(1, min(max_year, session_start - (2000 + int(m.group(1))) + 1))


def build(eligible: pd.DataFrame, datamerge: pd.DataFrame, attendance: dict[str, tuple[bool, Any]],
          students_cfg: dict[str, Any], indesign_images: set[str], clean_images: set[str],
          as_of: datetime) -> tuple[pd.DataFrame, list[str]]:
    """Return (student database, notes)."""
    names = {k.upper(): v for k, v in (students_cfg.get("program_names") or {}).items()}
    ycfg = students_cfg.get("year_of_study") or {}
    session, max_year = int(ycfg.get("session_start", datetime.now().year)), int(ycfg.get("max_year", 4))
    notes: list[str] = []
    elig = set(eligible.matric)

    rows = [{"Program": r.program, "year_of_study": int(r.year) if r.year == r.year else
             year_from_matric(r.matric, session, max_year), "student_id": r.matric, "name": r.name, "id": int(r.id)}
            for r in datamerge.itertuples()]
    in_csv = set(datamerge.matric)
    unknown_programs = set()
    extra = []
    for r in eligible.itertuples():
        if r.matric in in_csv:
            continue
        if r.program not in names:
            unknown_programs.add(r.program)
        extra.append({"Program": names.get(r.program, r.program), "student_id": r.matric, "name": r.name,
                      "year_of_study": year_from_matric(r.matric, session, max_year)})
    extra.sort(key=lambda d: (d["Program"], d["year_of_study"] or 0, d["name"]))
    next_id = int(datamerge.id.max()) + 1 if len(datamerge) else 1
    for i, d in enumerate(extra):
        d["id"] = next_id + i
    rows += extra

    df = pd.DataFrame(rows)
    status = {m: CONFIRMED if a else NOT_ATTENDING for m, (a, _) in attendance.items()}
    df["attendance"] = df.student_id.map(status).fillna(NO_RESPONSE)
    df["attendance_as_of"] = as_of.strftime("%d %b %Y")
    df["eligible"] = df.student_id.map(lambda m: "yes" if m in elig else "no")
    df["yearbook_photo"] = df.student_id.map(lambda m: "yes" if m in clean_images else "no")
    df["indesign_image"] = df.student_id.map(lambda m: "yes" if m in indesign_images else "no")
    df = df.sort_values("id").reset_index(drop=True)[DB_COLUMNS]

    for p in sorted(unknown_programs):
        notes.append(f'Program "{p}" has no English name in pipeline.yaml students.program_names - kept as is.')
    for r in df[df.eligible == "no"].itertuples():
        notes.append(f"{r.student_id} {r.name} (id {r.id}) is in the yearbook CSV but not on the eligible list.")
    for m in sorted(set(attendance) - set(df.student_id)):
        notes.append(f"{m} answered the form ({status[m]}) but is not on the eligible list or in the yearbook CSV "
                     f"- no coupon.")
    conf = df[df.attendance == CONFIRMED]
    for r in conf[conf.yearbook_photo == "no"].itertuples():
        notes.append(f"{r.student_id} {r.name} (id {r.id}) confirmed but has no clean portrait - run step 1, "
                     f"or the photo is missing.")
    todo = df[(df.yearbook_photo == "yes") & (df.indesign_image == "no")]
    if len(todo):
        notes.append(f"{len(todo)} student(s) have a clean portrait but no InDesign image yet (the app shows the "
                     f"default image for them): " + ", ".join(f"{r.student_id} (id {r.id})" for r in todo.itertuples()))
    return df, notes


def png_stems(folder: Path) -> set[str]:
    if not folder.is_dir():
        return set()
    return {p.stem.upper() for p in folder.iterdir() if p.suffix.lower() == ".png" and p.is_file()}


def build_from_settings(s: Settings) -> tuple[pd.DataFrame, list[str], dict[str, int]]:
    """Read every input named in pipeline.yaml and return (student database, notes, counts)."""
    eligible = read_eligible(s.eligible_xlsx, s.eligible)
    responses, as_of = read_responses(s.responses_xlsx, s.response_columns)
    datamerge = read_datamerge(s.datamerge_csv, s.yearbook.get("export", {}).get("datamerge_encoding", "utf-16"))
    known = dict(zip(eligible.matric, eligible.name))
    known.update(zip(datamerge.matric, datamerge.name))
    attendance, notes = match_attendance(responses, known)
    df, more = build(eligible, datamerge, attendance, s.students, png_stems(s.indesign_images_dir),
                     png_stems(s.clean_images_dir), as_of)
    counts = {"eligible": len(eligible), "responses": len(responses), "yearbook_csv": len(datamerge),
              **df.attendance.value_counts().to_dict()}
    return df, notes + more, counts
