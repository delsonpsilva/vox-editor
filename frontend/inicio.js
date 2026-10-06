/* VOX Editor 1.4 — cara nova: barra do topo, busca rápida (Ctrl+K), botão Novo, atividade, menu recolhível e tela inicial.
   Usa as funções do app.js ($, $$, api, esc, toast, fmt, fmtHours, fmtDur, S, upload, importarVox...). */
(function () {
  const TITULOS = { inicio: "Início", projetos: "Projetos", exportados: "Exportados", publicacoes: "Publicações",
    modelos: "Modelos", redes: "Redes sociais", marca: "Marca", ia: "Inteligência artificial" };
  const KIND = { analise: "Análise", render: "Exportação", download: "Download", publicar: "Publicação", "publicar-online": "Envio",
    semfundo: "Remover fundo", previa: "Prévia", banco: "Banco grátis", limpeza: "Limpeza com IA", pacote: "Pacote",
    online: "Envio para o online", trazer: "Trazer do online", montagem: "Exportação da montagem" };
  const A = { data: { trabalhos: [], analisando: [], proximas: [] }, t: null, open: false, pop: "#tb-act-pop" };
  // v1.6: o botão Atividade existe na barra da tela principal e na barra do editor
  const PARES = [["#tb-act", "#tb-act-pop", "#tb-act-n"], ["#ed-act", "#ed-act-pop", "#ed-act-n"]];
  const semAcento = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };
  const ler = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };
  const homeVisivel = () => !$("#view-home").classList.contains("hidden");

  /* ---------------- título e saudação ---------------- */
  function title(page) {
    $("#tb-page").textContent = TITULOS[page] || "Início";
    const h = new Date().getHours();
    $("#hero-hi").textContent = (h < 5 ? "Boa noite" : h < 12 ? "Bom dia" : h < 18 ? "Boa tarde" : "Boa noite") + ". O que vamos editar hoje?";
  }

  /* ---------------- números da tela inicial ---------------- */
  function readout(d) {
    A.lastD = d;
    const box = $("#readout");
    if (!d.projects) { box.innerHTML = ""; box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const agendadas = A.data.proximas.length;
    const itens = [
      [fmtHours(d.seconds_in), "de vídeo enviado", `${d.projects} projeto${d.projects > 1 ? "s" : ""}`],
      [fmtHours(d.removed), "de silêncio e erros cortados", "pela edição automática"],
      [String(d.clips), d.clips === 1 ? "corte criado" : "cortes criados", "para Reels, Shorts e TikTok"],
      [String(d.renders), d.renders === 1 ? "vídeo exportado" : "vídeos exportados", "prontos para publicar"],
      [String(agendadas), agendadas === 1 ? "publicação na fila" : "publicações na fila", agendadas ? "saem sozinhas" : "nada agendado"],
    ];
    box.innerHTML = itens.map(([n, l, s]) => `<div class="ro"><b>${esc(n)}</b><span>${esc(l)}</span><em>${esc(s)}</em></div>`).join("");
  }

  /* ---------------- console de criação (abas) ---------------- */
  function aba(nome) {
    $$(".console-tabs [data-ctab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.ctab === nome)));
    $$(".console-panel").forEach((p) => p.classList.toggle("hidden", p.dataset.cpanel !== nome));
    if (nome === "link") setTimeout(() => $("#link-url").focus(), 30);
  }

  function setupConsole() {
    $$(".console-tabs [data-ctab]").forEach((b) => b.addEventListener("click", () => aba(b.dataset.ctab)));
    $(".console-tabs").addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const tabs = $$(".console-tabs [data-ctab]"), i = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
      const n = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      aba(n.dataset.ctab); n.focus();
    });
    // colar um link na tela inicial abre a aba do link
    document.addEventListener("paste", () => setTimeout(() => {
      if (S.page === "inicio" && homeVisivel() && $("#link-url").value) aba("link");
    }, 0));
  }

  /* ---------------- botão Novo ---------------- */
  function novo(acao) {
    fecharMenus();
    const irInicio = (fn) => { if (location.hash && location.hash !== "#/") { location.hash = "#/"; setTimeout(fn, 350); } else fn(); };
    if (acao === "arquivo") irInicio(() => { aba("arquivo"); $("#dropzone").click(); });
    if (acao === "link") irInicio(() => aba("link"));
    if (["9:16", "16:9", "1:1"].includes(acao)) irInicio(() => { const b = $(`.fmt[data-blank="${acao}"]`); if (b) b.click(); });
    if (acao === "vox") $("#vox-input").click();
    if (acao === "online") $("#btn-from-online").click();
  }

  function fecharMenus() {
    $("#tb-new-menu").classList.add("hidden"); $("#tb-new").setAttribute("aria-expanded", "false");
    PARES.forEach(([b, p]) => { if ($(p)) { $(p).classList.add("hidden"); $(b).setAttribute("aria-expanded", "false"); } }); A.open = false;
  }

  function setupNovo() {
    $("#tb-new").addEventListener("click", (e) => {
      e.stopPropagation();
      const m = $("#tb-new-menu"), abrir = m.classList.contains("hidden");
      fecharMenus();
      if (abrir) { m.classList.remove("hidden"); $("#tb-new").setAttribute("aria-expanded", "true"); const f = $("button", m); if (f) f.focus(); }
    });
    $$("#tb-new-menu [data-new]").forEach((b) => b.addEventListener("click", () => novo(b.dataset.new)));
    $("#tb-new-menu").addEventListener("keydown", (e) => {
      const itens = $$("#tb-new-menu button").filter((b) => b.offsetParent), i = itens.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); itens[(i + 1) % itens.length].focus(); }
      if (e.key === "ArrowUp") { e.preventDefault(); itens[(i - 1 + itens.length) % itens.length].focus(); }
      if (e.key === "Escape") { fecharMenus(); $("#tb-new").focus(); }
    });
    document.addEventListener("click", (e) => { if (!e.target.closest(".tb-wrap")) fecharMenus(); });
  }

  /* ---------------- atividade (análises, exportações, postagens) ---------------- */
  const ativos = () => A.data.trabalhos.filter((j) => j.status === "processando" || j.status === "na fila");

  async function atualizar() {
    clearTimeout(A.t);
    try { A.data = await api("GET", "/api/atividade"); } catch (_) { A.t = setTimeout(atualizar, 30000); return; }
    const n = ativos().length + A.data.analisando.filter((p) => !A.data.trabalhos.some((j) => j.project === p.id && j.status === "processando")).length;
    PARES.forEach(([b, , nn]) => {
      const badge = $(nn); if (!badge) return;
      badge.textContent = n > 9 ? "9+" : n; badge.classList.toggle("hidden", !n);
      $(b).classList.toggle("busy", !!n);
    });
    if (A.open) desenharPop();
    if (homeVisivel() && S.page === "inicio") { desenharAndamento(); desenharProximas(); if (A.lastD) readout(A.lastD); }
    A.t = setTimeout(atualizar, n ? 3000 : (document.hidden ? 60000 : 20000));
  }

  const pct = (x) => Math.round((x || 0) * 100);
  const quando = (ts) => {
    const d = new Date(ts * 1000), hoje = new Date(), amanha = new Date(Date.now() + 864e5);
    const hora = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    if (d.toDateString() === hoje.toDateString()) return "Hoje, " + hora;
    if (d.toDateString() === amanha.toDateString()) return "Amanhã, " + hora;
    return d.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "short" }).replace(".", "") + ", " + hora;
  };

  function linhaTrabalho(j) {
    const andando = j.status === "processando" || j.status === "na fila";
    const nome = KIND[j.kind] || j.label || "Trabalho";
    const est = j.status === "erro" ? `<span class="act-st err">${esc(j.error || "Erro")}</span>`
      : j.status === "concluido" ? `<span class="act-st ok">Concluído</span>`
      : `<span class="act-st">${esc(j.msg || "")}${j.status === "processando" ? " · " + pct(j.pct) + "%" : ""}</span>`;
    return `<button type="button" class="act-row" data-goto="${esc(j.project)}" data-kind="${esc(j.project_kind || "")}">
      <span class="act-top"><b>${esc(j.label || nome)}</b><span class="act-proj">${esc(j.project_name || "")}</span></span>
      ${est}${andando ? `<span class="bar"><i style="width:${pct(j.pct)}%"></i></span>` : ""}</button>`;
  }

  function linhaAnalise(p) {
    return `<button type="button" class="act-row" data-goto="${esc(p.id)}">
      <span class="act-top"><b>Análise automática</b><span class="act-proj">${esc(p.name)}</span></span>
      <span class="act-st">${esc((p.progress || {}).msg || "Processando")} · ${pct((p.progress || {}).pct)}%</span>
      <span class="bar"><i style="width:${pct((p.progress || {}).pct)}%"></i></span></button>`;
  }

  function linhaPost(it) {
    return `<a class="next-row" href="#/publicacoes">
      <span class="net-dot" style="background:${NET_COLORS[it.net]}"></span>
      <span class="nr-txt"><b>${esc(it.title || "Vídeo")}</b><em>${esc(it.status === "publicando" ? "Publicando agora · " + pct(it.pct) + "%" : quando(it.when))}</em></span></a>`;
  }

  function desenharPop() {
    const d = A.data, at = ativos(), fim = d.trabalhos.filter((j) => !at.includes(j));
    const analise = d.analisando.filter((p) => !d.trabalhos.some((j) => j.project === p.id && j.status === "processando"));
    let h = `<div class="pop-head"><b>Atividade</b><span class="hint">${at.length + analise.length ? "Atualiza sozinho" : "Nada em andamento"}</span></div>`;
    if (analise.length || at.length) h += `<div class="pop-sec">${analise.map(linhaAnalise).join("")}${at.map(linhaTrabalho).join("")}</div>`;
    if (fim.length) h += `<div class="pop-label">Terminados há pouco</div><div class="pop-sec">${fim.slice(0, 6).map(linhaTrabalho).join("")}</div>`;
    if (d.proximas.length) h += `<div class="pop-label">Próximas publicações</div><div class="pop-sec">${d.proximas.slice(0, 4).map(linhaPost).join("")}</div>`;
    if (!analise.length && !d.trabalhos.length && !d.proximas.length)
      h += `<p class="pop-empty">Quando você enviar um vídeo, exportar ou agendar uma postagem, o andamento aparece aqui.</p>`;
    $(A.pop).innerHTML = h;
    ligarGoto($(A.pop));
  }

  function ligarGoto(box) {
    $$("[data-goto]", box).forEach((b) => b.addEventListener("click", () => {
      fecharMenus();
      const p = (S.projects || []).find((x) => x.id === b.dataset.goto);
      location.hash = "#/p/" + b.dataset.goto + ((p && p.kind === "montagem") || b.dataset.kind === "montagem" ? "/montagem" : "");
    }));
  }

  function desenharAndamento() {
    const d = A.data, at = ativos();
    const analise = d.analisando.filter((p) => !d.trabalhos.some((j) => j.project === p.id && j.status === "processando"));
    const box = $("#home-running");
    box.classList.toggle("hidden", !(at.length + analise.length));
    $("#running-list").innerHTML = analise.map(linhaAnalise).join("") + at.map(linhaTrabalho).join("");
    ligarGoto($("#running-list"));
  }

  function desenharProximas() {
    const box = $("#home-next");
    box.innerHTML = A.data.proximas.length ? A.data.proximas.slice(0, 5).map(linhaPost).join("")
      : `<p class="next-empty">Nada agendado. Em <a href="#/exportados">Exportados</a>, toque em <b>Publicar</b> num vídeo pronto para colocar na fila.</p>`;
  }

  function setupAtividade() {
    PARES.forEach(([b, p]) => {
      if (!$(b)) return;
      $(b).addEventListener("click", (e) => {
        e.stopPropagation();
        const abrir = $(p).classList.contains("hidden");
        fecharMenus();
        if (abrir) { A.open = true; A.pop = p; desenharPop(); $(p).classList.remove("hidden"); $(b).setAttribute("aria-expanded", "true"); atualizar(); }
      });
      $(p).addEventListener("keydown", (e) => { if (e.key === "Escape") { fecharMenus(); $(b).focus(); } });
    });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) atualizar(); });
  }

  /* ---------------- busca rápida (Ctrl+K) ---------------- */
  const IC = {
    page: '<path d="M4 4h16v16H4z"/><path d="M4 9h16"/>',
    proj: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10 9l5 3-5 3z"/>',
    acao: '<path d="M12 5v14M5 12h14"/>',
    cfg: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  };
  const K = { itens: [], sel: 0 };

  function catalogo() {
    const pages = Object.entries(TITULOS).map(([k, t]) => ({ g: "Telas", ic: "page", t, s: "", run: () => (location.hash = k === "inicio" ? "#/" : "#/" + k) }));
    const acoes = [
      { t: "Enviar vídeo", s: "Novo projeto a partir de um arquivo", run: () => novo("arquivo") },
      { t: "Importar por link", s: "YouTube e outros sites", run: () => novo("link") },
      { t: "Montagem vertical 9:16", s: "Projeto em branco", run: () => novo("9:16") },
      { t: "Montagem horizontal 16:9", s: "Projeto em branco", run: () => novo("16:9") },
      { t: "Montagem quadrada 1:1", s: "Projeto em branco", run: () => novo("1:1") },
      { t: "Abrir projeto (.vox)", s: "Arquivo salvo em outra instalação", run: () => novo("vox") },
      ...(isOnline() ? [] : [{ t: "Trazer do online", s: "Projetos do editor online", run: () => novo("online") }]),
      { t: "Configurações", s: "Exportação, senha, páginas públicas", ic: "cfg", run: () => $("[data-open-settings]").click() },
      { t: "Liberar espaço", s: "Apaga arquivos temporários", ic: "cfg", run: () => $("#btn-clean").click() },
      { t: "Recolher ou abrir o menu lateral", s: "Ctrl+B", ic: "cfg", run: () => recolher() },
    ].map((a) => ({ g: "Ações", ic: a.ic || "acao", ...a }));
    const projs = [...(S.projects || [])].sort((a, b) => b.updated - a.updated).map((p) => ({
      g: "Projetos", ic: "proj", t: p.name,
      s: [p.duration ? fmt(p.duration) : "", p.kind === "montagem" ? "montagem" : p.status === "pronto" ? "pronto" : p.status, p.clips ? p.clips + " cortes" : ""].filter(Boolean).join(" · "),
      run: () => (location.hash = "#/p/" + p.id + (p.kind === "montagem" ? "/montagem" : p.clips ? "/cortes" : "")),
    }));
    return { pages, acoes, projs };
  }

  function filtrar(q) {
    const { pages, acoes, projs } = catalogo(), nq = semAcento(q).trim();
    if (!nq) return [...projs.slice(0, 5), ...acoes.slice(0, 5), ...pages];
    const termos = nq.split(/\s+/);
    const nota = (it) => {
      const alvo = semAcento(it.t + " " + it.s);
      if (!termos.every((t) => alvo.includes(t))) return -1;
      return (semAcento(it.t).startsWith(nq) ? 3 : 0) + (semAcento(it.t).includes(nq) ? 1 : 0);
    };
    return [...projs, ...acoes, ...pages].map((it) => [nota(it), it]).filter(([n]) => n >= 0)
      .sort((a, b) => b[0] - a[0]).slice(0, 14).map(([, it]) => it);
  }

  function desenharK() {
    const box = $("#cmdk-list");
    if (!K.itens.length) { box.innerHTML = `<p class="cmdk-empty">Nada encontrado. Tente o nome do projeto ou uma ação, como "exportados".</p>`; return; }
    let g = "", h = "";
    K.itens.forEach((it, i) => {
      if (it.g !== g) { h += `<div class="cmdk-g">${esc(it.g)}</div>`; g = it.g; }
      h += `<button type="button" class="cmdk-it" role="option" id="ck-${i}" aria-selected="${i === K.sel}" data-i="${i}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${IC[it.ic]}</svg>
        <span><b>${esc(it.t)}</b>${it.s ? `<em>${esc(it.s)}</em>` : ""}</span></button>`;
    });
    box.innerHTML = h;
    $("#cmdk-q").setAttribute("aria-activedescendant", "ck-" + K.sel);
    const el = $(`#ck-${K.sel}`); if (el) el.scrollIntoView({ block: "nearest" });
    $$(".cmdk-it", box).forEach((b) => {
      b.addEventListener("click", () => executar(+b.dataset.i));
      b.addEventListener("mousemove", () => { if (K.sel !== +b.dataset.i) { K.sel = +b.dataset.i; $$(".cmdk-it", box).forEach((x) => x.setAttribute("aria-selected", String(x === b))); } });
    });
  }

  function executar(i) { const it = K.itens[i]; if (!it) return; $("#cmdk").close(); setTimeout(it.run, 10); }

  async function abrirBusca() {
    const dlg = $("#cmdk"); if (dlg.open) return;
    if (!S.projects) { try { S.projects = await api("GET", "/api/projects"); } catch (_) {} }
    $("#cmdk-q").value = ""; K.sel = 0; K.itens = filtrar(""); desenharK();
    dlg.showModal(); $("#cmdk-q").focus();
  }

  function setupBusca() {
    $("#tb-search").addEventListener("click", abrirBusca);
    $("#cmdk-q").addEventListener("input", (e) => { K.sel = 0; K.itens = filtrar(e.target.value); desenharK(); });
    $("#cmdk-q").addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); K.sel = Math.min(K.itens.length - 1, K.sel + 1); desenharK(); }
      if (e.key === "ArrowUp") { e.preventDefault(); K.sel = Math.max(0, K.sel - 1); desenharK(); }
      if (e.key === "Enter") { e.preventDefault(); executar(K.sel); }
    });
    $("#cmdk").addEventListener("click", (e) => { if (e.target === $("#cmdk")) $("#cmdk").close(); });
    document.addEventListener("keydown", (e) => {
      const ctrl = e.ctrlKey || e.metaKey;
      if (ctrl && e.key.toLowerCase() === "k" && $("#view-login").classList.contains("hidden")) {
        e.preventDefault(); if ($("#cmdk").open) $("#cmdk").close(); else if (!document.querySelector("dialog[open]")) abrirBusca();
      }
      if (ctrl && e.key.toLowerCase() === "b" && homeVisivel() && !document.querySelector("dialog[open]")) { e.preventDefault(); recolher(); }
    });
  }

  /* ---------------- menu lateral recolhível ---------------- */
  function recolher(forcar) {
    const mini = forcar !== undefined ? forcar : !document.body.classList.contains("side-mini");
    document.body.classList.toggle("side-mini", mini);
    guardar("vox-side-mini", mini ? "1" : "0");
    const b = $("#side-collapse");
    b.setAttribute("aria-label", mini ? "Abrir o menu" : "Recolher o menu");
    b.title = (mini ? "Abrir o menu" : "Recolher o menu") + " (Ctrl+B)";
  }

  function onHome(page) {
    if (page === "inicio") { desenharAndamento(); desenharProximas(); }
    atualizar();
  }

  function setup() {
    setupConsole(); setupNovo(); setupAtividade(); setupBusca();
    $("#side-collapse").addEventListener("click", () => recolher());
    if (ler("vox-side-mini") === "1") recolher(true);
    title("inicio");
  }

  window.V14 = { title, readout, onHome, abrirBusca, aba, atualizar, fecharMenus };
  setup();
})();
