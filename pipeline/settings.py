"""Load pipeline.yaml: where the event inputs live and where each step writes."""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml

PROJECT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = Path(__file__).resolve().parent / "yearbook" / "models"


@dataclass
class Settings:
    event: str
    question_dir: Path
    eligible_xlsx: Path
    eligible: dict[str, Any]          # sheets, header_row, columns
    responses_xlsx: Path
    response_columns: dict[str, str]
    clean_images_dir: Path
    datamerge_csv: Path
    corrections_dir: Path
    indesign_images_dir: Path
    students: dict[str, Any]          # program_names, year_of_study
    yearbook: dict[str, Any]          # naming, template, crop, quality, export, background
    path: Path

    def yearbook_config(self) -> dict[str, Any]:
        """The dict the portrait code (pipeline.yearbook) expects, as config.toml used to give it."""
        yb = {k: dict(v) for k, v in self.yearbook.items()}
        yb["paths"] = {
            "input_dir": str(self.question_dir),
            "responses_xlsx": str(self.responses_xlsx),
            "output_dir": str(self.clean_images_dir),
            "corrections_dir": str(self.corrections_dir),
            "models_dir": str(MODELS_DIR),
        }
        yb["naming"]["columns"] = dict(self.response_columns)
        yb["export"]["datamerge_csv"] = self.datamerge_csv.name
        return yb


def _path(value: str, base: Path) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return p if p.is_absolute() else base / p


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    """Load pipeline.yaml (default: <project>/pipeline.yaml, or $MADAM_PIPELINE)."""
    p = Path(path or os.environ.get("MADAM_PIPELINE") or PROJECT_DIR / "pipeline.yaml").resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Pipeline settings not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    q, out = raw["question"], raw["outputs"]
    qdir = _path(q["dir"], p.parent)
    clean = _path(out["clean_images_dir"], p.parent)
    return Settings(
        event=str(raw.get("event", "")),
        question_dir=qdir,
        eligible_xlsx=_path(q["eligible_xlsx"], qdir),
        eligible=q["eligible"],
        responses_xlsx=_path(q["responses_xlsx"], qdir),
        response_columns=q["responses"]["columns"],
        clean_images_dir=clean,
        datamerge_csv=_path(out.get("datamerge_csv", "yearbook_datamerge.csv"), clean),
        corrections_dir=_path(out.get("corrections_dir", clean / "corrections"), p.parent),
        indesign_images_dir=_path(out["indesign_images_dir"], p.parent),
        students=raw.get("students", {}),
        yearbook=raw.get("yearbook", {}),
        path=p,
    )


@contextmanager
def readable_copy(path: Path) -> Iterator[Path]:
    """Yield a temporary copy of `path`, so a workbook that is open (locked) in Excel can still be read."""
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    fd, tmp = tempfile.mkstemp(suffix=path.suffix)
    os.close(fd)
    try:
        shutil.copyfile(path, tmp)
        yield Path(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
