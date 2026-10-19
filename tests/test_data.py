import os

import pytest

from app.data import DataError, StudentDB, Student, check_duplicates, classify, load_config, normalize_id, read_students
from tests.conftest import ROWS, write_xlsx


# ---------------------------------------------------------------- classification

@pytest.mark.parametrize("raw, expected", [
    ("BS25110208", ("metric", "BS25110208")),
    ("  bs25110208 \n", ("metric", "BS25110208")),
    ("1", ("id", 1)),
    ("42", ("id", 42)),
    ("https://example.local/s/BS25110208", ("metric", "BS25110208")),
    ("ID:7", ("id", 7)),
    ("STUDENT BS25110208", ("metric", "BS25110208")),
    ("", None),
    ("   ", None),
    ("///", None),
])
def test_classify(raw, expected):
    assert classify(raw) == expected


@pytest.mark.parametrize("raw", ["001", "0001", " 01 ", "1"])
def test_leading_zero_ids(raw):
    assert classify(raw) == ("id", 1)


def test_leading_zero_lookup(env):
    db = StudentDB(load_config(env["config"]))
    db.load()
    for code in ("1", "001", "00001"):
        by, s = db.find(code)
        assert by == "id" and s.metric_no == "BS25110208"


# ---------------------------------------------------------------- Excel types

@pytest.mark.parametrize("value, expected", [
    (1, 1), (1.0, 1), ("1", 1), ("001", 1), (" 2 ", 2), ("3.0", 3),
    (1.5, None), ("abc", None), ("", None), (None, None), (float("nan"), None),
])
def test_normalize_id(value, expected):
    assert normalize_id(value) == expected


def test_float_and_string_ids_from_excel(env):
    students, report = read_students(env["excel"], None, load_config(env["config"]).columns)
    by_id = {s.id: s for s in students}
    assert set(by_id) == {1, 2, 3, 4}
    assert all(isinstance(s.id, int) for s in students)
    assert by_id[3].metric_no == "BS25110238"  # stripped + uppercased


# ---------------------------------------------------------------- duplicates

def test_duplicate_id_detected(env):
    write_xlsx(env["excel"], ROWS + [["X", 1, "BS00000001", "DUP", "1"]])
    with pytest.raises(DataError, match="duplicate id"):
        read_students(env["excel"], None, load_config(env["config"]).columns)


def test_duplicate_id_float_vs_int_detected():
    with pytest.raises(DataError, match="duplicate id"):
        check_duplicates([Student(1, "A1", "", "", 1), Student(1, "A2", "", "", 1)])


def test_duplicate_metric_detected(env):
    write_xlsx(env["excel"], ROWS + [["X", 1, "bs25110208", "DUP", 99]])
    with pytest.raises(DataError, match="duplicate metric_no"):
        read_students(env["excel"], None, load_config(env["config"]).columns)


# ---------------------------------------------------------------- images

def test_case_insensitive_image_matching(env):
    db = StudentDB(load_config(env["config"]))
    db.load()
    assert db.image_filename("BS25110221") == "bs25110221.PNG"
    assert db.image_filename("bs25110208") == "BS25110208.png"
    assert db.image_path("bs25110221").name == "bs25110221.PNG"
    assert db.image_filename("BS24110174") is None


def test_missing_and_orphan_images(env):
    db = StudentDB(load_config(env["config"]))
    db.load()
    s = db.summary()
    assert s["students"] == 4
    assert s["images_matched"] == 3
    assert [m["metric_no"] for m in s["missing_images"]] == ["BS24110174"]
    assert s["orphan_images"] == ["BI99999999.png"]


@pytest.mark.parametrize("bad", ["..", "../secret", "..\\secret", "a/b", "BS2511.png", "", "C:secret", "%2e%2e"])
def test_image_path_rejects_traversal(env, bad):
    db = StudentDB(load_config(env["config"]))
    db.load()
    assert db.image_path(bad) is None


# ---------------------------------------------------------------- reload / config

def test_reload_on_mtime_change(env):
    db = StudentDB(load_config(env["config"]))
    db.load()
    write_xlsx(env["excel"], ROWS + [["X", 2, "BS77777777", "NEW", 5]])
    st = os.stat(env["excel"])
    os.utime(env["excel"], (st.st_atime, st.st_mtime + 10))
    db.refresh_if_changed()
    assert db.find("5")[1].metric_no == "BS77777777"


def test_bad_reload_keeps_previous_data(env):
    db = StudentDB(load_config(env["config"]))
    db.load()
    write_xlsx(env["excel"], ROWS + [["X", 1, "BS00000001", "DUP", 1]])
    st = os.stat(env["excel"])
    os.utime(env["excel"], (st.st_atime, st.st_mtime + 10))
    db.refresh_if_changed()
    assert db.last_error and "duplicate id" in db.last_error
    assert db.find("1")[1].metric_no == "BS25110208"


def test_relative_paths_resolve_from_config_dir(env):
    cfg = load_config(env["config"])
    assert cfg.output_dir == (env["dir"] / "out").resolve()
