"use strict";
/* Editor IA — painel (sem dependências, funciona offline) */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
let markReady;
const READY = new Promise((r) => (markReady = r));
const S = { status: null, meta: null, cfg: null, P: null, wave: [], cuts: [], ducks: [], zoom: 1, poll: null,
  editing: false, mode: "edit", sel: null, sq: null, si: 0, scaps: [], filter: "all", framing: {} };

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
const hash = (o) => { const s = JSON.stringify(o); let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return (h >>> 0).toString(36); };

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
  applyAppIdentity(); applyMode();
  if (S.status.login_required) {
    try { await api("GET", "/api/projects"); } catch (_) { show("login"); return; }
  }
  try { S.meta = await api("GET", "/api/meta"); S.cfg = await api("GET", "/api/settings"); } catch (_) {}
  updateIABadge();
  markReady();
  route();
}

function route() {
  const m = location.hash.match(/^#\/p\/([0-9a-f]+)(\/cortes)?/);
  if (m) { S.mode = m[2] ? "studio" : "edit"; openProject(m[1]); return; }
  const pg = (location.hash.match(/^#\/(projetos|exportados|marca|publicacoes|modelos|redes|ia)/) || [])[1] || "inicio";
  goHome(pg);
}
window.addEventListener("hashchange", () => READY.then(route));

async function goHome(page = "inicio") {
  stopPoll();
  $("#video").pause(); $("#svideo").pause();
  S.P = null;
  show("home");
  S.prevPage = S.page; S.page = page;
  $$(".side-nav a[data-page]").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
  $$(".pages .page").forEach((el) => el.classList.toggle("hidden", el.id !== "pg-" + page));
  const st = S.status || {};
  const enc = st.encoder && st.encoder !== "libx264" ? "GPU (" + st.encoder.replace("h264_", "").toUpperCase() + ")" : "processador";
  $("#sys-badge").textContent = st.ffmpeg ? `Exportação pelo ${enc} · versão ${st.version}` : "FFmpeg não encontrado — rode o instalador";
  let list = [];
  try { list = await api("GET", "/api/projects"); } catch (e) { toast(e.message, true); return; }
  S.projects = list;
  $("#nav-count-p").textContent = list.length || "";
  loadDashboard();
  if (page === "inicio") renderProjectCards($("#recent-list"), [...list].sort((a, b) => b.updated - a.updated).slice(0, 6), true);
  if (page === "projetos") renderProjectsPage();
  if (page === "exportados") renderLibrary();
  if (page === "marca") renderBrandPage();
  if (page === "publicacoes") renderQueue();
  if (page === "modelos") renderModelos();
  if (page === "redes") renderRedes();
  if (page === "ia" && !(S.prevPage === "ia" && $("#ia-form").dataset.loaded)) renderIA();
  if (page !== "ia") delete $("#ia-form").dataset.loaded;
  refreshQueueCount();
  if (list.some((p) => p.status !== "pronto" && p.status !== "erro")) {
    clearTimeout(goHome._t);
    goHome._t = setTimeout(() => { if (S.P === null && !$("#view-home").classList.contains("hidden")) goHome(S.page); }, 2500);
  }
}

const fmtHours = (sec) => { sec = Math.round(sec || 0); if (sec < 600) return fmtDur(sec); const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60); return h ? `${h}h${String(m).padStart(2, "0")}` : `${m} min`; };

async function loadDashboard() {
  try {
    const d = await api("GET", "/api/dashboard");
    $("#nav-count-r").textContent = d.renders || "";
    const used = d.storage, free = d.free || 0;
    $("#st-used").textContent = fmtSize(used);
    $("#st-bar").style.width = Math.min(100, (used / Math.max(1, used + free)) * 100 * 8).toFixed(1) + "%";
    $("#dash-summary").innerHTML = d.projects
      ? `Você já enviou <b>${fmtHours(d.seconds_in)}</b> de vídeo em <b>${d.projects}</b> projeto${d.projects > 1 ? "s" : ""}. A IA tirou <b>${fmtHours(d.removed)}</b> de silêncio e hesitação, criou <b>${d.clips}</b> corte${d.clips === 1 ? "" : "s"} e você exportou <b>${d.renders}</b> vídeo${d.renders === 1 ? "" : "s"}.`
      : "Envie o primeiro vídeo para começar. A análise roda sozinha: transcrição, silêncios, respirações e sugestões de cortes.";
  } catch (_) {}
}

function miniTimeline(p) {
  if (!p.timeline || !p.timeline.length) return "";
  const bars = p.timeline.map(([a, b]) => `<i style="left:${(a * 100).toFixed(2)}%;width:${Math.max(0.3, (b - a) * 100).toFixed(2)}%"></i>`).join("");
  const cut = Math.max(0, (p.duration || 0) - (p.final || 0));
  return `<div class="mini-tl" title="Azul: o que ficou · Laranja: o que foi cortado">${bars}</div>
    <div class="mini-legend"><span>${fmt(p.duration)} → ${fmt(p.final)}</span><span>${cut >= 1 ? `−${cut < 600 ? fmtDur(cut) : fmtHours(cut)} cortados` : "sem cortes"}</span></div>`;
}

function renderProjectCards(box, list, compact = false) {
  if (!list.length) {
    box.innerHTML = `<div class="empty-state">${S.projects && S.projects.length ? "Nenhum projeto encontrado com essa busca." : "Nenhum projeto ainda. Arraste um vídeo para a faixa acima para começar."}</div>`;
    return;
  }
  box.innerHTML = list.map((p) => {
    const busy = p.status !== "pronto" && p.status !== "erro";
    const pct = Math.round(((p.progress || {}).pct || 0) * 100);
    return `<article class="pc" data-id="${p.id}">
      <button class="poster" data-open aria-label="Abrir ${esc(p.name)}">
        ${p.has_video ? `<img src="/api/projects/${p.id}/poster" alt="" loading="lazy" onerror="this.remove()">` : ""}
        <span class="noimg ${p.has_video ? "behind" : ""}"><svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg></span>
        ${p.duration ? `<span class="dur">${fmt(p.duration)}</span>` : ""}
        ${busy ? `<span class="state"><span>${esc((p.progress || {}).msg || "Processando")} ${pct}%</span><span class="bar"><i style="width:${pct}%"></i></span></span>` : ""}
        ${p.status === "erro" ? `<span class="state"><span>Não foi possível processar. Abra para tentar de novo.</span></span>` : ""}
      </button>
      <button class="menu-btn" data-menu aria-label="Ações do projeto"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg></button>
      <div class="menu hidden">
        <a data-act="edit">Abrir edição</a>
        <a data-act="studio">Abrir cortes e resumos</a>
        <a data-act="exports">Ver vídeos exportados (${p.renders})</a>
        <a data-act="rename">Renomear</a>
        ${p.status === "pronto" ? `<a data-act="pacote">Baixar projeto completo (.vox)</a>` : ""}
        ${p.status === "pronto" && !isOnline() ? `<a data-act="online">Enviar para o online</a>` : ""}
        <a data-act="delete" class="danger">Excluir projeto</a>
      </div>
      <div class="body">
        <div class="ttl" title="${esc(p.name)}">${esc(p.name)}</div>
        ${miniTimeline(p)}
        <div class="meta"><span>${new Date((p.updated || p.created) * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
          <span>${p.clips ? `${p.clips} corte${p.clips > 1 ? "s" : ""}` : ""}${p.clips && p.renders ? " · " : ""}${p.renders ? `${p.renders} exportado${p.renders > 1 ? "s" : ""}` : ""}</span></div>
      </div>
    </article>`;
  }).join("");
  $$(".pc", box).forEach((card) => {
    const p = list.find((x) => x.id === card.dataset.id);
    $("[data-open]", card).addEventListener("click", () => (location.hash = "#/p/" + p.id + (p.clips ? "/cortes" : "")));
    const menu = $(".menu", card);
    $("[data-menu]", card).addEventListener("click", (e) => { e.stopPropagation(); $$(".pc .menu").forEach((m) => m !== menu && m.classList.add("hidden")); menu.classList.toggle("hidden"); });
    $$("[data-act]", card).forEach((a) => a.addEventListener("click", () => projectAction(a.dataset.act, p)));
  });
}

async function projectAction(act, p) {
  $$(".pc .menu").forEach((m) => m.classList.add("hidden"));
  if (act === "edit") location.hash = "#/p/" + p.id;
  if (act === "studio") location.hash = "#/p/" + p.id + "/cortes";
  if (act === "exports") { S.libProject = p.id; location.hash = "#/exportados"; }
  if (act === "pacote") baixarPacote(p);
  if (act === "online") enviarOnline(p);
  if (act === "rename") {
    const name = await ask("Renomear projeto", "", p.name);
    if (name && name.trim() && name.trim() !== p.name) {
      try { await api("PATCH", `/api/projects/${p.id}`, { name: name.trim() }); toast("Projeto renomeado"); goHome(S.page); }
      catch (e) { toast(e.message, true); }
    }
  }
  if (act === "delete") {
    const ok = await ask("Excluir projeto?", `"${p.name}" será apagado com a edição, os cortes e os ${p.renders} vídeo(s) exportado(s). Isso não pode ser desfeito.`, null, "Excluir");
    if (ok) {
      try { await api("DELETE", `/api/projects/${p.id}`); toast("Projeto excluído"); goHome(S.page); }
      catch (e) { toast(e.message, true); }
    }
  }
}

function ask(title, text, value = null, okLabel = "Salvar") {
  return new Promise((resolve) => {
    const dlg = $("#askdlg"), inp = $("#ask-input");
    $("#ask-title").textContent = title; $("#ask-text").textContent = text || "";
    $("#ask-text").classList.toggle("hidden", !text);
    inp.classList.toggle("hidden", value === null); inp.value = value ?? "";
    $("#ask-ok").textContent = value === null ? okLabel : "Salvar";
    $("#ask-ok").classList.toggle("danger", okLabel === "Excluir");
    dlg.onclose = () => resolve(dlg.returnValue === "ok" ? (value === null ? true : inp.value) : null);
    dlg.returnValue = "";
    dlg.showModal();
    if (value !== null) { inp.focus(); inp.select(); }
  });
}

function renderProjectsPage() {
  const q = ($("#proj-search").value || "").toLowerCase().trim(), sort = $("#proj-sort").value;
  let list = (S.projects || []).filter((p) => !q || p.name.toLowerCase().includes(q));
  const by = { updated: (a, b) => b.updated - a.updated, created: (a, b) => b.created - a.created,
    name: (a, b) => a.name.localeCompare(b.name, "pt-BR"), duration: (a, b) => (b.duration || 0) - (a.duration || 0) }[sort];
  renderProjectCards($("#project-list"), list.sort(by));
}

async function renderLibrary() {
  let rs = [];
  try { rs = await api("GET", "/api/renders"); } catch (e) { toast(e.message, true); return; }
  const plats = (S.meta || {}).platforms || {};
  const projs = [...new Map(rs.map((r) => [r.project, r.project_name])).entries()];
  const selP = $("#lib-project"), selF = $("#lib-platform");
  if (S.libProject) { selP.dataset.v = S.libProject; S.libProject = null; }
  selP.innerHTML = `<option value="">Todos os projetos</option>` + projs.map(([id, n]) => `<option value="${id}">${esc(n)}</option>`).join("");
  selP.value = selP.dataset.v || "";
  const usedPlats = [...new Set(rs.map((r) => r.platform || ""))];
  selF.innerHTML = `<option value="">Todos os destinos</option>` + usedPlats.map((k) => `<option value="${k}">${esc(k ? (plats[k] || {}).name || k : "Vídeo editado (horizontal)")}</option>`).join("");
  selF.value = selF.dataset.v || "";
  const list = rs.filter((r) => (!selP.value || r.project === selP.value) && (!selF.value || (r.platform || "") === selF.value));
  const box = $("#lib-list");
  if (!list.length) { box.innerHTML = `<div class="empty-state">${rs.length ? "Nada com esse filtro." : "Nenhum vídeo exportado ainda. Abra um projeto e exporte um corte ou o vídeo editado."}</div>`; return; }
  box.innerHTML = list.map((r, i) => {
    const p = plats[r.platform] || null, url = `/api/projects/${r.project}/renders/${encodeURIComponent(r.file)}`;
    return `<article class="lc">
      <div class="th ${r.vertical ? "" : "h"}" data-i="${i}">
        <img src="${url}/thumb" alt="" loading="lazy" onerror="this.remove()">
        <span class="plat-tag">${p ? `<i style="background:${p.color}"></i>${esc(p.short)}` : "16:9"}</span>
        <span class="dur">${fmt(r.duration)}</span>
      </div>
      <div class="body">
        <span class="name" title="${esc(r.label || r.file)}">${esc(r.label || r.file)}</span>
        <span class="meta">${esc(r.project_name)}<br>${new Date(r.created * 1000).toLocaleDateString("pt-BR")} · ${fmtSize(r.size)}</span>
        <div class="row">
          <button class="btn small" data-play="${i}">Assistir</button>
          <a class="btn small" href="${url}" download>Baixar</a>
        </div>
        <button class="btn small primary" data-pub="${i}">Publicar nas redes</button>
      </div>
    </article>`;
  }).join("");
  $$("[data-pub]", box).forEach((b) => b.addEventListener("click", () => openPublish(list[+b.dataset.pub])));
  $$("[data-play]", box).forEach((b) => b.addEventListener("click", () => {
    const r = list[+b.dataset.play], th = $(`.th[data-i="${b.dataset.play}"]`, box);
    th.innerHTML = `<video src="/api/projects/${r.project}/renders/${encodeURIComponent(r.file)}" controls autoplay playsinline></video>`;
  }));
}

/* ---------- publicações ---------- */

const NET_COLORS = { youtube: "#FF3040", instagram: "#E1306C", facebook: "#3B8CFF", tiktok: "#25F4EE" };
const DAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

async function refreshQueueCount() {
  try { const q = await api("GET", "/api/publish/queue"); $("#nav-count-q").textContent = q.filter((x) => x.status === "agendado" || x.status === "publicando").length || ""; } catch (_) {}
}

async function renderQueue() {
  let q = [], st = {};
  try { [q, st] = await Promise.all([api("GET", "/api/publish/queue"), api("GET", "/api/publish/status")]); } catch (e) { toast(e.message, true); return; }
  S.pubStatus = st;
  const f = S.qFilter || "agendado";
  $$("#q-filter .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.v === f));
  const list = q.filter((x) => f === "agendado" ? (x.status === "agendado" || x.status === "publicando") : x.status === f);
  const box = $("#q-list");
  if (!list.length) {
    box.innerHTML = `<div class="empty-state">${f === "agendado" ? "Nada na fila. Em Exportados, clique em <b>Publicar nas redes</b> num vídeo pronto." : f === "publicado" ? "Nenhuma publicação feita ainda." : "Nenhum erro. Tudo certo."}</div>`;
  } else {
    let html = "", lastDay = "";
    for (const it of list) {
      const d = new Date(it.when * 1000);
      const day = d.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
      if (day !== lastDay) { html += `<div class="q-day">${esc(day.charAt(0).toUpperCase() + day.slice(1))}</div>`; lastDay = day; }
      const net = (st.networks || {})[it.net] || { name: it.net };
      html += `<div class="qi" data-id="${it.id}">
        <img src="/api/projects/${it.project}/renders/${encodeURIComponent(it.file)}/thumb" alt="" onerror="this.style.visibility='hidden'">
        <div>
          <div class="t">${esc(it.title || it.label || it.file)}</div>
          <div class="s">${esc(it.caption || "Sem legenda")}</div>
          <div class="when"><span class="net-chip"><i style="background:${NET_COLORS[it.net]}"></i>${esc(net.name)}</span>
            <span>${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>
            <span class="st-chip ${it.status}">${{ agendado: "agendado", publicando: `publicando ${Math.round((it.pct || 0) * 100)}%`, publicado: "publicado", erro: "erro" }[it.status] || it.status}</span>
            <span class="hint">${esc(it.project_name)}</span></div>
          ${it.status === "erro" ? `<div class="err-msg">${esc(it.error)}</div>` : ""}
          ${it.status === "publicado" && it.msg && it.msg !== "Publicado" ? `<div class="hint">${esc(it.msg)}</div>` : ""}
        </div>
        <div class="acts">
          ${it.status === "publicado" && it.url ? `<a class="btn small" href="${esc(it.url)}" target="_blank" rel="noopener">Ver na rede</a>` : ""}
          ${it.status === "agendado" ? `<button class="btn small" data-qnow>Publicar agora</button>` : ""}
          ${it.status === "erro" ? `<button class="btn small primary" data-qretry>Tentar de novo</button>` : ""}
          ${it.status !== "publicando" ? `<button class="btn small ghost" data-qdel>${it.status === "agendado" ? "Cancelar" : "Remover"}</button>` : ""}
        </div>
      </div>`;
    }
    box.innerHTML = html;
    $$(".qi", box).forEach((row) => {
      const id = row.dataset.id;
      const b1 = $("[data-qnow]", row); if (b1) b1.addEventListener("click", async () => { await api("PUT", `/api/publish/queue/${id}`, { when: Date.now() / 1000 }); toast("Vai ser publicado em instantes"); renderQueue(); });
      const b2 = $("[data-qretry]", row); if (b2) b2.addEventListener("click", async () => { await api("POST", `/api/publish/queue/${id}/retry`); renderQueue(); });
      const b3 = $("[data-qdel]", row); if (b3) b3.addEventListener("click", async () => { await api("DELETE", `/api/publish/queue/${id}`); renderQueue(); refreshQueueCount(); });
    });
  }
  renderSlots(st.slots || []);
  clearTimeout(S.qT);
  if (q.some((x) => x.status === "publicando" || (x.status === "agendado" && x.when * 1000 < Date.now() + 120000)))
    S.qT = setTimeout(() => { if (S.page === "publicacoes" && !S.P) renderQueue(); }, 4000);
}

function renderSlots(slots) {
  S.slots = JSON.parse(JSON.stringify(slots));
  const box = $("#slots");
  if (!S.slots.length) box.innerHTML = `<p class="hint">Nenhum horário. Adicione pelo menos um para usar "próximo horário livre".</p>`;
  else box.innerHTML = S.slots.map((sl, i) => `<div class="slot" data-i="${i}">
      <div class="days">${DAYS.map((d, k) => `<button type="button" data-d="${k}" class="${sl.days.includes(k) ? "on" : ""}" aria-pressed="${sl.days.includes(k)}">${d}</button>`).join("")}</div>
      <input type="time" value="${sl.time}" aria-label="Horário">
      <button class="btn small ghost" data-sdel>Remover</button></div>`).join("");
  const save = async () => { try { await api("PUT", "/api/publish/config", { slots: S.slots }); } catch (e) { toast(e.message, true); } };
  $$(".slot", box).forEach((row) => {
    const i = +row.dataset.i;
    $$("[data-d]", row).forEach((b) => b.addEventListener("click", () => {
      const d = +b.dataset.d, days = S.slots[i].days;
      S.slots[i].days = days.includes(d) ? days.filter((x) => x !== d) : [...days, d];
      if (!S.slots[i].days.length) S.slots[i].days = [d];
      renderSlots(S.slots); save();
    }));
    $("input", row).addEventListener("change", (e) => { S.slots[i].time = e.target.value || "19:00"; save(); });
    $("[data-sdel]", row).addEventListener("click", () => { S.slots.splice(i, 1); renderSlots(S.slots); save(); });
  });
}

async function openPublish(r) {
  let st;
  try { st = await api("GET", "/api/publish/status"); } catch (e) { toast(e.message, true); return; }
  S.pubTarget = r;
  const dlg = $("#pubdlg");
  $("#pub-thumb").src = `/api/projects/${r.project}/renders/${encodeURIComponent(r.file)}/thumb`;
  $("#pub-label").textContent = r.label || r.file;
  $("#pub-meta").textContent = `${r.project_name || ""} · ${fmt(r.duration)}`;
  let suggest = { ig_reels: "instagram", ig_stories: "instagram", yt_shorts: "youtube", tiktok: "tiktok", fb_reels: "facebook" }[r.platform];
  if (suggest && !(st.networks[suggest] || {}).connected) suggest = null;
  $("#pub-nets").innerHTML = Object.entries(st.networks).map(([k, n]) => `
    <label class="${n.connected ? "" : "off"}"><input type="checkbox" value="${k}" ${n.connected ? "" : "disabled"} ${n.connected && (k === suggest || !suggest) ? "checked" : ""}>
      <span><i class="net-dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${NET_COLORS[k]};margin-right:5px"></i>${esc(n.name)}
      <small>${n.connected ? esc(n.account) : "não conectado"}</small></span></label>`).join("");
  $("#pub-title").value = (r.title || r.label || "").slice(0, 100);
  $("#pub-caption").value = r.post || "";
  $("#pub-err").textContent = Object.values(st.networks).some((n) => n.connected) ? "" : "Nenhuma rede conectada ainda. Conecte em Redes sociais.";
  $$("input[name=pub-when]").forEach((x) => (x.checked = x.value === "slot"));
  $("#pub-at").classList.add("hidden");
  const d = new Date(Date.now() + 3600e3); d.setMinutes(0, 0, 0);
  $("#pub-at").value = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  dlg.showModal();
}

function setupPublish() {
  $$("#q-filter .seg-btn").forEach((b) => b.addEventListener("click", () => { S.qFilter = b.dataset.v; renderQueue(); }));
  $("#slot-add").addEventListener("click", async () => {
    S.slots = [...(S.slots || []), { days: [0, 1, 2, 3, 4, 5, 6], time: "12:00" }];
    renderSlots(S.slots); await api("PUT", "/api/publish/config", { slots: S.slots });
  });
  $$("input[name=pub-when]").forEach((x) => x.addEventListener("change", () => $("#pub-at").classList.toggle("hidden", !$("input[name=pub-when][value=at]").checked)));
  $("#pub-ok").addEventListener("click", async (e) => {
    e.preventDefault();
    const r = S.pubTarget, nets = $$("#pub-nets input:checked").map((x) => x.value);
    if (!nets.length) { $("#pub-err").textContent = "Escolha pelo menos uma rede conectada."; return; }
    const when = $("input[name=pub-when]:checked").value;
    const body = { project: r.project, file: r.file, nets, when, caption: $("#pub-caption").value, title: $("#pub-title").value,
      privacy: $("#pub-privacy").value, label: r.label || "" };
    if (when === "at") body.at = new Date($("#pub-at").value).getTime() / 1000;
    try {
      const res = await api("POST", "/api/publish/queue", body);
      $("#pubdlg").close();
      const first = Math.min(...res.items.map((x) => x.when));
      toast(when === "now" ? "Aprovado: publicando agora" : `Aprovado: agendado para ${new Date(first * 1000).toLocaleString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}`);
      refreshQueueCount();
      if (!S.P) { S.qFilter = "agendado"; location.hash = "#/publicacoes"; }
    } catch (err) { $("#pub-err").textContent = err.message; }
  });
}

/* ---------- redes sociais ---------- */

const APP_HELP = {
  youtube: { title: "Conectar o YouTube", id: "ID do cliente", html: `<ol>
    <li>Entre em <b>console.cloud.google.com</b>, crie um projeto e ative a <b>YouTube Data API v3</b>.</li>
    <li>Em <b>Credenciais</b>, crie um <b>ID do cliente OAuth</b> do tipo <b>Aplicativo da Web</b> e cole o endereço de retorno abaixo em "URIs de redirecionamento autorizados".</li>
    <li>Cole aqui o <b>ID do cliente</b> e a <b>chave secreta</b>.</li></ol>
    <p>Até o Google aprovar o seu projeto (auditoria da API), os vídeos enviados ficam <b>privados</b>; depois disso, saem públicos.</p>` },
  meta: { title: "Conectar Instagram e Facebook", id: "ID do app", html: `<ol>
    <li>Entre em <b>developers.facebook.com</b>, crie um app do tipo <b>Empresa</b> e adicione o <b>Login do Facebook para Empresas</b> e a <b>API do Instagram</b>.</li>
    <li>Cole o endereço de retorno abaixo nas <b>URIs de redirecionamento do OAuth válidas</b>.</li>
    <li>Seu Instagram precisa ser <b>profissional</b> (Criador ou Empresa) e estar ligado a uma <b>página do Facebook</b>.</li>
    <li>Cole aqui o <b>ID do app</b> e a <b>chave secreta</b>.</li></ol>
    <p>Com o app em modo de desenvolvimento, a postagem funciona nas contas em que você é administrador. Limite: 100 posts por dia no Instagram.</p>` },
  tiktok: { title: "Conectar o TikTok", id: "Client key", html: `<ol>
    <li>Entre em <b>developers.tiktok.com</b>, crie um app e adicione <b>Login Kit</b> e <b>Content Posting API</b> (com Direct Post).</li>
    <li>Cadastre o endereço de retorno abaixo. O TikTok costuma exigir endereço <b>https</b>: nesse caso, use a versão online com domínio próprio.</li>
    <li>Cole aqui a <b>Client key</b> e a <b>Client secret</b>.</li></ol>
    <p>Até o TikTok aprovar o app (auditoria), os vídeos saem <b>privados</b>.</p>` },
};

async function renderRedes() {
  const m = location.hash.match(/[?&](conectado|erro)=([^&]*)/);
  $("#net-msg").innerHTML = m ? `<div class="banner ${m[1] === "conectado" ? "ok" : "bad"}">${m[1] === "conectado" ? "Conta conectada com sucesso." : "Não foi possível conectar: " + esc(decodeURIComponent(m[2]))}</div>` : "";
  let st;
  try { st = await api("GET", "/api/publish/status"); } catch (e) { toast(e.message, true); return; }
  S.pubStatus = st;
  const notes = { youtube: "Privado até a aprovação do seu projeto no Google.", instagram: "Reels pela conta profissional ligada à página.",
    facebook: "Reels na página do Facebook escolhida.", tiktok: "Privado até a aprovação do app pelo TikTok." };
  $("#net-cards").innerHTML = Object.entries(st.networks).map(([k, n]) => `
    <div class="nc" data-net="${k}" data-app="${n.app}">
      <div class="hd"><i style="background:${NET_COLORS[k]}"></i><b>${esc(n.name)}</b></div>
      <div class="acc ${n.connected ? "ok" : ""}">${n.connected ? "Conectado: " + esc(n.account) : n.warn ? esc(n.warn) : n.app_ready ? "Pronto para conectar" : "Falta configurar o app desta rede"}</div>
      ${n.pages && n.pages.length > 1 ? `<label class="field">Página<select data-page>${n.pages.map((pg) => `<option value="${pg.id}" ${pg.id === n.page_id ? "selected" : ""}>${esc(pg.name)}${pg.ig ? " (@" + esc(pg.ig) + ")" : ""}</option>`).join("")}</select></label>` : ""}
      <div class="note">${notes[k]}</div>
      <div class="row">
        <button class="btn small" data-app-cfg>Configurar app</button>
        ${n.connected ? `<button class="btn small ghost" data-disc>Desconectar</button>` : `<a class="btn small primary ${n.app_ready ? "" : "disabled"}" href="${n.app_ready ? `/api/oauth/${n.app}/start` : "#/redes"}" data-conn>Conectar</a>`}
      </div>
    </div>`).join("") + `<div class="nc"><div class="hd"><i style="background:#25D366"></i><b>Status do WhatsApp</b></div>
      <div class="acc">Sem postagem automática</div><div class="note">O WhatsApp não oferece forma oficial de publicar no Status. Exporte em "Status do WhatsApp" e poste pelo celular.</div></div>`;
  $$("#net-cards .nc[data-net]").forEach((c) => {
    const app = c.dataset.app;
    $("[data-app-cfg]", c).addEventListener("click", () => openAppCfg(app));
    const d = $("[data-disc]", c); if (d) d.addEventListener("click", async () => { if (await ask("Desconectar?", "As postagens agendadas para esta conta vão dar erro até você conectar de novo.", null, "Desconectar")) { await api("DELETE", `/api/publish/account/${app}`); renderRedes(); } });
    const cn = $("[data-conn]", c); if (cn && !st.networks[c.dataset.net].app_ready) cn.addEventListener("click", (e) => { e.preventDefault(); openAppCfg(app); });
    const pg = $("[data-page]", c); if (pg) pg.addEventListener("change", async (e) => { await api("POST", "/api/publish/page", { page_id: e.target.value }); renderRedes(); });
  });
  // selos nos vídeos
  const b = brand();
  $("#br-soc-mode").value = b.social_mode || "destino"; $("#br-soc-every").value = String(b.social_every || 12);
  $("#br-soc-side").value = b.social_side || "direita";
  renderSocialRows();
}

function openAppCfg(app) {
  const h = APP_HELP[app], a = (S.pubStatus.apps || {})[app] || {};
  $("#app-title").textContent = h.title; $("#app-help").innerHTML = h.html;
  $("#app-id-lbl").firstChild.textContent = h.id;
  $("#app-redirect").value = `${location.origin}/api/oauth/${app}/callback`;
  $("#app-id").value = a.client_id || ""; $("#app-secret").value = "";
  $("#app-secret").placeholder = a.secret_set ? "Já salva — deixe vazio para manter" : "Cole a chave secreta";
  $("#appdlg").dataset.app = app;
  $("#appdlg").showModal();
}

function setupRedes() {
  $("#app-save").addEventListener("click", async (e) => {
    e.preventDefault();
    const app = $("#appdlg").dataset.app;
    try {
      S.pubStatus = await api("PUT", "/api/publish/config", { [app]: { client_id: $("#app-id").value, client_secret: $("#app-secret").value } });
      $("#appdlg").close(); toast("App salvo. Agora clique em Conectar."); renderRedes();
    } catch (err) { toast(err.message, true); }
  });
  $("#app-redirect").addEventListener("focus", (e) => e.target.select());
}

/* ---------- modelos ---------- */

async function renderModelos() {
  let d;
  try { d = await api("GET", "/api/defaults"); } catch (e) { toast(e.message, true); return; }
  S.defaults = d.defaults; S.mSel = { frame: d.defaults.studio.frame || "cheia", style: d.defaults.subtitles.style };
  const pid = d.preview_project;
  const meta = S.meta || {};
  $("#m-frames").innerHTML = Object.entries(meta.layouts || {}).map(([k, l]) => `
    <button class="style-card ${S.mSel.frame === k ? "active" : ""}" data-mf="${k}">
      <div class="im">${pid ? `<img src="/api/projects/${pid}/frame-preview?layout=${k}" alt="" onload="this.classList.add('ok')">` : ""}</div>
      <div class="tx"><b>${esc(l.name)}</b><small>${esc(l.desc)}</small></div></button>`).join("");
  $("#m-styles").innerHTML = Object.entries(meta.styles || {}).map(([k, st]) => `
    <button class="style-card ${S.mSel.style === k ? "active" : ""}" data-ms="${k}">
      <div class="im">${pid ? `<img src="/api/projects/${pid}/subtitle-preview?style=${k}&v=padrao" alt="" onload="this.classList.add('ok')">` : ""}</div>
      <div class="tx"><b>${esc(st.name)}</b><small>${esc(st.desc)}</small></div></button>`).join("");
  const np = $("#m-noprev"); if (np) np.remove();
  if (!pid) $("#m-frames").insertAdjacentHTML("beforebegin", `<p class="hint" id="m-noprev">As prévias aparecem depois que você tiver um projeto pronto.</p>`);
  $$("[data-mf]").forEach((b) => b.addEventListener("click", () => { S.mSel.frame = b.dataset.mf; $$("[data-mf]").forEach((x) => x.classList.toggle("active", x === b)); }));
  $$("[data-ms]").forEach((b) => b.addEventListener("click", () => { S.mSel.style = b.dataset.ms; $$("[data-ms]").forEach((x) => x.classList.toggle("active", x === b)); }));
  const sub = d.defaults.subtitles;
  $("#m-size").value = sub.size_pct ?? 100; $("#m-size-out").textContent = $("#m-size").value + "%";
  $("#m-y").value = sub.y_pct ?? 18; $("#m-y-out").textContent = yLabel(+$("#m-y").value);
  $("#m-layout").value = d.defaults.studio.layout || "face";
  renderModelosExtras(d.defaults);
}

function setupModelos() {
  $("#m-size").addEventListener("input", (e) => ($("#m-size-out").textContent = e.target.value + "%"));
  $("#m-y").addEventListener("input", (e) => ($("#m-y-out").textContent = yLabel(+e.target.value)));
  $("#m-save").addEventListener("click", async () => {
    const k = S.mSel.style, sd = (S.meta.style_defaults || {})[k] || {};
    const subtitles = { style: k, font: sd.font, uppercase: sd.uppercase, max_chars: sd.max_chars, lines: sd.lines,
      color: sd.color, highlight: sd.highlight, position: sd.position, size_pct: +$("#m-size").value, y_pct: +$("#m-y").value };
    const studioD = { frame: S.mSel.frame, layout: $("#m-layout").value };
    const ex = modelosExtras();
    Object.assign(subtitles, ex.subtitles); Object.assign(studioD, ex.studio);
    try {
      const r = await api("PUT", "/api/defaults", { subtitles, studio: studioD, audio: ex.audio, apply_all: $("#m-apply-all").checked });
      toast(r.applied ? `Padrão salvo e aplicado em ${r.applied} projeto(s)` : "Padrão salvo para os próximos projetos");
    } catch (e) { toast(e.message, true); }
  });
}

function renderBrandPage() {
  const app = S.status || {};
  $("#app-name").value = app.name || "Editor IA";
  $("#app-tagline").value = app.tagline || "";
  $("#app-accent").value = app.accent || "#FF8A3D";
  const b = brand(), nets = Object.entries((b.socials || {})).filter(([, v]) => v.on && v.handle).map(([k]) => ((S.meta || {}).socials || {})[k]?.name || k);
  $("#brand-summary").innerHTML = `
    <span>@perfil: <b>${esc(b.handle || "não definido")}</b></span>
    <span>Cores: <span class="sw" style="background:${b.color}"></span>tarja <span class="sw" style="background:${b.text}"></span>texto <span class="sw" style="background:${b.bg}"></span>fundo</span>
    <span>Logo nos vídeos: <b>${b.logo ? "sim" : "não"}</b> · Selo padrão: <b>${esc(b.kicker || "nenhum")}</b></span>
    <span>Redes nos selos: <b>${nets.length ? esc(nets.join(", ")) : "nenhuma"}</b></span>`;
}

function lighten(hex, f) {
  const n = parseInt(hex.slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
  const m = (c) => Math.round(c + (255 - c) * f);
  return `rgb(${m(r)},${m(g)},${m(b)})`;
}

function applyAppIdentity() {
  const st = S.status || {}, name = st.name || "Editor IA";
  $$(".app-name").forEach((el) => (el.textContent = name));
  $$(".app-tagline").forEach((el) => (el.textContent = st.tagline || ""));
  document.title = name;
  const acc = /^#[0-9a-f]{6}$/i.test(st.accent || "") ? st.accent : "#FF8A3D";
  const root = document.documentElement.style;
  root.setProperty("--accent", acc); root.setProperty("--accent-2", lighten(acc, 0.35));
  const n = parseInt(acc.slice(1), 16), lum = (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
  root.setProperty("--on-accent", lum > 0.6 ? "#17181C" : "#FFFFFF");
  root.setProperty("--accent-soft", `color-mix(in srgb, ${acc} 15%, transparent)`);
  $$(".logo.app-logo").forEach((el) => {
    el.classList.toggle("custom", !!st.app_logo);
    el.style.backgroundImage = st.app_logo ? `url("/api/app/logo?v=${S.appLogoV || 0}")` : "";
  });
}

function setupHome() {
  $("#proj-search").addEventListener("input", renderProjectsPage);
  $("#proj-sort").addEventListener("change", renderProjectsPage);
  $("#lib-project").addEventListener("change", (e) => { e.target.dataset.v = e.target.value; renderLibrary(); });
  $("#lib-platform").addEventListener("change", (e) => { e.target.dataset.v = e.target.value; renderLibrary(); });
  $("#file-input-2").addEventListener("change", (e) => { if (e.target.files[0]) { location.hash = "#/"; upload(e.target.files[0]); } e.target.value = ""; });
  document.addEventListener("click", () => $$(".pc .menu").forEach((m) => m.classList.add("hidden")));
  $("#btn-clean").addEventListener("click", async () => {
    const ok = await ask("Liberar espaço?", "Apaga só arquivos temporários (miniaturas, prévias e áudio de trabalho). Projetos, cortes e vídeos exportados ficam intactos; o que for preciso é refeito sozinho.", null, "Liberar");
    if (!ok) return;
    const r = await api("POST", "/api/maintenance/clean");
    toast(`${fmtSize(r.freed)} liberados`); loadDashboard();
  });
  const saveApp = async (patch) => {
    try { await api("PUT", "/api/settings", { app: patch }); S.status = await api("GET", "/api/status"); applyAppIdentity(); toast("Identidade salva"); }
    catch (e) { toast(e.message, true); }
  };
  $("#app-name").addEventListener("change", (e) => saveApp({ name: e.target.value.trim() || "Editor IA" }));
  $("#app-tagline").addEventListener("change", (e) => saveApp({ tagline: e.target.value.trim() }));
  $("#app-accent").addEventListener("change", (e) => saveApp({ accent: e.target.value }));
  $("#app-logo-file").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const r = await fetch("/api/app/logo", { method: "POST", body: f });
    if (!r.ok) { toast("Não consegui usar essa imagem (PNG ou JPG)", true); return; }
    S.appLogoV = Date.now(); S.status = await api("GET", "/api/status"); applyAppIdentity(); toast("Logo do programa atualizada");
    e.target.value = "";
  });
  $("#app-logo-del").addEventListener("click", async () => { await api("DELETE", "/api/app/logo"); S.status = await api("GET", "/api/status"); applyAppIdentity(); });
  $("#btn-open-brand").addEventListener("click", openBrand);
}

function statusLabel(p) {
  if (p.status === "pronto") return "Pronto para editar";
  if (p.status === "erro") return "Erro: " + esc((p.progress || {}).msg || "");
  return `${esc((p.progress || {}).msg || "Processando")} ${Math.round(((p.progress || {}).pct || 0) * 100)}%`;
}

function setupUpload() {
  const dz = $("#dropzone"), input = $("#file-input");
  $("#link-form").addEventListener("submit", (e) => { e.preventDefault(); importLink($("#link-url").value); });
  // colar um link em qualquer lugar da tela inicial já preenche o campo
  document.addEventListener("paste", (e) => {
    if (S.page !== "inicio" || $("#view-home").classList.contains("hidden") || /input|textarea/i.test(e.target.tagName)) return;
    const t = (e.clipboardData || window.clipboardData).getData("text") || "";
    if (/^https?:\/\//i.test(t.trim())) { $("#link-url").value = t.trim(); $("#link-url").focus(); }
  });
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) upload(f); });
  // também aceita soltar o vídeo em qualquer parte da tela inicial
  const home = $("#view-home");
  home.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
  home.addEventListener("dragleave", (e) => { if (e.target === home) dz.classList.remove("over"); });
  home.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("over"); const f = e.dataTransfer.files[0]; if (f && e.target !== dz && !dz.contains(e.target)) upload(f); });
  input.addEventListener("change", () => { if (input.files[0]) upload(input.files[0]); input.value = ""; });
}

/* ---------- importar pelo link e pelo arquivo do PC ---------- */

async function importLink(url) {
  url = (url || "").trim();
  if (!/^https?:\/\//i.test(url)) { toast("Cole um link completo, começando com https://", true); return; }
  const btn = $("#link-go"); btn.disabled = true;
  try {
    const p = await api("POST", "/api/projects/link", { url });
    $("#link-url").value = "";
    location.hash = "#/p/" + p.id;
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; }
}

async function importPath(path) {
  try { const p = await api("POST", "/api/projects/path", { path }); location.hash = "#/p/" + p.id; }
  catch (e) { toast(e.message, true); }
}

/* ---------- programa do PC (janela própria) ---------- */

const DESK = { on: false };
function deskApi() { return DESK.on && window.pywebview && window.pywebview.api; }

function setupDesktop() {
  const ready = () => {
    if (DESK.on || !(window.pywebview && window.pywebview.api)) return;
    DESK.on = true; document.body.classList.add("desktop");
  };
  window.addEventListener("pywebviewready", ready);
  ready();
  // escolher o vídeo pela janela do Windows: usa o arquivo direto, sem reenviar
  const pick = async (e) => {
    const a = deskApi(); if (!a) return;
    e.preventDefault(); e.stopPropagation();
    const path = await a.pick_video();
    if (path) { location.hash = "#/"; importPath(path); }
  };
  $("#dropzone").addEventListener("click", pick, true);
  const np = $("label[for=file-input-2]"); if (np) np.addEventListener("click", pick, true);
  document.addEventListener("click", async (e) => {
    const a = deskApi(); if (!a) return;
    const link = e.target.closest && e.target.closest("a[href]"); if (!link) return;
    const href = link.getAttribute("href");
    if (link.hasAttribute("download")) {  // "Baixar": janela Salvar do Windows
      e.preventDefault();
      let name = link.getAttribute("download") || decodeURIComponent(href.split("?")[0].split("/").pop() || "arquivo");
      if (!/\.\w{2,4}$/.test(name)) name += href.includes("/cover") ? ".jpg" : ".mp4";
      toast("Escolha onde salvar…");
      try { const dest = await a.save_file(href, name); if (dest) { toast("Salvo em " + dest); a.show_in_folder(dest); } }
      catch (err) { toast("Não consegui salvar: " + err, true); }
      return;
    }
    if (link.hasAttribute("data-conn") && href.startsWith("/api/oauth/")) {  // login da rede no navegador
      e.preventDefault();
      await a.open_external(href + (href.includes("?") ? "&" : "?") + "desk=1");
      toast("Faça o login no navegador. Quando terminar, volte aqui.");
      let n = 0; clearInterval(DESK.t);
      DESK.t = setInterval(async () => {
        if (++n > 100 || S.page !== "redes") { clearInterval(DESK.t); return; }
        const st = await api("GET", "/api/publish/status").catch(() => null);
        const net = link.closest(".nc") && link.closest(".nc").dataset.net;
        if (st && net && st.networks[net] && st.networks[net].connected) { clearInterval(DESK.t); toast("Conta conectada!"); renderRedes(); }
      }, 3000);
      return;
    }
    if (link.target === "_blank" || link.hasAttribute("data-ext")) { e.preventDefault(); a.open_external(link.href); }
  }, true);
  // fechar com postagens agendadas ou trabalhos em andamento
  window.voxConfirmClose = (posts, busy) => {
    const parts = [];
    if (busy) parts.push(`${busy} trabalho(s) em andamento (análise, download ou exportação) vão parar`);
    if (posts) parts.push(`${posts} publicação(ões) agendada(s) só vão sair quando o programa estiver aberto`);
    $("#close-msg").textContent = "Se fechar agora, " + parts.join(" e ") + ". Minimize para continuar trabalhando em segundo plano.";
    $("#closedlg").showModal();
  };
  $("#close-force").addEventListener("click", () => { const a = deskApi(); if (a) a.quit(); });
  $("#close-min").addEventListener("click", () => { const a = deskApi(); if (a) a.minimize(); });
}

function upload(file) {
  const box = $("#upload-progress"), bar = $("i", box), lbl = box.lastElementChild;
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

/* ---------------- projeto ---------------- */

async function openProject(id) {
  show("editor");
  const same = S.P && S.P.id === id;
  try { S.P = await api("GET", "/api/projects/" + id); }
  catch (e) { toast(e.message, true); location.hash = ""; return; }
  if (!same) { S.wave = []; S.toolsBuilt = false; S.mediaSet = false; S.sel = null; S.framing = {}; }
  $("#ed-name").textContent = S.P.name;
  applyProject();
}

function setMode(mode) {
  S.mode = mode;
  const base = "#/p/" + S.P.id + (mode === "studio" ? "/cortes" : "");
  if (location.hash !== base) history.replaceState(null, "", base);
  $$(".seg-btn[data-mode]").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $$(".edit-only").forEach((el) => el.classList.toggle("hidden", mode !== "edit"));
  if (S.P && S.P.status === "pronto") {
    $("#editor-body").classList.toggle("hidden", mode !== "edit");
    $("#studio-body").classList.toggle("hidden", mode !== "studio");
  }
  if (mode === "edit") { $("#svideo").pause(); drawTimeline(); } else { $("#video").pause(); renderStudio(); }
}

function applyProject() {
  const P = S.P;
  if (P.name && document.activeElement !== $("#ed-name") && $("#ed-name").textContent !== P.name) $("#ed-name").textContent = P.name;
  const ready = P.status === "pronto";
  $("#processing").classList.toggle("hidden", ready);
  if (!ready) {
    $("#editor-body").classList.add("hidden"); $("#studio-body").classList.add("hidden");
    const err = P.status === "erro";
    $("#proc-title").textContent = err ? "Não foi possível processar" : P.status === "baixando" ? "Trazendo o vídeo…" : "Analisando o vídeo…";
    $("#proc-msg").textContent = (P.progress || {}).msg || "";
    $("#proc-bar").style.width = Math.round(((P.progress || {}).pct || 0) * 100) + "%";
    $(".spinner", $("#processing")).classList.toggle("hidden", err);
    $("#btn-retry").classList.toggle("hidden", !err);
    $$(".edit-only").forEach((el) => el.classList.add("hidden"));
    startPoll();
    return;
  }
  const st = P.stats || {};
  $("#ed-dur").textContent = `${fmt(st.original)} → ${fmt(st.final)}`;
  S.cuts = (P.edit && P.edit.cuts) || [];
  S.ducks = (P.edit && P.edit.ducks) || [];
  if (!S.toolsBuilt) buildTools();
  if (!S.mediaSet) setupMedia();
  setMode(S.mode);
  renderTranscript();
  renderRenders();
  renderStats();
  if (S.mode === "edit") drawTimeline();
  if (busy()) startPoll(); else stopPoll();
}

const busy = () => (S.P.jobs || []).some((j) => j.status === "processando" || j.status === "na fila");

function renderStats() {
  const st = S.P.stats || {}, c = st.counts || {};
  const parts = [`Removido: ${fmtDur(st.removed_s)}`];
  if (c.silencio) parts.push(`${c.silencio} silêncios`);
  if (st.breaths) parts.push(`${st.breaths} respirações suavizadas`);
  if (c.respiracao) parts.push(`${c.respiracao} respirações cortadas`);
  if ((c.vicio || 0) + (c.repeticao || 0)) parts.push(`${(c.vicio || 0) + (c.repeticao || 0)} vícios e repetições`);
  if (c.gaguejo) parts.push(`${c.gaguejo} palavras quebradas`);
  if (c.ia) parts.push(`${c.ia} limpezas da IA`);
  if (c.manual) parts.push(`${c.manual} cortes manuais`);
  $("#stats").textContent = parts.join(" · ");
}

function startPoll() {
  if (S.poll) return;
  S.poll = setInterval(async () => {
    if (!S.P) return;
    try {
      const before = JSON.stringify((S.P.jobs || []).map((j) => j.id + j.status));
      const clipsBefore = JSON.stringify(S.P.clips);
      const P = await api("GET", "/api/projects/" + S.P.id);
      const wasReady = S.P.status === "pronto";
      S.P = P;
      if (!wasReady || P.status !== "pronto") { applyProject(); return; }
      renderJobs();
      const after = JSON.stringify((P.jobs || []).map((j) => j.id + j.status));
      if (before !== after) {
        renderRenders();
        const fin = (P.jobs || []).filter((j) => before.includes(j.id + "processando") && j.status !== "processando");
        fin.forEach((j) => {
          if (j.status === "erro") toast(j.error, true);
          else if (j.kind === "render") toast("Pronto: " + (j.label || "vídeo") + " — veja em Exportados");
          else if (j.kind === "cortes") toast(`${(j.result || {}).count || 0} cortes gerados (${(j.result || {}).source || ""})`);
          else if (j.kind === "limpeza") { toast(`A IA marcou ${(j.result || {}).count || 0} trecho(s) para limpar`); S.toolsBuilt = false; applyProject(); }
        });
      }
      if (JSON.stringify(P.clips) !== clipsBefore || S.mode === "studio") renderStudioProgress();
      if (JSON.stringify(P.clips) !== clipsBefore) renderStudio();
      if (!busy()) { stopPoll(); renderStudioProgress(); }
    } catch (_) {}
  }, 1000);
}
function stopPoll() { clearInterval(S.poll); S.poll = null; }

/* ---------- ferramentas (painel esquerdo da edição) ---------- */

let pending = {}, pendT = null;
function setSetting(sec, key, val, delay = 350) {
  S.P.settings[sec] = S.P.settings[sec] || {};
  S.P.settings[sec][key] = val;
  pending[sec] = { ...(pending[sec] || {}), [key]: val };
  clearTimeout(pendT);
  return new Promise((res) => {
    pendT = setTimeout(async () => {
      const patch = pending; pending = {};
      try { S.P = await api("PUT", `/api/projects/${S.P.id}/settings`, patch); applyProject(); }
      catch (e) { toast(e.message, true); }
      res();
    }, delay);
  });
}

function styleName(k) { return ((S.meta && S.meta.styles[k]) || {}).name || k; }

function buildTools() {
  S.toolsBuilt = true;
  const st = S.P.settings, an = S.P.analysis || {}, lv = an.levels || {};
  const box = $("#tools");
  const sw = (sec, key, on) => `<button class="sw ${on ? "on" : ""}" data-sw="${sec}.${key}" aria-label="Ligar ou desligar" aria-pressed="${on}"></button>`;
  const range = (sec, key, label, min, max, step, unit, val) => `
    <label class="field"><span class="lbl">${label}<b data-out="${sec}.${key}">${val}${unit}</b></span>
    <input type="range" min="${min}" max="${max}" step="${step}" value="${val}" data-range="${sec}.${key}" data-unit="${unit}"></label>`;
  box.innerHTML = `
    <div class="panel-title">Edição com IA</div>

    <div class="tool ${st.silence.enabled ? "" : "disabled"}">
      <div class="tool-head"><span class="dot" style="background:var(--sil)"></span><strong>Cortar silêncios</strong>${sw("silence", "enabled", st.silence.enabled)}</div>
      <p>Só corta onde há silêncio de verdade: o detector de voz protege o começo e o fim de cada palavra.</p>
      <div class="opts">
        <label class="checkline"><input type="checkbox" data-check="silence.auto" ${st.silence.auto ? "checked" : ""}> Limite automático (${an.threshold ?? "—"} dB · fundo ${lv.floor ?? "—"} · voz ${lv.speech ?? "—"})</label>
        <div data-manual-thr class="${st.silence.auto ? "hidden" : ""}">${range("silence", "threshold_db", "Silêncio abaixo de", -70, -15, 1, " dB", st.silence.threshold_db)}</div>
        ${range("silence", "min_dur", "Cortar pausas maiores que", 0.2, 3, 0.05, " s", st.silence.min_dur)}
        <label class="field">Ritmo das pausas
          <select data-select="silence.rhythm">
            <option value="natural" ${st.silence.rhythm === "natural" ? "selected" : ""}>Natural — respira como uma fala ao vivo</option>
            <option value="dinamico" ${st.silence.rhythm === "dinamico" ? "selected" : ""}>Dinâmico — bom para Reels</option>
            <option value="rapido" ${st.silence.rhythm === "rapido" ? "selected" : ""}>Rápido — sem respiro entre frases</option>
          </select>
        </label>
      </div>
    </div>

    <div class="tool ${st.breath.enabled ? "" : "disabled"}">
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

    <div class="tool ${st.fillers.enabled ? "" : "disabled"}">
      <div class="tool-head"><span class="dot" style="background:var(--fil)"></span><strong>Vícios e repetições</strong>${sw("fillers", "enabled", st.fillers.enabled)}</div>
      <p>Só corta quando dá para emendar sem a fala ficar picotada. Na dúvida, mantém a palavra.</p>
      <div class="opts">
        <label class="field">Palavras (separe por vírgula)<input type="text" data-words value="${esc(st.fillers.words.join(", "))}"></label>
        <label class="checkline"><input type="checkbox" data-check="fillers.repetitions" ${st.fillers.repetitions ? "checked" : ""}> Cortar palavras repetidas ("eu eu")</label>
        <label class="checkline"><input type="checkbox" data-check="fillers.speech_errors" ${st.fillers.speech_errors !== false ? "checked" : ""}> Cortar palavras começadas e abandonadas ("o pro- o problema") e frases repetidas ("eu vou, eu vou")</label>
      </div>
    </div>

    <div class="tool ${st.fillers.ai_cleanup !== false ? "" : "disabled"}">
      <div class="tool-head"><span class="dot" style="background:#2DD4BF"></span><strong>Limpeza da fala com IA</strong>${sw("fillers", "ai_cleanup", st.fillers.ai_cleanup !== false)}</div>
      <p>A IA lê a fala inteira e marca recomeços, correções ("na terça, quer dizer, na quarta"), gaguejos e comentários fora do assunto. Você revisa na transcrição antes de exportar.</p>
      <div class="opts">
        <button class="btn small primary" data-ai-clean>${(S.P.ai_cuts || []).length ? "Analisar de novo" : "Analisar a fala com IA"}</button>
        <span class="hint" data-ai-count>${(S.P.ai_cuts || []).length ? `${S.P.ai_cuts.length} trecho(s) marcado(s) pela IA — em verde-água na transcrição` : ""}</span>
      </div>
    </div>

    <div class="tool ${st.subtitles.enabled ? "" : "disabled"}">
      <div class="tool-head"><span class="dot" style="background:#FACC15"></span><strong>Legendas</strong>${sw("subtitles", "enabled", st.subtitles.enabled)}</div>
      <div class="opts">
        <button class="style-pick" data-open-styles>
          <img data-style-img alt="">
          <span><b data-style-name>${esc(styleName(st.subtitles.style))}</b><small>Trocar estilo da legenda</small></span>
        </button>
      </div>
    </div>

    <div class="tool ${st.audio.normalize ? "" : "disabled"}">
      <div class="tool-head"><span class="dot" style="background:var(--ok)"></span><strong>Volume profissional</strong>${sw("audio", "normalize", st.audio.normalize)}</div>
      <p>Normaliza o volume no padrão das plataformas.</p>
      <div class="opts">
        <select data-select="audio.target_lufs" aria-label="Padrão de volume">
          <option value="-14" ${st.audio.target_lufs == -14 ? "selected" : ""}>YouTube / Reels (−14 LUFS)</option>
          <option value="-16" ${st.audio.target_lufs == -16 ? "selected" : ""}>Podcast (−16 LUFS)</option>
          <option value="-23" ${st.audio.target_lufs == -23 ? "selected" : ""}>TV (−23 LUFS)</option>
        </select>
      </div>
    </div>
    <p class="hint center">${S.P.transcribe_seconds != null ? `Transcrição feita em ${fmtDur(S.P.transcribe_seconds)}` : ""}</p>`;

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
  $("[data-words]", box).addEventListener("change", (e) => setSetting("fillers", "words", e.target.value.split(",").map((x) => x.trim()).filter(Boolean)));
  $("[data-open-styles]", box).addEventListener("click", openStyles);
  $("[data-ai-clean]", box).addEventListener("click", async () => {
    const ai = (S.cfg || {}).ai || {};
    if (!ai.provider || ai.provider === "none" || !ai.api_key_set) { toast("Configure o Claude (ou outra IA) em Configurações para usar a limpeza com IA.", true); return; }
    try { S.P = await api("POST", `/api/projects/${S.P.id}/cleanup-ai`); toast("A IA está lendo a fala…"); startPoll(); } catch (e) { toast(e.message, true); }
  });
  refreshStyleThumbs();
}

/* ---------- mídia / reprodução ---------- */

function setupMedia() {
  S.mediaSet = true;
  const src = `/api/projects/${S.P.id}/media`;
  $("#video").src = src; $("#svideo").src = src;
  $("#audio-only").classList.toggle("hidden", !!S.P.media.has_video);
  $("#video").style.display = S.P.media.has_video ? "" : "none";
  fetch(`/api/projects/${S.P.id}/wave`).then((r) => r.json()).then((w) => { S.wave = w; drawTimeline(); });
}

function activeRanges() { return S.cuts.filter((c) => c.active).map((c) => [c.s, c.e]).sort((a, b) => a[0] - b[0]); }

function duckVol(t) {
  for (const d of S.ducks) if (d.active && t >= d.s && t <= d.e) return Math.pow(10, d.db / 20);
  return 1;
}

function tick() {
  requestAnimationFrame(tick);
  if (!S.P || !S.P.media || S.P.status !== "pronto") return;
  if (S.mode === "edit") {
    const v = $("#video");
    if ($("#chk-preview").checked && !v.paused) {
      const t = v.currentTime;
      for (const [s, e] of activeRanges()) {
        if (t >= s - 0.01 && t < e - 0.03) { v.currentTime = e; break; }
        if (s > t) break;
      }
      v.volume = duckVol(t);
    } else v.volume = 1;
    $("#time").textContent = `${fmt(v.currentTime, true)} / ${fmt(S.P.media.duration)}`;
    highlightWord(v.currentTime);
    drawPlayhead();
  } else studioTick();
}

function togglePlay() { const v = $("#video"); if (v.paused) v.play(); else v.pause(); }

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

function wordAt(t) {
  const words = S.P.words || [];
  let lo = 0, hi = words.length - 1, idx = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (words[m].s <= t) { idx = m; lo = m + 1; } else hi = m - 1; }
  return idx;
}

function highlightWord(t) {
  const words = S.P.words || [];
  if (!words.length || !S.wordEls) return;
  let idx = wordAt(t);
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
    $("#video").currentTime = S.P.words[+w.dataset.i].s;
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

/* ---------- exportados ---------- */

function renderJobs() {
  const jobs = (S.P.jobs || []).filter((j) => j.status !== "concluido" && j.kind !== "cortes");
  const html = jobs.map((j) => `
    <div class="job ${j.status === "erro" ? "erro" : ""}">
      <div class="row between"><strong>${esc(j.label || j.kind)}</strong><span class="mono">${j.status === "erro" ? "erro" : j.status === "na fila" ? "na fila" : Math.round(j.pct * 100) + "%"}</span></div>
      <div class="bar"><i style="width:${Math.round(j.pct * 100)}%"></i></div>
      <span class="hint">${esc(j.status === "erro" ? j.error : j.msg)}</span>
    </div>`).join("");
  $$(".jobs-box").forEach((b) => (b.innerHTML = html));
}

function renderRenders() {
  renderJobs();
  const rs = S.P.renders || [];
  const plats = (S.meta || {}).platforms || {};
  const html = rs.length ? rs.map((r) => `
    <div class="render">
      <span class="name">${esc(r.label || r.file)}</span>
      <span class="hint">${r.platform && plats[r.platform] ? esc(plats[r.platform].short) + " · " : ""}${fmt(r.duration)} · ${fmtSize(r.size)} · ${r.vertical ? "9:16" : "horizontal"}${r.subtitles ? " · legenda" : ""} · ${fmtDur(r.seconds)} (${r.encoder === "libx264" ? "CPU" : esc((r.encoder || "").replace("h264_", "").toUpperCase())})</span>
      <span class="file">${esc(r.file)}</span>
      <div class="row">
        <a class="btn small" href="/api/projects/${S.P.id}/renders/${encodeURIComponent(r.file)}" download>Baixar</a>
        <button class="btn small primary" data-pubr="${esc(r.file)}">Publicar</button>
        <button class="btn small ghost" data-del="${esc(r.file)}">Apagar</button>
      </div>
    </div>`).join("") : `<p class="hint">Os vídeos exportados aparecem aqui.</p>`;
  $$(".renders-box").forEach((box) => {
    box.innerHTML = html;
    $$("[data-pubr]", box).forEach((b) => b.addEventListener("click", () => {
      const r = rs.find((x) => x.file === b.dataset.pubr);
      openPublish({ ...r, project: S.P.id, project_name: S.P.name });
    }));
    $$("[data-del]", box).forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("Apagar este arquivo exportado?")) return;
      S.P = await api("DELETE", `/api/projects/${S.P.id}/renders/${encodeURIComponent(b.dataset.del)}`); renderRenders();
    }));
  });
}

async function startRender(url, body, msg = "Adicionado à fila de exportação") {
  try { S.P = await api("POST", url, body); renderJobs(); startPoll(); toast(msg); }
  catch (e) { toast(e.message, true); }
}

/* ---------- linha do tempo ---------- */

function drawTimeline() {
  const cv = $("#tl"); if (!cv || !S.P || !S.P.media || S.mode !== "edit") return;
  const wrap = $("#tl-scroll");
  const W = Math.max(300, wrap.clientWidth * S.zoom), H = 120, dpr = window.devicePixelRatio || 1;
  cv.style.width = W + "px"; cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d"); g.scale(dpr, dpr);
  const dur = S.P.media.duration || 1, x = (t) => (t / dur) * W;
  g.fillStyle = "#121418"; g.fillRect(0, 0, W, H);
  g.fillStyle = "#8E929B"; g.font = "10px " + getComputedStyle(document.body).getPropertyValue("--mono");
  const stepOpts = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];
  const step = stepOpts.find((s) => (s / dur) * W > 70) || 3600;
  for (let t = 0; t <= dur; t += step) { g.fillRect(x(t), 0, 1, 6); g.fillText(fmt(t), x(t) + 3, 10); }
  for (const c of S.P.clips || []) {
    g.fillStyle = c.kind === "resumo" ? "rgba(255,138,61,.55)" : "rgba(74,222,128,.45)";
    for (const [s, e] of c.segments) g.fillRect(x(s), 14, Math.max(2, x(e) - x(s)), 6);
  }
  const top = 26, h = 70, mid = top + h / 2, n = S.wave.length;
  if (n) {
    g.fillStyle = "#4ADE80";
    const bw = W / n;
    for (let i = 0; i < n; i++) { const a = S.wave[i] * h / 2; g.fillRect(i * bw, mid - a, Math.max(1, bw - 0.3), a * 2 || 1); }
  }
  const colors = { silencio: "rgba(255,138,61,.55)", respiracao: "rgba(90,169,255,.55)", vicio: "rgba(192,132,252,.6)", repeticao: "rgba(192,132,252,.6)", gaguejo: "rgba(250,204,21,.6)", ia: "rgba(45,212,191,.6)", manual: "rgba(248,113,113,.6)" };
  for (const c of S.cuts) {
    if (!c.active) continue;
    g.fillStyle = colors[c.type] || colors.manual;
    g.fillRect(x(c.s), top, Math.max(1, x(c.e) - x(c.s)), h);
  }
  g.fillStyle = "rgba(90,169,255,.45)";
  for (const d of S.ducks) if (d.active) g.fillRect(x(d.s), top + h - 10, Math.max(1, x(d.e) - x(d.s)), 10);
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
    const r = e.currentTarget.getBoundingClientRect();
    $("#video").currentTime = ((e.clientX - r.left) / r.width) * S.P.media.duration;
  });
  $("#zoom-in").addEventListener("click", () => { S.zoom = Math.min(64, S.zoom * 2); drawTimeline(); followPlayhead(); });
  $("#zoom-out").addEventListener("click", () => { S.zoom = Math.max(1, S.zoom / 2); drawTimeline(); });
  window.addEventListener("resize", () => { clearTimeout(S.rz); S.rz = setTimeout(drawTimeline, 150); });
}
function followPlayhead() {
  const wrap = $("#tl-scroll"), cv = $("#tl");
  wrap.scrollLeft = ($("#video").currentTime / S.P.media.duration) * cv.clientWidth - wrap.clientWidth / 2;
}

/* =================== ESTÚDIO DE CORTES =================== */

const studio = () => S.P.settings.studio;

function renderStudio() {
  if (!S.P || S.P.status !== "pronto" || S.mode !== "studio") return;
  const st = studio(), meta = S.meta || { platforms: {} };
  // plataformas
  $("#s-platforms").innerHTML = Object.entries(meta.platforms).map(([k, p]) => `
    <button class="plat ${st.platform === k ? "active" : ""}" data-plat="${k}"><i style="background:${p.color}"></i><span>${esc(p.short)}<small>${p.max ? "até " + fmtDur(p.max) : "sem limite"}</small></span></button>`).join("");
  $$("#s-platforms .plat").forEach((b) => b.addEventListener("click", () => { setSetting("studio", "platform", b.dataset.plat, 50); }));
  const plat = meta.platforms[st.platform] || {};
  $("#s-plat-hint").textContent = plat.name ? `${plat.name}${plat.w ? " · 1080×1920" : " · 16:9"}${plat.split ? ` · vídeos maiores que ${plat.max}s são divididos em partes automaticamente` : ""}` : "";
  $$("#s-mode .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.v === st.mode));
  $("#s-mode-hint").textContent = {
    cortes: "Trechos contínuos que funcionam sozinhos.",
    resumo: "Os melhores momentos do vídeo inteiro juntos, abrindo com a frase mais forte.",
    ambos: "Uma mistura de cortes e resumos.",
  }[st.mode] || "";
  $$("#s-dur .chip-btn").forEach((b) => b.classList.toggle("active", String(st.duration) === b.dataset.v));
  $("#s-free").classList.toggle("hidden", st.duration !== "livre");
  $("#s-min").value = st.min; $("#s-max").value = st.max;
  $("#s-count").textContent = st.count;
  if (document.activeElement !== $("#s-instr")) $("#s-instr").value = st.instructions || "";
  $("#s-layout").value = st.layout; $("#s-title").value = st.title_mode; $("#s-subs").checked = st.subtitles !== false;
  $("#s-zoom").checked = st.zoom_cuts !== false; $("#s-enhance").value = st.enhance || "auto";
  const ai = (S.cfg || {}).ai || {};
  $("#s-ai-hint").textContent = ai.provider && ai.provider !== "none" && ai.api_key_set
    ? `Usando ${ai.provider === "anthropic" ? "Claude" : "IA externa"} (${ai.model})`
    : "Sem IA configurada: usando análise local. Para resumos melhores, configure o Claude em Configurações.";
  $("#s-style-name").textContent = styleName(S.P.settings.subtitles.style);
  refreshStyleThumbs();
  refreshFrameThumb();
  renderStudioProgress();
  renderClipGrid();
  renderExtras();
}

function renderStudioProgress() {
  const job = (S.P.jobs || []).find((j) => j.kind === "cortes" && (j.status === "processando" || j.status === "na fila"));
  const box = $("#s-gen-progress");
  box.classList.toggle("hidden", !job);
  $("#s-generate").disabled = !!job;
  if (job) $("span", box).textContent = job.msg + " Pode levar até 1 minuto em vídeos longos.";
}

function clipThumb(c) {
  const t = c.segments[0][0] + Math.min(1.5, (c.segments[0][1] - c.segments[0][0]) / 2);
  const st = studio();
  const vertical = (S.meta.platforms[st.platform] || {}).h ? 1 : 0;
  return `/api/projects/${S.P.id}/thumb?t=${t.toFixed(2)}&vertical=${vertical}&layout=${st.layout}`;
}

function renderClipGrid() {
  const clips = (S.P.clips || []).filter((c) => S.filter === "all" || c.kind === S.filter);
  const all = S.P.clips || [];
  const nC = all.filter((c) => c.kind !== "resumo").length, nR = all.filter((c) => c.kind === "resumo").length;
  $("#s-count-title").textContent = all.length ? `${nC} corte${nC === 1 ? "" : "s"} · ${nR} resumo${nR === 1 ? "" : "s"}` : "Cortes e resumos";
  $("#s-source").textContent = S.P.clips_source ? `Criados por: ${S.P.clips_source}` : "";
  $("#s-export-all").disabled = !clips.length;
  const grid = $("#s-grid");
  if (!clips.length) {
    grid.innerHTML = `<div class="empty">Nenhum ${S.filter === "resumo" ? "resumo" : S.filter === "corte" ? "corte" : "corte ou resumo"} ainda. Escolha as opções ao lado e clique em <b>Gerar com IA</b>.</div>`;
    return;
  }
  grid.innerHTML = clips.map((c) => `
    <article class="ccard ${S.sel === c.id ? "selected" : ""}" data-id="${c.id}">
      <button class="thumb" data-preview aria-label="Ver prévia de ${esc(c.title)}">
        <img src="${clipThumb(c)}" alt="" loading="lazy">
        <span class="tag ${c.kind === "resumo" ? "resumo" : ""}">${c.kind === "resumo" ? "RESUMO" : "CORTE"}</span>
        ${c.parts > 1 ? `<span class="parts">${c.parts} partes</span>` : ""}
        <span class="dur">${fmt(c.final)}</span>
        <span class="play"><svg width="18" height="18" viewBox="0 0 24 24" fill="#fff"><path d="M6 4l14 8-14 8z"/></svg></span>
      </button>
      <div class="body">
        <div class="ttl" contenteditable="true" spellcheck="false" data-title>${esc(c.title)}</div>
        <div class="meta">${c.kind === "resumo" ? `${c.segments.length} momentos · ` : `${fmt(c.segments[0][0])}–${fmt(c.segments[0][1])} · `}${esc(c.reason || "")}</div>
        ${c.score ? `<div class="score" title="Potencial ${Math.round(c.score)}"><i style="width:${Math.min(100, c.score)}%"></i></div>` : ""}
        ${c.rendered ? `<span class="done">✓ exportado</span>` : ""}
        <div class="acts">
          <button class="btn small primary" data-export>Exportar</button>
          <a class="btn small icon ghost" href="/api/projects/${S.P.id}/clips/${c.id}/cover" download aria-label="Baixar capa" title="Baixar capa (thumbnail)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5L5 21"/></svg></a>
          <button class="btn small icon ghost" data-del aria-label="Remover"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg></button>
        </div>
      </div>
    </article>`).join("");
  $$(".ccard", grid).forEach((el) => {
    const c = S.P.clips.find((x) => x.id === el.dataset.id);
    $("[data-preview]", el).addEventListener("click", () => selectClip(c.id, true));
    $("[data-export]", el).addEventListener("click", () => {
      const p = S.meta.platforms[studio().platform];
      startRender(`/api/projects/${S.P.id}/clips/${c.id}/render`, {}, c.parts > 1 ? `Exportando em ${c.parts} partes para ${p.short}` : `Exportando para ${p.short}`);
    });
    $("[data-del]", el).addEventListener("click", async () => {
      if (!confirm("Remover este corte da lista?")) return;
      S.P = await api("DELETE", `/api/projects/${S.P.id}/clips/${c.id}`);
      if (S.sel === c.id) selectClip(null);
      renderClipGrid();
    });
    const t = $("[data-title]", el);
    t.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") { e.preventDefault(); t.blur(); } });
    t.addEventListener("blur", async () => {
      const val = t.textContent.trim();
      if (val && val !== c.title) { S.P = await api("PUT", `/api/projects/${S.P.id}/clips/${c.id}`, { title: val, hook: val.slice(0, 60) }); }
    });
  });
  if (S.sel && !S.P.clips.find((c) => c.id === S.sel)) selectClip(null);
  else if (!S.sel && clips.length) selectClip(clips[0].id, false);
}

/* ----- prévia no "celular" ----- */

function buildCaps(c) {
  const sub = S.P.settings.subtitles, words = S.P.words || [];
  const maxc = sub.style === "uma_palavra" ? 1 : (sub.max_chars || 20) * (sub.lines || 2);
  const inKeep = (t) => c.keeps.some(([s, e]) => t >= s && t <= e);
  const list = [];
  words.forEach((w, i) => { if (inKeep((w.s + w.e) / 2)) list.push(i); });
  const blocks = []; let cur = [];
  for (const i of list) {
    const w = words[i];
    if (cur.length) {
      const first = words[cur[0]], last = words[cur[cur.length - 1]];
      const chars = cur.reduce((a, j) => a + words[j].w.length + 1, 0) + w.w.length;
      if (chars > maxc || w.s - last.e > 0.7 || w.e - first.s > 4 || (/[.?!…]$/.test(last.w) && cur.length >= 3)) { blocks.push(cur); cur = []; }
    }
    cur.push(i);
  }
  if (cur.length) blocks.push(cur);
  return blocks.map((b) => ({ s: words[b[0]].s, e: words[b[b.length - 1]].e + 0.25, idx: b }));
}

async function selectClip(id, play = false) {
  S.sel = id;
  $$(".ccard").forEach((el) => el.classList.toggle("selected", el.dataset.id === id));
  const v = $("#svideo");
  v.pause();
  const c = id && S.P.clips.find((x) => x.id === id);
  $("#s-ph-empty").classList.toggle("hidden", !!c);
  if (!c) $("#s-clipedit").classList.add("hidden");
  $("#s-post").classList.toggle("hidden", !(c && c.post));
  if (!c) { S.sq = null; return; }
  if (c.post) $("#s-post-text").textContent = c.post;
  $("#s-clipedit").classList.remove("hidden");
  $("#s-ed-hook").value = c.hook || c.title || "";
  $("#s-ed-kicker").value = c.kicker || "";
  $("#s-ed-kicker").placeholder = ((S.cfg || {}).brand || {}).kicker || "Ex.: PALAVRA DE HOJE";
  $("#s-cover").href = `/api/projects/${S.P.id}/clips/${c.id}/cover`;
  S.sq = c.keeps; S.si = 0; S.scaps = buildCaps(c);
  S.sTotal = c.keeps.reduce((a, [s, e]) => a + e - s, 0);
  v.currentTime = c.keeps.length ? c.keeps[0][0] : 0;
  applyPhoneLook(c);
  refreshFrameThumb();
  if (play) { try { await v.play(); } catch (_) {} }
  // enquadramento (rosto) para a prévia
  if (studio().layout === "face" && !S.framing[c.id] && S.P.media.width > S.P.media.height) {
    try { S.framing[c.id] = await api("GET", `/api/projects/${S.P.id}/clips/${c.id}/framing`); applyPhoneLook(c); } catch (_) {}
  }
}

function applyPhoneLook(c) {
  const st = studio(), sub = S.P.settings.subtitles, scr = $("#s-screen"), v = $("#svideo");
  const vertical = !!(S.meta.platforms[st.platform] || {}).h;
  scr.style.aspectRatio = vertical ? "9/16" : "16/9";
  scr.classList.toggle("blur", vertical && st.layout === "blur");
  scr.style.setProperty("--bgimg", c ? `url("${clipThumb(c).replace("layout=blur", "layout=center")}")` : "none");
  v.style.objectPosition = "50% 50%";
  if (vertical && st.layout === "face" && S.framing[c.id]) {
    const m = S.P.media, cwf = (9 / 16) / (m.width / m.height);
    const cx = S.framing[c.id].centers[0] ?? 0.5;
    const p = Math.min(1, Math.max(0, (cx - cwf / 2) / (1 - cwf)));
    v.style.objectPosition = `${(p * 100).toFixed(1)}% 50%`;
    S.curFraming = S.framing[c.id];
  } else S.curFraming = null;
  v.style.objectFit = vertical ? (st.layout === "blur" ? "contain" : "cover") : "contain";
  const cap = $("#s-cap");
  cap.className = `ph-cap st-${sub.style} pos-${sub.position || "baixo"}` +
    (["palavra_ativa", "caixa_ativa", "destaque", "uma_palavra", "impacto", "classico"].includes(sub.style) ? " st-outline" : "");
  const W = scr.clientWidth || 258;
  const factor = { uma_palavra: 0.13, impacto: 0.095, minimalista: 0.05, caixa: 0.056, classico: 0.056 }[sub.style] || 0.066;
  const mult = (sub.size_pct ?? ({ p: 82, m: 100, g: 120 }[sub.size || "m"] || 100)) / 100;
  cap.style.fontSize = (W * factor * mult * (vertical ? 1 : 0.78 * 16 / 9 * 9 / 16)).toFixed(1) + "px";
  cap.style.fontFamily = `"${sub.font}", "Poppins ExtraBold", sans-serif`;
  cap.style.textTransform = sub.uppercase ? "uppercase" : "none";
  cap.style.letterSpacing = sub.style === "impacto" ? "0.03em" : "0";
  cap.style.setProperty("--hl", sub.highlight); cap.style.setProperty("--cc", sub.color);
  renderPhoneFrame(c, vertical);
  const ttl = $("#s-ph-title");
  ttl.style.setProperty("--hl", sub.highlight);
  ttl.innerHTML = c ? `<span>${esc(c.hook || c.title)}</span>` : "";
  ttl.style.fontFamily = cap.style.fontFamily;
  S.lastCapKey = null;
}

function brand() { return { handle: "", kicker: "", color: "#FF8A3D", text: "#FFFFFF", bg: "#101114", progress: true, ...((S.cfg || {}).brand || {}) }; }

function renderPhoneFrame(c, vertical) {
  const scr = $("#s-screen"), v = $("#svideo");
  let fr = $("#s-frame");
  if (!fr) { fr = document.createElement("div"); fr.id = "s-frame"; fr.className = "ph-frame"; scr.appendChild(fr); }
  const st = studio(), b = brand();
  const layout = vertical ? (st.frame || "cheia") : "cheia";
  const g = ((S.meta || {}).geometry || {})[layout];
  S.curGeom = g && vertical ? g : null;
  scr.classList.remove("fr-blur");
  v.classList.remove("boxed"); v.style.left = v.style.top = v.style.width = v.style.height = "";
  if (!g || !vertical || !c) { fr.innerHTML = ""; return; }
  const W = scr.clientWidth || 258, k = W / 1080, px = (n) => (n * k).toFixed(1) + "px";
  const col = { color: b.color, bg: b.bg, text: b.text };
  const [bx, by, bw, bh] = g.box;
  if (g.layout !== "cheia" && !(bx === 0 && by === 0 && bw === 1080 && bh === 1920)) {
    v.classList.add("boxed");
    Object.assign(v.style, { left: px(bx), top: px(by), width: px(bw), height: px(bh) });
    scr.style.background = g.bg === "blur" ? "#000" : b.bg;
    if (g.bg === "blur") scr.classList.add("fr-blur");
  } else scr.style.background = "#000";
  let html = "";
  for (const [x, y, w, h, key, a] of g.bands) html += `<div class="band" style="left:${px(x)};top:${px(y)};width:${px(w)};height:${px(h)};background:${col[key]};opacity:${(1 - a / 255).toFixed(2)}"></div>`;
  if (g.outline) { const [x, y, w, h] = g.outline; html += `<div class="foutline" style="left:${px(x - 3)};top:${px(y - 3)};width:${px(w + 6)};height:${px(h + 6)}"></div>`; }
  const title = c.hook || c.title || "", kicker = (c.kicker || b.kicker || "").toUpperCase();
  if (g.title && title) {
    const [cx, cy, tw] = g.title;
    html += `<div class="ftitle" style="left:${px(cx)};top:${px(cy)};width:${px(tw)};font-size:${px(70)};color:${b.text};${g.bg === "blur" ? "text-shadow:0 2px 6px #000" : ""}">${esc(title)}</div>`;
  }
  if (g.kicker && kicker) {
    const [kx, ky] = g.kicker, ft = g.layout === "faixa_topo";
    html += `<div class="fkicker" data-kicker style="left:${px(kx)};top:${px(ky)};font-size:${px(42)};background:${ft ? b.bg : b.color};color:${ft ? b.text : "#111"}">${esc(kicker)}</div>`;
  }
  if (b.handle) {
    const h = b.handle.startsWith("@") || b.handle.includes(" ") ? b.handle : "@" + b.handle;
    html += `<div class="fhandle" style="left:${px(g.handle[0])};top:${px(g.handle[1])};font-size:${px(34)};color:${b.text}">${esc(h)}</div>`;
  }
  if (b.logo && g.logo) html += `<img class="flogo" src="/api/brand/logo?v=${S.logoV || 0}" style="left:${px(g.logo[0])};top:${px(g.logo[1])};height:${px(g.logo[2])}" alt="">`;
  if (b.progress) html += `<div class="fprog" style="top:${px(g.progress[0])};height:${Math.max(2, g.progress[1] * k).toFixed(1)}px;width:100%"><i id="s-fprog" style="background:${b.color}"></i></div>`;
  fr.innerHTML = html;
  const cap = $("#s-cap");
  const subc = S.P.settings.subtitles;
  if (g.sub) { cap.style.top = px(g.sub[1]); cap.style.bottom = "auto"; cap.style.transform = "translateY(-50%)"; }
  else {
    const yy = 1920 * (1 - (0.08 + 0.84 * (subc.y_pct ?? 18) / 100));
    cap.style.top = px(yy); cap.style.bottom = "auto"; cap.style.transform = "translateY(-50%)";
  }
  // logo (posição/tamanho/transparência)
  const lg = $("#s-frame .flogo");
  if (lg) {
    const sz = { p: 70, m: 100, g: 140 }[b.logo_size || "m"] * k, m = 36 * k, pos = b.logo_pos || "auto";
    lg.style.height = sz + "px"; lg.style.opacity = b.logo_opacity ?? 1;
    lg.style.left = lg.style.right = lg.style.top = lg.style.bottom = "";
    if (pos === "auto") { lg.style.left = px(g.logo[0]); lg.style.top = px(g.logo[1]); }
    else {
      if (pos.endsWith("esq")) lg.style.left = m + "px"; else lg.style.right = m + "px";
      if (pos.startsWith("sup")) lg.style.top = m + "px"; else lg.style.bottom = (70 * k) + "px";
    }
  }
  // selo da rede social (aparece nos mesmos momentos do vídeo final)
  const nets = Object.keys((S.meta || {}).socials || {}).filter((n) => ((b.socials || {})[n] || {}).on && ((b.socials || {})[n] || {}).handle);
  let showNets = [];
  if ((b.social_mode || "destino") !== "off" && nets.length) {
    const dest = ((S.meta || {}).platform_net || {})[st.platform];
    showNets = (b.social_mode || "destino") === "destino" ? [nets.includes(dest) ? dest : nets[0]] : nets;
  }
  S.badgeNets = showNets;
  if (showNets.length) {
    const yb = { faixa_topo: 550, moldura: 642, cartao: 602 }[g.layout] || 1920 * 0.30;
    const el = document.createElement("div");
    el.className = "ph-badge"; el.id = "s-badge";
    el.style.top = px(yb); el.style.transform = "translate(0,-50%)"; el.style.fontSize = px(36);
    if ((b.social_side || "direita") === "esquerda") el.style.left = px(36); else el.style.right = px(36);
    fr.appendChild(el);
  }
}

function badgeAt(out) {
  const b = brand(), every = Math.max(6, +(b.social_every || 12)), nets = S.badgeNets || [];
  if (!nets.length || (S.sTotal || 0) < 3) return null;
  let i = 0;
  for (let t = 1.5; t + 4 <= S.sTotal - 0.4; t += every, i++) if (out >= t && out < t + 4) return { net: nets[i % nets.length], a: t };
  return null;
}

function updateBadge(out) {
  const el = $("#s-badge"); if (!el) return;
  const cur = badgeAt(out), b = brand();
  const side = (b.social_side || "direita") === "esquerda" ? -1 : 1;
  if (!cur) { el.style.transform = `translate(${side * 130}%,-50%)`; el.style.opacity = 0; return; }
  if (el.dataset.net !== cur.net) {
    const info = S.meta.socials[cur.net], soc = (b.socials || {})[cur.net] || {};
    let h = (soc.handle || "").trim(); if (!["whatsapp", "site"].includes(cur.net) && h && !h.startsWith("@")) h = "@" + h;
    const hasIcon = (S.meta.icons || []).includes(cur.net);
    el.innerHTML = `<span class="bi" style="background:${hasIcon ? "transparent" : info.color}">${hasIcon ? `<img src="/api/brand/icon/${cur.net}?v=${S.logoV || 0}" alt="">` : "+"}</span>
      <span class="bt"><small style="color:${info.color === "#FFFFFF" ? b.color : info.color}">${esc((soc.cta || info.cta).toUpperCase())}</small><b>${esc(h)}</b></span>`;
    el.dataset.net = cur.net;
  }
  el.style.transform = "translate(0,-50%)"; el.style.opacity = 1;
}

function studioTick() {
  const v = $("#svideo");
  if (!S.sq || !S.sq.length) return;
  let t = v.currentTime;
  if (!v.paused) {
    const [s, e] = S.sq[S.si] || [0, 0];
    if (t >= e - 0.02 || t < s - 0.5) {
      // próximo trecho (ou procurar o trecho certo após um salto)
      let next = S.sq.findIndex(([a, b]) => t >= a - 0.02 && t < b - 0.02);
      if (next < 0 || next === S.si) next = S.si + 1;
      if (next >= S.sq.length) { v.pause(); S.si = 0; v.currentTime = S.sq[0][0]; t = v.currentTime; }
      else { S.si = next; if (!(t >= S.sq[next][0] - 0.02 && t < S.sq[next][1])) v.currentTime = S.sq[next][0]; t = v.currentTime; }
    }
    v.volume = duckVol(t);
  }
  // tempo de saída
  let out = 0;
  for (let i = 0; i < S.si; i++) out += S.sq[i][1] - S.sq[i][0];
  out += Math.max(0, Math.min(t, S.sq[S.si][1]) - S.sq[S.si][0]);
  $("#s-ph-bar").style.width = ((out / (S.sTotal || 1)) * 100).toFixed(1) + "%";
  $("#s-ph-time").textContent = `${fmt(out)} / ${fmt(S.sTotal)}`;
  const tm = studio().title_mode;
  const bandTitle = S.curGeom && S.curGeom.title;
  $("#s-ph-title").classList.toggle("hidden", !!bandTitle || !(tm === "fixo" || (tm === "inicio" && out < 4)));
  const kk = $("#s-frame [data-kicker]");
  if (kk && S.curGeom && (S.curGeom.layout === "cheia" || S.curGeom.layout === "rodape")) kk.style.display = (tm === "fixo" || out < 4) ? "" : "none";
  const fp = $("#s-fprog"); if (fp) fp.style.width = ((out / (S.sTotal || 1)) * 100).toFixed(1) + "%";
  updateBadge(out);
  if (S.curFraming && S.curFraming.segments) {
    const k = S.curFraming.segments.findIndex(([a, b]) => t >= a - 0.05 && t <= b + 0.05);
    if (k >= 0 && k !== S.curK) {
      S.curK = k;
      const m = S.P.media, cwf = (9 / 16) / (m.width / m.height), cx = S.curFraming.centers[k];
      const p = Math.min(1, Math.max(0, (cx - cwf / 2) / (1 - cwf)));
      v.style.objectPosition = `${(p * 100).toFixed(1)}% 50%`;
    }
  }
  renderPhoneCaption(t);
}

function renderPhoneCaption(t) {
  const cap = $("#s-cap"), sub = S.P.settings.subtitles, words = S.P.words || [];
  if (S.P.settings.studio.subtitles === false || !sub.enabled) { cap.innerHTML = ""; return; }
  const b = S.scaps.find((x) => t >= x.s - 0.05 && t <= x.e);
  const wi = wordAt(t);
  const key = (b ? b.s : "-") + ":" + wi;
  if (key === S.lastCapKey) return;
  S.lastCapKey = key;
  if (!b) { cap.innerHTML = ""; return; }
  if (sub.style === "uma_palavra") {
    const i = b.idx.includes(wi) ? wi : b.idx[0];
    const w = words[i].w;
    cap.innerHTML = `<span class="wd on ${w.replace(/[.,!?…]/g, "").length >= 6 ? "hlw" : ""}">${esc(w)}</span>`;
    return;
  }
  const inner = b.idx.map((i) => `<span class="wd ${i === wi ? "on" : i < wi ? "past" : ""}">${esc(words[i].w)}</span>`).join(" ");
  cap.innerHTML = sub.style === "caixa" ? `<span class="box">${inner}</span>` : inner;
}

function setupStudio() {
  $$("#s-mode .seg-btn").forEach((b) => b.addEventListener("click", () => setSetting("studio", "mode", b.dataset.v, 50)));
  $$("#s-dur .chip-btn").forEach((b) => b.addEventListener("click", () => setSetting("studio", "duration", b.dataset.v, 50)));
  $("#s-min").addEventListener("change", (e) => setSetting("studio", "min", +e.target.value));
  $("#s-max").addEventListener("change", (e) => setSetting("studio", "max", +e.target.value));
  $("#s-cnt-minus").addEventListener("click", () => setSetting("studio", "count", Math.max(1, studio().count - 1), 400).then(renderStudio));
  $("#s-cnt-plus").addEventListener("click", () => setSetting("studio", "count", Math.min(15, studio().count + 1), 400).then(renderStudio));
  $("#s-instr").addEventListener("change", (e) => setSetting("studio", "instructions", e.target.value.trim()));
  $("#s-layout").addEventListener("change", (e) => setSetting("studio", "layout", e.target.value, 50));
  $("#s-title").addEventListener("change", (e) => setSetting("studio", "title_mode", e.target.value, 50));
  $("#s-subs").addEventListener("change", (e) => setSetting("studio", "subtitles", e.target.checked, 50));
  $("#s-zoom").addEventListener("change", (e) => setSetting("studio", "zoom_cuts", e.target.checked, 50));
  $("#s-enhance").addEventListener("change", (e) => setSetting("studio", "enhance", e.target.value, 50));
  $("#s-style-btn").addEventListener("click", openStyles);
  $("#s-generate").addEventListener("click", async () => {
    const hasClips = (S.P.clips || []).length;
    const append = hasClips && confirm("Manter os cortes atuais e adicionar os novos?\n\nOK = adicionar · Cancelar = substituir");
    try {
      if (pendT) { clearTimeout(pendT); const patch = pending; pending = {}; S.P = await api("PUT", `/api/projects/${S.P.id}/settings`, patch); }
      S.P = await api("POST", `/api/projects/${S.P.id}/clips/generate`, { append: !!append });
      renderStudioProgress(); startPoll();
    } catch (e) { toast(e.message, true); }
  });
  $$("#s-filter .seg-btn").forEach((b) => b.addEventListener("click", () => {
    S.filter = b.dataset.v; $$("#s-filter .seg-btn").forEach((x) => x.classList.toggle("active", x === b)); renderClipGrid();
  }));
  $("#s-export-all").addEventListener("click", () => {
    const ids = (S.P.clips || []).filter((c) => S.filter === "all" || c.kind === S.filter).map((c) => c.id);
    const p = S.meta.platforms[studio().platform];
    if (!confirm(`Exportar ${ids.length} vídeo(s) para ${p.name}?`)) return;
    startRender(`/api/projects/${S.P.id}/clips/render-all`, { ids }, `${ids.length} vídeo(s) na fila de exportação`);
  });
  const v = $("#svideo");
  $("#s-play").addEventListener("click", () => {
    if (!S.sq) return;
    if (v.paused) { if (!(v.currentTime >= S.sq[S.si][0] - 0.1 && v.currentTime < S.sq[S.si][1])) v.currentTime = S.sq[S.si][0]; v.play(); } else v.pause();
  });
  v.addEventListener("click", () => $("#s-play").click());
  const icons = (btn, playing) => { $(".ico-play", btn).classList.toggle("hidden", playing); $(".ico-pause", btn).classList.toggle("hidden", !playing); };
  v.addEventListener("play", () => icons($("#s-play"), true));
  v.addEventListener("pause", () => icons($("#s-play"), false));
  $(".ph-bar").addEventListener("click", (e) => {
    if (!S.sq) return;
    const r = e.currentTarget.getBoundingClientRect();
    let target = ((e.clientX - r.left) / r.width) * S.sTotal;
    for (let i = 0; i < S.sq.length; i++) {
      const d = S.sq[i][1] - S.sq[i][0];
      if (target <= d) { S.si = i; v.currentTime = S.sq[i][0] + target; break; }
      target -= d;
    }
  });
  $("#s-mute").addEventListener("click", () => {
    v.muted = !v.muted;
    $(".ico-muted", $("#s-mute")).classList.toggle("hidden", !v.muted);
    $(".ico-sound", $("#s-mute")).classList.toggle("hidden", v.muted);
  });
  $("#s-copy-post").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("#s-post-text").textContent); toast("Texto copiado"); } catch (_) { toast("Não consegui copiar", true); }
  });
}

/* ----- galeria de molduras + marca ----- */

function frameVersion() { return hash([brand(), S.P.settings.subtitles, studio().layout, studio().platform, S.logoV || 0]); }
function layoutName(k) { return (((S.meta || {}).layouts || {})[k] || {}).name || k; }

function refreshFrameThumb() {
  if (!S.P || !S.P.settings) return;
  const st = studio();
  const url = `/api/projects/${S.P.id}/frame-preview?layout=${st.frame || "cheia"}&clip=${S.sel || ""}&v=${frameVersion()}`;
  const img = $("#s-frame-img"); if (img.getAttribute("src") !== url) img.src = url;
  $("#s-frame-name").textContent = layoutName(st.frame || "cheia");
}

function openFrames() {
  renderFrameGrid();
  if (!$("#framesdlg").open) $("#framesdlg").showModal();
}

function openBrand() {
  const b = brand();
  $("#br-handle").value = b.handle || ""; $("#br-kicker").value = b.kicker || "";
  $("#br-color").value = b.color; $("#br-text").value = b.text; $("#br-bg").value = b.bg;
  $("#br-progress").checked = b.progress !== false;
  $("#br-logo-img").classList.toggle("hidden", !b.logo); $("#br-logo-del").classList.toggle("hidden", !b.logo);
  if (b.logo) $("#br-logo-img").src = `/api/brand/logo?v=${S.logoV || 0}`;
  $("#br-logo-pos").value = b.logo_pos || "auto"; $("#br-logo-size").value = b.logo_size || "m";
  $("#br-logo-op").value = Math.round((b.logo_opacity ?? 1) * 100); $("#br-logo-op-out").textContent = $("#br-logo-op").value + "%";
  $("#br-soc-mode").value = b.social_mode || "destino"; $("#br-soc-every").value = String(b.social_every || 12);
  $("#br-soc-side").value = b.social_side || "direita";
  renderSocialRows();
  if (!$("#branddlg").open) $("#branddlg").showModal();
}

function renderFrameGrid() {
  const cur = studio().frame || "cheia", v = frameVersion();
  $("#frame-grid").innerHTML = Object.entries(S.meta.layouts).map(([k, l]) => `
    <button class="style-card ${cur === k ? "active" : ""}" data-frame="${k}">
      <div class="im"><img data-src="/api/projects/${S.P.id}/frame-preview?layout=${k}&clip=${S.sel || ""}&v=${v}" alt="Prévia da moldura ${esc(l.name)}"></div>
      <div class="tx"><b>${esc(l.name)}</b><small>${esc(l.desc)}</small></div>
    </button>`).join("");
  $$("#frame-grid img").forEach((img, i) => { img.onload = () => img.classList.add("ok"); setTimeout(() => (img.src = img.dataset.src), i * 80); });
  $$("#frame-grid .style-card").forEach((btn) => btn.addEventListener("click", async () => {
    $$("#frame-grid .style-card").forEach((x) => x.classList.toggle("active", x === btn));
    await setSetting("studio", "frame", btn.dataset.frame, 10);
    refreshFrameThumb();
    if (S.sel) applyPhoneLook(S.P.clips.find((c) => c.id === S.sel));
  }));
}

async function saveBrand(patch, regrid = true) {
  try {
    S.cfg = await api("PUT", "/api/settings", { brand: patch });
    refreshFrameThumb();
    if (regrid && $("#framesdlg").open && S.P) renderFrameGrid();
    if (S.P && S.sel) applyPhoneLook(S.P.clips.find((c) => c.id === S.sel));
    if (!S.P) renderBrandPage();
  } catch (e) { toast(e.message, true); }
}

function renderSocialRows() {
  const b = brand(), soc = b.socials || {}, icons = (S.meta || {}).icons || [];
  $("#br-socials").innerHTML = Object.entries(S.meta.socials).map(([k, n]) => {
    const r = soc[k] || {};
    return `<div class="soc-row" data-net="${k}">
      <label class="nm checkline"><input type="checkbox" data-f="on" ${r.on ? "checked" : ""}><i style="background:${n.color}"></i>${esc(n.name)}</label>
      <input type="text" data-f="handle" value="${esc(r.handle || "")}" placeholder="${k === "whatsapp" ? "(00) 00000-0000" : k === "site" ? "seusite.com.br" : "@seuperfil"}" aria-label="Perfil no ${esc(n.name)}">
      <input type="text" data-f="cta" value="${esc(r.cta || "")}" placeholder="${esc(n.cta)}" aria-label="Convite do ${esc(n.name)}">
      <div class="ic">${icons.includes(k) ? `<img src="/api/brand/icon/${k}?v=${S.logoV || 0}" alt="Ícone enviado"><button class="btn small ghost" data-icon-del>Remover</button>` :
        `<label class="btn small" title="Enviar o ícone oficial do kit de marca da rede">Ícone<input type="file" accept="image/*" data-icon hidden></label>`}</div>
    </div>`;
  }).join("");
  $$("#br-socials .soc-row").forEach((row) => {
    const net = row.dataset.net;
    $$("[data-f]", row).forEach((inp) => inp.addEventListener("change", () => {
      const cur = JSON.parse(JSON.stringify(brand().socials || {}));
      cur[net] = cur[net] || {};
      const f = inp.dataset.f;
      cur[net][f] = f === "on" ? inp.checked : inp.value.trim();
      if (f === "handle" && inp.value.trim() && !cur[net].on) { cur[net].on = true; $("[data-f=on]", row).checked = true; }
      saveBrand({ socials: cur });
    }));
    const up = $("[data-icon]", row);
    if (up) up.addEventListener("change", async () => {
      const f = up.files[0]; if (!f) return;
      const r = await fetch(`/api/brand/icon/${net}`, { method: "POST", body: f });
      if (!r.ok) { toast("Não consegui usar essa imagem", true); return; }
      S.logoV = Date.now(); S.meta = await api("GET", "/api/meta"); renderSocialRows(); saveBrand({});
    });
    const del = $("[data-icon-del]", row);
    if (del) del.addEventListener("click", async () => {
      await api("DELETE", `/api/brand/icon/${net}`); S.logoV = Date.now(); S.meta = await api("GET", "/api/meta"); renderSocialRows(); saveBrand({});
    });
  });
}

function setupFrames() {
  $("#br-logo-pos").addEventListener("change", (e) => saveBrand({ logo_pos: e.target.value }));
  $("#br-logo-size").addEventListener("change", (e) => saveBrand({ logo_size: e.target.value }));
  $("#br-logo-op").addEventListener("input", (e) => ($("#br-logo-op-out").textContent = e.target.value + "%"));
  $("#br-logo-op").addEventListener("change", (e) => saveBrand({ logo_opacity: +e.target.value / 100 }));
  $("#br-soc-mode").addEventListener("change", (e) => saveBrand({ social_mode: e.target.value }));
  $("#br-soc-every").addEventListener("change", (e) => saveBrand({ social_every: +e.target.value }));
  $("#br-soc-side").addEventListener("change", (e) => saveBrand({ social_side: e.target.value }));
  $("#s-frame-btn").addEventListener("click", openFrames);
  $("#frames-close").addEventListener("click", () => $("#framesdlg").close());
  $("#brand-close").addEventListener("click", () => { $("#branddlg").close(); if (S.P && $("#framesdlg").open) renderFrameGrid(); });
  $("#btn-frames-brand").addEventListener("click", openBrand);
  $("#br-handle").addEventListener("change", (e) => saveBrand({ handle: e.target.value.trim() }));
  $("#br-kicker").addEventListener("change", (e) => { e.target.value = e.target.value.trim().toUpperCase(); saveBrand({ kicker: e.target.value }); });
  $("#br-color").addEventListener("change", (e) => saveBrand({ color: e.target.value }));
  $("#br-text").addEventListener("change", (e) => saveBrand({ text: e.target.value }));
  $("#br-bg").addEventListener("change", (e) => saveBrand({ bg: e.target.value }));
  $("#br-progress").addEventListener("change", (e) => saveBrand({ progress: e.target.checked }));
  $("#br-logo-file").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const r = await fetch("/api/brand/logo", { method: "POST", body: f });
      if (!r.ok) throw new Error((await r.json()).detail || "Falha no envio do logo");
      S.logoV = Date.now(); S.cfg = await api("GET", "/api/settings"); openBrand(); refreshFrameThumb();
      if (S.P && S.sel) applyPhoneLook(S.P.clips.find((c) => c.id === S.sel));
    } catch (err) { toast(err.message, true); }
    e.target.value = "";
  });
  $("#br-logo-del").addEventListener("click", async () => {
    await api("DELETE", "/api/brand/logo"); S.logoV = Date.now(); S.cfg = await api("GET", "/api/settings"); openBrand(); refreshFrameThumb();
  });
  const saveClip = async (field, val) => {
    if (!S.sel) return;
    try {
      S.P = await api("PUT", `/api/projects/${S.P.id}/clips/${S.sel}`, { [field]: val });
      const c = S.P.clips.find((x) => x.id === S.sel); applyPhoneLook(c); refreshFrameThumb();
    } catch (e) { toast(e.message, true); }
  };
  $("#s-ed-hook").addEventListener("change", (e) => saveClip("hook", e.target.value.trim()));
  $("#s-ed-kicker").addEventListener("change", (e) => { e.target.value = e.target.value.trim().toUpperCase(); saveClip("kicker", e.target.value); });
}

/* ----- galeria de estilos de legenda ----- */

function yLabel(y) { return y <= 10 ? "bem embaixo" : y < 35 ? "embaixo" : y < 65 ? "no meio" : y < 90 ? "em cima" : "no topo"; }

function styleVersion() {
  const s = { ...S.P.settings.subtitles }; delete s.style; delete s.enabled;
  return hash(s);
}
function refreshStyleThumbs() {
  if (!S.P || !S.P.words || !S.P.words.length) return;
  const st = S.P.settings.subtitles.style;
  const url = `/api/projects/${S.P.id}/subtitle-preview?style=${st}&v=${styleVersion()}`;
  $$("#s-style-img,[data-style-img]").forEach((img) => { if (img.getAttribute("src") !== url) img.src = url; });
  $$("#s-style-name,[data-style-name]").forEach((el) => (el.textContent = styleName(st)));
}

function openStyles() {
  if (!S.P.words || !S.P.words.length) { toast("Este vídeo não tem transcrição para legendar", true); return; }
  const dlg = $("#styles");
  fillStyleCustom();
  renderStyleGrid();
  if (!dlg.open) dlg.showModal();
}

function renderStyleGrid() {
  const cur = S.P.settings.subtitles;
  const v = styleVersion();
  $("#style-grid").innerHTML = Object.entries(S.meta.styles).map(([k, s]) => `
    <button class="style-card ${cur.style === k ? "active" : ""}" data-style="${k}">
      <div class="im"><img data-src="/api/projects/${S.P.id}/subtitle-preview?style=${k}&v=${cur.style === k ? v : "padrao"}" alt="Prévia do estilo ${esc(s.name)}"></div>
      <div class="tx"><b>${esc(s.name)}</b><small>${esc(s.desc)}</small></div>
    </button>`).join("");
  // carrega as prévias em sequência curta (o servidor gera cada uma com o motor real)
  $$("#style-grid img").forEach((img, i) => {
    img.onload = () => img.classList.add("ok");
    setTimeout(() => (img.src = img.dataset.src), i * 60);
  });
  $$("#style-grid .style-card").forEach((b) => b.addEventListener("click", async () => {
    const k = b.dataset.style, d = S.meta.style_defaults[k];
    const patch = { style: k, font: d.font, uppercase: d.uppercase, max_chars: d.max_chars, lines: d.lines,
      color: d.color, highlight: d.highlight, position: d.position, y_pct: { baixo: 18, meio: 50, topo: 82 }[d.position] ?? 18 };
    try {
      S.P = await api("PUT", `/api/projects/${S.P.id}/settings`, { subtitles: patch });
      $$("#style-grid .style-card").forEach((x) => x.classList.toggle("active", x === b));
      fillStyleCustom(); refreshStyleThumbs();
      if (S.sel) applyPhoneLook(S.P.clips.find((c) => c.id === S.sel));
    } catch (e) { toast(e.message, true); }
  }));
}

function fillStyleCustom() {
  const s = S.P.settings.subtitles;
  $("#sc-font").innerHTML = (S.meta.fonts || []).map((f) => `<option ${f === s.font ? "selected" : ""}>${esc(f)}</option>`).join("");
  const pct = s.size_pct ?? ({ p: 82, m: 100, g: 120 }[s.size || "m"]);
  $("#sc-size").value = pct; $("#sc-size-out").textContent = pct + "%";
  const y = s.y_pct ?? 18; $("#sc-y").value = y; $("#sc-y-out").textContent = yLabel(y);
  const lay = (studio().frame || "cheia"), g = ((S.meta || {}).geometry || {})[lay];
  $("#sc-band-note").textContent = g && g.sub ? `Na moldura "${layoutName(lay)}" a legenda fica dentro da faixa; a altura não muda nela (o tamanho, sim).` : "";
  $("#sc-color").value = s.color; $("#sc-hl").value = s.highlight; $("#sc-upper").checked = !!s.uppercase;
  $("#sc-chars").value = s.max_chars; $("#sc-chars-out").textContent = s.max_chars;
}

function setupStyles() {
  $("#styles-close").addEventListener("click", () => $("#styles").close());
  const upd = async (key, val) => {
    S.P = await api("PUT", `/api/projects/${S.P.id}/settings`, { subtitles: { [key]: val } });
    refreshStyleThumbs();
    const cur = S.P.settings.subtitles.style;
    const img = $(`#style-grid [data-style="${cur}"] img`);
    if (img) { img.classList.remove("ok"); img.src = `/api/projects/${S.P.id}/subtitle-preview?style=${cur}&v=${styleVersion()}`; }
    if (S.sel) applyPhoneLook(S.P.clips.find((c) => c.id === S.sel));
  };
  $("#sc-font").addEventListener("change", (e) => upd("font", e.target.value));
  $("#sc-size").addEventListener("input", (e) => ($("#sc-size-out").textContent = e.target.value + "%"));
  $("#sc-size").addEventListener("change", (e) => upd("size_pct", +e.target.value));
  $("#sc-y").addEventListener("input", (e) => ($("#sc-y-out").textContent = yLabel(+e.target.value)));
  $("#sc-y").addEventListener("change", (e) => upd("y_pct", +e.target.value));
  $("#sc-color").addEventListener("change", (e) => upd("color", e.target.value));
  $("#sc-hl").addEventListener("change", (e) => upd("highlight", e.target.value));
  $("#sc-upper").addEventListener("change", (e) => upd("uppercase", e.target.checked));
  $("#sc-chars").addEventListener("input", (e) => ($("#sc-chars-out").textContent = e.target.value));
  $("#sc-chars").addEventListener("change", (e) => upd("max_chars", +e.target.value));
}

/* ---------- configurações ---------- */

const PRESETS = {
  groq: { "transcription.api_base": "https://api.groq.com/openai/v1", "transcription.api_model": "whisper-large-v3-turbo" },
  openai: { "transcription.api_base": "https://api.openai.com/v1", "transcription.api_model": "whisper-1" },
};
const AI_MODELS = { anthropic: "claude-haiku-4-5-20251001", openai_compat: "gpt-4o-mini" };
const AI_MODEL_LIST = {
  anthropic: [["claude-haiku-4-5-20251001", "Haiku 4.5 — rápido e barato (recomendado)"], ["claude-sonnet-5-5", "Sonnet 5.5 — escreve melhor, custa o dobro"]],
  openai_compat: [["gpt-4o-mini", "GPT-4o mini — barato"], ["gpt-4.1-mini", "GPT-4.1 mini"], ["gpt-4.1", "GPT-4.1"]],
};
// custo aproximado por hora de vídeo (texto da transcrição + respostas), pelos preços oficiais da Anthropic
const AI_COST = { "claude-haiku-4-5": 0.10, "claude-sonnet-5-5": 0.20, "claude-opus-5-5": 0.40 };
const AI_WHERE = {
  anthropic: ["platform.claude.com", "https://platform.claude.com/settings/keys"],
  openai_compat: ["platform.openai.com", "https://platform.openai.com/api-keys"],
};

function fillForm(form, cfg) {
  $$("[name]", form).forEach((el) => {
    const [sec, key] = el.name.split(".");
    if (!cfg[sec]) return;
    if (el.type === "radio") el.checked = String(cfg[sec][key]) === el.value;
    else if (el.dataset.key !== undefined) {
      el.value = "";
      el.placeholder = cfg[sec].api_key_set ? `Configurada (${cfg[sec].api_key_hint || "oculta"}). Deixe vazio para manter` : "Cole sua chave aqui";
    } else el.value = cfg[sec][key] ?? "";
  });
}

function formVal(form, name) {
  const els = $$(`[name="${name}"]`, form);
  if (!els.length) return "";
  if (els[0].type === "radio") { const c = els.find((x) => x.checked); return c ? c.value : ""; }
  return els[0].value;
}

function refreshShow(form = $("#settings-form")) {
  $$("[data-show]", form).forEach((el) => {
    const m = el.dataset.show.match(/^([\w.]+)(!?=)(\w+)$/);
    const val = formVal(form, m[1]);
    el.classList.toggle("hidden", m[2] === "=" ? val !== m[3] : val === m[3]);
  });
}

function collectSettings(form = $("#settings-form")) {
  const out = {};
  $$("[name]", form).forEach((el) => {
    const [sec, key] = el.name.split(".");
    out[sec] = out[sec] || {};
    if (el.type === "radio") { if (el.checked) out[sec][key] = el.value; return; }
    if (el.dataset.key !== undefined && !el.value) return;
    out[sec][key] = el.value.trim();
  });
  return out;
}

async function openSettings() {
  const cfg = await api("GET", "/api/settings");
  S.cfg = cfg;
  fillForm($("#settings-form"), cfg);
  fillSecurity(cfg);
  const st = S.status || {};
  $("#sys-info").textContent = `Detectado: renderização ${st.encoder && st.encoder !== "libx264" ? "com GPU (" + st.encoder + ")" : "pelo processador"} · transcrição local ${st.local_transcription ? (st.gpu_transcription ? "com GPU NVIDIA" : "pelo processador") : "não instalada"} · enquadramento por rosto ${S.meta && S.meta.face_detection ? "ativo" : "indisponível"}.`;
  refreshShow();
  $("#settings").showModal();
}

function iaExtras() {
  const form = $("#ia-form"), prov = formVal(form, "ai.provider");
  $("#ia-models").innerHTML = (AI_MODEL_LIST[prov] || []).map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
  const w = AI_WHERE[prov];
  $("#ia-where").innerHTML = w ? `Onde pegar a chave: <a href="${w[1]}" target="_blank" rel="noopener" data-ext>${w[0]}</a>. É preciso colocar crédito na conta (a partir de US$ 5).` : "";
  const model = form.elements["ai.model"].value || "";
  const k = Object.keys(AI_COST).find((x) => model.startsWith(x));
  $("#ia-cost").innerHTML = prov === "none" ? "" : k
    ? `Custo estimado: <b>cerca de US$ ${AI_COST[k].toFixed(2).replace(".", ",")} por hora de vídeo</b> analisada. Um vídeo por dia dá poucos reais por mês.`
    : "O custo depende do modelo escolhido. Veja a tabela de preços no site do provedor. Em geral são centavos por vídeo.";
}

async function renderIA() {
  const form = $("#ia-form");
  try { S.cfg = await api("GET", "/api/settings"); } catch (e) { toast(e.message, true); return; }
  fillForm(form, S.cfg);
  form.dataset.loaded = "1";
  $("#ia-test-msg").textContent = ""; $("#ia-saved").textContent = "";
  refreshShow(form); iaExtras();
}

function updateIABadge() {
  const on = S.cfg && S.cfg.ai && S.cfg.ai.provider !== "none" && S.cfg.ai.api_key_set;
  $("#nav-ia-on").classList.toggle("hidden", !on);
}

function setupSettings() {
  $$("[data-open-settings]").forEach((b) => b.addEventListener("click", openSettings));
  $$("[data-close-settings]").forEach((a) => a.addEventListener("click", () => $("#settings").close()));
  const form = $("#settings-form");
  form.addEventListener("change", () => refreshShow(form));
  $("#btn-save-settings").addEventListener("click", async (e) => {
    e.preventDefault();
    try { S.cfg = await api("PUT", "/api/settings", collectSettings(form)); $("#settings").close(); toast("Configurações salvas"); if (S.mode === "studio") renderStudio(); }
    catch (err) { toast(err.message, true); }
  });
  // página Inteligência artificial
  const ia = $("#ia-form");
  ia.addEventListener("change", (e) => {
    if (e.target.name === "ai.provider" && AI_MODELS[e.target.value]) {
      const cur = ia.elements["ai.model"].value, list = (AI_MODEL_LIST[e.target.value] || []).map((x) => x[0]);
      if (!list.includes(cur)) ia.elements["ai.model"].value = AI_MODELS[e.target.value];
      if (e.target.value === "openai_compat" && !ia.elements["ai.base_url"].value) ia.elements["ai.base_url"].value = "https://api.openai.com/v1";
    }
    refreshShow(ia); iaExtras();
  });
  ia.elements["ai.model"].addEventListener("input", iaExtras);
  $$("[data-preset]", ia).forEach((b) => b.addEventListener("click", () => {
    for (const [k, v] of Object.entries(PRESETS[b.dataset.preset])) ia.elements[k].value = v;
  }));
  const save = async () => { S.cfg = await api("PUT", "/api/settings", collectSettings(ia)); fillForm(ia, S.cfg); refreshShow(ia); iaExtras(); updateIABadge(); };
  $("#ia-save").addEventListener("click", async () => {
    try { await save(); $("#ia-saved").textContent = "Salvo."; toast("Configurações da IA salvas"); }
    catch (err) { toast(err.message, true); }
  });
  $("#ia-test").addEventListener("click", async () => {
    $("#ia-test-msg").textContent = "Testando…";
    try { await save(); const r = await api("POST", "/api/settings/test-ai"); $("#ia-test-msg").textContent = r.msg; }
    catch (err) { $("#ia-test-msg").textContent = err.message; }
  });
}

/* ---------- ligações gerais ---------- */

function setupEditor() {
  $("#btn-back").addEventListener("click", () => { location.hash = "#/projetos"; });
  $$(".seg-btn[data-mode]").forEach((b) => b.addEventListener("click", () => { if (S.P && S.P.status === "pronto") setMode(b.dataset.mode); }));
  $("#btn-play").addEventListener("click", togglePlay);
  const v = $("#video");
  const icons = (btn, playing) => { $(".ico-play", btn).classList.toggle("hidden", playing); $(".ico-pause", btn).classList.toggle("hidden", !playing); };
  v.addEventListener("play", () => icons($("#btn-play"), true));
  v.addEventListener("pause", () => icons($("#btn-play"), false));
  v.addEventListener("click", togglePlay);
  $("#btn-retry").addEventListener("click", async () => { S.P = await api("POST", `/api/projects/${S.P.id}/reprocess`); applyProject(); });
  $("#btn-reset").addEventListener("click", async () => {
    if (!confirm("Desfazer todos os cortes manuais e restaurações?")) return;
    S.P = await api("POST", `/api/projects/${S.P.id}/reset`); applyProject();
  });
  const menus = [["#btn-export", "#menu-export"], ["#btn-render", "#menu-render"]];
  menus.forEach(([b, m]) => $(b).addEventListener("click", (e) => {
    e.stopPropagation(); menus.forEach(([, o]) => o !== m && $(o).classList.add("hidden")); $(m).classList.toggle("hidden");
  }));
  document.addEventListener("click", () => menus.forEach(([, m]) => $(m).classList.add("hidden")));
  $$("[data-export]").forEach((a) => a.addEventListener("click", () => { location.href = `/api/projects/${S.P.id}/export/${a.dataset.export}`; }));
  $$("[data-render]").forEach((a) => a.addEventListener("click", () => startRender(`/api/projects/${S.P.id}/render`, JSON.parse(a.dataset.render))));
  document.addEventListener("keydown", (e) => {
    if ($("#view-editor").classList.contains("hidden") || S.editing || document.querySelector("dialog[open]")) return;
    if (e.target.closest && e.target.closest("#s-clipedit")) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (["input", "select", "textarea"].includes(tag) || e.target.isContentEditable) return;
    if (e.code === "Space") { e.preventDefault(); if (S.mode === "edit") togglePlay(); else $("#s-play").click(); }
    if (S.mode !== "edit") return;
    if ((e.key === "Delete" || e.key === "Backspace") && selectedWords()) { e.preventDefault(); cutSelection(); }
    if (e.key === "ArrowLeft") $("#video").currentTime -= 5;
    if (e.key === "ArrowRight") $("#video").currentTime += 5;
  });
}


/* =====================================================================
   v0.9 — senha do PC, ligação PC ↔ online, destaques, áudio e celular
   ===================================================================== */

const isOnline = () => !!(S.status || {}).online_mode;

function applyMode() {
  document.body.classList.toggle("online", isOnline());
}

/* ---------- baixar um arquivo (no PC abre a janela Salvar; no navegador, download normal) ---------- */
function baixar(href, name) {
  const a = document.createElement("a");
  a.href = href; a.setAttribute("download", name || ""); a.style.display = "none";
  document.body.appendChild(a); a.click(); setTimeout(() => a.remove(), 500);
}

/* ---------- caixa de transferência (enviar, trazer, importar) ---------- */
const XFER = {};
function xferShow(title, msg = "", pct = 0) {
  $("#xfer").classList.remove("hidden");
  $("#xfer-title").textContent = title; $("#xfer-msg").textContent = msg;
  $("#xfer-bar").style.width = Math.round(pct * 100) + "%";
}
function xferHide() { $("#xfer").classList.add("hidden"); }

function acompanharJob(pid, kind, title, onDone) {
  clearInterval(XFER.t);
  xferShow(title, "Começando…", 0);
  XFER.t = setInterval(async () => {
    let list = [];
    try { list = await api("GET", `/api/jobs/${pid}`); } catch (_) { return; }
    const j = list.find((x) => x.kind === kind);
    if (!j) return;
    xferShow(title, j.msg || "", j.pct || 0);
    if (j.status === "concluido") { clearInterval(XFER.t); setTimeout(xferHide, 2500); xferShow(title, "Pronto!", 1); if (onDone) onDone(j); }
    if (j.status === "erro") { clearInterval(XFER.t); xferHide(); toast(j.error || "Não deu certo", true); }
  }, 1500);
}

async function enviarOnline(p) {
  if (!(S.cfg && S.cfg.online && S.cfg.online.url)) {
    toast("Primeiro coloque o endereço e a senha do online em Configurações → Versão online.", true);
    openSettings(); return;
  }
  if (!confirm(`Enviar "${p.name}" para o online?\n\nVai o projeto completo: vídeo, edição, cortes e exportados. No online ele abre como está, sem nova análise (não gasta API).`)) return;
  try {
    await api("POST", `/api/projects/${p.id}/enviar-online`);
    acompanharJob(p.id, "enviar", "Enviando para o online", () => toast(`"${p.name}" já está no online. Abra ${S.cfg.online.url} para continuar de lá.`));
  } catch (e) { toast(e.message, true); }
}

function baixarPacote(p) {
  toast("Preparando o projeto completo…");
  baixar(`/api/projects/${p.id}/pacote`, (p.name || "projeto").replace(/[\\/:*?"<>|]+/g, "_").slice(0, 60) + ".vox");
}

function importarVox(file) {
  if (!/\.vox$/i.test(file.name) && file.type !== "application/zip") { toast("Escolha um arquivo .vox (projeto salvo pelo VOX Editor).", true); return; }
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/projects/importar-pacote");
  xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
  const t0 = Date.now();
  xferShow("Importando projeto", "Enviando…", 0);
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = e.loaded / e.total, speed = e.loaded / Math.max((Date.now() - t0) / 1000, 0.1);
    xferShow("Importando projeto", `${Math.round(pct * 100)}% · ${fmtSize(speed)}/s · faltam ${fmtDur((e.total - e.loaded) / speed)}`, pct * 0.95);
    if (pct >= 1) xferShow("Importando projeto", "Abrindo o projeto…", 0.97);
  };
  xhr.onload = () => {
    if (xhr.status >= 200 && xhr.status < 300) {
      const p = JSON.parse(xhr.responseText);
      xferShow("Importando projeto", "Pronto!", 1); setTimeout(xferHide, 2000);
      toast(`"${p.name}" importado, do jeito que estava.`);
      location.hash = "#/p/" + p.id + ((p.clips || []).length ? "/cortes" : "");
    } else {
      xferHide();
      let msg = xhr.statusText; try { msg = JSON.parse(xhr.responseText).detail; } catch (_) {}
      toast("Não consegui importar: " + msg, true);
    }
  };
  xhr.onerror = () => { xferHide(); toast("Falha de conexão no envio", true); };
  xhr.send(file);
}

async function abrirTrazerOnline() {
  const box = $("#online-list");
  box.innerHTML = `<p class="hint">Carregando os projetos do online…</p>`;
  $("#onlinedlg").showModal();
  let list;
  try { list = await api("GET", "/api/online/projetos"); }
  catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p><p class="hint">Confira o endereço e a senha em Configurações → Versão online.</p>`; return; }
  if (!list.length) { box.innerHTML = `<p class="hint">O online ainda não tem projetos.</p>`; return; }
  box.innerHTML = list.map((p) => `
    <div class="online-item">
      <div><b>${esc(p.name)}</b><small>${fmt(p.duration || 0)} · ${p.clips || 0} corte(s) · ${p.renders || 0} exportado(s) · ${fmtSize(p.size || 0)}${p.status !== "pronto" ? " · " + esc(p.status) : ""}</small></div>
      <button type="button" class="btn small primary" data-trazer="${p.id}" ${p.status !== "pronto" ? "disabled" : ""}>Trazer</button>
    </div>`).join("");
  $$("[data-trazer]", box).forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      await api("POST", `/api/online/trazer/${b.dataset.trazer}`);
      $("#onlinedlg").close();
      acompanharJob("_online", "trazer", "Trazendo do online", (j) => {
        toast("Projeto trazido do online.");
        if (j.result && j.result.id) location.hash = "#/p/" + j.result.id; else goHome("projetos");
      });
    } catch (e) { b.disabled = false; toast(e.message, true); }
  }));
}

/* ---------- Configurações: senha do PC e versão online ---------- */
function fillSecurity(cfg) {
  const set = !!(cfg.security && cfg.security.password_set);
  $("#pw-status").textContent = set
    ? "A senha está ligada: o programa pede a senha ao abrir."
    : "Sem senha: qualquer pessoa que usar este computador abre o editor. Crie uma senha para proteger seus projetos e contas.";
  $("#pw-cur-wrap").classList.toggle("hidden", !set);
  $("#pw-remove").classList.toggle("hidden", !set);
  ["#pw-cur", "#pw-new", "#pw-new2"].forEach((k) => ($(k).value = ""));
  const on = cfg.online || {};
  $("#on-url").value = on.url || "";
  $("#on-pass").value = "";
  $("#on-pass").placeholder = on.password_set ? "Guardada. Deixe vazio para manter" : "A senha que você criou na instalação da VPS";
  $("#on-msg").textContent = "";
}

async function salvarSenha(remover) {
  const cur = $("#pw-cur").value, nova = remover ? "" : $("#pw-new").value;
  if (!remover) {
    if (nova.length < 4) { toast("A senha precisa ter pelo menos 4 caracteres.", true); return; }
    if (nova !== $("#pw-new2").value) { toast("As duas senhas novas não conferem.", true); return; }
  } else if (!confirm("Tirar a senha? Qualquer pessoa neste computador vai poder abrir o editor.")) return;
  try {
    await api("POST", "/api/security/password", { current: cur, new: nova });
    S.cfg = await api("GET", "/api/settings"); S.status = await api("GET", "/api/status");
    fillSecurity(S.cfg);
    toast(remover ? "Senha retirada." : "Senha salva. Da próxima vez que abrir, o programa vai pedir.");
  } catch (e) { toast(e.message, true); }
}

async function salvarOnline() {
  const url = $("#on-url").value.trim(), password = $("#on-pass").value;
  S.cfg.online = await api("PUT", "/api/online/config", { url, password });
  $("#on-pass").value = "";
  $("#on-pass").placeholder = S.cfg.online.password_set ? "Guardada. Deixe vazio para manter" : "";
}

function setupV09Settings() {
  $("#pw-save").addEventListener("click", () => salvarSenha(false));
  $("#pw-remove").addEventListener("click", () => salvarSenha(true));
  $("#on-test").addEventListener("click", async () => {
    const msg = $("#on-msg");
    msg.className = "hint"; msg.textContent = "Testando…";
    try {
      await salvarOnline();
      const r = await api("POST", "/api/online/testar");
      msg.className = "hint ok"; msg.textContent = `Conectado ao online (versão ${r.version}, ${r.projects} projeto(s)).`;
    } catch (e) { msg.className = "err"; msg.textContent = e.message; }
  });
  $("#on-copy").addEventListener("click", async () => {
    const msg = $("#on-msg");
    if (!confirm("Copiar as configurações deste PC para o online?\n\nO que for igual é substituído pelo que está aqui (chaves de IA, marca, modelos, músicas, agenda). As contas conectadas no online não mudam.")) return;
    msg.className = "hint"; msg.textContent = "Copiando…";
    try {
      await salvarOnline();
      await api("POST", "/api/online/copiar-config");
      msg.className = "hint ok"; msg.textContent = "Configurações copiadas para o online.";
    } catch (e) { msg.className = "err"; msg.textContent = e.message; }
  });
}

/* ---------- músicas de fundo ---------- */
async function loadMusicas(force = false) {
  if (S.musicas && !force) return S.musicas;
  try { S.musicas = await api("GET", "/api/musicas"); } catch (_) { S.musicas = []; }
  return S.musicas;
}

function fillMusicSelect(sel, current) {
  const list = S.musicas || [];
  sel.innerHTML = `<option value="">Sem música</option>` + list.map((m) =>
    `<option value="${esc(m.nome)}">${esc(m.nome.replace(/\.[^.]+$/, ""))}${m.duracao ? " · " + fmt(m.duracao) : ""}</option>`).join("");
  if (current && !list.some((m) => m.nome === current)) sel.insertAdjacentHTML("beforeend", `<option value="${esc(current)}">${esc(current)} (não encontrada)</option>`);
  sel.value = current || "";
}

function enviarMusica(file, onDone) {
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/musicas");
  xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
  xferShow("Enviando música", file.name, 0);
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) xferShow("Enviando música", file.name, e.loaded / e.total); };
  xhr.onload = () => {
    xferHide();
    if (xhr.status >= 200 && xhr.status < 300) { S.musicas = JSON.parse(xhr.responseText); toast("Música adicionada."); onDone && onDone(file.name.replace(/[\\/:*?"<>|]+/g, "_")); }
    else { let msg = xhr.statusText; try { msg = JSON.parse(xhr.responseText).detail; } catch (_) {} toast(msg, true); }
  };
  xhr.onerror = () => { xferHide(); toast("Falha de conexão no envio", true); };
  xhr.send(file);
}

/* ---------- estúdio: destaques e áudio ---------- */
async function renderExtras() {
  if (!S.P || !S.P.settings) return;
  const sub = S.P.settings.subtitles || {}, st = S.P.settings.studio || {}, au = S.P.settings.audio || {};
  $("#s-kw").checked = sub.keywords !== false;
  $("#s-kwcolor").value = sub.keyword_color || "#39E75F";
  $("#s-emoji").checked = sub.emojis !== false;
  $("#s-emph").checked = st.emphasis_zoom !== false;
  $("#s-clean").checked = !!au.clean;
  const vol = Math.round((au.music_volume ?? 0.12) * 100);
  $("#s-musicvol").value = vol; $("#s-musicvol-out").textContent = vol + "%";
  const ai = (S.cfg || {}).ai || {};
  const comIA = ai.provider && ai.provider !== "none" && ai.api_key_set;
  $("#s-kw-hint").textContent = comIA
    ? "A IA escolhe as palavras e os emojis de cada corte (só uma vez por trecho; fica guardado)."
    : "Sem IA: usa uma lista de palavras de fé e números. Com o Claude ligado, a escolha fica bem mais esperta.";
  await loadMusicas();
  fillMusicSelect($("#s-music"), au.music || "");
  $("#s-musicvol-wrap").classList.toggle("hidden", !au.music);
  $("#s-music-play").classList.toggle("hidden", !au.music);
}

function setupV09Studio() {
  $("#s-kw").addEventListener("change", (e) => setSetting("subtitles", "keywords", e.target.checked, 50));
  $("#s-kwcolor").addEventListener("change", (e) => setSetting("subtitles", "keyword_color", e.target.value, 50));
  $("#s-emoji").addEventListener("change", (e) => setSetting("subtitles", "emojis", e.target.checked, 50));
  $("#s-emph").addEventListener("change", (e) => setSetting("studio", "emphasis_zoom", e.target.checked, 50));
  $("#s-clean").addEventListener("change", (e) => setSetting("audio", "clean", e.target.checked, 50));
  $("#s-music").addEventListener("change", (e) => {
    setSetting("audio", "music", e.target.value, 50);
    $("#s-musicvol-wrap").classList.toggle("hidden", !e.target.value);
    $("#s-music-play").classList.toggle("hidden", !e.target.value);
    $("#s-music-audio").pause();
  });
  $("#s-musicvol").addEventListener("input", (e) => ($("#s-musicvol-out").textContent = e.target.value + "%"));
  $("#s-musicvol").addEventListener("change", (e) => setSetting("audio", "music_volume", +e.target.value / 100, 50));
  $("#s-music-file").addEventListener("change", (e) => {
    const f = e.target.files[0]; e.target.value = "";
    if (f) enviarMusica(f, (nome) => { fillMusicSelect($("#s-music"), nome); $("#s-music").dispatchEvent(new Event("change")); });
  });
  $("#s-music-play").addEventListener("click", () => {
    const a = $("#s-music-audio"), nome = $("#s-music").value;
    if (!nome) return;
    if (!a.paused) { a.pause(); $("#s-music-play").textContent = "Ouvir"; return; }
    a.src = `/api/musicas/${encodeURIComponent(nome)}`; a.volume = Math.min(1, (+$("#s-musicvol").value / 100) * 3);
    a.play(); $("#s-music-play").textContent = "Parar";
    a.onended = () => ($("#s-music-play").textContent = "Ouvir");
  });
}

/* ---------- Modelos: destaques e áudio padrão ---------- */
async function renderModelosExtras(d) {
  const sub = d.subtitles || {}, st = d.studio || {}, au = d.audio || {};
  $("#m-kw").checked = sub.keywords !== false;
  $("#m-kwcolor").value = sub.keyword_color || "#39E75F";
  $("#m-emoji").checked = sub.emojis !== false;
  $("#m-emph").checked = st.emphasis_zoom !== false;
  $("#m-clean").checked = !!au.clean;
  const vol = Math.round((au.music_volume ?? 0.12) * 100);
  $("#m-musicvol").value = vol; $("#m-musicvol-out").textContent = vol + "%";
  await loadMusicas(true);
  fillMusicSelect($("#m-music"), au.music || "");
}

function modelosExtras() {
  return {
    subtitles: { keywords: $("#m-kw").checked, keyword_color: $("#m-kwcolor").value, emojis: $("#m-emoji").checked },
    studio: { emphasis_zoom: $("#m-emph").checked },
    audio: { clean: $("#m-clean").checked, music: $("#m-music").value, music_volume: +$("#m-musicvol").value / 100 },
  };
}

/* ---------- celular: menu de baixo e menu lateral como gaveta ---------- */
function setupMobile() {
  $("#bn-more").addEventListener("click", (e) => { e.stopPropagation(); document.body.classList.toggle("drawer-open"); });
  document.addEventListener("click", (e) => {
    if (!document.body.classList.contains("drawer-open")) return;
    if (!e.target.closest(".side") || e.target.closest("a, button[data-open-settings]")) document.body.classList.remove("drawer-open");
  });
  window.addEventListener("hashchange", () => {
    document.body.classList.remove("drawer-open");
    const pg = (location.hash.match(/^#\/(projetos|exportados|publicacoes)/) || [])[1] || (location.hash.startsWith("#/p/") ? "" : "inicio");
    $$(".bottom-nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === pg));
  });
  $$(".bottom-nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === "inicio" && (location.hash || "#/") === "#/"));
}

function setupV09() {
  setupV09Settings(); setupV09Studio(); setupMobile();
  if (matchMedia("(pointer: coarse)").matches) {  // celular: não existe "arrastar"
    const st = $("#dropzone .drop-copy strong"), sp = $("#dropzone .drop-copy span");
    if (st) st.textContent = "Toque para escolher um vídeo";
    if (sp) sp.textContent = "Da galeria ou dos arquivos. Pregação, aula, live ou podcast.";
  }
  $("#xfer-close").addEventListener("click", xferHide);
  $("#vox-input").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) importarVox(f); });
  $("#btn-from-online").addEventListener("click", abrirTrazerOnline);
  $("#exp-pacote").addEventListener("click", () => { $("#menu-export").classList.add("hidden"); if (S.P) baixarPacote(S.P); });
  $("#exp-online").addEventListener("click", () => { $("#menu-export").classList.add("hidden"); if (S.P) enviarOnline(S.P); });
  $("#m-musicvol").addEventListener("input", (e) => ($("#m-musicvol-out").textContent = e.target.value + "%"));
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await api("POST", "/api/login", { password: $("#login-pass").value }); $("#login-err").textContent = ""; boot(); }
  catch (err) { $("#login-err").textContent = /Muitas tentativas/.test(err.message) ? err.message : "Senha incorreta"; }
});

setupDesktop(); setupUpload(); setupHome(); setupPublish(); setupRedes(); setupModelos(); setupEditor(); setupTranscript(); setupTimeline(); setupSettings(); setupStudio(); setupStyles(); setupFrames(); setupV09();
requestAnimationFrame(tick);
boot();
