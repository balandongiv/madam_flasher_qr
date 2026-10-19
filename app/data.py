"""Config loading, Excel loading, input classification and image matching.

Shared by the web app (app/main.py) and the coupon generator (generate_coupons.py).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

log = logging.getLogger("madam_flasher")

PROJECT_DIR = Path(__file__).resolve().parent.parent
SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9_-]+")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


# --------------------------------------------------------------------------- config

@dataclass
class Config:
    excel_file: Path
    images_dir: Path
    output_dir: Path
    sheet: str | int | None
    columns: dict[str, str]
    host: str
    port: int
    show_name_caption: bool
    display_window_position: str | None
    display_fullscreen: bool
    camera_label_contains: str
    debounce_seconds: float
    default_image: Path | None = None   # shown when a student has no image; None = show nothing


def _resolve(base: Path, value: str) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return p if p.is_absolute() else (base / p).resolve()


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Load config.yaml. `path` defaults to $MADAM_CONFIG, then <project>/config.yaml."""
    cfg_path = Path(path or os.environ.get("MADAM_CONFIG") or PROJECT_DIR / "config.yaml").resolve()
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Config file not found: {cfg_path} (copy config.example.yaml to config.yaml)")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    base = cfg_path.parent
    paths = raw.get("paths", {})
    excel = raw.get("excel", {})
    server = raw.get("server", {})
    display = raw.get("display", {})
    scanner = raw.get("scanner", {})
    columns = {"program": "Program", "year": "year_of_study", "metric": "metric_no", "name": "name", "id": "id"}
    columns.update(excel.get("columns") or {})
    return Config(
        excel_file=_resolve(base, paths["excel_file"]),
        images_dir=_resolve(base, paths["images_dir"]),
        output_dir=_resolve(base, paths.get("output_dir", "./output")),
        sheet=excel.get("sheet"),
        columns=columns,
        host=str(server.get("host", "127.0.0.1")),
        port=int(server.get("port", 8000)),
        show_name_caption=bool(display.get("show_name_caption", False)),
        display_window_position=str(display.get("window_position") or "").strip() or None,
        display_fullscreen=bool(display.get("fullscreen", True)),
        camera_label_contains=str(scanner.get("camera_label_contains", "") or ""),
        debounce_seconds=float(scanner.get("debounce_seconds", 3)),
        default_image=_resolve(base, paths["default_image"]) if paths.get("default_image") else None,
    )


# --------------------------------------------------------------------------- input rules

def normalize_id(value: Any) -> int | None:
    """Turn an Excel/typed id (1, 1.0, '1', '001', ' 1.0 ') into an int. None if blank/invalid."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or not value.is_integer():  # NaN or 1.5
            return None
        return int(value)
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else None


def normalize_metric(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and value != value):
        return None
    s = str(value).strip().upper()
    return s or None


def classify(code: Any) -> tuple[str, int | str] | None:
    """Classify scanned/typed input.

    Returns ("id", int) for all-digit input (leading zeros ignored),
    ("metric", str) otherwise, or None for empty/unusable input.
    A URL or prefixed payload (e.g. 'https://x/s/BS25110208', 'ID:1') uses its last token.
    """
    if code is None:
        return None
    s = str(code).strip().upper()
    if not s:
        return None
    if not SAFE_KEY_RE.match(s):
        tokens = [t for t in _TOKEN_SPLIT_RE.split(s) if t]
        if not tokens:
            return None
        s = tokens[-1]
    if s.isdigit():
        return ("id", int(s))
    return ("metric", s)


def is_safe_key(value: str) -> bool:
    return bool(SAFE_KEY_RE.match(value or ""))


# --------------------------------------------------------------------------- data

class DataError(Exception):
    """Excel data cannot be used (duplicates, missing columns, ...)."""


@dataclass
class Student:
    id: int
    metric_no: str
    name: str
    program: str
    year: Any

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "metric_no": self.metric_no, "name": self.name,
                "program": self.program, "year": self.year}


@dataclass
class LoadReport:
    warnings: list[str] = field(default_factory=list)


def _clean_cell(v: Any) -> Any:
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def read_students(excel_file: Path, sheet: str | int | None, columns: dict[str, str]) -> tuple[list[Student], LoadReport]:
    """Read students from a temporary copy of the workbook (works while Excel has it open)."""
    excel_file = Path(excel_file)
    if not excel_file.is_file():
        raise DataError(f"Excel file not found: {excel_file}")
    fd, tmp = tempfile.mkstemp(suffix=excel_file.suffix or ".xlsx", prefix="madam_")
    os.close(fd)
    try:
        shutil.copyfile(excel_file, tmp)
        df = pd.read_excel(tmp, sheet_name=0 if sheet is None else sheet, dtype=object, engine="openpyxl")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    missing_cols = [c for c in columns.values() if c not in df.columns]
    if missing_cols:
        raise DataError(f"Missing column(s) {missing_cols} in {excel_file}; found {list(df.columns)}")

    report = LoadReport()
    students: list[Student] = []
    for idx, row in df.iterrows():
        excel_row = int(idx) + 2  # header is row 1
        vals = {k: _clean_cell(row[c]) for k, c in columns.items()}
        if all(v is None for v in vals.values()):
            continue
        sid = normalize_id(vals["id"])
        metric = normalize_metric(vals["metric"])
        if sid is None:
            report.warnings.append(f"row {excel_row}: invalid or blank id {vals['id']!r}; skipped")
            continue
        if metric is None:
            report.warnings.append(f"row {excel_row}: blank metric_no (id {sid}); skipped")
            continue
        if not is_safe_key(metric):
            report.warnings.append(f"row {excel_row}: metric_no {metric!r} has unexpected characters")
        for k in ("name", "program", "year"):
            if vals[k] is None:
                report.warnings.append(f"row {excel_row}: blank {columns[k]} (id {sid})")
        students.append(Student(id=sid, metric_no=metric, name=str(vals["name"] or ""),
                                program=str(vals["program"] or ""), year=vals["year"]))

    check_duplicates(students)
    return students, report


def check_duplicates(students: list[Student]) -> None:
    def dups(key):
        seen: dict[Any, int] = {}
        for s in students:
            seen[key(s)] = seen.get(key(s), 0) + 1
        return sorted((k for k, n in seen.items() if n > 1), key=str)

    problems = []
    d_id = dups(lambda s: s.id)
    d_metric = dups(lambda s: s.metric_no)
    if d_id:
        problems.append(f"duplicate id(s): {d_id}")
    if d_metric:
        problems.append(f"duplicate metric_no(s): {d_metric}")
    if problems:
        raise DataError("; ".join(problems))


def index_images(images_dir: Path) -> dict[str, str]:
    """Map UPPERCASE metric_no -> actual PNG filename in images_dir (case-insensitive)."""
    images_dir = Path(images_dir)
    if not images_dir.is_dir():
        return {}
    out: dict[str, str] = {}
    for entry in os.scandir(images_dir):
        if entry.is_file():
            stem, ext = os.path.splitext(entry.name)
            if ext.lower() == ".png" and is_safe_key(stem):
                out.setdefault(stem.upper(), entry.name)
    return out


def _mtime(p: Path) -> float | None:
    try:
        return os.stat(p).st_mtime
    except OSError:
        return None


class StudentDB:
    """In-memory student index that reloads when the Excel file or image folder changes."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._lock = threading.RLock()
        self.by_id: dict[int, Student] = {}
        self.by_metric: dict[str, Student] = {}
        self.images: dict[str, str] = {}
        self.warnings: list[str] = []
        self.last_error: str | None = None
        self._excel_mtime: float | None = None
        self._images_mtime: float | None = None

    # loading -----------------------------------------------------------------
    def load(self) -> None:
        """Load everything now. Raises DataError on first load problems."""
        with self._lock:
            self._load_excel()
            self._load_images()

    def _load_excel(self) -> None:
        mtime = _mtime(self.cfg.excel_file)
        students, report = read_students(self.cfg.excel_file, self.cfg.sheet, self.cfg.columns)
        self.by_id = {s.id: s for s in students}
        self.by_metric = {s.metric_no: s for s in students}
        self.warnings = report.warnings
        self._excel_mtime = mtime
        self.last_error = None
        log.info("Loaded %d students from %s", len(students), self.cfg.excel_file)

    def _load_images(self) -> None:
        self._images_mtime = _mtime(self.cfg.images_dir)
        self.images = index_images(self.cfg.images_dir)

    def refresh_if_changed(self) -> None:
        """Reload Excel/images if modified. On a bad reload keep the previous data."""
        with self._lock:
            m = _mtime(self.cfg.excel_file)
            if m is not None and m != self._excel_mtime:
                try:
                    self._load_excel()
                except Exception as e:  # file mid-save, duplicates introduced, ...
                    self._excel_mtime = m
                    self.last_error = f"Reload failed, keeping previous data: {e}"
                    log.error(self.last_error)
            if _mtime(self.cfg.images_dir) != self._images_mtime:
                self._load_images()

    def reload(self) -> None:
        with self._lock:
            self._load_excel()
            self._load_images()

    # queries -----------------------------------------------------------------
    def find(self, code: Any) -> tuple[str | None, Student | None]:
        """Return (matched_by, student). matched_by is 'id' or 'qr' (metric_no)."""
        c = classify(code)
        if c is None:
            return None, None
        kind, value = c
        with self._lock:
            if kind == "id":
                return "id", self.by_id.get(value)
            return "qr", self.by_metric.get(value)

    def image_filename(self, metric_no: str) -> str | None:
        return self.images.get(str(metric_no).strip().upper())

    def image_path(self, metric_no: str) -> Path | None:
        """Resolve an image strictly inside images_dir, or None."""
        if not is_safe_key(metric_no):
            return None
        fname = self.image_filename(metric_no)
        if not fname:
            return None
        base = self.cfg.images_dir.resolve()
        p = (base / fname).resolve()
        if p.parent != base or not p.is_file():
            return None
        return p

    def students(self) -> list[Student]:
        with self._lock:
            return sorted(self.by_id.values(), key=lambda s: s.id)

    def missing_images(self) -> list[Student]:
        return [s for s in self.students() if s.metric_no not in self.images]

    def orphan_images(self) -> list[str]:
        with self._lock:
            return sorted(self.images[k] for k in self.images if k not in self.by_metric)

    def summary(self) -> dict[str, Any]:
        students = self.students()
        missing = self.missing_images()
        return {
            "students": len(students),
            "images_in_folder": len(self.images),
            "images_matched": len(students) - len(missing),
            "missing_images": [{"id": s.id, "metric_no": s.metric_no, "name": s.name} for s in missing],
            "orphan_images": self.orphan_images(),
            "warnings": list(self.warnings),
            "last_error": self.last_error,
        }
