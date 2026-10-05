"use strict";
/* VOX Editor — Montagem: editor manual multicamadas.
   Linha do tempo com trilhas (vídeo, imagem, texto, cor, áudio), prévia na hora num canvas e exportação pelo
   servidor (FFmpeg) com as mesmas contas de posição, tamanho, giro, transparência e esmaecimento.
   Usa as funções do app.js: $, $$, api, toast, esc, fmt, fmtSize, baixar, openPublish. */

const Montagem = (() => {
  const FONTES = ["Poppins ExtraBold", "Poppins", "Anton", "Bebas Neue", "Archivo Black"];
  const FORMATOS = { "9:16": "Vertical 9:16 (Reels, Shorts, TikTok)", "16:9": "Horizontal 16:9 (YouTube)",
    "1:1": "Quadrado 1:1", "4:5": "Retrato 4:5 (Feed)" };
  const DIM = { "9:16": [1080, 1920], "16:9": [1920, 1080], "1:1": [1080, 1080], "4:5": [1080, 1350] };
  const ACEITA = { video: ["video", "image", "color"], text: ["text", "tarja"], audio: ["audio"] };
  const NOME_TRILHA = { video: "Vídeo", text: "Texto", audio: "Áudio" };
  const headW = () => { const c = document.querySelector("#montage-body .mt-corner"); return (c && c.offsetWidth) || 150; };  // cabeçalho das trilhas
  const ALTURA = { video: 58, text: 40, audio: 46 };
  const CORES_FUNDO = ["#000000", "#FFFFFF", "#101114", "#1B2A4A", "#0F3D3E", "#3B1F4A", "#7A1F2B", "#C2410C",
    "#FF8A3D", "#FACC15", "#16A34A", "#0EA5E9", "#6366F1", "#EC4899", "#F5E6C8", "#6B7280"];
  const TEXTOS = [
    { nome: "Título", desc: "Grande, em maiúsculas", it: { text: "SEU TÍTULO AQUI", font: "Poppins ExtraBold", size: 0.085, upper: true, strokeW: 0.06, y: 0.42 } },
    { nome: "Legenda", desc: "Frase com fundo escuro", it: { text: "Escreva a frase aqui", font: "Poppins", size: 0.055, boxOn: true, boxAlpha: 0.65, y: 0.78 } },
    { nome: "Nome na tela", desc: "Quem está falando", it: { text: "Pr. Nome Sobrenome\nIgreja ou cargo", font: "Poppins", size: 0.048, boxOn: true, box: "#FF8A3D", boxAlpha: 0.95, color: "#111111", y: 0.84 } },
    { nome: "Versículo", desc: "Referência bíblica", it: { text: "JOÃO 3:16", font: "Bebas Neue", size: 0.1, color: "#F5E6C8", strokeW: 0.05, y: 0.2 } },
    { nome: "Chamada", desc: "Destaque forte", it: { text: "INSCREVA-SE", font: "Anton", size: 0.09, color: "#FACC15", strokeW: 0.08, upper: true, y: 0.62 } },
    { nome: "Texto simples", desc: "Sem enfeite", it: { text: "Texto", font: "Poppins", size: 0.07, y: 0.5 } },
  ];

  const M = { pid: null, P: null, m: null, sel: null, t: 0, playing: false, pps: 40, hist: [], fut: [], snap: true,
    saveT: null, saving: false, savedAt: 0, built: false, pool: new Map(), imgs: new Map(), raf: 0, clock: null,
    drag: null, editBefore: null, exportJob: null, proxyPoll: null, open: false, follow: true };

  const box = () => $("#montage-body");
  const fps = () => (M.m ? M.m.fps : 30);
  const q = (t) => Math.max(0, Math.round(t * fps()) / fps());
  const media = (id) => M.m.media.find((x) => x.id === id);
  const track = (id) => M.m.tracks.find((x) => x.id === id);
  const itemById = (id) => M.m.items.find((x) => x.id === id);
  const total = () => M.m.items.reduce((a, i) => Math.max(a, i.start + i.dur), 0);
  const uid = (p) => p + Math.random().toString(36).slice(2, 10);
  const urlMidia = (mid) => `/api/projects/${M.pid}/midias/${mid}`;
  const mainTrack = () => M.m.tracks.find((t) => t.main) || M.m.tracks.find((t) => t.kind === "video");
  const kindOf = (it) => (it.type === "text" || it.type === "tarja" ? "text" : it.type === "audio" ? "audio" : "video");
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const ico = (d, s = 16) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  const I = {
    play: '<path d="M7 4l13 8-13 8z" fill="currentColor" stroke="none"/>',
    pause: '<rect x="6" y="4" width="4" height="16" fill="currentColor" stroke="none"/><rect x="14" y="4" width="4" height="16" fill="currentColor" stroke="none"/>',
    undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    redo: '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
    split: '<path d="M12 3v18"/><path d="M5 8l-2 4 2 4M19 8l2 4-2 4"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    magnet: '<path d="M6 3v8a6 6 0 0 0 12 0V3"/><path d="M6 7h4M14 7h4"/>',
    zin: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4M8 11h6M11 8v6"/>',
    zout: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4M8 11h6"/>',
    fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    eyeoff: '<path d="M3 3l18 18"/><path d="M10.6 6.1A10 10 0 0 1 12 6c6 0 10 6 10 6a17 17 0 0 1-3.2 3.9M6.6 6.6C3.8 8.4 2 12 2 12s4 7 10 7a9.7 9.7 0 0 0 4.4-1"/>',
    vol: '<path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>',
    mute: '<path d="M11 5L6 9H3v6h3l5 4z"/><path d="M22 9l-6 6M16 9l6 6"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    unlock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    text: '<path d="M4 7V5h16v2M9 19h6M12 5v14"/>',
    img: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 17l-5-5-9 8"/>',
    film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    fill: '<path d="M12 3l9 9-9 9-9-9z"/>',
    sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    download: '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
    center: '<circle cx="12" cy="12" r="2"/><path d="M12 3v4M12 17v4M3 12h4M17 12h4"/>',
  };

  /* ---------------- montagem (dados) ---------------- */

  const snapshot = () => JSON.stringify({ tracks: M.m.tracks, items: M.m.items, formato: M.m.formato, bg: M.m.bg, fps: M.m.fps, suave: M.m.suave });
  function restore(s) {
    const o = JSON.parse(s);
    Object.assign(M.m, o);
    const [w, h] = DIM[M.m.formato] || [M.m.w, M.m.h];
    M.m.w = w; M.m.h = h;
    if (M.sel && !itemById(M.sel)) M.sel = null;
  }
  function commit(before) {
    if (before && before !== snapshot()) { M.hist.push(before); if (M.hist.length > 120) M.hist.shift(); M.fut = []; }
    save(); renderAll();
  }
  function undo() { if (!M.hist.length) return; M.fut.push(snapshot()); restore(M.hist.pop()); save(); renderAll(); }
  function redo() { if (!M.fut.length) return; M.hist.push(snapshot()); restore(M.fut.pop()); save(); renderAll(); }

  function save(delay = 700) {
    clearTimeout(M.saveT);
    setSaveState("Alterações não salvas");
    M.saveT = setTimeout(flush, delay);
  }
  async function flush() {
    clearTimeout(M.saveT); M.saveT = null;
    if (!M.m || !M.pid) return;
    M.saving = true; setSaveState("Salvando…");
    try {
      const r = await api("PUT", `/api/projects/${M.pid}/montagem`, M.m);
      M.m.media = r.media; M.savedAt = Date.now(); setSaveState("Salvo");
    } catch (e) { setSaveState("Não salvou — " + e.message); }
    M.saving = false;
  }
  function setSaveState(t) { const el = $(".mt-save", box()); if (el) el.textContent = t; }

  function overlaps(it, tid, ignore) {
    return M.m.items.some((o) => o !== it && o.id !== ignore && o.track === tid && o.start < it.start + it.dur - 1e-4 && it.start < o.start + o.dur - 1e-4);
  }
  /** Coloca o item numa trilha livre: a preferida, outra do mesmo tipo, ou cria uma trilha nova acima. */
  function place(it, preferred) {
    const kind = kindOf(it);
    const ok = (t) => t && t.kind === kind && !t.locked;
    let t = track(preferred);
    if (ok(t) && (t.main && M.snap || !overlaps(it, t.id))) { it.track = t.id; return; }
    const livres = M.m.tracks.filter((x) => ok(x) && !x.main && !overlaps(it, x.id));
    if (livres.length) { it.track = livres[0].id; return; }
    const nt = newTrack(kind, t ? M.m.tracks.indexOf(t) : (kind === "audio" ? M.m.tracks.length : 0));
    it.track = nt.id;
  }
  function newTrack(kind, at) {
    const n = M.m.tracks.filter((x) => x.kind === kind).length + 1;
    const t = { id: uid("t"), kind, name: `${NOME_TRILHA[kind]} ${n}`, hidden: false, muted: false, locked: false };
    M.m.tracks.splice(clamp(at, 0, M.m.tracks.length), 0, t);
    return t;
  }
  /** Trilha principal magnética: os itens ficam colados, sem buracos, a partir do zero. */
  function compactMain() {
    const mt = mainTrack(); if (!mt || !M.snap) return;
    const its = M.m.items.filter((i) => i.track === mt.id).sort((a, b) => a.start - b.start);
    let t = 0;
    its.forEach((i) => { i.start = q(t); t = i.start + i.dur; });
  }
  function itemsAt(t) { return M.m.items.filter((i) => i.start <= t + 1e-6 && t < i.start + i.dur - 1e-6); }

  /* ---------------- abrir / fechar ---------------- */

  async function open(P) {
    M.open = true;
    if (!M.built) build();
    if (M.pid !== P.id) {
      stop(); clearPool(); M.pid = P.id; M.P = P; M.sel = null; M.t = 0; M.hist = []; M.fut = [];
      try { M.m = await api("GET", `/api/projects/${P.id}/montagem`); }
      catch (e) { toast(e.message, true); return; }
      M.pps = fitZoom();
      document.fonts && Promise.all(FONTES.map((f) => document.fonts.load(`32px "${f}"`))).then(draw).catch(() => {});
      checkProxies();
    }
    M.P = P;
    renderAll();
    requestAnimationFrame(() => { layoutCanvas(); sync(); draw(); });
    if (!M.ro && window.ResizeObserver) {  // a área da prévia muda de tamanho sem a janela mudar (celular, gavetas)
      M.ro = new ResizeObserver(() => { if (M.open) { layoutCanvas(); draw(); } });
      M.ro.observe($(".mt-canvas-wrap", box()));
    }
  }
  function close() { M.open = false; stop(); if (M.saveT) flush(); }

  function fitZoom() {
    const sc = $(".mt-scroll", box());
    const w = Math.max(300, (sc ? sc.clientWidth : 900) - headW() - 40);
    const d = Math.max(10, total() || 30);
    return clamp(w / d, 0.5, 400);
  }

  /* ---------------- tela ---------------- */

  function build() {
    M.built = true;
    box().innerHTML = `
      <aside class="mt-lib mt-sheet" data-sheet="lib">
        <div class="mt-sheet-head"><b>Biblioteca</b><button class="btn icon small ghost" data-close-sheet aria-label="Fechar">${ico(I.x)}</button></div>
        <div class="seg full small mt-tabs" role="tablist">
          <button class="seg-btn active" data-tab="midias">Mídias</button>
          <button class="seg-btn" data-tab="textos">Textos</button>
          <button class="seg-btn" data-tab="fundos">Fundos</button>
          <button class="seg-btn" data-tab="tarjas">Tarjas</button>
          <button class="seg-btn" data-tab="musicas">Músicas</button>
        </div>
        <div class="mt-tab" data-tab="midias">
          <label class="btn primary mt-upbtn">${ico(I.up)} Enviar vídeo, foto ou música
            <input type="file" multiple hidden accept="video/*,image/*,audio/*,.mov,.mkv,.mp3,.m4a,.wav"></label>
          <p class="hint">Toque numa mídia para colocar no cursor, ou arraste para a linha do tempo.</p>
          <div class="mt-uploads"></div>
          <div class="mt-media"></div>
        </div>
        <div class="mt-tab hidden" data-tab="textos">
          <p class="hint">Toque para colocar no cursor. Depois edite o texto em Ajustes.</p>
          <div class="mt-presets">${TEXTOS.map((p, i) => `<button class="mt-preset" data-preset="${i}">
            <span class="pv" style="font-family:'${p.it.font}';color:${p.it.color || "#fff"};${p.it.boxOn ? `background:${p.it.box || "#000"}` : ""}">${esc(p.it.text.split("\n")[0])}</span>
            <b>${esc(p.nome)}</b><span class="hint">${esc(p.desc)}</span></button>`).join("")}</div>
        </div>
        <div class="mt-tab hidden" data-tab="fundos">
          <p class="hint">Cor sólida no fundo (por baixo de tudo) ou como faixa. Toque para colocar no cursor.</p>
          <div class="mt-swatches">${CORES_FUNDO.map((c) => `<button class="mt-sw" data-color="${c}" style="background:${c}" aria-label="Cor ${c}"></button>`).join("")}</div>
          <label class="field-inline">Outra cor <input type="color" class="mt-swcustom" value="#2B2D35"></label>
          <p class="hint">Bancos de vídeos e fotos livres (Pexels e Pixabay) chegam na próxima fase.</p>
        </div>
        <div class="mt-tab hidden" data-tab="tarjas">
          <p class="hint">Tarjas com nome, cargo, versículo, redes sociais… Escolha as cores e o tempo, e toque no modelo para colocar no cursor.</p>
          <label class="mt-f"><span>Linha 1</span><input type="text" class="mt-tj-l1" maxlength="120" placeholder="Nome (ou deixe o do modelo)"></label>
          <label class="mt-f"><span>Linha 2</span><input type="text" class="mt-tj-l2" maxlength="120" placeholder="Cargo, igreja, @perfil…"></label>
          <div class="mt-tj-pals"></div>
          <div class="mt-f"><span>Fica na tela por</span><div class="seg small mt-tj-durs">${[5, 10, 15].map((d) => `<button class="seg-btn ${d === 5 ? "active" : ""}" data-tjdur="${d}">${d} s</button>`).join("")}</div></div>
          <div class="mt-tj-grid"><p class="hint">Carregando modelos…</p></div>
        </div>
        <div class="mt-tab hidden" data-tab="musicas">
          <form class="mt-msearch"><input type="search" placeholder="Buscar música (ex.: piano, calmo, épico)" maxlength="80"><button class="btn small" type="submit">Buscar</button></form>
          <div class="mt-moods"></div>
          <p class="hint">Músicas livres (Creative Commons) que podem ser usadas em vídeos, inclusive monetizados. Quando pedir crédito, o texto pronto fica no Ajustes da música para colar na descrição.</p>
          <div class="mt-mlist"></div>
          <div class="panel-title">Minhas músicas</div>
          <div class="mt-mine"><p class="hint">Carregando…</p></div>
        </div>
      </aside>

      <main class="mt-stage">
        <div class="mt-canvas-wrap"><canvas class="mt-canvas" aria-label="Prévia da montagem"></canvas></div>
        <div class="mt-transport">
          <button class="btn icon round mt-play" aria-label="Tocar ou pausar">${ico(I.play, 14)}</button>
          <span class="mono mt-time">0:00,0 / 0:00</span>
          <div class="grow"></div>
          <span class="hint mt-save"></span>
        </div>
      </main>

      <aside class="mt-props panel mt-sheet" data-sheet="props"></aside>

      <section class="mt-bottom">
        <div class="mt-toolbar">
          <button class="btn icon small ghost" data-act="undo" title="Desfazer (Ctrl+Z)" aria-label="Desfazer">${ico(I.undo)}</button>
          <button class="btn icon small ghost" data-act="redo" title="Refazer (Ctrl+Y)" aria-label="Refazer">${ico(I.redo)}</button>
          <span class="mt-sep"></span>
          <button class="btn small ghost" data-act="split" title="Dividir no cursor (S)">${ico(I.split)}<span class="lbl">Dividir</span></button>
          <button class="btn small ghost" data-act="dup" title="Duplicar (Ctrl+D)">${ico(I.copy)}<span class="lbl">Duplicar</span></button>
          <button class="btn small ghost" data-act="del" title="Apagar (Delete)">${ico(I.trash)}<span class="lbl">Apagar</span></button>
          <span class="mt-sep"></span>
          <button class="btn small ghost mt-snap on" data-act="snap" title="Ímã: encaixa nos cortes e mantém a trilha principal sem buracos">${ico(I.magnet)}<span class="lbl">Ímã</span></button>
          <div class="menu-wrap">
            <button class="btn small ghost" data-act="addtrack">${ico(I.plus)}<span class="lbl">Trilha</span></button>
            <div class="menu hidden mt-trackmenu">
              <a data-newtrack="video">Trilha de vídeo / imagem</a><a data-newtrack="text">Trilha de texto</a><a data-newtrack="audio">Trilha de áudio</a>
            </div>
          </div>
          <div class="grow"></div>
          <button class="btn icon small ghost" data-act="zout" aria-label="Diminuir zoom">${ico(I.zout)}</button>
          <button class="btn icon small ghost" data-act="zfit" aria-label="Caber tudo">${ico(I.fit)}</button>
          <button class="btn icon small ghost" data-act="zin" aria-label="Aumentar zoom">${ico(I.zin)}</button>
          <button class="btn small primary mt-export" data-act="export">${ico(I.download)}<span class="lbl">Exportar</span></button>
        </div>
        <div class="mt-scroll">
          <div class="mt-inner">
            <div class="mt-rulerrow"><div class="mt-corner"><span class="hint mt-dur"></span></div><div class="mt-ruler"></div></div>
            <div class="mt-rows"></div>
            <div class="mt-ph"><i></i></div>
          </div>
        </div>
      </section>

      <nav class="mt-mobilebar">
        <button data-sheet-open="lib" data-tabgo="midias">${ico(I.film, 20)}<span>Mídias</span></button>
        <button data-sheet-open="lib" data-tabgo="textos">${ico(I.text, 20)}<span>Texto</span></button>
        <button data-sheet-open="lib" data-tabgo="fundos">${ico(I.fill, 20)}<span>Fundos</span></button>
        <button data-sheet-open="lib" data-tabgo="tarjas">${ico(I.text, 20)}<span>Tarjas</span></button>
        <button data-sheet-open="lib" data-tabgo="musicas">${ico(I.music, 20)}<span>Músicas</span></button>
        <button data-sheet-open="props">${ico(I.sliders, 20)}<span>Ajustes</span></button>
      </nav>
      <div class="mt-backdrop"></div>`;
    wire();
  }

  function wire() {
    const B = box();
    $$(".mt-tabs .seg-btn", B).forEach((b) => b.addEventListener("click", () => tab(b.dataset.tab)));
    $(".mt-upbtn input", B).addEventListener("change", (e) => { [...e.target.files].forEach(upload); e.target.value = ""; });
    $$("[data-preset]", B).forEach((b) => b.addEventListener("click", () => { addText(TEXTOS[+b.dataset.preset].it); closeSheets(); }));
    $$("[data-color]", B).forEach((b) => b.addEventListener("click", () => { addColor(b.dataset.color); closeSheets(); }));
    $(".mt-swcustom", B).addEventListener("change", (e) => { addColor(e.target.value.toUpperCase()); closeSheets(); });
    wireTarjas(B);
    wireMusicas(B);
    $(".mt-play", B).addEventListener("click", toggle);
    $$("[data-act]", B).forEach((b) => b.addEventListener("click", (e) => act(b.dataset.act, e)));
    $$("[data-newtrack]", B).forEach((a) => a.addEventListener("click", () => {
      const before = snapshot(); const k = a.dataset.newtrack;
      newTrack(k, k === "audio" ? M.m.tracks.length : 0); $(".mt-trackmenu", B).classList.add("hidden"); commit(before);
    }));
    document.addEventListener("click", (e) => { if (!e.target.closest || !e.target.closest(".mt-toolbar .menu-wrap")) { const mm = $(".mt-trackmenu", B); if (mm) mm.classList.add("hidden"); } });
    $$("[data-sheet-open]", B).forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.tabgo) tab(b.dataset.tabgo);
      openSheet(b.dataset.sheetOpen);
    }));
    $$("[data-close-sheet]", B).forEach((b) => b.addEventListener("click", closeSheets));
    $(".mt-backdrop", B).addEventListener("click", closeSheets);
    // linha do tempo
    const sc = $(".mt-scroll", B);
    $(".mt-ruler", B).addEventListener("pointerdown", scrubStart);
    $(".mt-rows", B).addEventListener("pointerdown", rowsDown);
    sc.addEventListener("wheel", (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      zoomAround(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.clientX);
    }, { passive: false });
    sc.addEventListener("scroll", () => { if (!M.playing) return; M.follow = false; clearTimeout(M.followT); M.followT = setTimeout(() => (M.follow = true), 1500); });
    // prévia
    const cv = $(".mt-canvas", B);
    cv.addEventListener("pointerdown", canvasDown);
    window.addEventListener("resize", () => { if (M.open) { layoutCanvas(); draw(); renderTimeline(); } });
    document.addEventListener("keydown", keys);
    // soltar arquivos direto na montagem
    B.addEventListener("dragover", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { e.preventDefault(); B.classList.add("drop"); } });
    B.addEventListener("dragleave", (e) => { if (e.target === B) B.classList.remove("drop"); });
    B.addEventListener("drop", (e) => { if (!e.dataTransfer || !e.dataTransfer.files.length) return; e.preventDefault(); B.classList.remove("drop"); [...e.dataTransfer.files].forEach(upload); });
  }

  function tab(name) {
    $$(".mt-tabs .seg-btn", box()).forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    $$(".mt-tab", box()).forEach((t) => t.classList.toggle("hidden", t.dataset.tab !== name));
  }
  function openSheet(name) { box().classList.add("sheet-open"); $$(".mt-sheet", box()).forEach((s) => s.classList.toggle("open", s.dataset.sheet === name)); }
  function closeSheets() { box().classList.remove("sheet-open"); $$(".mt-sheet", box()).forEach((s) => s.classList.remove("open")); }

  function renderAll() {
    if (!M.m) return;
    renderMedia(); renderTimeline(); renderProps(); draw(); updateTime();
    $(".mt-snap", box()).classList.toggle("on", M.snap);
    $("[data-act=undo]", box()).disabled = !M.hist.length;
    $("[data-act=redo]", box()).disabled = !M.fut.length;
  }

  /* ---------------- biblioteca de mídias ---------------- */

  function renderMedia() {
    const el = $(".mt-media", box());
    const list = M.m.media || [];
    if (!list.length) { el.innerHTML = `<div class="mt-empty">Nenhuma mídia ainda. Envie vídeos, fotos ou músicas para montar.</div>`; return; }
    el.innerHTML = list.map((x) => {
      const icon = x.kind === "audio" ? I.music : x.kind === "image" ? I.img : I.film;
      const thumb = x.kind !== "audio" && x.preview ? `<img src="${urlMidia(x.id)}/thumb?t=${x.kind === "video" ? Math.min(2, (x.duration || 0) / 3).toFixed(1) : 0}" alt="" loading="lazy" onerror="this.remove()">` : "";
      const info = x.kind === "image" ? `${x.w}×${x.h}` : fmt(x.duration);
      return `<div class="mt-mi ${x.main ? "main" : ""}" data-mid="${x.id}" title="${esc(x.name)}">
        <div class="th">${thumb}<span class="ic">${ico(icon, 18)}</span>${!x.preview ? `<span class="prep">preparando prévia…</span>` : ""}</div>
        <div class="nm">${esc(x.name)}</div><div class="hint">${x.main ? "vídeo do projeto · " : ""}${info}</div>
        ${x.main ? "" : `<button class="mt-mi-del" data-delmid="${x.id}" aria-label="Remover mídia">${ico(I.x, 12)}</button>`}
      </div>`;
    }).join("");
    $$(".mt-mi", el).forEach((card) => {
      card.addEventListener("pointerdown", (e) => libDown(e, card.dataset.mid));
    });
    $$("[data-delmid]", el).forEach((b) => {
      b.addEventListener("pointerdown", (e) => e.stopPropagation());
      b.addEventListener("click", async (e) => {
        e.stopPropagation();
        const x = media(b.dataset.delmid);
        if (!confirm(`Remover "${x.name}" do projeto? Os pedaços dela na linha do tempo também saem.`)) return;
        await flush();
        try { const r = await api("DELETE", `/api/projects/${M.pid}/midias/${x.id}`); M.m.items = r.items; M.m.media = r.media; clearPool(); renderAll(); }
        catch (err) { toast(err.message, true); }
      });
    });
  }

  function upload(file) {
    const wrap = $(".mt-uploads", box());
    const row = document.createElement("div");
    row.className = "mt-upl";
    row.innerHTML = `<span class="nm">${esc(file.name)}</span><span class="hint pct">0%</span><div class="bar"><i></i></div>`;
    wrap.appendChild(row);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/projects/${M.pid}/midias`);
    xhr.setRequestHeader("x-filename", encodeURIComponent(file.name));
    xhr.upload.onprogress = (e) => { if (!e.lengthComputable) return; const p = e.loaded / e.total; $("i", row).style.width = (p * 100).toFixed(1) + "%"; $(".pct", row).textContent = Math.round(p * 100) + "%" + (p >= 1 ? " · conferindo…" : ""); };
    xhr.onload = () => {
      row.remove();
      if (xhr.status >= 200 && xhr.status < 300) {
        const it = JSON.parse(xhr.responseText);
        if (!media(it.id)) M.m.media.push(it);
        renderMedia(); toast(`"${it.name}" pronto na biblioteca`);
        checkProxies();
      } else {
        let msg = xhr.statusText; try { msg = JSON.parse(xhr.responseText).detail; } catch (_) {}
        toast(`${file.name}: ${msg}`, true);
      }
    };
    xhr.onerror = () => { row.remove(); toast("Falha de conexão no envio de " + file.name, true); };
    xhr.send(file);
  }

  function checkProxies() {
    clearInterval(M.proxyPoll);
    if (!(M.m.media || []).some((x) => !x.preview)) return;
    M.proxyPoll = setInterval(async () => {
      if (!M.pid) return;
      try {
        const r = await api("GET", `/api/projects/${M.pid}/montagem`);
        const antes = JSON.stringify(M.m.media.map((x) => x.preview));
        M.m.media = r.media;
        if (JSON.stringify(M.m.media.map((x) => x.preview)) !== antes) { clearPool(); renderMedia(); renderTimeline(); draw(); }
        if (!M.m.media.some((x) => !x.preview)) clearInterval(M.proxyPoll);
      } catch (_) {}
    }, 3000);
  }

  /** Arrastar da biblioteca para a linha do tempo (mouse e dedo). Um toque sem arrastar coloca no cursor. */
  function libDown(e, mid) {
    if (e.button && e.button !== 0) return;
    const x0 = e.clientX, y0 = e.clientY;
    let ghost = null;
    const mv = (ev) => {
      if (!ghost && Math.hypot(ev.clientX - x0, ev.clientY - y0) > 8 && ev.pointerType === "mouse") {
        const md = media(mid);
        ghost = document.createElement("div"); ghost.className = "mt-ghost"; ghost.textContent = md.name; document.body.appendChild(ghost);
      }
      if (ghost) { ghost.style.left = ev.clientX + 8 + "px"; ghost.style.top = ev.clientY + 8 + "px"; }
    };
    const up = (ev) => {
      window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up);
      if (ghost) {
        ghost.remove();
        const lane = document.elementFromPoint(ev.clientX, ev.clientY);
        const row = lane && lane.closest && lane.closest(".mt-row");
        if (row) {
          const rect = $(".mt-lane", row).getBoundingClientRect();
          addMedia(mid, q(Math.max(0, (ev.clientX - rect.left) / M.pps)), row.dataset.track);
        }
      } else if (Math.hypot(ev.clientX - x0, ev.clientY - y0) < 8) { addMedia(mid, M.t); closeSheets(); }
    };
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
  }

  function addMedia(mid, at, trackId) {
    const md = media(mid); if (!md) return;
    if (!md.preview && md.kind === "video") toast("A prévia desse vídeo ainda está sendo preparada; ele já pode ser montado e exportado.");
    const before = snapshot();
    const kind = md.kind === "audio" ? "audio" : md.kind === "image" ? "image" : "video";
    const dur = kind === "image" ? 5 : Math.max(1 / fps(), md.duration || 5);
    const it = { id: uid("i"), type: kind, track: null, src: mid, start: q(at), dur: q(dur), in: 0, x: 0.5, y: 0.5, scale: 1,
      rot: 0, opacity: 1, volume: 1, fadeIn: 0, fadeOut: 0, speed: 1, fit: kind === "video" && !mainBusy(at) ? "cover" : "contain" };
    let pref = trackId;
    if (!pref || !ACEITA[(track(pref) || {}).kind || ""] || !ACEITA[track(pref).kind].includes(kind)) {
      if (kind === "audio") pref = (M.m.tracks.find((t) => t.kind === "audio") || {}).id;
      else if (kind === "video" && !mainBusy(at)) pref = mainTrack().id;
      else pref = (M.m.tracks.find((t) => t.kind === "video" && !t.main) || mainTrack() || {}).id;
    }
    M.m.items.push(it);
    place(it, pref);
    if (track(it.track).main) {  // na trilha principal entra no ponto do cursor, empurrando o resto
      const mt = track(it.track);
      M.m.items.filter((o) => o !== it && o.track === mt.id && o.start >= it.start - 1e-6).forEach((o) => (o.start += it.dur));
      const dentro = M.m.items.find((o) => o !== it && o.track === mt.id && o.start < it.start && o.start + o.dur > it.start);
      if (dentro) it.start = dentro.start + dentro.dur;
      compactMain();
    }
    M.sel = it.id;
    commit(before);
  }
  function mainBusy(at) { const mt = mainTrack(); return mt && M.m.items.some((i) => i.track === mt.id && i.start <= at + 1e-6 && at < i.start + i.dur); }

  function addText(preset) {
    const before = snapshot();
    const it = { id: uid("i"), type: "text", track: null, src: null, start: q(M.t), dur: 4, in: 0, x: 0.5, y: 0.5, scale: 1, rot: 0,
      opacity: 1, volume: 1, fadeIn: 0.25, fadeOut: 0.25, speed: 1, fit: "contain", text: "Texto", font: "Poppins ExtraBold",
      size: 0.07, color: "#FFFFFF", stroke: "#000000", strokeW: 0, box: "#000000", boxOn: false, boxAlpha: 0.6, upper: false,
      ...JSON.parse(JSON.stringify(preset)) };
    if (!M.m.tracks.some((t) => t.kind === "text")) newTrack("text", 0);
    M.m.items.push(it); place(it, M.m.tracks.find((t) => t.kind === "text").id);
    M.sel = it.id; commit(before);
    if (window.innerWidth <= 900) openSheet("props");
  }

  function addColor(color) {
    const before = snapshot();
    const fim = Math.max(5, total() - M.t);
    let fundo = M.m.tracks.filter((t) => t.kind === "video" && !t.main).pop();
    const mi = M.m.tracks.indexOf(mainTrack());
    // fundo vai numa trilha abaixo da principal; se não houver, cria
    if (!fundo || M.m.tracks.indexOf(fundo) < mi) fundo = newTrack("video", mi + 1), fundo.name = "Fundo";
    const it = { id: uid("i"), type: "color", track: null, src: null, start: q(M.t), dur: q(fim), in: 0, x: 0.5, y: 0.5, scale: 1,
      rot: 0, opacity: 1, volume: 1, fadeIn: 0, fadeOut: 0, speed: 1, fit: "contain", color, w: 1, h: 1 };
    M.m.items.push(it); place(it, fundo.id);
    M.sel = it.id; commit(before);
  }

  /* ---------------- tarjas (lower thirds) ---------------- */
  // Mesmas contas de backend/core/tarjas.py: o que aparece na prévia é o que sai no vídeo.
  const TJ_LARG = { "Poppins ExtraBold": 0.6, "Poppins": 0.58, "Anton": 0.44, "Bebas Neue": 0.38, "Archivo Black": 0.68 };
  const TJ_PAPEIS = ["c1", "c2", "t1", "t2"];
  const TJ = { spec: null, pal: "vox", dur: 5, l1: "", l2: "" };
  try { Object.assign(TJ, JSON.parse(localStorage.getItem("vox-tarjas") || "{}"), { spec: null }); } catch (_) {}
  const tjGuardar = () => { try { localStorage.setItem("vox-tarjas", JSON.stringify({ pal: TJ.pal, dur: TJ.dur, l1: TJ.l1, l2: TJ.l2 })); } catch (_) {} };
  function tjCabe(texto, tam, fonte, maxw) {
    const f = (TJ_LARG[fonte] || 0.6) * (texto === texto.toUpperCase() && /[A-ZÀ-Ý]/.test(texto) ? 1.12 : 1);
    const est = Math.max(1, texto.length) * tam * f;
    return est <= maxw ? tam : tam * maxw / est;
  }
  /** Desenha a tarja no tempo t (ou só mede, se ctx for null). Devolve a caixa [x0, y0, x1, y1] em pixels da tela. */
  function drawTarja(ctx, it, t, W, H, medir) {
    const S = TJ.spec; if (!S) return null;
    const mo = S.modelos.find((m) => m.id === it.tpl) || S.modelos[0];
    const ent = S.entrada, sai = S.saida, menor = Math.min(W, H) * (it.scale || 1);
    const sobe = H > W ? S.sobe_vertical || 0 : 0, A = S.ancora || 0.83;
    const ox = ((it.x ?? 0.5) - 0.5) * W, oy = ((it.y ?? 0.5) - 0.5) * H;
    const ypx = (y) => (A - sobe) * H + (y - A) * menor + oy;
    const cor = (c) => (TJ_PAPEIS.includes(c) ? it[c] : c) || "#FFFFFF";
    const lt = t - it.start, dur = it.dur;
    const bb = [Infinity, Infinity, -Infinity, -Infinity];
    const junta = (x0, y0, x1, y1) => { bb[0] = Math.min(bb[0], x0); bb[1] = Math.min(bb[1], y0); bb[2] = Math.max(bb[2], x1); bb[3] = Math.max(bb[3], y1); };
    const op = it.opacity ?? 1;
    const tela = ctx || document.createElement("canvas").getContext("2d");
    mo.camadas.forEach((c) => {
      const pin = clamp((lt - (c.atraso || 0)) / ent, 0, 1), pout = clamp((dur - lt) / sai, 0, 1);
      const anda = (1 - (1 - Math.pow(1 - pin, 3))) + (1 - (1 - Math.pow(1 - pout, 3)));
      const dx = (c.dx || 0) * W * anda, dy = (c.dy || 0) * H * anda;
      const a = op * Math.min(pin, pout);
      if (c.k === "r") {
        const w = Math.max(2, Math.round(c.w * (c.lw ? W : menor))), h = Math.max(2, Math.round(c.h * menor));
        const x = c.x * W + ox, y = ypx(c.y);
        junta(x, y, x + w, y + h);
        if (!medir && a > 0.001) { tela.globalAlpha = a * (c.alfa ?? 1); tela.fillStyle = cor(c.cor); tela.fillRect(x + dx, y + dy, w, h); }
        return;
      }
      let texto = (c.linha === 2 ? it.l2 : it.l1) || "";
      if (c.maius) texto = texto.toUpperCase();
      texto = texto.replace(/\r/g, "").split("\n")[0].trim();
      if (!texto) return;
      const bx = c.x * W + ox + (c.recuo || 0) * menor, centro = c.alinha === "centro";
      const tam = tjCabe(texto, c.tam * menor, c.fonte, centro ? W * 0.9 : Math.max(W * 0.2, W * 0.95 - bx));
      tela.font = `${tam}px "${c.fonte || "Poppins ExtraBold"}"`;
      const tw = tela.measureText(texto).width;
      const top = ypx(c.y) - tam / 2, x0 = centro ? bx - tw / 2 : bx;
      const pad = c.caixa ? Math.max(2, Math.round((c.pad ?? 0.28) * tam)) : 0;
      junta(x0 - pad, top - pad, x0 + tw + pad, top + tam + pad);
      if (medir || a <= 0.001) return;
      if (c.caixa) { tela.globalAlpha = a * (c.alfa ?? 1); tela.fillStyle = cor(c.caixa); tela.fillRect(x0 + dx - pad, top + dy - pad, tw + pad * 2, tam + pad * 2); }
      tela.globalAlpha = a; tela.textAlign = "left"; tela.textBaseline = "top";
      if (c.contorno) { tela.lineJoin = "round"; tela.lineWidth = Math.max(1, Math.round(c.contorno * tam)) * 2; tela.strokeStyle = "rgba(0,0,0,.85)"; tela.strokeText(texto, x0 + dx, top + dy); }
      tela.fillStyle = cor(c.cor); tela.fillText(texto, x0 + dx, top + dy);
    });
    return bb[0] === Infinity ? null : bb;
  }
  function tjPaleta(id) { return (TJ.spec.paletas.find((p) => p.id === id) || TJ.spec.paletas[0]); }
  function tjCartoes() {
    const grid = $(".mt-tj-grid", box()); if (!grid || !TJ.spec) return;
    const pal = tjPaleta(TJ.pal);
    $(".mt-tj-pals", box()).innerHTML = `<span class="hint">Cores</span>` + TJ.spec.paletas.map((p) => `<button class="mt-pal ${p.id === TJ.pal ? "on" : ""}" data-pal="${p.id}" title="${esc(p.nome)}" style="background:linear-gradient(135deg,${p.c1} 50%,${p.c2} 50%)"></button>`).join("");
    $$(".mt-tj-durs [data-tjdur]", box()).forEach((b) => b.classList.toggle("active", +b.dataset.tjdur === TJ.dur));
    if (!grid.querySelector("canvas")) {
      grid.innerHTML = TJ.spec.modelos.map((m) => `<button class="mt-tjcard" data-tpl="${m.id}"><canvas width="320" height="96"></canvas><b>${esc(m.nome)}</b></button>`).join("");
      $$("[data-tpl]", grid).forEach((b) => b.addEventListener("click", () => { addTarja(b.dataset.tpl); closeSheets(); }));
    }
    $$(".mt-tjcard", grid).forEach((card) => {
      const m = TJ.spec.modelos.find((x) => x.id === card.dataset.tpl);
      const cv = $("canvas", card), ctx = cv.getContext("2d");
      const W = 1920, H = 1080, k = cv.width / (W * 0.62);
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, cv.width, cv.height);
      const g = ctx.createLinearGradient(0, 0, cv.width, cv.height); g.addColorStop(0, "#3a4b5e"); g.addColorStop(1, "#1d2530");
      ctx.fillStyle = g; ctx.fillRect(0, 0, cv.width, cv.height);
      const fake = { tpl: m.id, start: 0, dur: 10, x: 0.5, y: 0.5, scale: 1, opacity: 1, l1: TJ.l1 || m.l1, l2: TJ.l2 || m.l2, ...Object.fromEntries(TJ_PAPEIS.map((c) => [c, pal[c]])) };
      const bb = drawTarja(null, fake, 5, W, H, true) || [0, H * 0.7, W, H * 0.95];
      const cx = m.camadas.some((c) => c.alinha === "centro") ? (bb[0] + bb[2]) / 2 - (cv.width / k) / 2 : Math.max(0, bb[0] - 40);
      ctx.setTransform(k, 0, 0, k, -cx * k, -((bb[1] + bb[3]) / 2) * k + cv.height / 2);
      drawTarja(ctx, fake, 5, W, H);
    });
  }
  async function wireTarjas(B) {
    const l1 = $(".mt-tj-l1", B), l2 = $(".mt-tj-l2", B);
    l1.value = TJ.l1 || ""; l2.value = TJ.l2 || "";
    [l1, l2].forEach((inp) => { inp.addEventListener("keydown", (e) => e.stopPropagation()); inp.addEventListener("input", () => { TJ.l1 = l1.value; TJ.l2 = l2.value; tjGuardar(); tjCartoes(); }); });
    $(".mt-tj-pals", B).addEventListener("click", (e) => { const b = e.target.closest("[data-pal]"); if (!b) return; TJ.pal = b.dataset.pal; tjGuardar(); tjCartoes(); });
    $$("[data-tjdur]", B).forEach((b) => b.addEventListener("click", () => { TJ.dur = +b.dataset.tjdur; tjGuardar(); tjCartoes(); }));
    try { TJ.spec = await (await fetch("tarjas.json", { cache: "no-cache" })).json(); }
    catch (_) { $(".mt-tj-grid", B).innerHTML = `<p class="err">Não consegui carregar os modelos de tarja.</p>`; return; }
    if (!TJ.spec.paletas.some((p) => p.id === TJ.pal)) TJ.pal = TJ.spec.paletas[0].id;
    tjCartoes();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { tjCartoes(); draw(); });
    draw();
  }
  function addTarja(tpl) {
    if (!TJ.spec) return;
    const m = TJ.spec.modelos.find((x) => x.id === tpl) || TJ.spec.modelos[0];
    const pal = tjPaleta(TJ.pal);
    const before = snapshot();
    const it = { id: uid("i"), type: "tarja", track: null, src: null, start: q(M.t), dur: TJ.dur || 5, in: 0, x: 0.5, y: 0.5, scale: 1,
      rot: 0, opacity: 1, volume: 1, fadeIn: 0, fadeOut: 0, speed: 1, fit: "contain", tpl: m.id,
      l1: TJ.l1 || m.l1, l2: TJ.l2 || m.l2, ...Object.fromEntries(TJ_PAPEIS.map((c) => [c, pal[c]])) };
    if (!M.m.tracks.some((t) => t.kind === "text")) newTrack("text", 0);
    M.m.items.push(it); place(it, M.m.tracks.find((t) => t.kind === "text").id);
    M.sel = it.id; commit(before);
    if (window.innerWidth <= 900) openSheet("props");
  }

  /* ---------------- músicas livres ---------------- */
  const MU = { audio: null, tocando: null, faixas: [], humor: "inspirador", q: "", pagina: 1 };
  function pararPrevia() { if (MU.audio) { MU.audio.pause(); } MU.tocando = null; $$(".mt-mplay", box()).forEach((b) => (b.innerHTML = ico(I.play, 12))); }
  function tocarPrevia(url, btn) {
    if (MU.tocando === url) { pararPrevia(); return; }
    pararPrevia();
    if (M.playing) stop();
    MU.audio = MU.audio || new Audio();
    MU.audio.src = url; MU.audio.volume = 0.8;
    MU.audio.play().then(() => { MU.tocando = url; btn.innerHTML = ico(I.pause, 12); }).catch(() => toast("Não consegui tocar a prévia dessa música.", true));
    MU.audio.onended = pararPrevia;
  }
  function linhaMusica(f) {
    const lic = { cc0: "Livre (CC0)", by: "CC BY", "by-sa": "CC BY-SA" }[f.license] || f.license;
    return `<div class="mt-mrow" data-tid="${esc(f.id)}">
      <button class="btn icon small mt-mplay" data-play="${esc(f.url)}" aria-label="Ouvir">${ico(I.play, 12)}</button>
      <div class="mt-minfo"><b>${esc(f.title || "Sem título")}</b><span class="hint">${esc(f.creator || "")}${f.duration ? " · " + fmt(f.duration) : ""} · <span class="mt-lic ${f.license}">${esc(lic)}</span></span></div>
      <button class="btn small primary" data-usar>Usar</button>
      <button class="btn icon small ghost" data-guardar title="Guardar nas minhas músicas" aria-label="Guardar nas minhas músicas">${ico(I.download, 14)}</button>
    </div>`;
  }
  async function buscarMusicas(mais) {
    const lista = $(".mt-mlist", box());
    if (!mais) { MU.pagina = 1; MU.faixas = []; lista.innerHTML = `<p class="hint">Buscando…</p>`; }
    let r;
    try { r = await api("GET", `/api/trilhas?q=${encodeURIComponent(MU.q)}&humor=${encodeURIComponent(MU.q ? "" : MU.humor)}&pagina=${MU.pagina}`); }
    catch (e) { lista.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
    MU.faixas = MU.faixas.concat(r.faixas);
    lista.innerHTML = MU.faixas.length ? MU.faixas.map(linhaMusica).join("") + (r.mais ? `<button class="btn small ghost mt-mmais">Mais músicas</button>` : "")
      : `<p class="hint">Nenhuma música encontrada. Tente outra palavra (em inglês costuma achar mais: piano, calm, epic).</p>`;
    const mm = $(".mt-mmais", lista); if (mm) mm.addEventListener("click", () => { MU.pagina++; buscarMusicas(true); });
  }
  async function minhasMusicas() {
    const el = $(".mt-mine", box()); if (!el) return;
    let ls = [];
    try { ls = await api("GET", "/api/musicas"); } catch (_) {}
    el.innerHTML = ls.length ? ls.map((x) => `<div class="mt-mrow" data-minha="${esc(x.nome)}">
        <button class="btn icon small mt-mplay" data-play="/api/musicas/${encodeURIComponent(x.nome)}" aria-label="Ouvir">${ico(I.play, 12)}</button>
        <div class="mt-minfo"><b>${esc(x.nome.replace(/\.[^.]+$/, ""))}</b><span class="hint">${fmt(x.duracao)}</span></div>
        <button class="btn small" data-usar-minha>Usar</button></div>`).join("")
      : `<p class="hint">Nenhuma ainda. Guarde as que gostar aqui em cima, ou envie as suas em Marca.</p>`;
  }
  async function usarMusica(caminho, rotulo) {
    toast(`Baixando "${rotulo}"…`);
    let md;
    try { md = await api("POST", caminho); } catch (e) { toast(e.message, true); return; }
    if (!media(md.id)) M.m.media.push(md);
    renderMedia();
    addMedia(md.id, M.t);
    const it = itemById(M.sel);
    if (it && it.type === "audio") { it.volume = 0.25; it.duck = true; save(); renderProps(); }
    toast(md.credito ? "Música na trilha de áudio. O crédito para a descrição está em Ajustes." : "Música na trilha de áudio, baixinha e abaixando quando alguém fala.");
  }
  function wireMusicas(B) {
    const moods = $(".mt-moods", B);
    const pintar = () => $$("[data-humor]", moods).forEach((b) => b.classList.toggle("active", !MU.q && b.dataset.humor === MU.humor));
    api("GET", "/api/trilhas/humores").then((hs) => {
      moods.innerHTML = hs.map((h) => `<button class="chip-btn" data-humor="${h.id}">${esc(h.nome)}</button>`).join("");
      pintar();
    }).catch(() => {});
    moods.addEventListener("click", (e) => { const b = e.target.closest("[data-humor]"); if (!b) return; MU.humor = b.dataset.humor; MU.q = ""; $(".mt-msearch input", B).value = ""; pintar(); buscarMusicas(); });
    const inp = $(".mt-msearch input", B);
    inp.addEventListener("keydown", (e) => e.stopPropagation());
    $(".mt-msearch", B).addEventListener("submit", (e) => { e.preventDefault(); MU.q = inp.value.trim(); pintar(); buscarMusicas(); });
    let carregou = false;
    $$('.mt-tabs [data-tab="musicas"], [data-tabgo="musicas"]', B).forEach((b) => b.addEventListener("click", () => {
      if (carregou) return; carregou = true; buscarMusicas(); minhasMusicas();
    }));
    const tab = $('.mt-tab[data-tab="musicas"]', B);
    tab.addEventListener("click", async (e) => {
      const pl = e.target.closest("[data-play]"); if (pl) { tocarPrevia(pl.dataset.play, pl); return; }
      const row = e.target.closest(".mt-mrow"); if (!row) return;
      if (e.target.closest("[data-usar]")) {
        const f = MU.faixas.find((x) => x.id === row.dataset.tid); pararPrevia(); closeSheets();
        usarMusica(`/api/projects/${M.pid}/trilhas/${encodeURIComponent(row.dataset.tid)}`, f ? f.title : "música");
      } else if (e.target.closest("[data-usar-minha]")) {
        pararPrevia(); closeSheets();
        usarMusica(`/api/projects/${M.pid}/minhas-musicas/${encodeURIComponent(row.dataset.minha)}`, row.dataset.minha);
      } else if (e.target.closest("[data-guardar]")) {
        try { const r = await api("POST", `/api/trilhas/${encodeURIComponent(row.dataset.tid)}/guardar`); toast(`Guardada em Minhas músicas: ${r.nome}`); minhasMusicas(); }
        catch (err) { toast(err.message, true); }
      }
    });
  }
  /** Prévia: a música marcada "abaixar quando falam" fica baixinha enquanto toca um vídeo com som. */
  function duckK(it, t) {
    if (!it.duck) return 1;
    const fala = M.m.items.some((o) => o !== it && (o.type === "video" || (o.type === "audio" && !o.duck)) && o.start <= t && t < o.start + o.dur
      && o.volume > 0.01 && !(track(o.track) || {}).muted && (media(o.src) || {}).has_audio !== false);
    return fala ? 0.3 : 1;
  }

  /* ---------------- linha do tempo ---------------- */

  function renderTimeline() {
    const B = box(); if (!M.m) return;
    const dur = Math.max(total(), 5);
    const sc = $(".mt-scroll", B);
    const laneW = Math.max((dur + Math.max(10, dur * 0.25)) * M.pps, (sc.clientWidth || 800) - headW());
    $(".mt-inner", B).style.width = headW() + laneW + "px";
    $(".mt-dur", B).textContent = fmt(total());
    // régua
    const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];
    const step = steps.find((s) => s * M.pps >= 64) || 3600;
    const n = Math.ceil(laneW / M.pps / step);
    let r = "";
    for (let i = 0; i <= n; i++) {
      const t = i * step;
      r += `<span class="tk" style="left:${(t * M.pps).toFixed(1)}px">${step < 1 ? fmt(t, true) : fmt(t)}</span>`;
    }
    $(".mt-ruler", B).style.width = laneW + "px";
    $(".mt-ruler", B).innerHTML = r;
    // trilhas
    const rows = M.m.tracks.map((t) => {
      const its = M.m.items.filter((i) => i.track === t.id);
      return `<div class="mt-row k-${t.kind} ${t.main ? "main" : ""} ${t.locked ? "locked" : ""} ${t.hidden ? "off" : ""}" data-track="${t.id}" style="height:${ALTURA[t.kind]}px">
        <div class="mt-head">
          <span class="tn" title="Dois cliques para renomear">${esc(t.name)}${t.main ? ' <i class="main-tag">principal</i>' : ""}</span>
          <span class="tb">
            ${t.kind !== "audio" ? `<button data-th="hidden" aria-label="Esconder trilha" title="Mostrar/esconder">${ico(t.hidden ? I.eyeoff : I.eye, 14)}</button>` : ""}
            ${t.kind !== "text" ? `<button data-th="muted" aria-label="Silenciar trilha" title="Som ligado/desligado">${ico(t.muted ? I.mute : I.vol, 14)}</button>` : ""}
            <button data-th="locked" aria-label="Travar trilha" title="Travar/destravar">${ico(t.locked ? I.lock : I.unlock, 14)}</button>
          </span>
        </div>
        <div class="mt-lane" style="width:${laneW}px">${its.map(itemHTML).join("")}</div>
      </div>`;
    }).join("");
    $(".mt-rows", B).innerHTML = rows;
    $$(".mt-row", B).forEach((row) => {
      const t = track(row.dataset.track);
      $$("[data-th]", row).forEach((b) => b.addEventListener("click", (e) => {
        e.stopPropagation(); const before = snapshot(); t[b.dataset.th] = !t[b.dataset.th]; commit(before);
      }));
      $(".tn", row).addEventListener("dblclick", () => {
        const nome = prompt("Nome da trilha", t.name);
        if (nome && nome.trim()) { const before = snapshot(); t.name = nome.trim().slice(0, 40); commit(before); }
      });
      $(".mt-head", row).addEventListener("contextmenu", (e) => {
        e.preventDefault();
        if (t.main) return toast("A trilha principal não pode ser removida.");
        if (M.m.items.some((i) => i.track === t.id)) return toast("Esvazie a trilha antes de removê-la.");
        if (confirm(`Remover a trilha "${t.name}"?`)) { const before = snapshot(); M.m.tracks = M.m.tracks.filter((x) => x !== t); commit(before); }
      });
    });
    placePlayhead();
  }

  function itemHTML(it) {
    const w = Math.max(3, it.dur * M.pps);
    const md = it.src ? media(it.src) : null;
    let label = "", bg = "";
    if (it.type === "text") label = (it.text || "").replace(/\n/g, " ");
    else if (it.type === "tarja") label = "Tarja · " + (it.l1 || "");
    else if (it.type === "color") { label = "Cor"; bg = `background:${it.color}`; }
    else label = md ? md.name : "?";
    if ((it.type === "video" || it.type === "image") && md && md.preview && w > 36) {
      const tt = it.type === "video" ? Math.round(it.in / 15) * 15 : 0;
      bg = `background-image:url('${urlMidia(md.id)}/thumb?t=${tt}')`;
    }
    const extra = [it.speed !== 1 ? `${it.speed}×` : "", it.fadeIn ? "◢" : "", it.fadeOut ? "◣" : ""].filter(Boolean).join(" ");
    return `<div class="mt-item t-${it.type} ${M.sel === it.id ? "sel" : ""}" data-id="${it.id}" style="left:${(it.start * M.pps).toFixed(2)}px;width:${w.toFixed(2)}px;${bg}">
      <span class="h-l"></span><span class="lb">${w > 30 ? esc(label) : ""}${extra && w > 70 ? ` <i>${extra}</i>` : ""}</span><span class="h-r"></span></div>`;
  }

  function placePlayhead() {
    const ph = $(".mt-ph", box()); if (!ph) return;
    ph.style.left = headW() + M.t * M.pps + "px";
  }
  function followPlayhead() {
    const sc = $(".mt-scroll", box()); if (!sc || !M.follow) return;
    const x = M.t * M.pps, vis = sc.clientWidth - headW();
    if (x < sc.scrollLeft || x > sc.scrollLeft + vis - 40) sc.scrollLeft = Math.max(0, x - vis * 0.2);
  }
  function zoomAround(f, clientX) {
    const sc = $(".mt-scroll", box());
    const rect = sc.getBoundingClientRect();
    const px = clientX != null ? clientX - rect.left - headW() : (M.t * M.pps - sc.scrollLeft);
    const tAt = (sc.scrollLeft + px) / M.pps;
    M.pps = clamp(M.pps * f, 0.3, 600);
    renderTimeline();
    sc.scrollLeft = Math.max(0, tAt * M.pps - px);
  }

  function scrubStart(e) {
    const lane = $(".mt-ruler", box()).getBoundingClientRect();
    const set = (ev) => { seek(q(Math.max(0, (ev.clientX - lane.left) / M.pps))); };
    set(e);
    const mv = (ev) => set(ev);
    const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
  }

  function rowsDown(e) {
    const itEl = e.target.closest(".mt-item");
    if (!itEl) {  // espaço vazio: tira a seleção e leva o cursor
      if (e.target.closest(".mt-head")) return;
      const lane = e.target.closest(".mt-lane");
      if (lane && e.pointerType === "mouse") {
        const r = lane.getBoundingClientRect();
        seek(q(Math.max(0, (e.clientX - r.left) / M.pps)));
      }
      if (M.sel) { M.sel = null; renderTimeline(); renderProps(); draw(); }
      return;
    }
    const it = itemById(itEl.dataset.id);
    const tr = track(it.track);
    const wasSel = M.sel === it.id;
    if (!wasSel) { M.sel = it.id; $$(".mt-item.sel", box()).forEach((x) => x.classList.remove("sel")); itEl.classList.add("sel"); renderProps(); draw(); }
    if (tr.locked) return;
    if (e.pointerType !== "mouse" && !wasSel) return;  // no celular: primeiro toque seleciona, o segundo arrasta
    e.preventDefault();
    const mode = e.target.classList.contains("h-l") ? "l" : e.target.classList.contains("h-r") ? "r" : "move";
    M.drag = { mode, it, el: itEl, x0: e.clientX, y0: e.clientY, orig: { ...it }, before: snapshot(), moved: false, pointer: e.pointerId };
    itEl.setPointerCapture(e.pointerId);
    itEl.addEventListener("pointermove", dragMove);
    itEl.addEventListener("pointerup", dragEnd);
    itEl.addEventListener("pointercancel", dragEnd);
  }

  function snapTime(t, self, alsoEnd = 0) {
    if (!M.snap) return t;
    const thr = 8 / M.pps;
    const pts = [0, M.t];
    M.m.items.forEach((o) => { if (o.id !== self) pts.push(o.start, o.start + o.dur); });
    let best = t, bd = thr;
    pts.forEach((p) => {
      if (Math.abs(p - t) < bd) { bd = Math.abs(p - t); best = p; }
      if (alsoEnd && Math.abs(p - (t + alsoEnd)) < bd) { bd = Math.abs(p - (t + alsoEnd)); best = p - alsoEnd; }
    });
    return best;
  }

  function dragMove(e) {
    const d = M.drag; if (!d) return;
    const dx = (e.clientX - d.x0) / M.pps;
    if (!d.moved && Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 3) return;
    d.moved = true;
    const it = d.it, o = d.orig, md = it.src ? media(it.src) : null;
    const maxSrc = md && (it.type === "video" || it.type === "audio") ? md.duration : Infinity;
    if (d.mode === "move") {
      it.start = q(Math.max(0, snapTime(o.start + dx, it.id, it.dur)));
      d.el.style.left = it.start * M.pps + "px";
      d.el.style.transform = `translateY(${e.clientY - d.y0}px)`;
      d.el.classList.add("dragging");
    } else if (d.mode === "l") {
      let ns = snapTime(o.start + dx, it.id);
      const minStart = o.start + o.dur - 1 / fps();
      const lim = it.type === "video" || it.type === "audio" ? o.start - o.in / o.speed : -Infinity;
      ns = q(clamp(ns, Math.max(0, lim), minStart));
      const delta = ns - o.start;
      it.start = ns; it.dur = q(o.dur - delta);
      if (it.type === "video" || it.type === "audio") it.in = Math.max(0, +(o.in + delta * o.speed).toFixed(4));
      d.el.style.left = it.start * M.pps + "px"; d.el.style.width = Math.max(3, it.dur * M.pps) + "px";
    } else {
      let ne = snapTime(o.start + o.dur + dx, it.id);
      const maxEnd = o.start + (maxSrc - o.in) / o.speed;
      ne = clamp(ne, o.start + 1 / fps(), maxEnd);
      it.dur = q(ne - o.start);
      d.el.style.width = Math.max(3, it.dur * M.pps) + "px";
    }
    if (d.mode !== "move") seekQuiet(d.mode === "l" ? it.start : it.start + it.dur - 1 / fps());
    updateTime();
  }

  function dragEnd(e) {
    const d = M.drag; if (!d) return;
    M.drag = null;
    d.el.removeEventListener("pointermove", dragMove); d.el.removeEventListener("pointerup", dragEnd); d.el.removeEventListener("pointercancel", dragEnd);
    if (!d.moved) { if (e.pointerType === "mouse") seek(q(clamp(M.t, 0, total()))); return; }
    const it = d.it;
    if (d.mode === "move") {
      d.el.style.pointerEvents = "none";  // olha a trilha que está por baixo do pedaço arrastado
      const under = document.elementFromPoint(e.clientX, e.clientY);
      const row = under && under.closest && under.closest(".mt-row");
      const target = row ? track(row.dataset.track) : track(it.track);
      const from = track(d.orig.track);
      if (target && target.main && M.snap && ACEITA.video.includes(it.type)) {
        // reordena na trilha principal pelo ponto onde soltou
        it.track = target.id;
        const outros = M.m.items.filter((o) => o !== it && o.track === target.id).sort((a, b) => a.start - b.start);
        const meio = it.start + it.dur / 2;
        let t = 0; let posto = false;
        outros.forEach((o) => { if (!posto && meio < o.start + o.dur / 2) { it.start = t; t += it.dur; posto = true; } o.start = t; t += o.dur; });
        if (!posto) it.start = t;
      } else {
        it.track = null;
        place(it, target && ACEITA[target.kind].includes(it.type) ? target.id : from.id);
      }
    }
    compactMain();
    commit(d.before);
  }

  /* ---------------- ações ---------------- */

  function act(a, e) {
    if (a === "undo") undo();
    if (a === "redo") redo();
    if (a === "split") split();
    if (a === "dup") duplicate();
    if (a === "del") remove();
    if (a === "snap") { M.snap = !M.snap; $(".mt-snap", box()).classList.toggle("on", M.snap); toast(M.snap ? "Ímã ligado: encaixa nos cortes e fecha os buracos da trilha principal" : "Ímã desligado: posição livre"); }
    if (a === "zin") zoomAround(1.5);
    if (a === "zout") zoomAround(1 / 1.5);
    if (a === "zfit") { M.pps = fitZoom(); renderTimeline(); $(".mt-scroll", box()).scrollLeft = 0; }
    if (a === "addtrack") { e.stopPropagation(); $(".mt-trackmenu", box()).classList.toggle("hidden"); }
    if (a === "export") exportar();
  }

  function split() {
    const t = M.t;
    let alvos = M.sel ? [itemById(M.sel)] : itemsAt(t).filter((i) => track(i.track).main);
    alvos = alvos.filter((i) => i && i.start + 1 / fps() <= t && t <= i.start + i.dur - 1 / fps() && !track(i.track).locked);
    if (!alvos.length) return toast("Coloque o cursor em cima do pedaço que quer dividir.");
    const before = snapshot();
    alvos.forEach((it) => {
      const cut = q(t);
      const right = { ...JSON.parse(JSON.stringify(it)), id: uid("i"), start: cut, dur: q(it.start + it.dur - cut), fadeIn: 0 };
      if (it.type === "video" || it.type === "audio") right.in = +(it.in + (cut - it.start) * it.speed).toFixed(4);
      it.dur = q(cut - it.start); it.fadeOut = 0;
      M.m.items.push(right);
      M.sel = right.id;
    });
    commit(before);
  }
  function duplicate() {
    const it = itemById(M.sel); if (!it) return;
    const before = snapshot();
    const c = { ...JSON.parse(JSON.stringify(it)), id: uid("i"), start: q(it.start + it.dur) };
    M.m.items.push(c);
    if (track(it.track).main && M.snap) {
      M.m.items.filter((o) => o !== c && o !== it && o.track === it.track && o.start >= c.start - 1e-6).forEach((o) => (o.start += c.dur));
      c.track = it.track;
    } else place(c, it.track);
    compactMain();
    M.sel = c.id; commit(before);
  }
  function remove() {
    const it = itemById(M.sel); if (!it) return;
    if (track(it.track).locked) return toast("Essa trilha está travada.");
    const before = snapshot();
    M.m.items = M.m.items.filter((x) => x !== it);
    M.sel = null; compactMain(); commit(before);
  }

  async function recomecar() {
    if (!confirm("Recomeçar a montagem a partir da edição automática? Tudo o que foi montado aqui será trocado.")) return;
    try { await flush(); M.m = await api("POST", `/api/projects/${M.pid}/montagem/recomecar`, {}); M.hist = []; M.fut = []; M.sel = null; clearPool(); M.pps = fitZoom(); renderAll(); layoutCanvas(); draw(); toast("Montagem refeita a partir da edição automática"); }
    catch (e) { toast(e.message, true); }
  }

  /* ---------------- exportar ---------------- */

  async function exportar() {
    if (!M.m.items.length) return toast("A linha do tempo está vazia.");
    if (M.exportJob) return toast("Já existe uma exportação em andamento.");
    stop();
    clearTimeout(M.saveT);
    const btn = $(".mt-export", box());
    try {
      const P = await api("POST", `/api/projects/${M.pid}/montagem/exportar`, { montagem: M.m });
      const job = (P.jobs || []).find((j) => j.kind === "montagem" && j.status !== "concluido" && j.status !== "erro");
      M.exportJob = job ? job.id : "?";
      setSaveState("Salvo");
      toast("Exportação começou. Pode continuar editando.");
    } catch (e) { toast(e.message, true); return; }
    const tick = async () => {
      try {
        const js = await api("GET", `/api/jobs/${M.pid}`);
        const j = js.find((x) => x.id === M.exportJob) || js.find((x) => x.kind === "montagem");
        if (!j) { M.exportJob = null; return; }
        $(".lbl", btn).textContent = j.status === "na fila" ? "Na fila…" : `Exportando ${Math.round(j.pct * 100)}%`;
        btn.style.setProperty("--p", (j.pct * 100).toFixed(1) + "%"); btn.classList.add("busy");
        if (j.status === "concluido" || j.status === "erro") {
          M.exportJob = null; btn.classList.remove("busy"); $(".lbl", btn).textContent = "Exportar";
          if (j.status === "erro") toast("A exportação falhou: " + j.error, true);
          else { toast("Vídeo da montagem pronto! Está em Ajustes → Exportados e na página Exportados."); }
          try { M.P = await api("GET", `/api/projects/${M.pid}`); if (typeof S !== "undefined" && S.P && S.P.id === M.pid) S.P = M.P; } catch (_) {}
          renderProps();
          return;
        }
        setTimeout(tick, 1000);
      } catch (_) { setTimeout(tick, 2500); }
    };
    tick();
  }

  /* ---------------- painel de ajustes ---------------- */

  function renderProps() {
    const el = $(".mt-props", box()); if (!el || !M.m) return;
    const it = itemById(M.sel);
    const head = `<div class="mt-sheet-head"><b>Ajustes</b><button class="btn icon small ghost" data-close-sheet aria-label="Fechar">${ico(I.x)}</button></div>`;
    const rng = (k, label, min, max, step, val, unit = "", fmtv) => `
      <label class="mt-f"><span>${label}<b data-out="${k}">${fmtv ? fmtv(val) : val + unit}</b></span>
        <input type="range" data-k="${k}" min="${min}" max="${max}" step="${step}" value="${val}"></label>`;
    let html = head;
    if (!it) {
      html += `<div class="panel-title">Projeto</div>
        <label class="mt-f"><span>Formato do vídeo</span><select data-proj="formato">${Object.entries(FORMATOS).map(([k, v]) => `<option value="${k}" ${M.m.formato === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
        <label class="mt-f"><span>Quadros por segundo</span><select data-proj="fps">${[24, 25, 30, 60].map((f) => `<option ${M.m.fps === f ? "selected" : ""}>${f}</option>`).join("")}</select></label>
        <label class="mt-f row"><span>Cor do fundo</span><input type="color" data-proj="bg" value="${M.m.bg}"></label>
        <label class="mt-f"><span>Emendas da fala</span><select data-proj="suave">${[["suave", "Suaves (recomendado)"], ["bem_suave", "Bem suaves"], ["seca", "Secas (corte colado)"]].map(([v, n]) => `<option value="${v}" ${(M.m.suave || "suave") === v ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        ${(M.m.media || []).some((x) => x.main) && (M.P || {}).kind !== "montagem" ? `<button class="btn small" data-recomecar>Recomeçar da edição automática</button>` : ""}
        <div class="panel-title">Atalhos</div>
        <ul class="mt-keys hint">
          <li><kbd>Espaço</kbd> tocar / pausar</li><li><kbd>S</kbd> dividir no cursor</li><li><kbd>Delete</kbd> apagar</li>
          <li><kbd>Ctrl</kbd>+<kbd>Z</kbd> desfazer · <kbd>Ctrl</kbd>+<kbd>Y</kbd> refazer</li><li><kbd>Ctrl</kbd>+<kbd>D</kbd> duplicar</li>
          <li><kbd>←</kbd><kbd>→</kbd> um quadro · com <kbd>Shift</kbd> 1 segundo</li><li><kbd>Ctrl</kbd>+roda do mouse: zoom</li>
          <li>Clique direito no nome da trilha vazia: remover</li>
        </ul>`;
    } else {
      const md = it.src ? media(it.src) : null;
      const nome = { video: "Vídeo", image: "Imagem", text: "Texto", color: "Cor", audio: "Áudio", tarja: "Tarja" }[it.type];
      html += `<div class="panel-title">${nome}${md ? ` · <span class="mt-mname">${esc(md.name)}</span>` : ""}</div>
        <div class="hint">Começa em ${fmt(it.start, true)} · dura ${fmt(it.dur, true)}${md && it.type !== "image" ? ` · do original ${fmt(it.in, true)}` : ""}</div>
        <div class="row mt-pbtns">
          <button class="btn small" data-pact="split">${ico(I.split, 14)} Dividir</button>
          <button class="btn small" data-pact="dup">${ico(I.copy, 14)} Duplicar</button>
          <button class="btn small ghost danger" data-pact="del">${ico(I.trash, 14)} Apagar</button>
        </div>`;
      if (it.type === "text") {
        html += `<label class="mt-f"><span>Texto</span><textarea data-k="text" rows="3">${esc(it.text)}</textarea></label>
          <label class="mt-f"><span>Fonte</span><select data-k="font">${FONTES.map((f) => `<option ${it.font === f ? "selected" : ""} style="font-family:'${f}'">${f}</option>`).join("")}</select></label>
          ${rng("size", "Tamanho da letra", 0.02, 0.4, 0.005, it.size, "", (v) => Math.round(v * 1000) / 10 + "%")}
          <div class="row mt-colors">
            <label>Cor <input type="color" data-k="color" value="${it.color}"></label>
            <label>Contorno <input type="color" data-k="stroke" value="${it.stroke}"></label>
            <label class="chk"><input type="checkbox" data-k="upper" ${it.upper ? "checked" : ""}> MAIÚSCULAS</label>
          </div>
          ${rng("strokeW", "Espessura do contorno", 0, 0.2, 0.01, it.strokeW, "", (v) => Math.round(v * 100) + "%")}
          <div class="row mt-colors">
            <label class="chk"><input type="checkbox" data-k="boxOn" ${it.boxOn ? "checked" : ""}> Fundo atrás do texto</label>
            <label>Cor <input type="color" data-k="box" value="${it.box}"></label>
          </div>
          ${it.boxOn ? rng("boxAlpha", "Transparência do fundo", 0, 1, 0.05, it.boxAlpha, "", (v) => Math.round(v * 100) + "%") : ""}`;
      }
      if (it.type === "tarja" && TJ.spec) {
        html += `<label class="mt-f"><span>Modelo</span><select data-k="tpl">${TJ.spec.modelos.map((m) => `<option value="${m.id}" ${it.tpl === m.id ? "selected" : ""}>${esc(m.nome)}</option>`).join("")}</select></label>
          <label class="mt-f"><span>Linha 1</span><input type="text" data-k="l1" maxlength="120" value="${esc(it.l1 || "")}"></label>
          <label class="mt-f"><span>Linha 2</span><input type="text" data-k="l2" maxlength="120" value="${esc(it.l2 || "")}"></label>
          <div class="mt-f"><span>Cores prontas</span><div class="mt-tj-pals in">${TJ.spec.paletas.map((p) => `<button class="mt-pal" data-ppal="${p.id}" title="${esc(p.nome)}" style="background:linear-gradient(135deg,${p.c1} 50%,${p.c2} 50%)"></button>`).join("")}</div></div>
          <div class="row mt-colors">
            <label>Fundo <input type="color" data-k="c1" value="${it.c1}"></label>
            <label>Destaque <input type="color" data-k="c2" value="${it.c2}"></label>
            <label>Texto <input type="color" data-k="t1" value="${it.t1}"></label>
            <label>Texto 2 <input type="color" data-k="t2" value="${it.t2}"></label>
          </div>
          <div class="mt-f"><span>Fica na tela por</span><div class="seg small">${[5, 10, 15].map((d) => `<button class="seg-btn ${Math.abs(it.dur - d) < 0.01 ? "active" : ""}" data-pdur="${d}">${d} s</button>`).join("")}</div></div>
          <p class="hint">Arraste a tarja na prévia para mudar o lugar. Para um tempo livre, puxe a ponta dela na linha do tempo.</p>`;
      }
      if (it.type === "audio" && md) {
        html += `<label class="checkline"><input type="checkbox" data-k="duck" ${it.duck ? "checked" : ""}> Abaixar sozinha quando alguém fala</label>`;
        if (md.credito) html += `<div class="mt-credito"><span class="hint">Crédito obrigatório (cole na descrição do vídeo):</span><p>${esc(md.credito)}</p><button class="btn small" data-copiar-credito>Copiar crédito</button></div>`;
      }
      if (it.type === "color") {
        html += `<label class="mt-f row"><span>Cor</span><input type="color" data-k="color" value="${it.color}"></label>
          ${rng("w", "Largura", 0.05, 1, 0.01, it.w, "", (v) => Math.round(v * 100) + "%")}
          ${rng("h", "Altura", 0.02, 1, 0.01, it.h, "", (v) => Math.round(v * 100) + "%")}`;
      }
      if (it.type !== "audio") {
        html += `<div class="panel-title">Posição e tamanho</div>
          ${it.type === "video" || it.type === "image" ? `<div class="seg full small mt-fit"><button class="seg-btn ${it.fit !== "cover" ? "active" : ""}" data-fit="contain">Inteiro</button><button class="seg-btn ${it.fit === "cover" ? "active" : ""}" data-fit="cover">Preencher a tela</button></div>` : ""}
          ${rng("x", "Horizontal", -0.5, 1.5, 0.005, it.x, "", (v) => Math.round(v * 100) + "%")}
          ${rng("y", "Vertical", -0.5, 1.5, 0.005, it.y, "", (v) => Math.round(v * 100) + "%")}
          ${rng("scale", "Tamanho", 0.05, 4, 0.01, it.scale, "", (v) => Math.round(v * 100) + "%")}
          ${it.type !== "text" && it.type !== "tarja" ? rng("rot", "Giro", -180, 180, 1, it.rot, "°") : ""}
          ${rng("opacity", "Opacidade", 0, 1, 0.01, it.opacity, "", (v) => Math.round(v * 100) + "%")}
          <button class="btn small" data-pact="center">${ico(I.center, 14)} Centralizar e tamanho original</button>`;
      }
      if (it.type !== "tarja") html += `<div class="panel-title">Entrada e saída</div>
        ${rng("fadeIn", "Entrada suave", 0, 3, 0.05, it.fadeIn, "s")}
        ${rng("fadeOut", "Saída suave", 0, 3, 0.05, it.fadeOut, "s")}`;
      if (it.type === "video" || it.type === "audio") {
        html += `<div class="panel-title">Som e velocidade</div>
          ${md && (md.has_audio || it.type === "audio") ? rng("volume", "Volume", 0, 2, 0.01, it.volume, "", (v) => Math.round(v * 100) + "%") : `<p class="hint">Este vídeo não tem som.</p>`}
          <label class="mt-f"><span>Velocidade</span><select data-k="speed">${[0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4].map((s) => `<option value="${s}" ${it.speed === s ? "selected" : ""}>${s === 1 ? "Normal (1×)" : s + "×"}</option>`).join("")}</select></label>`;
      }
    }
    // exportados da montagem
    const rs = ((M.P || {}).renders || []).filter((r) => r.montagem);
    html += `<div class="panel-title">Exportados da montagem</div>` + (rs.length ? rs.slice(0, 6).map((r) => `
      <div class="render"><span class="name">${esc(r.label || r.file)}</span>
        <span class="hint">${fmt(r.duration)} · ${fmtSize(r.size)} · ${new Date(r.created * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
        <div class="row"><a class="btn small" href="/api/projects/${M.pid}/renders/${encodeURIComponent(r.file)}" download>Baixar</a>
        <button class="btn small primary" data-pub="${esc(r.file)}">Publicar</button></div></div>`).join("") : `<p class="hint">Quando exportar, o vídeo aparece aqui.</p>`);
    el.innerHTML = html;
    wireProps(el, it);
  }

  function showVal(k, v) {
    if (k === "size") return Math.round(v * 1000) / 10 + "%";
    if (k === "rot") return v + "°";
    if (k === "fadeIn" || k === "fadeOut") return String(v).replace(".", ",") + "s";
    return Math.round(v * 100) + "%";
  }

  function wireProps(el, it) {
    $$("[data-close-sheet]", el).forEach((b) => b.addEventListener("click", closeSheets));
    $$("[data-pub]", el).forEach((b) => b.addEventListener("click", () => {
      const r = M.P.renders.find((x) => x.file === b.dataset.pub);
      if (typeof openPublish === "function") openPublish({ ...r, project: M.pid, project_name: M.P.name });
    }));
    const rc = $("[data-recomecar]", el); if (rc) rc.addEventListener("click", recomecar);
    $$("[data-proj]", el).forEach((inp) => inp.addEventListener("change", () => {
      const before = snapshot(); const k = inp.dataset.proj;
      if (k === "formato") { M.m.formato = inp.value; [M.m.w, M.m.h] = DIM[inp.value]; }
      if (k === "fps") M.m.fps = +inp.value;
      if (k === "bg") M.m.bg = inp.value.toUpperCase();
      if (k === "suave") M.m.suave = inp.value;
      commit(before); layoutCanvas(); draw();
    }));
    if (!it) return;
    $$("[data-pact]", el).forEach((b) => b.addEventListener("click", () => {
      const a = b.dataset.pact;
      if (a === "split") split(); if (a === "dup") duplicate(); if (a === "del") remove();
      if (a === "center") { const before = snapshot(); Object.assign(it, { x: 0.5, y: 0.5, scale: 1, rot: 0 }); commit(before); }
    }));
    $$("[data-fit]", el).forEach((b) => b.addEventListener("click", () => { const before = snapshot(); it.fit = b.dataset.fit; commit(before); }));
    $$("[data-ppal]", el).forEach((b) => b.addEventListener("click", () => {
      const p = TJ.spec.paletas.find((x) => x.id === b.dataset.ppal); if (!p) return;
      const before = snapshot(); TJ_PAPEIS.forEach((c) => (it[c] = p[c])); TJ.pal = p.id; tjGuardar(); commit(before);
    }));
    $$("[data-pdur]", el).forEach((b) => b.addEventListener("click", () => { const before = snapshot(); it.dur = +b.dataset.pdur; TJ.dur = it.dur; tjGuardar(); commit(before); }));
    const cc = $("[data-copiar-credito]", el);
    if (cc) cc.addEventListener("click", () => {
      const txt = (media(it.src) || {}).credito || "";
      (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(() => toast("Crédito copiado")).catch(() => prompt("Copie o crédito:", txt));
    });
    $$("[data-k]", el).forEach((inp) => {
      const k = inp.dataset.k;
      const read = () => inp.type === "checkbox" ? inp.checked : inp.type === "range" || k === "speed" ? +inp.value : inp.value;
      inp.addEventListener("input", () => {
        if (!M.editBefore) M.editBefore = snapshot();
        let v = read();
        if (k === "speed") {  // mantém o mesmo trecho do original: a duração muda junto
          const span = it.dur * it.speed; it.speed = v; it.dur = q(span / v);
          const md = media(it.src); if (md) it.dur = Math.min(it.dur, q((md.duration - it.in) / v));
        } else it[k] = v;
        const out = $(`[data-out="${k}"]`, el);
        if (out) out.textContent = showVal(k, v);
        draw();
        if (k === "text" || k === "speed" || k === "l1") renderTimeline();
      });
      inp.addEventListener("change", () => {
        const b = M.editBefore; M.editBefore = null;
        if (k === "boxOn" || k === "speed" || k === "tpl" || k === "duck") { commit(b); return; }
        if (b && b !== snapshot()) { M.hist.push(b); M.fut = []; }
        save(); renderTimeline();
        $("[data-act=undo]", box()).disabled = !M.hist.length;
      });
      if (inp.tagName === "TEXTAREA" || inp.type === "text") inp.addEventListener("keydown", (e) => e.stopPropagation());
    });
  }

  /* ---------------- reprodução ---------------- */

  function seek(t) { M.t = Math.max(0, t); if (M.playing) M.clock = { t: M.t, now: performance.now() }; placePlayhead(); updateTime(); sync(); draw(); }
  function seekQuiet(t) { M.t = Math.max(0, t); placePlayhead(); sync(); draw(); }
  function updateTime() {
    const el = $(".mt-time", box()); if (el) el.textContent = `${fmt(M.t, true)} / ${fmt(total())}`;
  }
  function toggle() { if (M.playing) stop(); else play(); }
  function play() {
    if (!M.m.items.length) return;
    if (M.t >= total() - 0.05) M.t = 0;
    M.playing = true; M.follow = true;
    M.clock = { t: M.t, now: performance.now() };
    $(".mt-play", box()).innerHTML = ico(I.pause, 14);
    cancelAnimationFrame(M.raf);
    const loop = () => {
      if (!M.playing) return;
      M.t = M.clock.t + (performance.now() - M.clock.now) / 1000;
      if (M.t >= total()) { M.t = total(); stop(); placePlayhead(); updateTime(); draw(); return; }
      sync(); draw(); placePlayhead(); updateTime(); followPlayhead();
      M.raf = requestAnimationFrame(loop);
    };
    sync();
    M.raf = requestAnimationFrame(loop);
  }
  function stop() {
    M.playing = false; cancelAnimationFrame(M.raf);
    M.pool.forEach((list) => list.forEach((el) => { try { el.pause(); } catch (_) {} }));
    const b = M.m && $(".mt-play", box()); if (b) b.innerHTML = ico(I.play, 14);
    if (M.m) sync();
  }
  function clearPool() {
    M.pool.forEach((list) => list.forEach((el) => { try { el.pause(); el.removeAttribute("src"); el.load(); } catch (_) {} }));
    M.pool.clear();
  }

  /** Um elemento de vídeo/áudio por pedaço que está tocando ou vai tocar logo; reaproveitados por arquivo. */
  function elFor(it, need) {
    const key = it.src;
    let list = M.pool.get(key);
    if (!list) { list = []; M.pool.set(key, list); }
    let el = list.find((x) => x._item === it.id);
    if (el) return el;
    el = list.find((x) => !need.has(x._item));
    if (!el) {
      if (list.length >= 4) return null;
      const md = media(it.src);
      if (!md || !md.preview) return null;
      el = document.createElement(md.kind === "audio" ? "audio" : "video");
      el.preload = "auto"; el.playsInline = true; el.setAttribute("playsinline", "");
      el.src = urlMidia(it.src);
      el.addEventListener("seeked", () => { if (el._pending != null) { const p = el._pending; el._pending = null; el.currentTime = p; } else if (!M.playing) draw(); });
      el.addEventListener("loadeddata", () => { if (!M.playing) draw(); });
      list.push(el);
    }
    el._item = it.id;
    try { el.pause(); } catch (_) {}
    setTime(el, it.in + Math.max(0, M.t - it.start) * it.speed);
    return el;
  }
  function setTime(el, t) {
    if (el.readyState < 1) { el._pending = null; el.addEventListener("loadedmetadata", () => { el.currentTime = t; }, { once: true }); return; }
    if (el.seeking) el._pending = t; else el.currentTime = t;
  }

  function fadeK(it, t) {
    const lt = t - it.start;
    let k = 1;
    if (it.fadeIn > 0) k *= clamp(lt / it.fadeIn, 0, 1);
    if (it.fadeOut > 0) k *= clamp((it.dur - lt) / it.fadeOut, 0, 1);
    return k;
  }
  /** Na prévia, o som desce e sobe rapidinho nas emendas entre pedaços colados (igual ao arquivo exportado,
      que cruza os dois lados). Sem isso, cada troca de pedaço soava como um "pá" seco. */
  const RAMPA_PREVIA = { seca: 0, suave: 0.06, bem_suave: 0.12 };
  function emendaK(it, t) {
    const r = RAMPA_PREVIA[(M.m && M.m.suave) || "suave"] || 0;
    if (!r || it.type !== "video") return 1;
    const fim = it.start + it.dur, lt = t - it.start;
    const colado = (x) => M.m.items.some((o) => o !== it && o.track === it.track && o.type === "video" &&
      Math.abs((x === "antes" ? o.start + o.dur : o.start) - (x === "antes" ? it.start : fim)) < 0.02);
    let k = 1;
    if (lt < r && colado("antes")) k = Math.min(k, 0.25 + 0.75 * clamp(lt / r, 0, 1));
    if (fim - t < r && colado("depois")) k = Math.min(k, 0.25 + 0.75 * clamp((fim - t) / r, 0, 1));
    return k;
  }

  function sync() {
    if (!M.m) return;
    const t = M.t;
    const av = M.m.items.filter((i) => (i.type === "video" || i.type === "audio") && (i.src && media(i.src)));
    const active = av.filter((i) => i.start <= t && t < i.start + i.dur);
    const need = new Set(active.map((i) => i.id));
    if (M.playing) {  // prepara o próximo pedaço de cada trilha
      M.m.tracks.forEach((tr) => {
        const nx = av.filter((i) => i.track === tr.id && i.start > t && i.start - t < 1.5).sort((a, b) => a.start - b.start)[0];
        if (nx) need.add(nx.id);
      });
    }
    av.filter((i) => need.has(i.id)).forEach((it) => {
      const el = elFor(it, need); if (!el) return;
      const on = active.includes(it);
      const tr = track(it.track);
      if (!on) { if (!el.paused) el.pause(); return; }
      const target = it.in + (t - it.start) * it.speed;
      const vol = tr.muted || (tr.hidden && it.type === "video") ? 0 : it.volume * fadeK(it, t) * emendaK(it, t) * duckK(it, t);
      el.volume = clamp(vol, 0, 1); el.muted = vol <= 0.001;
      if (Math.abs(el.playbackRate - it.speed) > 0.001) el.playbackRate = it.speed;
      if (M.playing) {
        if (el.paused) { setTime(el, target); el.play().catch(() => {}); }
        else if (Math.abs(el.currentTime - target) > 0.25) setTime(el, target);
      } else {
        if (!el.paused) el.pause();
        if (Math.abs(el.currentTime - target) > 0.5 / fps()) setTime(el, target);
      }
    });
    M.pool.forEach((list) => list.forEach((el) => { if (!need.has(el._item) && !el.paused) el.pause(); }));
  }

  /* ---------------- prévia (canvas) ---------------- */

  function layoutCanvas() {
    const wrap = $(".mt-canvas-wrap", box()), cv = $(".mt-canvas", box());
    if (!wrap || !M.m) return;
    const W = M.m.w, H = M.m.h;
    const bw = wrap.clientWidth - 16, bh = wrap.clientHeight - 16;
    if (bw <= 0 || bh <= 0) return;
    const k = Math.min(bw / W, bh / H);
    const cw = Math.max(40, Math.floor(W * k)), ch = Math.max(40, Math.floor(H * k));
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.style.width = cw + "px"; cv.style.height = ch + "px";
    cv.width = Math.round(cw * dpr); cv.height = Math.round(ch * dpr);
    M.view = { k: cv.width / W, css: cw / W };
  }

  function sizeOf(it) {
    const W = M.m.w, H = M.m.h;
    if (it.type === "color") return [W * it.w * it.scale, H * it.h * it.scale];
    const md = media(it.src) || {};
    const aw = md.w || W, ah = md.h || H;
    const k = (it.fit === "cover" ? Math.max : Math.min)(W / aw, H / ah) * it.scale;
    return [aw * k, ah * k];
  }
  function textLines(it) { return ((it.upper ? (it.text || "").toUpperCase() : it.text) || "").split("\n"); }
  function textBox(ctx, it) {
    const tam = it.size * Math.min(M.m.w, M.m.h) * it.scale, lh = tam * 1.18, lines = textLines(it);
    ctx.font = `${tam}px "${it.font}"`;
    const ws = lines.map((l) => ctx.measureText(l).width);
    return { tam, lh, lines, ws, w: Math.max(10, ...ws), h: lh * lines.length };
  }

  function draw() {
    const cv = $(".mt-canvas", box()); if (!cv || !M.m || !M.view) return;
    const ctx = cv.getContext("2d");
    const W = M.m.w, H = M.m.h, t = M.t;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.setTransform(M.view.k, 0, 0, M.view.k, 0, 0);
    ctx.fillStyle = M.m.bg; ctx.fillRect(0, 0, W, H);
    const order = M.m.tracks.slice().reverse();
    let selBox = null;
    order.forEach((tr) => {
      if (tr.hidden || tr.kind === "audio") return;
      M.m.items.filter((i) => i.track === tr.id && i.start <= t && t < i.start + i.dur).forEach((it) => {
        const a = it.opacity * fadeK(it, t);
        ctx.save();
        ctx.globalAlpha = clamp(a, 0, 1);
        const cx = it.x * W, cy = it.y * H;
        if (it.type === "tarja") {
          ctx.globalAlpha = 1;
          const bb = drawTarja(ctx, it, t, W, H);
          if (it.id === M.sel && bb) selBox = { cx: (bb[0] + bb[2]) / 2, cy: (bb[1] + bb[3]) / 2, w: bb[2] - bb[0] + 12, h: bb[3] - bb[1] + 12, rot: 0, tarja: true };
        } else if (it.type === "text") {
          const b = textBox(ctx, it);
          ctx.textAlign = "center"; ctx.textBaseline = "top";
          const y0 = cy - b.h / 2;
          b.lines.forEach((ln, i) => {
            if (!ln.trim()) return;
            const top = y0 + i * b.lh + (b.lh - b.tam) / 2;
            if (it.boxOn) {
              const pad = Math.max(2, b.tam * 0.22);
              ctx.save(); ctx.globalAlpha = clamp(a * it.boxAlpha, 0, 1); ctx.fillStyle = it.box;
              ctx.fillRect(cx - b.ws[i] / 2 - pad, top - pad, b.ws[i] + pad * 2, b.tam + pad * 2); ctx.restore();
            }
            if (it.strokeW > 0) { ctx.lineJoin = "round"; ctx.lineWidth = Math.max(1, it.strokeW * b.tam) * 2; ctx.strokeStyle = it.stroke; ctx.strokeText(ln, cx, top); }
            ctx.fillStyle = it.color; ctx.fillText(ln, cx, top);
          });
          if (it.id === M.sel) selBox = { cx, cy, w: b.w + 16, h: b.h + 8, rot: 0 };
        } else {
          const [w, h] = sizeOf(it);
          ctx.translate(cx, cy); ctx.rotate((it.rot * Math.PI) / 180);
          if (it.type === "color") { ctx.fillStyle = it.color; ctx.fillRect(-w / 2, -h / 2, w, h); }
          else {
            const src = it.type === "image" ? img(it.src) : elOf(it);
            if (src && (it.type === "image" ? src.complete && src.naturalWidth : src.readyState >= 2)) {
              if (it.fit === "cover" && it.scale <= 1.0001 && Math.abs(it.rot) < 0.01 && Math.abs(it.x - 0.5) < 1e-4 && Math.abs(it.y - 0.5) < 1e-4) {
                ctx.drawImage(src, -w / 2, -h / 2, w, h);
              } else ctx.drawImage(src, -w / 2, -h / 2, w, h);
            } else {
              ctx.fillStyle = "rgba(255,255,255,.06)"; ctx.fillRect(-w / 2, -h / 2, w, h);
              ctx.fillStyle = "rgba(255,255,255,.5)"; ctx.font = `${Math.round(H * 0.025)}px sans-serif`; ctx.textAlign = "center";
              ctx.fillText(media(it.src) && !media(it.src).preview ? "preparando prévia…" : "carregando…", 0, 0);
            }
          }
          if (it.id === M.sel) selBox = { cx, cy, w, h, rot: it.rot };
        }
        ctx.restore();
      });
    });
    if (selBox && !M.playing) {
      ctx.save();
      ctx.translate(selBox.cx, selBox.cy); ctx.rotate((selBox.rot * Math.PI) / 180);
      const px = 1 / M.view.css;
      ctx.strokeStyle = "#FF8A3D"; ctx.lineWidth = 2 * px; ctx.setLineDash([6 * px, 4 * px]);
      ctx.strokeRect(-selBox.w / 2, -selBox.h / 2, selBox.w, selBox.h);
      ctx.setLineDash([]); ctx.fillStyle = "#FF8A3D";
      ctx.beginPath(); ctx.arc(selBox.w / 2, selBox.h / 2, 7 * px, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
      M.selBox = selBox;
    } else M.selBox = null;
    if (M.guide) {
      ctx.save(); ctx.strokeStyle = "rgba(255,138,61,.8)"; ctx.lineWidth = 1 / M.view.css;
      if (M.guide.x) { ctx.beginPath(); ctx.moveTo(W / 2, 0); ctx.lineTo(W / 2, H); ctx.stroke(); }
      if (M.guide.y) { ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke(); }
      ctx.restore();
    }
  }
  function elOf(it) { const list = M.pool.get(it.src) || []; return list.find((x) => x._item === it.id) || null; }
  function img(mid) {
    let im = M.imgs.get(mid);
    if (!im) { im = new Image(); im.onload = () => { if (!M.playing) draw(); }; im.src = urlMidia(mid); M.imgs.set(mid, im); }
    return im;
  }

  /** Mover e redimensionar direto na prévia. */
  function canvasDown(e) {
    if (!M.m || M.playing) return;
    const cv = e.currentTarget, r = cv.getBoundingClientRect();
    const toP = (ev) => [((ev.clientX - r.left) / r.width) * M.m.w, ((ev.clientY - r.top) / r.height) * M.m.h];
    const [px, py] = toP(e);
    const hit = (b) => {
      const a = (-b.rot * Math.PI) / 180, dx = px - b.cx, dy = py - b.cy;
      const lx = dx * Math.cos(a) - dy * Math.sin(a), ly = dx * Math.sin(a) + dy * Math.cos(a);
      return { inside: Math.abs(lx) <= b.w / 2 && Math.abs(ly) <= b.h / 2, corner: Math.hypot(lx - b.w / 2, ly - b.h / 2) < 22 / M.view.css };
    };
    let it = itemById(M.sel), mode = null;
    if (it && M.selBox) { const h = hit(M.selBox); if (h.corner && it.type !== "audio" && it.type !== "tarja") mode = "scale"; else if (h.inside) mode = "move"; }
    if (!mode) {
      const ctx = cv.getContext("2d");
      const cands = M.m.tracks.filter((t) => !t.hidden && t.kind !== "audio" && !t.locked)
        .flatMap((tr) => M.m.items.filter((i) => i.track === tr.id && i.start <= M.t && M.t < i.start + i.dur));
      it = null;
      for (const c of cands) {
        let b;
        if (c.type === "tarja") {
          const bb = drawTarja(null, c, M.t, M.m.w, M.m.h, true); if (!bb) continue;
          b = { cx: (bb[0] + bb[2]) / 2, cy: (bb[1] + bb[3]) / 2, w: bb[2] - bb[0] + 12, h: bb[3] - bb[1] + 12, rot: 0 };
        } else if (c.type === "text") { const tb = textBox(ctx, c); b = { cx: c.x * M.m.w, cy: c.y * M.m.h, w: tb.w + 16, h: tb.h + 8, rot: 0 }; }
        else { const [w, h] = sizeOf(c); b = { cx: c.x * M.m.w, cy: c.y * M.m.h, w, h, rot: c.rot }; }
        if (hit(b).inside) { it = c; break; }
      }
      if (!it) { if (M.sel) { M.sel = null; renderTimeline(); renderProps(); draw(); } return; }
      M.sel = it.id; mode = "move"; renderTimeline(); renderProps(); draw();
    }
    if (track(it.track).locked) return;
    e.preventDefault();
    cv.setPointerCapture(e.pointerId);
    const before = snapshot(), o = { ...it };
    const c0 = [o.x * M.m.w, o.y * M.m.h];
    const d0 = Math.max(1, Math.hypot(px - c0[0], py - c0[1]));
    let moved = false;
    const mv = (ev) => {
      const [qx, qy] = toP(ev);
      moved = true;
      if (mode === "move") {
        let nx = o.x + (qx - px) / M.m.w, ny = o.y + (qy - py) / M.m.h;
        M.guide = { x: Math.abs(nx - 0.5) < 0.012, y: Math.abs(ny - 0.5) < 0.012 };
        if (M.guide.x) nx = 0.5; if (M.guide.y) ny = 0.5;
        it.x = +nx.toFixed(4); it.y = +ny.toFixed(4);
      } else {
        it.scale = +clamp(o.scale * (Math.hypot(qx - c0[0], qy - c0[1]) / d0), 0.05, 6).toFixed(3);
      }
      draw();
    };
    const up = () => {
      cv.removeEventListener("pointermove", mv); cv.removeEventListener("pointerup", up); cv.removeEventListener("pointercancel", up);
      M.guide = null;
      if (moved) commit(before); else draw();
    };
    cv.addEventListener("pointermove", mv); cv.addEventListener("pointerup", up); cv.addEventListener("pointercancel", up);
  }

  /* ---------------- teclado ---------------- */

  function keys(e) {
    if (!M.open || $("#view-editor").classList.contains("hidden") || document.querySelector("dialog[open]")) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (["input", "select", "textarea"].includes(tag) || e.target.isContentEditable) return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (e.code === "Space") { e.preventDefault(); toggle(); return; }
    if (ctrl && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if (ctrl && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
    if (ctrl && e.key.toLowerCase() === "d") { e.preventDefault(); duplicate(); return; }
    if (ctrl) return;
    if (e.key.toLowerCase() === "s") { e.preventDefault(); split(); }
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); remove(); }
    if (e.key === "ArrowLeft") { e.preventDefault(); seek(q(M.t - (e.shiftKey ? 1 : 1 / fps()))); }
    if (e.key === "ArrowRight") { e.preventDefault(); seek(q(M.t + (e.shiftKey ? 1 : 1 / fps()))); }
    if (e.key === "Home") seek(0);
    if (e.key === "End") seek(total());
    if (e.key === "+" || e.key === "=") zoomAround(1.5);
    if (e.key === "-") zoomAround(1 / 1.5);
    if (e.key === "Escape" && M.sel) { M.sel = null; renderTimeline(); renderProps(); draw(); }
  }

  return { open, close, flush, get state() { return M; } };
})();
