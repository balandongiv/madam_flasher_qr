"""FastAPI app: scan a QR coupon (or type an id) and show the student's image.

Pages:
  /display        main Chrome window: the student's image only (what the audience sees). Click it to open the
                  floating, always-on-top control panel (Document Picture-in-Picture) with the operator UI.
  /?embed=1       the compact operator UI that runs inside that floating panel
  /               the same operator UI as a normal page (e.g. on a second monitor)

Run:  python app.py   (or: python -m app.main [--config PATH] [--open])
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.data import LOOPBACK_HOSTS, Config, StudentDB, classify, is_safe_key, load_config
from app.display import DisplayState

log = logging.getLogger("madam_flasher")
STATIC_DIR = Path(__file__).resolve().parent / "static"
LOG_FIELDS = ["timestamp", "input", "matched_by", "metric_no", "result"]
DEFAULT_IMAGE_URL = "/api/default-image"


class LookupRequest(BaseModel):
    code: str
    source: str = "manual"  # "scan" (camera) or "manual" (typed)


class ScanLog:
    """Append-only CSV log with server-side debounce of repeated camera scans."""

    def __init__(self, path: Path, debounce_seconds: float):
        self.path = path
        self.debounce = debounce_seconds
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def is_repeat(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key)
            self._last[key] = now
            return last is not None and now - last < self.debounce

    def write(self, raw: str, matched_by: str, metric_no: str, result: str) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.path.exists() or self.path.stat().st_size == 0
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(LOG_FIELDS)
                w.writerow([datetime.now().isoformat(timespec="seconds"), raw, matched_by, metric_no, result])


def print_startup_report(db: StudentDB) -> None:
    s = db.summary()
    print(f"[madam_flasher] Excel: {db.cfg.excel_file}")
    print(f"[madam_flasher] Images: {db.cfg.images_dir}")
    print(f"[madam_flasher] Students loaded: {s['students']}")
    print(f"[madam_flasher] Images matched: {s['images_matched']} / {s['students']} "
          f"({s['images_in_folder']} PNGs in folder)")
    if s["missing_images"]:
        print(f"[madam_flasher] Students with NO image ({len(s['missing_images'])}):")
        for m in s["missing_images"]:
            print(f"    id {m['id']:>5}  {m['metric_no']}  {m['name']}")
    if s["orphan_images"]:
        print(f"[madam_flasher] Images with no student ({len(s['orphan_images'])}): {', '.join(s['orphan_images'])}")
    for w in s["warnings"]:
        print(f"[madam_flasher] WARNING {w}")
    d = db.cfg.default_image
    if d is None:
        print("[madam_flasher] Default image: none (students without an image are not shown)")
    elif d.is_file():
        print(f"[madam_flasher] Default image: {d}")
    else:
        print(f"[madam_flasher] WARNING default image not found: {d} (students without an image are not shown)")
    print("[madam_flasher] Each scan / Backup No. waits as 'Next': press N to show it, B to show the default image")


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    db = StudentDB(cfg)
    db.load()  # fail fast on duplicates / missing file
    scan_log = ScanLog(cfg.output_dir / "scan_log.csv", cfg.debounce_seconds)
    display = DisplayState(cfg.show_name_caption)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        print_startup_report(db)
        yield

    app = FastAPI(title="Madam Flasher QR", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.scan_log = scan_log
    app.state.cfg = cfg
    app.state.display = display
    boot_id = uuid.uuid4().hex  # pages reload themselves when this changes (server restarted, maybe new code)

    @app.middleware("http")
    async def no_stale_pages(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-cache")  # always revalidate html/js/css
        return response

    @app.get("/api/config")
    def client_config():
        return {
            "show_name_caption": cfg.show_name_caption,
            "camera_label_contains": cfg.camera_label_contains,
            "debounce_seconds": cfg.debounce_seconds,
            "has_default_image": default_image_path() is not None,
        }

    def default_image_path() -> Path | None:
        d = cfg.default_image
        return d if d is not None and d.is_file() else None

    @app.post("/api/lookup")
    def lookup(req: LookupRequest):
        db.refresh_if_changed()
        raw = req.code.strip()[:200]
        c = classify(raw)
        matched_by, student = db.find(raw)
        if c is None:
            result = "invalid"
        elif student is None:
            result = "not_found"
        elif db.image_filename(student.metric_no) is None:
            result = "image_missing"
        else:
            result = "success"

        repeat = req.source == "scan" and c is not None and scan_log.is_repeat(f"{c[0]}:{c[1]}")
        if not repeat:
            scan_log.write(raw, matched_by or "", student.metric_no if student else "", result)
        # Found students wait as the next image (N shows it, B shows the default instead);
        # errors stay on the operator screen.
        image_url = None
        if result == "success":
            image_url = f"/api/image/{student.metric_no}"
        elif result == "image_missing" and default_image_path() is not None:
            image_url = DEFAULT_IMAGE_URL
        pending = False
        if image_url:
            if not repeat:
                display.stage(student, image_url)
            p = display.snapshot()["pending"]
            pending = p is not None and p["metric_no"] == student.metric_no

        body = {
            "result": result,
            "matched_by": matched_by,
            "student": student.to_dict() if student else None,
            "image_url": image_url,
            "default_image": image_url == DEFAULT_IMAGE_URL,
            "pending": pending,
            "repeat": repeat,
            "display": display.snapshot(),
        }
        return body

    @app.get("/api/display/state")
    def display_state():
        return display.snapshot()

    @app.post("/api/display/confirm")
    def display_confirm():
        """Show the next (waiting) image. Shortcut N."""
        return {"confirmed": display.confirm(), **display.snapshot()}

    @app.post("/api/display/default")
    def display_default():
        """Show the default image instead of the next one (or of the current one). Shortcut B."""
        shown = default_image_path() is not None and display.show_default(DEFAULT_IMAGE_URL)
        return {"shown": shown, **display.snapshot()}

    @app.post("/api/display/clear")
    def display_clear():
        display.clear()
        return display.snapshot()

    @app.get("/api/display/events")
    async def display_events(request: Request):
        """Server-sent events: one `data:` message per display change."""
        async def stream():
            sent = None
            idle = 0.0
            while not await request.is_disconnected():
                if display.version != sent:
                    snap = display.snapshot()
                    sent = snap["version"]
                    idle = 0.0
                    yield f"data: {json.dumps({**snap, 'boot': boot_id})}\n\n"
                elif idle >= 15:
                    idle = 0.0
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.1)
                idle += 0.1

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/image/{metric_no}")
    def image(metric_no: str):
        if not is_safe_key(metric_no):
            raise HTTPException(status_code=400, detail="Invalid metric_no")
        path = db.image_path(metric_no)
        if path is None:
            db.refresh_if_changed()
            path = db.image_path(metric_no)
        if path is None:
            raise HTTPException(status_code=404, detail="Image not found")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.get(DEFAULT_IMAGE_URL)
    def default_image():
        path = default_image_path()
        if path is None:
            raise HTTPException(status_code=404, detail="Default image not configured or missing")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @app.get("/api/health")
    def health():
        db.refresh_if_changed()
        return {"status": "ok" if not db.last_error else "degraded", **db.summary()}

    @app.post("/api/reload")
    def reload():
        try:
            db.reload()
        except Exception as e:
            return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})
        return {"status": "ok", **db.summary()}

    @app.get("/display", include_in_schema=False)
    def display_page():
        return FileResponse(STATIC_DIR / "display.html")

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def _find_chrome() -> str | None:
    candidates = [
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def open_display_later(cfg: Config, base_url: str, delay: float = 1.5) -> None:
    """Open the display as a chromeless Chrome app window; the controls float on top of it."""
    display_url = base_url + "display"

    def _open():
        time.sleep(delay)
        chrome = _find_chrome()
        if not chrome:
            print("[madam_flasher] Chrome not found; opening default browser")
            webbrowser.open(display_url)
            return
        # Own Chrome profile so the position/full-screen flags are always honoured and the camera permission sticks.
        profile = cfg.output_dir / "chrome-display-profile"
        args = [chrome, f"--user-data-dir={profile}", f"--app={display_url}",
                "--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble"]
        if cfg.display_window_position:
            args.append(f"--window-position={cfg.display_window_position}")
        if cfg.display_fullscreen:
            args.append("--start-fullscreen")
        subprocess.Popen(args)

    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Madam Flasher QR display server")
    parser.add_argument("--config", help="path to config.yaml (default: project config.yaml or $MADAM_CONFIG)")
    parser.add_argument("--open", action="store_true",
                        help="open the display window in Chrome once the server is up")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config(args.config)
    if cfg.host not in LOOPBACK_HOSTS:
        raise SystemExit(f"Refusing to bind to {cfg.host!r}: server.host must be 127.0.0.1 (student data stays local)")

    import uvicorn
    app = create_app(cfg)
    url = f"http://{'[::1]' if cfg.host == '::1' else cfg.host}:{cfg.port}/"
    print(f"[madam_flasher] Display:  {url}display   (click it to open the floating control panel)")
    print(f"[madam_flasher] Operator as a normal page: {url}")
    if args.open:
        open_display_later(cfg, url)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning", timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
