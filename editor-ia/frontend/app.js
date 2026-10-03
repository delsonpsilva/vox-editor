"use strict";
/* Editor IA — painel (sem dependências, funciona offline) */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const S = { status: null, P: null, wave: [], cuts: [], ducks: [], zoom: 1, poll: null, raf: null, editing: false };

function fmt(t, ms = false) {
  if (t == null || isNaN(t)) return "0:00";
  t = Math.max(0, t);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = Math.floor(t % 60);
  const base = (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
  return ms ? base + "," + String(Math.floor((t % 1) * 10)) : base;
}
const fmtDur = (t) => { t = Math.round(t || 0); const m = Math.floor(t / 60), s = t % 60; return m ? `${m}min ${s}s` : `${s}s`; };
const fmtSize = (b) => b > 1e9 ? (b / 1e9).toFixed(2) + " GB" : (b / 1e6).toFixed(1) + " MB";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.classList.toggle("error", err); t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), err ? 7000 : 3000);
}

async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  if (r.status === 401) { show("login"); throw new Error("login necessário"); }
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = j.detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

function show(view) {
  $$(".view").forEach((v) => v.classList.add("hidden"));
  $("#view-" + view).classList.remove("hidden");
}

/* ---------------- início ---------------- */

async function boot() {
  try { S.status = await api("GET", "/api/status"); } catch (e) { S.status = {}; }
  $$(".app-name").forEach((el) => (el.textContent = S.status.name || "Editor IA"));
  document.title = S.status.name || "Editor IA";
  if (S.status.login_required) {
    try { await api("GET", "/api/projects"); } catch (_) { show("login"); return; }
  }
  route();
}

function route() {
  const m = location.hash.match(/^#\/p\/([0-9a-f]+)/);
  if (m) openProject(m[1]); else goHome();
}
window.addEventListener("hashchange", route);

async function goHome() {
  stopPoll();
  const v = $("#video"); v.pause();
  show("home");
  const st = S.status || {};
  const enc = st.encoder && st.encoder !== "libx264" ? "GPU (" + st.encoder.replace("h264_", "").toUpperCase() + ")" : "CPU";
  $("#sys-badge").textContent = st.ffmpeg ? `Renderização: ${enc}` : "FFmpeg não encontrado — rode o instalador";
  const list = await api("GET", "/api/projects");
  const box = $("#project-list");
  if (!list.length) { box.innerHTML = `<div class="empty">Nenhum projeto ainda. Envie seu primeiro vídeo acima.</div>`; return; }
  box.innerHTML = list.map((p) => `
    <button class="pcard" data-id="${p.id}">
      <span class="t">${esc(p.name)}</span>
      <span class="row"><span class="hint">${new Date(p.created * 1000).toLocaleString("pt-BR")}</span>
      <span class="chip mono">${p.duration ? fmt(p.duration) + (p.final ? " → " + fmt(p.final) : "") : "—"}</span></span>
      <span class="hint">${statusLabel(p)}</span>
    </button>`).join("");
  $$(".pcard", box).forEach((b) => b.addEventListener("click", () => (location.hash = "#/p/" + b.dataset.id)));
  if (list.some((p) => p.status !== "pronto" && p.status !== "erro")) {
    clearTimeout(goHome._t); goHome._t = setTimeout(() => { if (!location.hash) goHome(); }, 2500);
  }
}
function statusLabel(p) {
  if (p.status === "pronto") return "Pronto para editar";
  if (p.status === "erro") return "Erro: " + esc((p.progress || {}).msg || "");
  return `${esc((p.progress || {}).msg || "Processando")} ${Math.round(((p.progress || {}).pct || 0) * 100)}%`;
}

function setupUpload() {
  const dz = $("#dropzone"), input = $("#file-input");
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) upload(f); });
  input.addEventListener("change", () => { if (input.files[0]) upload(input.files[0]); input.value = ""; });
}

function upload(file) {
  const box = $("#upload-progress"), bar = $("i", box), lbl = $("span", box);
  box.classList.remove("hidden");
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/projects");
  xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
  const t0 = Date.now();
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = e.loaded / e.total, secs = (Date.now() - t0) / 1000;
    const speed = e.loaded / Math.max(secs, 0.1);
    bar.style.width = (pct * 100).toFixed(1) + "%";
    lbl.textContent = `Enviando ${file.name}: ${Math.round(pct * 100)}% · ${fmtSize(speed)}/s · faltam ${fmtDur((e.total - e.loaded) / speed)}`;
  };
  xhr.onload = () => {
    box.classList.add("hidden"); bar.style.width = "0";
    if (xhr.status >= 200 && xhr.status < 300) {
      const p = JSON.parse(xhr.responseText); location.hash = "#/p/" + p.id;
    } else {
      let msg = xhr.statusText; try { msg = JSON.parse(xhr.responseText).detail; } catch (_) {}
      toast("Falha no envio: " + msg, true);
    }
  };
  xhr.onerror = () => { box.classList.add("hidden"); toast("Falha de conexão no envio", true); };
  xhr.send(file);
}

/* ---------------- editor ---------------- */

async function openProject(id) {
  show("editor");
  try { S.P = await api("GET", "/api/projects/" + id); }
  catch (e) { toast(e.message, true); location.hash = ""; return; }
  S.wave = [];
  $("#ed-name").textContent = S.P.name;
  applyProject(true);
}

function applyProject(first = false) {
  const P = S.P;
  const ready = P.status === "pronto";
  $("#processing").classList.toggle("hidden", ready);
  $("#editor-body").classList.toggle("hidden", !ready);
  $("#btn-render").disabled = !ready; $("#btn-export").disabled = !ready;
  if (!ready) {
    const err = P.status === "erro";
    $("#proc-title").textContent = err ? "Não foi possível processar" : "Analisando o vídeo…";
    $("#proc-msg").textContent = (P.progress || {}).msg || "";
    $("#proc-bar").style.width = Math.round(((P.progress || {}).pct || 0) * 100) + "%";
    $(".spinner").classList.toggle("hidden", err);
    $("#btn-retry").classList.toggle("hidden", !err);
    startPoll();
    return;
  }
  const st = P.stats || {};
  $("#ed-dur").textContent = `${fmt(st.original)} → ${fmt(st.final)}`;
  S.cuts = (P.edit && P.edit.cuts) || [];
  S.ducks = (P.edit && P.edit.ducks) || [];
  if (first || !S.toolsBuilt) buildTools();
  if (first) setupMedia();
  renderTranscript();
  renderClips();
  renderRenders();
  renderStats();
  drawTimeline();
  if ((P.jobs || []).some((j) => j.status === "processando" || j.status === "na fila")) startPoll(); else stopPoll();
}

function renderStats() {
  const st = S.P.stats || {}, c = st.counts || {};
  const parts = [`Removido: ${fmtDur(st.removed_s)}`];
  if (c.silencio) parts.push(`${c.silencio} silêncios`);
  if (st.breaths) parts.push(`${st.breaths} respirações suavizadas`);
  if (c.respiracao) parts.push(`${c.respiracao} respirações cortadas`);
  if ((c.vicio || 0) + (c.repeticao || 0)) parts.push(`${(c.vicio || 0) + (c.repeticao || 0)} vícios e repetições`);
  if (c.manual) parts.push(`${c.manual} cortes manuais`);
  $("#stats").textContent = parts.join(" · ");
}

function startPoll() {
  if (S.poll) return;
  S.poll = setInterval(async () => {
    if (!S.P) return;
    try {
      const before = JSON.stringify((S.P.jobs || []).map((j) => j.status));
      const P = await api("GET", "/api/projects/" + S.P.id);
      const wasReady = S.P.status === "pronto";
      const after = JSON.stringify((P.jobs || []).map((j) => j.status));
      S.P = P;
      if (!wasReady && P.status === "pronto") { S.toolsBuilt = false; applyProject(true); return; }
      if (P.status !== "pronto") { applyProject(); return; }
      renderJobs();
      if (before !== after) {
        const done = (P.jobs || []).find((j) => j.status === "concluido" && j.kind === "render");
        renderRenders(); renderClips();
        if (done && before.includes("processando")) toast("Renderização concluída — veja em Exportados");
        const err = (P.jobs || []).find((j) => j.status === "erro");
        if (err && before.includes("processando")) toast(err.error, true);
      }
      if (!(P.jobs || []).some((j) => j.status === "processando" || j.status === "na fila")) stopPoll();
    } catch (_) {}
  }, 1000);
}
function stopPoll() { clearInterval(S.poll); S.poll = null; }

/* ---------- ferramentas (painel esquerdo) ---------- */

let pending = {}, pendT = null;
function setSetting(sec, key, val) {
  S.P.settings[sec][key] = val;
  pending[sec] = { ...(pending[sec] || {}), [key]: val };
  clearTimeout(pendT);
  pendT = setTimeout(async () => {
    const patch = pending; pending = {};
    try { S.P = await api("PUT", `/api/projects/${S.P.id}/settings`, patch); applyProject(); }
    catch (e) { toast(e.message, true); }
  }, 350);
}

function buildTools() {
  S.toolsBuilt = true;
  const st = S.P.settings, an = S.P.analysis || {}, lv = an.levels || {};
  const box = $("#tools");
  const sw = (sec, key, on) => `<button class="sw ${on ? "on" : ""}" data-sw="${sec}.${key}" aria-label="Ligar ou desligar" aria-pressed="${on}"></button>`;
  const range = (sec, key, label, min, max, step, unit, val) => `
    <label class="field"><span class="lbl">${label}<b data-out="${sec}.${key}">${val}${unit}</b></span>
    <input type="range" min="${min}" max="${max}" step="${step}" value="${val}" data-range="${sec}.${key}" data-unit="${unit}"></label>`;
  box.innerHTML = `
    <div class="hint" style="font-weight:600;letter-spacing:.08em;text-transform:uppercase">Edição com IA</div>

    <div class="tool ${st.silence.enabled ? "" : "disabled"}" data-tool="silence">
      <div class="tool-head"><span class="dot" style="background:var(--sil)"></span><strong>Cortar silêncios</strong>${sw("silence", "enabled", st.silence.enabled)}</div>
      <p>Remove pausas longas sem cortar o começo nem o fim das palavras.</p>
      <div class="opts">
        <label class="checkline"><input type="checkbox" data-check="silence.auto" ${st.silence.auto ? "checked" : ""}> Limite automático (${an.threshold ?? "—"} dB · fundo ${lv.floor ?? "—"} dB · voz ${lv.speech ?? "—"} dB)</label>
        <div data-manual-thr class="${st.silence.auto ? "hidden" : ""}">${range("silence", "threshold_db", "Silêncio abaixo de", -70, -15, 1, " dB", st.silence.threshold_db)}</div>
        ${range("silence", "min_dur", "Cortar pausas maiores que", 0.2, 3, 0.05, " s", st.silence.min_dur)}
        ${range("silence", "pad", "Margem antes/depois da fala", 0, 0.5, 0.01, " s", st.silence.pad)}
      </div>
    </div>

    <div class="tool ${st.breath.enabled ? "" : "disabled"}" data-tool="breath">
      <div class="tool-head"><span class="dot" style="background:var(--br)"></span><strong>Respirações</strong>${sw("breath", "enabled", st.breath.enabled)}</div>
      <p>Abaixar o volume deixa a fala natural; cortar deixa mais dinâmico.</p>
      <div class="opts">
        <select data-select="breath.mode" aria-label="Modo das respirações">
          <option value="attenuate" ${st.breath.mode === "attenuate" ? "selected" : ""}>Abaixar o volume (recomendado)</option>
          <option value="cut" ${st.breath.mode === "cut" ? "selected" : ""}>Cortar</option>
        </select>
        ${range("breath", "reduce_db", "Redução", 6, 40, 1, " dB", st.breath.reduce_db)}
      </div>
    </div>

    <div class="tool ${st.fillers.enabled ? "" : "disabled"}" data-tool="fillers">
      <div class="tool-head"><span class="dot" style="background:var(--fil)"></span><strong>Vícios e repetições</strong>${sw("fillers", "enabled", st.fillers.enabled)}</div>
      <p>Palavras como "é" e "tipo" só são cortadas quando aparecem soltas, entre pausas.</p>
      <div class="opts">
        <label class="field">Palavras (separe por vírgula)<input type="text" data-words value="${esc(st.fillers.words.join(", "))}"></label>
        <label class="checkline"><input type="checkbox" data-check="fillers.repetitions" ${st.fillers.repetitions ? "checked" : ""}> Cortar palavras repetidas ("eu eu")</label>
      </div>
    </div>

    <div class="tool ${st.subtitles.enabled ? "" : "disabled"}" data-tool="subtitles">
      <div class="tool-head"><span class="dot" style="background:#FACC15"></span><strong>Legendas</strong>${sw("subtitles", "enabled", st.subtitles.enabled)}</div>
      <p>Geradas palavra por palavra e sincronizadas com os cortes.</p>
      <div class="opts">
        <select data-select="subtitles.style" aria-label="Estilo da legenda">
          <option value="destaque" ${st.subtitles.style === "destaque" ? "selected" : ""}>Destaque palavra a palavra</option>
          <option value="classico" ${st.subtitles.style === "classico" ? "selected" : ""}>Clássica</option>
          <option value="caixa" ${st.subtitles.style === "caixa" ? "selected" : ""}>Com caixa de fundo</option>
        </select>
        <select data-select="subtitles.position" aria-label="Posição da legenda">
          <option value="baixo" ${st.subtitles.position === "baixo" ? "selected" : ""}>Embaixo</option>
          <option value="meio" ${st.subtitles.position === "meio" ? "selected" : ""}>No meio</option>
          <option value="topo" ${st.subtitles.position === "topo" ? "selected" : ""}>No topo</option>
        </select>
        ${range("subtitles", "max_chars", "Letras por linha", 14, 48, 1, "", st.subtitles.max_chars)}
        <div class="row">
          <label class="checkline"><input type="checkbox" data-check="subtitles.uppercase" ${st.subtitles.uppercase ? "checked" : ""}> MAIÚSCULAS</label>
          <div class="grow"></div>
          <input type="color" data-color="subtitles.color" value="${st.subtitles.color}" aria-label="Cor do texto">
          <input type="color" data-color="subtitles.highlight" value="${st.subtitles.highlight}" aria-label="Cor do destaque">
        </div>
        <label class="field">Fonte<input type="text" data-text="subtitles.font" value="${esc(st.subtitles.font)}"></label>
      </div>
    </div>

    <div class="tool ${st.audio.normalize ? "" : "disabled"}" data-tool="audio">
      <div class="tool-head"><span class="dot" style="background:#4ADE80"></span><strong>Volume profissional</strong>${sw("audio", "normalize", st.audio.normalize)}</div>
      <p>Normaliza o volume no padrão das plataformas.</p>
      <div class="opts">
        <select data-select="audio.target_lufs" aria-label="Padrão de volume">
          <option value="-14" ${st.audio.target_lufs == -14 ? "selected" : ""}>YouTube / Reels (−14 LUFS)</option>
          <option value="-16" ${st.audio.target_lufs == -16 ? "selected" : ""}>Podcast (−16 LUFS)</option>
          <option value="-23" ${st.audio.target_lufs == -23 ? "selected" : ""}>TV (−23 LUFS)</option>
        </select>
      </div>
    </div>
    <p class="hint" style="text-align:center">${S.P.transcribe_seconds != null ? `Transcrição feita em ${fmtDur(S.P.transcribe_seconds)}` : ""}</p>`;

  $$("[data-sw]", box).forEach((b) => b.addEventListener("click", () => {
    const [sec, key] = b.dataset.sw.split(".");
    const on = !b.classList.contains("on");
    b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
    b.closest(".tool").classList.toggle("disabled", !on);
    setSetting(sec, key, on);
  }));
  $$("[data-range]", box).forEach((r) => {
    r.addEventListener("input", () => { $(`[data-out="${r.dataset.range}"]`, box).textContent = r.value + r.dataset.unit; });
    r.addEventListener("change", () => { const [sec, key] = r.dataset.range.split("."); setSetting(sec, key, parseFloat(r.value)); });
  });
  $$("[data-check]", box).forEach((c) => c.addEventListener("change", () => {
    const [sec, key] = c.dataset.check.split(".");
    if (c.dataset.check === "silence.auto") $("[data-manual-thr]", box).classList.toggle("hidden", c.checked);
    setSetting(sec, key, c.checked);
  }));
  $$("[data-select]", box).forEach((s) => s.addEventListener("change", () => {
    const [sec, key] = s.dataset.select.split(".");
    setSetting(sec, key, key === "target_lufs" ? parseFloat(s.value) : s.value);
  }));
  $$("[data-color]", box).forEach((c) => c.addEventListener("change", () => { const [sec, key] = c.dataset.color.split("."); setSetting(sec, key, c.value); }));
  $$("[data-text]", box).forEach((c) => c.addEventListener("change", () => { const [sec, key] = c.dataset.text.split("."); setSetting(sec, key, c.value.trim()); }));
  $("[data-words]", box).addEventListener("change", (e) => setSetting("fillers", "words", e.target.value.split(",").map((x) => x.trim()).filter(Boolean)));
}

/* ---------- mídia / reprodução com cortes ---------- */

function setupMedia() {
  const v = $("#video");
  v.src = `/api/projects/${S.P.id}/media`;
  $("#audio-only").classList.toggle("hidden", !!S.P.media.has_video);
  v.style.display = S.P.media.has_video ? "" : "none";
  fetch(`/api/projects/${S.P.id}/wave`).then((r) => r.json()).then((w) => { S.wave = w; drawTimeline(); });
}

function activeRanges() {
  return S.cuts.filter((c) => c.active).map((c) => [c.s, c.e]).sort((a, b) => a[0] - b[0]);
}

function tick() {
  const v = $("#video");
  if (!S.P || !S.P.media || S.P.status !== "pronto") { S.raf = requestAnimationFrame(tick); return; }
  if ($("#chk-preview").checked && !v.paused) {
    const t = v.currentTime;
    for (const [s, e] of activeRanges()) {
      if (t >= s - 0.01 && t < e - 0.03) { v.currentTime = e; break; }
      if (s > t) break;
    }
    let vol = 1;
    for (const d of S.ducks) if (d.active && t >= d.s && t <= d.e) { vol = Math.pow(10, d.db / 20); break; }
    v.volume = vol;
  } else v.volume = 1;
  if (S.clipEnd != null && v.currentTime >= S.clipEnd) { v.pause(); S.clipEnd = null; }
  $("#time").textContent = `${fmt(v.currentTime, true)} / ${fmt(S.P.media.duration)}`;
  highlightWord(v.currentTime);
  drawPlayhead();
  S.raf = requestAnimationFrame(tick);
}

function togglePlay() {
  const v = $("#video");
  if (v.paused) v.play(); else v.pause();
}

/* ---------- transcrição ---------- */

function wordCut(w) {
  const mid = (w.s + w.e) / 2;
  for (const c of S.cuts) {
    if (c.type === "silencio" || c.type === "respiracao") continue;
    if (mid >= c.s && mid <= c.e) return c;
  }
  return null;
}

function renderTranscript() {
  const words = S.P.words || [];
  const box = $("#transcript");
  if (!words.length) {
    box.innerHTML = `<p class="hint">Sem transcrição (fala não detectada ou transcrição desativada). Os cortes de silêncio e respiração funcionam mesmo assim.</p>`;
    return;
  }
  const chips = [
    ...S.cuts.filter((c) => c.type === "silencio" || c.type === "respiracao").map((c) => ({ ...c, kind: c.type === "silencio" ? "sil" : "br" })),
    ...S.ducks.map((d) => ({ ...d, kind: "br", duck: true })),
  ].sort((a, b) => a.s - b.s);
  let ci = 0, html = "", lastTs = -999;
  words.forEach((w, i) => {
    while (ci < chips.length && chips[ci].s < w.s) {
      const c = chips[ci++];
      const d = (c.e - c.s).toFixed(1).replace(".", ",");
      const label = c.kind === "sil" ? `pausa ${d}s` : c.duck ? `respiração ${c.db} dB` : `respiração ${d}s`;
      html += `<button class="cchip ${c.kind} ${c.active ? "on" : "off"}" data-cut="${c.id}" title="${c.active ? "Clique para manter este trecho" : "Clique para aplicar de novo"}">${label}</button>`;
    }
    if (w.s - lastTs > 30 && (i === 0 || /[.?!]$/.test(words[i - 1].w))) { html += `<span class="ts">${fmt(w.s)}</span>`; lastTs = w.s; }
    const c = wordCut(w);
    const cls = c ? (c.active ? `cut ${c.type}` : "kept") : "";
    html += `<span class="w ${cls}" data-i="${i}"${c ? ` data-cut="${c.id}" data-type="${c.type}"` : ""}>${esc(w.w)}</span> `;
  });
  box.innerHTML = html;
  S.wordEls = $$(".w", box);
  S.nowIdx = -1;
}

function highlightWord(t) {
  const words = S.P.words || [];
  if (!words.length || !S.wordEls) return;
  let lo = 0, hi = words.length - 1, idx = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (words[m].s <= t) { idx = m; lo = m + 1; } else hi = m - 1; }
  if (idx >= 0 && t > words[idx].e + 0.3) idx = -1;
  if (idx === S.nowIdx) return;
  if (S.nowIdx >= 0 && S.wordEls[S.nowIdx]) S.wordEls[S.nowIdx].classList.remove("now");
  S.nowIdx = idx;
  if (idx >= 0 && S.wordEls[idx]) {
    const el = S.wordEls[idx]; el.classList.add("now");
    const box = $("#transcript");
    if (!$("#video").paused && (el.offsetTop < box.scrollTop || el.offsetTop > box.scrollTop + box.clientHeight - 40))
      box.scrollTop = el.offsetTop - box.clientHeight / 3;
  }
}

async function toggleCut(id, type) {
  try {
    S.P = type === "manual"
      ? await api("DELETE", `/api/projects/${S.P.id}/cuts/${id}`)
      : await api("POST", `/api/projects/${S.P.id}/cuts/${id}/toggle`);
    applyProject();
  } catch (e) { toast(e.message, true); }
}

function setupTranscript() {
  const box = $("#transcript");
  box.addEventListener("click", (e) => {
    if (S.editing) return;
    const chip = e.target.closest(".cchip");
    if (chip) { toggleCut(chip.dataset.cut); return; }
    const w = e.target.closest(".w");
    if (!w || !window.getSelection().isCollapsed) return;
    if (w.dataset.cut && w.classList.contains("cut")) { toggleCut(w.dataset.cut, w.dataset.type); return; }
    const word = S.P.words[+w.dataset.i];
    $("#video").currentTime = word.s; S.clipEnd = null;
  });
  box.addEventListener("dblclick", (e) => {
    const w = e.target.closest(".w");
    if (!w || w.classList.contains("cut")) return;
    e.preventDefault(); window.getSelection().removeAllRanges();
    editWord(w);
  });
  document.addEventListener("selectionchange", () => {
    const r = selectedWords();
    const bar = $("#sel-bar");
    if (!r) { bar.classList.add("hidden"); return; }
    const rect = window.getSelection().getRangeAt(0).getBoundingClientRect();
    const host = $(".transcript-box").getBoundingClientRect();
    bar.style.left = Math.max(8, rect.left - host.left) + "px";
    bar.style.top = (rect.bottom - host.top + 6) + "px";
    bar.classList.remove("hidden");
  });
  $("#btn-cut-sel").addEventListener("mousedown", (e) => e.preventDefault());
  $("#btn-cut-sel").addEventListener("click", cutSelection);
}

function selectedWords() {
  const sel = window.getSelection();
  if (!sel.rangeCount || sel.isCollapsed) return null;
  const box = $("#transcript");
  const range = sel.getRangeAt(0);
  if (!box.contains(range.commonAncestorContainer)) return null;
  const ws = $$(".w", box).filter((el) => range.intersectsNode(el));
  if (!ws.length) return null;
  return [+ws[0].dataset.i, +ws[ws.length - 1].dataset.i];
}

async function cutSelection() {
  const r = selectedWords();
  if (!r) return;
  const words = S.P.words;
  const a = words[r[0]], b = words[r[1]];
  const prevE = r[0] > 0 ? words[r[0] - 1].e : 0;
  const nextS = r[1] + 1 < words.length ? words[r[1] + 1].s : b.e + 0.2;
  const s = Math.max(prevE + 0.02, a.s - 0.04), e = Math.min(nextS - 0.02, b.e + 0.06);
  window.getSelection().removeAllRanges();
  $("#sel-bar").classList.add("hidden");
  try { S.P = await api("POST", `/api/projects/${S.P.id}/cuts`, { s, e }); applyProject(); toast("Trecho cortado"); }
  catch (err) { toast(err.message, true); }
}

function editWord(el) {
  const i = +el.dataset.i;
  S.editing = true;
  const old = S.P.words[i].w;
  el.innerHTML = `<input value="${esc(old)}" size="${Math.max(4, old.length + 2)}" aria-label="Corrigir palavra">`;
  const inp = $("input", el); inp.focus(); inp.select();
  const done = async (save) => {
    if (!S.editing) return;
    S.editing = false;
    const val = inp.value.trim();
    if (save && val && val !== old) {
      try { S.P = await api("PUT", `/api/projects/${S.P.id}/words/${i}`, { w: val }); applyProject(); return; }
      catch (e) { toast(e.message, true); }
    }
    el.textContent = old;
  };
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); e.stopPropagation(); });
  inp.addEventListener("blur", () => done(true));
}

/* ---------- cortes sugeridos ---------- */

function renderClips() {
  const clips = S.P.clips || [];
  $("#clips-src").textContent = S.P.clips_source ? `Análise: ${S.P.clips_source}` : "";
  const box = $("#clips");
  if (!clips.length) { box.innerHTML = `<p class="hint">Nenhum corte sugerido ainda. Vídeos curtos ou sem fala podem não gerar cortes.</p>`; return; }
  box.innerHTML = clips.map((c) => `
    <div class="clip" data-clip="${c.id}">
      <div class="row between"><span class="meta mono">${fmt(c.s)}–${fmt(c.e)} · ${Math.round(c.e - c.s)}s</span>${c.score ? `<span class="score">nota ${Math.round(c.score)}</span>` : ""}</div>
      <div class="ttl" contenteditable="true" spellcheck="false" data-title>${esc(c.title)}</div>
      ${c.reason ? `<div class="meta">${esc(c.reason)}</div>` : ""}
      <div class="row">
        <button class="btn small" data-play>▶ Assistir</button>
        <button class="btn small primary" data-rclip='{"vertical":true,"subtitles":true}'>Vertical 9:16</button>
        <button class="btn small" data-rclip='{"vertical":false,"subtitles":true}'>Horizontal</button>
      </div>
    </div>`).join("");
  $$(".clip", box).forEach((el) => {
    const c = clips.find((x) => x.id === el.dataset.clip);
    $("[data-play]", el).addEventListener("click", () => { const v = $("#video"); v.currentTime = c.s; S.clipEnd = c.e; v.play(); });
    $$("[data-rclip]", el).forEach((b) => b.addEventListener("click", () => startRender(`/api/projects/${S.P.id}/clips/${c.id}/render`, JSON.parse(b.dataset.rclip))));
    const t = $("[data-title]", el);
    t.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") { e.preventDefault(); t.blur(); } });
    t.addEventListener("blur", () => { const val = t.textContent.trim(); if (val && val !== c.title) api("PUT", `/api/projects/${S.P.id}/clips/${c.id}`, { title: val }).then((P) => (S.P = P)); });
  });
}

/* ---------- renderizações ---------- */

async function startRender(url, body) {
  try {
    S.P = await api("POST", url, body);
    switchTab("renders"); renderJobs(); startPoll();
    toast("Renderização adicionada à fila");
  } catch (e) { toast(e.message, true); }
}

function renderJobs() {
  const jobs = (S.P.jobs || []).filter((j) => j.status !== "concluido" || Date.now() / 1000 - j.created < 5);
  $("#jobs").innerHTML = jobs.filter((j) => j.status !== "concluido").map((j) => `
    <div class="job ${j.status === "erro" ? "erro" : ""}">
      <div class="row between"><strong>${esc(j.label || j.kind)}</strong><span class="mono">${j.status === "erro" ? "erro" : Math.round(j.pct * 100) + "%"}</span></div>
      <div class="bar"><i style="width:${Math.round(j.pct * 100)}%"></i></div>
      <span class="hint">${esc(j.status === "erro" ? j.error : j.msg)}</span>
    </div>`).join("");
}

function renderRenders() {
  renderJobs();
  const rs = S.P.renders || [];
  $("#renders").innerHTML = rs.length ? rs.map((r) => `
    <div class="render">
      <span class="name">${esc(r.file)}</span>
      <span class="hint">${fmt(r.duration)} · ${fmtSize(r.size)} · ${r.vertical ? "9:16" : "horizontal"}${r.subtitles ? " · legendas" : ""} · feito em ${fmtDur(r.seconds)} (${r.encoder === "libx264" ? "CPU" : esc((r.encoder || "").replace("h264_", "").toUpperCase())})</span>
      <div class="row">
        <a class="btn small primary" href="/api/projects/${S.P.id}/renders/${encodeURIComponent(r.file)}" download>Baixar</a>
        <button class="btn small ghost" data-del="${esc(r.file)}">Apagar</button>
      </div>
    </div>`).join("") : `<p class="hint">Os vídeos renderizados aparecem aqui.</p>`;
  $$("[data-del]", $("#renders")).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Apagar este arquivo exportado?")) return;
    S.P = await api("DELETE", `/api/projects/${S.P.id}/renders/${encodeURIComponent(b.dataset.del)}`); renderRenders();
  }));
}

function switchTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $("#tab-clips").classList.toggle("hidden", name !== "clips");
  $("#tab-renders").classList.toggle("hidden", name !== "renders");
}

/* ---------- linha do tempo ---------- */

function drawTimeline() {
  const cv = $("#tl"); if (!cv || !S.P || !S.P.media) return;
  const wrap = $("#tl-scroll");
  const W = Math.max(300, wrap.clientWidth * S.zoom), H = 120, dpr = window.devicePixelRatio || 1;
  cv.style.width = W + "px"; cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d"); g.scale(dpr, dpr);
  const dur = S.P.media.duration || 1, x = (t) => (t / dur) * W;
  g.fillStyle = "#121418"; g.fillRect(0, 0, W, H);
  // régua
  g.fillStyle = "#8E929B"; g.font = "10px " + getComputedStyle(document.body).getPropertyValue("--mono");
  const stepOpts = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];
  const step = stepOpts.find((s) => (s / dur) * W > 70) || 3600;
  for (let t = 0; t <= dur; t += step) { g.fillRect(x(t), 0, 1, 6); g.fillText(fmt(t), x(t) + 3, 10); }
  // cortes sugeridos (faixa verde)
  g.fillStyle = "rgba(74,222,128,.35)";
  for (const c of S.P.clips || []) g.fillRect(x(c.s), 14, Math.max(2, x(c.e) - x(c.s)), 6);
  // forma de onda
  const top = 26, h = 70, mid = top + h / 2, n = S.wave.length;
  if (n) {
    g.fillStyle = "#4ADE80";
    const bw = W / n;
    for (let i = 0; i < n; i++) { const a = S.wave[i] * h / 2; g.fillRect(i * bw, mid - a, Math.max(1, bw - 0.3), a * 2 || 1); }
  }
  // cortes e respirações
  const colors = { silencio: "rgba(255,138,61,.55)", respiracao: "rgba(90,169,255,.55)", vicio: "rgba(192,132,252,.6)", repeticao: "rgba(192,132,252,.6)", manual: "rgba(248,113,113,.6)" };
  for (const c of S.cuts) {
    if (!c.active) continue;
    g.fillStyle = colors[c.type] || colors.manual;
    g.fillRect(x(c.s), top, Math.max(1, x(c.e) - x(c.s)), h);
  }
  g.fillStyle = "rgba(90,169,255,.45)";
  for (const d of S.ducks) if (d.active) g.fillRect(x(d.s), top + h - 10, Math.max(1, x(d.e) - x(d.s)), 10);
  // trilha do resultado final
  g.fillStyle = "#2B3A52"; g.fillRect(0, 102, W, 12);
  g.fillStyle = "#5AA9FF";
  for (const [s, e] of (S.P.edit || {}).keeps || []) g.fillRect(x(s), 102, Math.max(1, x(e) - x(s)), 12);
  S.tlImage = g.getImageData(0, 0, cv.width, cv.height);
  drawPlayhead(true);
}

function drawPlayhead(force) {
  const cv = $("#tl"); if (!S.tlImage || !cv) return;
  const v = $("#video"), dur = S.P.media.duration || 1;
  const px = Math.round((v.currentTime / dur) * cv.width);
  if (!force && px === S.lastPx) return;
  S.lastPx = px;
  const g = cv.getContext("2d");
  g.putImageData(S.tlImage, 0, 0);
  g.fillStyle = "#FFFFFF"; g.fillRect(px - 1, 0, 2 * (window.devicePixelRatio || 1), cv.height);
}

function setupTimeline() {
  $("#tl").addEventListener("click", (e) => {
    const cv = e.currentTarget, r = cv.getBoundingClientRect();
    $("#video").currentTime = ((e.clientX - r.left) / r.width) * S.P.media.duration; S.clipEnd = null;
  });
  $("#zoom-in").addEventListener("click", () => { S.zoom = Math.min(64, S.zoom * 2); drawTimeline(); followPlayhead(); });
  $("#zoom-out").addEventListener("click", () => { S.zoom = Math.max(1, S.zoom / 2); drawTimeline(); });
  window.addEventListener("resize", () => { clearTimeout(S.rz); S.rz = setTimeout(drawTimeline, 150); });
}
function followPlayhead() {
  const wrap = $("#tl-scroll"), cv = $("#tl");
  const px = ($("#video").currentTime / S.P.media.duration) * cv.clientWidth;
  wrap.scrollLeft = px - wrap.clientWidth / 2;
}

/* ---------- configurações ---------- */

const PRESETS = {
  groq: { "transcription.api_base": "https://api.groq.com/openai/v1", "transcription.api_model": "whisper-large-v3-turbo" },
  openai: { "transcription.api_base": "https://api.openai.com/v1", "transcription.api_model": "whisper-1" },
};
const AI_MODELS = { anthropic: "claude-haiku-4-5-20251001", openai_compat: "gpt-4o-mini" };

async function openSettings() {
  const cfg = await api("GET", "/api/settings");
  const form = $("#settings-form");
  $$("[name]", form).forEach((el) => {
    const [sec, key] = el.name.split(".");
    if (el.dataset.key !== undefined) {
      el.value = "";
      el.placeholder = cfg[sec].api_key_set ? `Configurada (${cfg[sec].api_key_hint || "oculta"}) — deixe vazio para manter` : "Cole sua chave aqui";
    } else el.value = cfg[sec][key] ?? "";
  });
  const st = S.status || {};
  $("#sys-info").textContent = `Detectado: renderização ${st.encoder && st.encoder !== "libx264" ? "com GPU (" + st.encoder + ")" : "pelo processador"} · transcrição local ${st.local_transcription ? (st.gpu_transcription ? "com GPU NVIDIA" : "pelo processador") : "não instalada"}.`;
  $("#ai-test").textContent = "";
  refreshShow();
  $("#settings").showModal();
}

function refreshShow() {
  const form = $("#settings-form");
  $$("[data-show]", form).forEach((el) => {
    const m = el.dataset.show.match(/^([\w.]+)(!?=)(\w+)$/);
    const val = form.elements[m[1]].value;
    el.classList.toggle("hidden", m[2] === "=" ? val !== m[3] : val === m[3]);
  });
}

function collectSettings() {
  const out = {};
  $$("[name]", $("#settings-form")).forEach((el) => {
    const [sec, key] = el.name.split(".");
    out[sec] = out[sec] || {};
    if (el.dataset.key !== undefined && !el.value) return;
    out[sec][key] = el.value;
  });
  return out;
}

function setupSettings() {
  $$("[data-open-settings]").forEach((b) => b.addEventListener("click", openSettings));
  const form = $("#settings-form");
  form.addEventListener("change", (e) => {
    if (e.target.name === "ai.provider" && AI_MODELS[e.target.value]) form.elements["ai.model"].value = AI_MODELS[e.target.value];
    refreshShow();
  });
  $$("[data-preset]", form).forEach((b) => b.addEventListener("click", () => {
    for (const [k, v] of Object.entries(PRESETS[b.dataset.preset])) form.elements[k].value = v;
  }));
  $("#btn-save-settings").addEventListener("click", async (e) => {
    e.preventDefault();
    try { await api("PUT", "/api/settings", collectSettings()); $("#settings").close(); toast("Configurações salvas"); }
    catch (err) { toast(err.message, true); }
  });
  $("#btn-test-ai").addEventListener("click", async () => {
    $("#ai-test").textContent = "Testando…";
    await api("PUT", "/api/settings", collectSettings());
    const r = await api("POST", "/api/settings/test-ai");
    $("#ai-test").textContent = r.msg;
  });
}

/* ---------- ligações gerais ---------- */

function setupEditor() {
  $("#btn-back").addEventListener("click", () => { location.hash = ""; });
  $("#btn-play").addEventListener("click", togglePlay);
  const v = $("#video");
  v.addEventListener("play", () => { $("#ico-play").classList.add("hidden"); $("#ico-pause").classList.remove("hidden"); });
  v.addEventListener("pause", () => { $("#ico-pause").classList.add("hidden"); $("#ico-play").classList.remove("hidden"); });
  v.addEventListener("click", togglePlay);
  $("#btn-retry").addEventListener("click", async () => { S.P = await api("POST", `/api/projects/${S.P.id}/reprocess`); applyProject(); });
  $("#btn-reset").addEventListener("click", async () => {
    if (!confirm("Desfazer todos os cortes manuais e restaurações?")) return;
    S.P = await api("POST", `/api/projects/${S.P.id}/reset`); applyProject();
  });
  $("#btn-regen").addEventListener("click", async () => {
    S.P = await api("POST", `/api/projects/${S.P.id}/clips/regenerate`); startPoll(); toast("Gerando novos cortes…");
  });
  $$(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
  // menus
  const menus = [["#btn-export", "#menu-export"], ["#btn-render", "#menu-render"]];
  menus.forEach(([b, m]) => $(b).addEventListener("click", (e) => {
    e.stopPropagation(); menus.forEach(([, o]) => o !== m && $(o).classList.add("hidden")); $(m).classList.toggle("hidden");
  }));
  document.addEventListener("click", () => menus.forEach(([, m]) => $(m).classList.add("hidden")));
  $$("[data-export]").forEach((a) => a.addEventListener("click", () => { location.href = `/api/projects/${S.P.id}/export/${a.dataset.export}`; }));
  $$("[data-render]").forEach((a) => a.addEventListener("click", () => startRender(`/api/projects/${S.P.id}/render`, JSON.parse(a.dataset.render))));
  // atalhos
  document.addEventListener("keydown", (e) => {
    if ($("#view-editor").classList.contains("hidden") || S.editing) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (["input", "select", "textarea"].includes(tag) || e.target.isContentEditable) return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    if ((e.key === "Delete" || e.key === "Backspace") && selectedWords()) { e.preventDefault(); cutSelection(); }
    if (e.key === "ArrowLeft") $("#video").currentTime -= 5;
    if (e.key === "ArrowRight") $("#video").currentTime += 5;
  });
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await api("POST", "/api/login", { password: $("#login-pass").value }); $("#login-err").textContent = ""; route(); }
  catch (err) { $("#login-err").textContent = "Senha incorreta"; }
});

setupUpload(); setupEditor(); setupTranscript(); setupTimeline(); setupSettings();
S.raf = requestAnimationFrame(tick);
boot();
