import csv

import pytest
from fastapi.testclient import TestClient

from app.data import load_config
from app.main import create_app


@pytest.fixture
def client(env):
    app = create_app(load_config(env["config"]))
    with TestClient(app) as c:
        c.env = env
        yield c


def read_log(env):
    path = env["dir"] / "out" / "scan_log.csv"
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_lookup_by_id_and_leading_zeros(client):
    for code in ("1", "001"):
        r = client.post("/api/lookup", json={"code": code}).json()
        assert r["result"] == "success"
        assert r["matched_by"] == "id"
        assert r["student"]["metric_no"] == "BS25110208"
        assert r["image_url"] == "/api/image/BS25110208"


def test_lookup_by_metric(client):
    r = client.post("/api/lookup", json={"code": "bs25110221", "source": "scan"}).json()
    assert r["result"] == "success" and r["matched_by"] == "qr"


def test_not_found_and_image_missing(client):
    assert client.post("/api/lookup", json={"code": "99999"}).json()["result"] == "not_found"
    assert client.post("/api/lookup", json={"code": "BS00000000"}).json()["result"] == "not_found"
    r = client.post("/api/lookup", json={"code": "4"}).json()
    assert r["result"] == "image_missing"
    assert r["student"]["name"] == "PREWIN DER GURU A/L SIVAKUMAR"
    assert r["image_url"] is None
    assert client.post("/api/lookup", json={"code": "  "}).json()["result"] == "invalid"


def test_image_endpoint(client):
    r = client.get("/api/image/BS25110208")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get("/api/image/bs25110221").status_code == 200
    assert client.get("/api/image/BS24110174").status_code == 404


@pytest.mark.parametrize("path", [
    "/api/image/..%2Fsecret", "/api/image/..%5Csecret", "/api/image/%2e%2e",
    "/api/image/secret.png", "/api/image/../secret",
])
def test_image_endpoint_rejects_traversal(client, path):
    r = client.get(path)
    assert r.status_code in (400, 404)
    assert r.content != b"outside"


def test_scan_debounce_logs_once(client):
    for _ in range(3):
        client.post("/api/lookup", json={"code": "BS25110208", "source": "scan"})
    client.post("/api/lookup", json={"code": "7", "source": "manual"})
    rows = read_log(client.env)
    assert [r["input"] for r in rows] == ["BS25110208", "7"]
    assert rows[0] == {**rows[0], "matched_by": "qr", "metric_no": "BS25110208", "result": "success"}
    assert rows[1]["result"] == "not_found"


def test_health(client):
    h = client.get("/api/health").json()
    assert h["students"] == 4 and h["images_matched"] == 3
    assert h["missing_images"][0]["metric_no"] == "BS24110174"


def test_reload(client):
    assert client.post("/api/reload").json()["status"] == "ok"


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "jsQR.js" in r.text
    assert client.get("/vendor/jsQR.js").status_code == 200
