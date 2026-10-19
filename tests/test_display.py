import pytest
from fastapi.testclient import TestClient

from app.data import Student, load_config
from app.display import DisplayState
from app.main import create_app

A = Student(1, "BS25110208", "A", "P", 1)
B = Student(2, "BS25110221", "B", "P", 1)


def test_stage_then_confirm():
    d = DisplayState(False)
    assert d.snapshot()["mode"] == "idle"
    assert d.confirm() is False
    d.stage(A)
    snap = d.snapshot()
    assert snap["mode"] == "idle" and snap["pending"]["metric_no"] == "BS25110208"
    assert d.confirm() is True
    snap = d.snapshot()
    assert snap["mode"] == "image" and snap["metric_no"] == "BS25110208" and snap["pending"] is None
    assert "remaining" not in snap  # no countdown: stays until replaced or cleared


def test_next_waits_while_current_stays():
    d = DisplayState(False)
    d.stage(A)
    d.confirm()
    d.stage(B)
    snap = d.snapshot()
    assert snap["metric_no"] == "BS25110208" and snap["pending"]["metric_no"] == "BS25110221"
    d.clear()
    snap = d.snapshot()
    assert snap["mode"] == "idle" and snap["pending"] is None


def test_show_default_for_pending_or_current():
    d = DisplayState(False)
    assert d.show_default("/api/default-image") is False  # nothing waiting, nothing shown
    d.stage(A)
    assert d.show_default("/api/default-image") is True
    snap = d.snapshot()
    assert snap["metric_no"] == "BS25110208" and snap["image_url"] == "/api/default-image" and snap["pending"] is None
    d.stage(B)
    d.confirm()
    v = d.version
    assert d.show_default("/api/default-image") is True  # wrong image already on screen: replace it
    snap = d.snapshot()
    assert snap["metric_no"] == "BS25110221" and snap["image_url"] == "/api/default-image" and d.version > v


def test_caption_only_when_enabled():
    for caption, want in ((False, None), (True, "A")):
        d = DisplayState(caption)
        d.stage(A)
        d.confirm()
        assert d.snapshot()["caption"] == want


@pytest.fixture
def client(env):
    with TestClient(create_app(load_config(env["config"]))) as c:
        yield c


def test_only_success_reaches_display(client):
    assert client.get("/api/display/state").json()["mode"] == "idle"
    client.post("/api/lookup", json={"code": "99999"})       # not found
    client.post("/api/lookup", json={"code": "4"})           # image missing, no default configured
    snap = client.get("/api/display/state").json()
    assert snap["mode"] == "idle" and snap["pending"] is None
    r = client.post("/api/lookup", json={"code": "1"}).json()
    assert r["pending"] is True and r["display"]["mode"] == "idle"  # waits for N
    r = client.post("/api/display/confirm").json()
    assert r["confirmed"] is True and r["mode"] == "image" and r["metric_no"] == "BS25110208"
    client.post("/api/lookup", json={"code": "99999"})       # error keeps the current image
    assert client.get("/api/display/state").json()["metric_no"] == "BS25110208"
    assert client.post("/api/display/default").json()["shown"] is False  # no default image configured
    assert client.post("/api/display/clear").json()["mode"] == "idle"
    assert client.get("/api/display/state").json()["mode"] == "idle"


def test_pages_served(client):
    op = client.get("/")
    assert op.status_code == 200 and "jsQR.js" in op.text and "Backup No." in op.text
    disp = client.get("/display")
    assert disp.status_code == 200 and "display.js" in disp.text
    assert "video" not in disp.text and "Backup" not in disp.text  # audience window has no controls


def _client_with(env, extra_paths="", extra_display=""):
    cfg = env["config"]
    text = cfg.read_text(encoding="utf-8")
    text = text.replace("  output_dir: './out'\n", "  output_dir: './out'\n" + extra_paths)
    text = text.replace("display: {show_name_caption: false}",
                        "display: {show_name_caption: false" + extra_display + "}")
    cfg.write_text(text, encoding="utf-8")
    return TestClient(create_app(load_config(cfg)))


def test_missing_image_shows_default(env):
    default = env["dir"] / "default_bg.png"
    default.write_bytes((env["images"] / "BS25110208.png").read_bytes())
    with _client_with(env, f"  default_image: '{default}'\n") as c:
        r = c.post("/api/lookup", json={"code": "4"}).json()
        assert r["result"] == "image_missing" and r["default_image"] is True
        assert r["image_url"] == "/api/default-image" and r["pending"] is True
        r = c.post("/api/display/confirm").json()
        assert r["mode"] == "image" and r["image_url"] == "/api/default-image"
        img = c.get("/api/default-image")
        assert img.status_code == 200 and img.headers["content-type"] == "image/png"
        # a student with an image still gets their own image
        assert c.post("/api/lookup", json={"code": "1"}).json()["image_url"] == "/api/image/BS25110208"


def test_default_image_configured_but_absent(env):
    with _client_with(env, f"  default_image: '{env['dir'] / 'nope.png'}'\n") as c:
        r = c.post("/api/lookup", json={"code": "4"}).json()
        assert r["image_url"] is None and r["display"]["pending"] is None
        assert c.get("/api/default-image").status_code == 404


def test_next_and_default_shortcuts(env):
    default = env["dir"] / "default_bg.png"
    default.write_bytes((env["images"] / "BS25110208.png").read_bytes())
    with _client_with(env, f"  default_image: '{default}'\n") as c:
        r = c.post("/api/lookup", json={"code": "BS25110208", "source": "scan"}).json()
        assert r["result"] == "success" and r["pending"] is True
        assert r["display"]["mode"] == "idle" and r["display"]["pending"]["metric_no"] == "BS25110208"
        # repeat scan of the coupon still in front of the camera stays pending
        assert c.post("/api/lookup", json={"code": "BS25110208", "source": "scan"}).json()["pending"] is True
        r = c.post("/api/display/confirm").json()  # N
        assert r["confirmed"] is True and r["mode"] == "image" and r["metric_no"] == "BS25110208"
        assert c.post("/api/display/confirm").json()["confirmed"] is False
        # typed Backup No. also waits for N; B shows the default image instead
        r = c.post("/api/lookup", json={"code": "2", "source": "manual"}).json()
        assert r["pending"] is True and r["display"]["metric_no"] == "BS25110208"
        r = c.post("/api/display/default").json()  # B
        assert r["shown"] is True and r["metric_no"] == "BS25110221" and r["image_url"] == "/api/default-image"
        assert r["pending"] is None
        assert c.get("/api/config").json()["has_default_image"] is True
