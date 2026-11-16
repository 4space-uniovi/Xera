/* Lógica de la interfaz: WebSocket de control, estado y ajustes. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);

  const S = { ws: null, open: false, isOwner: false, ownerPresent: false, rate: 20, state: {} };

  /* ---------- pestañas ---------- */
  document.querySelectorAll(".tab").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".tabpane").forEach((p) => p.classList.toggle("active", p.id === "tab-" + btn.dataset.tab));
      pollCamera();
      if (btn.dataset.tab === "status") refreshStatus();
      if (btn.dataset.tab === "settings") loadSettings();
    })
  );

  /* ---------- WebSocket ---------- */
  function send(obj) {
    if (S.open) S.ws.send(JSON.stringify(obj));
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/control`);
    S.ws = ws;
    ws.onopen = () => { S.open = true; render(); };
    ws.onclose = () => {
      S.open = false; S.isOwner = false; S.ownerPresent = false;
      joy.setEnabled(false);
      render();
      setTimeout(connect, 1000); // el backend ya paró el rover al ver cerrarse el socket
    };
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "hello") { setRate(m.send_rate_hz); }
      else if (m.type === "state") { S.state = m; S.isOwner = m.is_owner; S.ownerPresent = m.owner_present; render(); }
      else if (m.type === "denied") { flash("Otro cliente tiene el control ahora mismo."); }
      else if (m.type === "error") { flash(m.detail); }
    };
  }

  /* ---------- joystick y envío periódico ---------- */
  const joy = new Joystick($("pad"), $("knob"), (x, y) => {
    $("val-x").textContent = x;
    $("val-y").textContent = y;
    if (x === 0 && y === 0 && S.isOwner) send({ type: "move", x: 0, y: 0 }); // al soltar, sin esperar al tick
  });

  let timer = null;
  function setRate(hz) {
    S.rate = hz;
    clearInterval(timer);
    // Mientras tengamos el control enviamos SIEMPRE (también 0,0): es el "latido" que
    // mantiene vivo el watchdog del backend.
    timer = setInterval(() => { if (S.isOwner) send({ type: "move", x: joy.x, y: joy.y }); }, 1000 / hz);
  }

  $("btn-stop").addEventListener("click", () => { joy.reset(); send({ type: "stop" }); });
  $("btn-control").addEventListener("click", () => send({ type: S.isOwner ? "release_control" : "request_control" }));
  window.addEventListener("blur", () => joy.reset());
  document.addEventListener("visibilitychange", () => { if (document.hidden) joy.reset(); });

  /* ---------- velocidad máxima ---------- */
  let speedTimer = null, speedDragging = false;
  $("speed").addEventListener("input", (e) => {
    speedDragging = true;
    $("speed-val").textContent = e.target.value;
    clearTimeout(speedTimer);
    speedTimer = setTimeout(async () => {
      await putConfig({ motion: { max_speed: Number(e.target.value) } });
      speedDragging = false;
    }, 200);
  });

  /* ---------- renderizado ---------- */
  function render() {
    const wsPill = $("ws-pill");
    wsPill.className = "pill " + (S.open ? "ok" : "bad");
    wsPill.lastElementChild.textContent = S.open ? "Conectado" : "Desconectado";

    const ctl = $("ctl-pill");
    ctl.className = "pill " + (S.isOwner ? "ok" : S.ownerPresent ? "warn" : "");
    ctl.lastElementChild.textContent = S.isOwner ? "Tienes el control" : S.ownerPresent ? "Control ocupado" : "Control libre";

    const btn = $("btn-control");
    btn.textContent = S.isOwner ? "Liberar control" : "Pedir control";
    btn.disabled = !S.open || (!S.isOwner && S.ownerPresent);
    joy.setEnabled(S.open && S.isOwner);

    if (S.state.max_speed !== undefined && !speedDragging) {
      $("speed").value = S.state.max_speed;
      $("speed-val").textContent = S.state.max_speed;
    }
    if (!S.isOwner && S.open) flash(S.ownerPresent ? "Otro cliente está conduciendo. Solo puedes ver." : "Pulsa «Pedir control» para conducir.");
    else if (S.isOwner) flash("");
  }

  let flashTimer = null;
  function flash(text) {
    $("msg").textContent = text;
    clearTimeout(flashTimer);
  }

  /* ---------- vídeo ---------- */
  // El <img> solo está conectado al stream mientras se ve la pestaña Control: así el
  // backend no captura (ni gasta CPU) si nadie mira.
  const img = $("video-img"), vmsg = $("video-msg");
  let videoOn = false;
  const videoWanted = () => !document.hidden && $("tab-control").classList.contains("active");

  function stopVideo() { img.removeAttribute("src"); img.hidden = true; videoOn = false; }

  async function pollCamera() {
    let cam;
    try { cam = await (await fetch("/api/camera/status")).json(); } catch (e) { return; }
    if (videoOn && (cam.state === "disconnected" || cam.state === "error")) stopVideo(); // el stream murió
    if (cam.available && videoWanted() && !videoOn) {
      img.src = "/api/camera/stream?t=" + Date.now();
      img.hidden = false; videoOn = true;
    } else if (!videoWanted() && videoOn) {
      stopVideo();
    }
    vmsg.hidden = videoOn && cam.state === "streaming";
    if (!vmsg.hidden) {
      vmsg.querySelector("b").textContent = cam.available ? "Conectando con la cámara…" : "Webcam desconectada";
      $("video-detail").textContent = cam.detail || "";
    }
  }
  img.addEventListener("error", stopVideo);
  setInterval(pollCamera, 2000);
  document.addEventListener("visibilitychange", pollCamera);

  /* ---------- estado del sistema ---------- */
  function stat(label, value, sub, level) {
    return `<div class="stat"><div class="label"><i class="dot ${level || ""}"></i>${label}</div>
      <div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
  }
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  async function refreshStatus() {
    try {
      const d = await (await fetch("/api/status")).json();
      $("rover-name").textContent = d.rover + (d.demo ? " · DEMO" : "");
      const s = d.serial, c = d.camera, w = d.wifi, m = d.motion;
      $("status-grid").innerHTML = [
        stat("ESP32-S3", s.connected ? (s.simulated ? "Simulado" : "Conectado") : "Desconectado",
             s.connected ? `${s.frames_sent} tramas enviadas${s.last_rx ? " · ESP32: " + esc(s.last_rx) : ""}` : esc(s.error || "sin puerto"),
             s.connected ? (s.simulated ? "warn" : "ok") : "bad"),
        stat("Puerto serie", esc(s.port || "—"), `${s.baudrate} baud · protocolo ${esc(s.protocol)} · último: ${s.last_sent.x},${s.last_sent.y} · reconexiones: ${s.reconnects}`),
        stat("Webcam", c.state === "streaming" ? "Emitiendo" : c.available ? "Conectada" : "Desconectada",
             c.available ? `${esc(c.name)} · ${c.fps_measured} fps · ${c.clients} espectador(es)` : esc(c.detail || ""), c.available ? "ok" : "bad"),
        stat("Wi-Fi", esc(w.mode), esc(w.detail || w.ssid || ""), w.state === "not_implemented" ? "warn" : "ok"),
        stat("Dirección IP", esc(w.ip), `http://${esc(w.ip)}:${location.port || 80}`),
        stat("Clientes conectados", m.clients),
        stat("Control de movimiento", S.isOwner ? "Lo tienes tú" : S.ownerPresent ? "Ocupado" : "Libre",
             `Salida: ${m.output.x},${m.output.y} · velocidad máx. ${m.max_speed}% · watchdog: ${m.watchdog_trips} paros`,
             S.ownerPresent ? "warn" : "ok"),
      ].join("");
    } catch (e) {
      $("status-grid").innerHTML = stat("Backend", "Sin respuesta", esc(e.message), "bad");
    }
  }
  setInterval(() => { if ($("tab-status").classList.contains("active")) refreshStatus(); }, 2000);

  /* ---------- ajustes ---------- */
  async function putConfig(patch) {
    const r = await fetch("/api/config", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
    return r.ok ? r.json() : Promise.reject(await r.json());
  }

  const fields = () => [...$("settings-form").querySelectorAll("[name]")];

  async function loadSettings() {
    const [cfg, st, ports] = await Promise.all([fetch("/api/config").then((r) => r.json()), fetch("/api/status").then((r) => r.json()),
                                               fetch("/api/serial/ports").then((r) => r.json())]);
    $("protocol-select").innerHTML = st.protocols.map((p) => `<option>${esc(p)}</option>`).join("");
    $("port-list").innerHTML = ["auto", ...ports.map((p) => p.device)].map((p) => `<option value="${esc(p)}">`).join("");
    const devs = st.camera.devices.map((d) => d.device);
    if (cfg.camera.device !== "auto" && !devs.includes(cfg.camera.device)) devs.push(cfg.camera.device);
    $("camera-select").innerHTML = ["auto", ...devs].map((d) => `<option>${esc(d)}</option>`).join("");
    for (const f of fields()) f.value = f.name.split(".").reduce((o, k) => o[k], cfg);
  }

  $("settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const patch = {};
    for (const f of fields()) {
      if (f.disabled) continue;
      const [sec, key] = f.name.split(".");
      (patch[sec] ||= {})[key] = f.type === "number" || f.name === "serial.baudrate" ? Number(f.value) : f.value;
    }
    try {
      await putConfig(patch);
      $("settings-msg").textContent = "Ajustes guardados.";
      refreshStatus();
    } catch (err) {
      $("settings-msg").textContent = "Error: " + (Array.isArray(err.detail) ? err.detail.map((d) => `${d.field}: ${d.msg}`).join("; ") : "no se pudo guardar");
    }
  });

  /* ---------- inicio ---------- */
  render();
  connect();
  refreshStatus();
})();
