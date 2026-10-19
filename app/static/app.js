/* Madam Flasher QR — operator UI: webcam QR scanning, Backup No. entry, display preview.
   Runs in the floating panel opened from /display (?embed=1), or as a normal page at /.
   The audience sees only /display, which follows the server's display state. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const video = $("video"), canvas = $("frame"), ctx = canvas.getContext("2d", { willReadFrequently: true });
  const cameraSel = $("camera"), codeInput = $("code");

  // ?embed=1: compact layout for the floating control panel opened from /display
  if (new URLSearchParams(location.search).has("embed")) document.body.classList.add("embed");

  const CAMERA_KEY = "madamFlasher.cameraId";
  const SCAN_INTERVAL_MS = 120;
  const SCAN_WIDTH = 640;
  const DEFAULT_IMAGE_URL = "/api/default-image";

  let cfg = { show_name_caption: false, camera_label_contains: "", debounce_seconds: 3, has_default_image: false };
  let stream = null;
  let detector = null;
  let busy = false;
  let lastScan = { code: null, seen: 0 };
  let previewKey = null;  // image_url on the audience screen
  let nextKey = null;     // image_url of the next (waiting) image
  let waiting = null;     // { metric_no, sub } of the lookup waiting for N / B

  // ------------------------------------------------------------------ storage (may be blocked)
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
  };

  // ------------------------------------------------------------------ result card
  function setResult(cls, title, sub = "") {
    $("result").className = "card result " + cls;
    $("result-title").className = "result-title";
    $("result-title").textContent = title;
    $("result-sub").textContent = sub;
  }

  const who = (s) => `${s.name} · ${s.metric_no} · No. ${s.id}`;

  // The waiting image was shown (N), replaced by the default (B) or cancelled — possibly from the display window.
  function syncWaiting(state) {
    if (!waiting || !state || state.pending) return;
    if (state.mode === "image" && state.metric_no === waiting.metric_no) {
      if (state.image_url === DEFAULT_IMAGE_URL) setResult("warn", "Default image on screen", waiting.sub);
      else setResult("ok", "On screen", waiting.sub);
    } else {
      setResult("", "Not shown", waiting.sub);
    }
    waiting = null;
  }

  function setImage(img, empty, key, url) {
    if (!url) {
      img.classList.add("hidden");
      img.removeAttribute("src");
      empty.classList.remove("hidden");
      return null;
    }
    if (key !== url) img.src = url + "?t=" + Date.now();
    img.classList.remove("hidden");
    empty.classList.add("hidden");
    return url;
  }

  // ------------------------------------------------------------------ display preview (mirrors /display)
  function renderPreview(state) {
    syncWaiting(state);
    const on = state && state.mode === "image";
    previewKey = setImage($("preview-img"), $("preview-empty"), previewKey, on ? state.image_url : null);
    $("preview-name").textContent = on ? (state.student ? who(state.student) : state.metric_no) : "";

    const p = state && state.pending;
    nextKey = setImage($("next-img"), $("next-empty"), nextKey, p ? p.image_url : null);
    $("next-name").textContent = p ? who(p.student) + (p.image_url === DEFAULT_IMAGE_URL ? " — no image, default" : "") : "";
    $("next-card").classList.toggle("waiting", !!p);
    $("show-next").disabled = !p;
    $("show-default").disabled = !cfg.has_default_image || !(p || on);
  }

  function connectEvents() {
    const es = new EventSource("/api/display/events");
    es.onopen = () => $("link").classList.add("on");
    let boot = null;
    es.onmessage = (e) => {
      let state;
      try { state = JSON.parse(e.data); } catch { return; }
      if (boot && state.boot && state.boot !== boot) { location.reload(); return; } // server restarted: get new code
      boot = state.boot || boot;
      renderPreview(state);
    };
    es.onerror = () => $("link").classList.remove("on"); // EventSource reconnects by itself
  }

  async function clearDisplay() {
    try {
      const r = await fetch("/api/display/clear", { method: "POST" });
      renderPreview(await r.json());
    } catch { /* events will resync */ }
    refocus();
  }

  // ------------------------------------------------------------------ lookup
  async function lookup(code, source) {
    busy = true;
    try {
      const res = await fetch("/api/lookup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, source }),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const r = await res.json();
      const s = r.student;
      const how = r.matched_by === "id" ? "Backup No." : "QR";
      if (r.pending) {
        const sub = r.default_image ? `${who(s)} — no image, default will be shown` : `${who(s)} (${how})`;
        waiting = { metric_no: s.metric_no, sub };
        setResult("pending", "Press N to show", sub + (cfg.has_default_image ? " · B = default image" : ""));
      } else if (r.repeat && r.image_url) {
        setResult("", "Repeat scan ignored", `${who(s)} (${how})`);
      } else if (r.result === "image_missing") {
        setResult("warn", "Image missing", `${who(s)} — nothing sent to the display`);
      } else if (r.result === "not_found") {
        setResult("err", "Not found", `${how}: ${code}`);
      } else {
        setResult("err", "Unreadable input", code);
      }
      if (r.display) renderPreview(r.display);
    } catch (e) {
      setResult("err", "Server error", e.message);
    } finally {
      busy = false;
      refocus();
    }
  }

  // ------------------------------------------------------------------ manual entry and keys
  function refocus() {
    if (document.activeElement !== cameraSel) codeInput.focus({ preventScroll: true });
  }

  async function displayAction(path) {
    try {
      const r = await fetch(path, { method: "POST" });
      renderPreview(await r.json());
    } catch { /* events will resync */ }
    refocus();
  }
  const showNext = () => displayAction("/api/display/confirm");
  async function showDefault() {
    const replacing = !waiting;  // nothing waiting: B swaps the image already on screen
    try {
      const r = await (await fetch("/api/display/default", { method: "POST" })).json();
      renderPreview(r);
      if (r.shown && replacing && r.student) setResult("warn", "Default image on screen", who(r.student));
    } catch { /* events will resync */ }
    refocus();
  }

  $("manual").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = codeInput.value.trim();
    codeInput.value = "";
    if (v) lookup(v, "manual");
  });
  codeInput.addEventListener("blur", () => setTimeout(refocus, 50));
  // N / B are shortcuts even while the Backup No. box has focus (it only takes numbers).
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    const k = e.key.toLowerCase();
    if (k === "escape") { e.preventDefault(); clearDisplay(); }
    else if (k === "n") { e.preventDefault(); showNext(); }
    else if (k === "b") { e.preventDefault(); showDefault(); }
  });
  $("show-next").addEventListener("click", showNext);
  $("show-default").addEventListener("click", showDefault);
  $("clear-display").addEventListener("click", clearDisplay);
  $("open-display").addEventListener("click", () => {
    window.open("/display", "madamFlasherDisplay", "popup,width=1280,height=720");
    refocus();
  });

  // ------------------------------------------------------------------ camera
  async function listCameras() {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "videoinput");
  }

  function fillCameraSelect(cams, activeId) {
    cameraSel.innerHTML = "";
    cams.forEach((c, i) => {
      const o = document.createElement("option");
      o.value = c.deviceId;
      o.textContent = c.label || `Camera ${i + 1}`;
      if (c.deviceId === activeId) o.selected = true;
      cameraSel.appendChild(o);
    });
  }

  async function startCamera(deviceId) {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    const video_c = { width: { ideal: 1280 }, height: { ideal: 720 } };
    if (deviceId) video_c.deviceId = { exact: deviceId };
    stream = await navigator.mediaDevices.getUserMedia({ video: video_c, audio: false });
    video.srcObject = stream;
    await video.play().catch(() => {});
    const track = stream.getVideoTracks()[0];
    return track.getSettings().deviceId || deviceId || "";
  }

  function pickCamera(cams) {
    const saved = store.get(CAMERA_KEY);
    if (saved && cams.some((c) => c.deviceId === saved)) return saved;
    const want = (cfg.camera_label_contains || "").toLowerCase();
    if (want) {
      const m = cams.find((c) => c.label.toLowerCase().includes(want));
      if (m) return m.deviceId;
    }
    return null; // default camera
  }

  async function initCamera() {
    const msg = $("camera-msg");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      msg.textContent = "Camera API unavailable (open via http://127.0.0.1 or localhost in Chrome). Manual entry still works.";
      return;
    }
    try {
      let cams = await listCameras();
      const target = cams.some((c) => c.label) ? pickCamera(cams) : null;
      let active = await startCamera(target);
      cams = await listCameras(); // labels are visible after permission is granted
      const preferred = pickCamera(cams);
      if (preferred && preferred !== active) active = await startCamera(preferred);
      fillCameraSelect(cams, active);
      msg.textContent = "";
    } catch (e) {
      msg.textContent = "Camera error: " + (e.message || e.name) + ". Manual entry still works.";
      return;
    }
    cameraSel.addEventListener("change", async () => {
      try {
        const id = await startCamera(cameraSel.value);
        store.set(CAMERA_KEY, id);
        $("camera-msg").textContent = "";
      } catch (e) {
        $("camera-msg").textContent = "Camera error: " + (e.message || e.name);
      }
      refocus();
    });
    navigator.mediaDevices.addEventListener?.("devicechange", async () => {
      fillCameraSelect(await listCameras(), stream?.getVideoTracks()[0]?.getSettings().deviceId);
    });
    await initDetector();
    scanLoop();
  }

  // ------------------------------------------------------------------ QR decoding
  async function initDetector() {
    const engine = $("scan-engine");
    if ("BarcodeDetector" in window) {
      try {
        const formats = await window.BarcodeDetector.getSupportedFormats();
        if (formats.includes("qr_code")) {
          detector = new window.BarcodeDetector({ formats: ["qr_code"] });
          engine.textContent = "Decoder: BarcodeDetector";
          return;
        }
      } catch { /* fall through */ }
    }
    engine.textContent = typeof jsQR === "function" ? "Decoder: jsQR" : "No QR decoder available";
  }

  async function decodeFrame() {
    if (video.readyState < 2 || !video.videoWidth) return null;
    if (detector) {
      const codes = await detector.detect(video);
      return codes.length ? codes[0].rawValue : null;
    }
    if (typeof jsQR !== "function") return null;
    const scale = Math.min(1, SCAN_WIDTH / video.videoWidth);
    const w = Math.round(video.videoWidth * scale), h = Math.round(video.videoHeight * scale);
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    ctx.drawImage(video, 0, 0, w, h);
    const data = ctx.getImageData(0, 0, w, h);
    const r = jsQR(data.data, w, h, { inversionAttempts: "dontInvert" });
    return r && r.data ? r.data : null;
  }

  function onDetected(code) {
    code = code.trim();
    if (!code) return;
    const now = Date.now();
    const debounceMs = cfg.debounce_seconds * 1000;
    // Same code seen again within the window (e.g. coupon still in front of camera): ignore, extend window.
    if (code === lastScan.code && now - lastScan.seen < debounceMs) {
      lastScan.seen = now;
      return;
    }
    lastScan = { code, seen: now };
    lookup(code, "scan");
  }

  function scanLoop() {
    let last = 0;
    const tick = async (t) => {
      if (!busy && t - last >= SCAN_INTERVAL_MS) {
        last = t;
        try {
          const code = await decodeFrame();
          if (code) onDetected(code);
        } catch { /* transient decode errors */ }
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------------ startup
  async function init() {
    try {
      cfg = { ...cfg, ...(await (await fetch("/api/config")).json()) };
      const h = await (await fetch("/api/health")).json();
      $("health").textContent = `${h.students} students · ${h.images_matched} images` +
        (h.last_error ? " · reload error" : "");
      if (h.last_error) $("health").title = h.last_error;
    } catch (e) {
      setResult("err", "Cannot reach server", e.message);
    }
    connectEvents();
    refocus();
    initCamera();
  }

  init();
})();
