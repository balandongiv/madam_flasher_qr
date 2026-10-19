/* Madam Flasher QR — main display. Shows only the current student's image (or black).
   The operator controls open in a floating, always-on-top panel (Document Picture-in-Picture),
   falling back to a small popup window where that API is unavailable. */
(() => {
  "use strict";

  const photo = document.getElementById("photo");
  const caption = document.getElementById("caption");
  const PANEL_URL = "/?embed=1";
  const PANEL_SIZE = { width: 440, height: 600 };
  let shown = null;      // image_url currently on screen
  let loading = null;    // image_url being preloaded
  let panel = null;      // floating panel window

  // ------------------------------------------------------------------ image
  function render(state) {
    if (!state || state.mode !== "image") {
      shown = loading = null;
      photo.classList.remove("on");
      caption.textContent = "";
      return;
    }
    caption.textContent = state.caption || "";
    const key = state.image_url;
    if (key === shown || key === loading) return; // no flicker on repeats
    loading = key;
    const img = new Image();
    img.onload = () => {
      if (loading !== key) return; // superseded by a newer image
      photo.src = img.src;
      photo.classList.add("on");
      shown = key;
      loading = null;
    };
    img.onerror = () => { if (loading === key) loading = null; };
    img.src = state.image_url + "?t=" + Date.now();
  }

  function connect() {
    const es = new EventSource("/api/display/events");
    let boot = null;
    es.onmessage = (e) => {
      let state;
      try { state = JSON.parse(e.data); } catch { return; }
      if (boot && state.boot && state.boot !== boot) { location.reload(); return; } // server restarted: get new code
      boot = state.boot || boot;
      render(state);
    };
    // On error EventSource reconnects automatically; the first message after reconnect resyncs the state.
  }

  // ------------------------------------------------------------------ floating control panel
  function panelOpen() { return panel && !panel.closed; }

  function setPanelState(open) {
    document.body.classList.toggle("panel-closed", !open);
    if (open) document.body.classList.remove("setup");
  }

  async function openPanel() {
    if (panelOpen()) { panel.focus(); return; }
    if ("documentPictureInPicture" in window) {
      try {
        const pip = await window.documentPictureInPicture.requestWindow(PANEL_SIZE);
        pip.document.title = "Madam Flasher – Control";
        const style = pip.document.createElement("style");
        style.textContent = "html,body{margin:0;height:100%;background:#111;overflow:hidden}" +
          "iframe{border:0;width:100%;height:100%;display:block}";
        pip.document.head.appendChild(style);
        const frame = pip.document.createElement("iframe");
        frame.src = PANEL_URL;
        frame.allow = "camera; fullscreen";
        pip.document.body.appendChild(frame);
        frame.addEventListener("load", () => frame.contentWindow.focus());
        pip.addEventListener("pagehide", () => { panel = null; setPanelState(false); });
        panel = pip;
        setPanelState(true);
        return;
      } catch (e) {
        console.warn("Picture-in-Picture panel unavailable, using a popup:", e);
      }
    }
    const left = Math.max(0, screen.availWidth - PANEL_SIZE.width - 24);
    panel = window.open(PANEL_URL, "madamFlasherPanel",
      `popup,width=${PANEL_SIZE.width},height=${PANEL_SIZE.height},left=${left},top=24`);
    if (panel) {
      setPanelState(true);
      const watch = setInterval(() => { if (!panelOpen()) { clearInterval(watch); setPanelState(false); } }, 1000);
    }
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen().catch(() => {});
  }

  // Click (or C) opens the panel; double-click (or F) toggles full screen; N shows the next image, B the default.
  let clickTimer = null;
  document.addEventListener("click", () => {
    clearTimeout(clickTimer);
    clickTimer = setTimeout(() => { if (!panelOpen()) openPanel(); }, 250);
  });
  document.addEventListener("dblclick", () => { clearTimeout(clickTimer); toggleFullscreen(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "n" || e.key === "N") { e.preventDefault(); fetch("/api/display/confirm", { method: "POST" }); }
    else if (e.key === "b" || e.key === "B") { e.preventDefault(); fetch("/api/display/default", { method: "POST" }); }
    else if (e.key === "c" || e.key === "C" || e.key === "Enter" || e.key === " ") { e.preventDefault(); openPanel(); }
    else if (e.key === "f" || e.key === "F") toggleFullscreen();
  });
  document.getElementById("open-panel").addEventListener("click", (e) => {
    e.stopPropagation();
    openPanel();
  });

  // The pointer (and, once set up, the prompt) appear only while the mouse moves.
  let pointerTimer = null;
  document.addEventListener("mousemove", () => {
    document.body.classList.add("pointer");
    clearTimeout(pointerTimer);
    pointerTimer = setTimeout(() => document.body.classList.remove("pointer"), 2000);
  });

  setPanelState(false);
  document.body.classList.add("setup");
  connect();
})();
