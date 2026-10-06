/* VOX Editor 1.5 — Edição automática 2.0: perfis de um clique (com prévia do resultado) e capítulos do YouTube.
   Usa as funções do app.js ($, $$, api, esc, toast, fmt, S, applyProject). */
(function () {
  const E = { perfis: null, caps: null, t: null, carregando: false };
  const iaLigada = () => { const ai = (S.cfg || {}).ai || {}; return ai.provider && ai.provider !== "none" && ai.api_key_set; };
  const menos = (s) => (s >= 60 ? `−${Math.round(s / 60)} min` : `−${Math.round(s)} s`);

  /* ---------------- perfis ---------------- */
  function desenharPerfis() {
    const box = $("#perfil-box"); if (!box) return;
    const d = E.perfis;
    const lista = d ? d.perfis : [];
    box.innerHTML = `
      <div class="tool-head"><span class="dot" style="background:var(--accent)"></span><strong>Perfil da edição</strong>
        <span class="hint">${d && !d.atual ? "personalizado" : ""}</span></div>
      <p>Um clique ajusta silêncios, ritmo, respirações e vícios para o tipo de vídeo. Dá para afinar nos ajustes abaixo.</p>
      <div class="perfis" role="radiogroup" aria-label="Perfil da edição">
        ${d ? lista.map((p) => `
          <button type="button" class="perfil ${d.atual === p.id ? "on" : ""}" role="radio" aria-checked="${d.atual === p.id}" data-perfil="${p.id}" title="${esc(p.desc)}">
            <b>${esc(p.nome)}</b>
            <span>${p.final != null ? `${fmt(p.final)} <em>${menos(p.removido || 0)}</em>` : esc(p.desc)}</span>
          </button>`).join("") : `<p class="hint">Calculando o resultado de cada perfil…</p>`}
      </div>
      <label class="checkline"><input type="checkbox" id="perfil-padrao"> Usar o perfil escolhido nos próximos projetos</label>`;
    $$("[data-perfil]", box).forEach((b) => b.addEventListener("click", () => aplicar(b.dataset.perfil)));
  }

  async function carregarPerfis() {
    if (!S.P) return;
    const pid = S.P.id;
    try { const d = await api("GET", `/api/projects/${pid}/perfis`); if (S.P && S.P.id === pid) { E.perfis = d; desenharPerfis(); } } catch (_) {}
  }

  async function aplicar(perfil) {
    const padrao = $("#perfil-padrao") && $("#perfil-padrao").checked;
    $$("[data-perfil]").forEach((b) => b.classList.toggle("on", b.dataset.perfil === perfil));
    try {
      S.P = await api("POST", `/api/projects/${S.P.id}/perfil`, { perfil, padrao });
      S.toolsBuilt = false; applyProject();
      const nome = ((E.perfis || { perfis: [] }).perfis.find((p) => p.id === perfil) || {}).nome || "Perfil";
      toast(`${nome} aplicado${padrao ? " e salvo como padrão" : ""}`);
    } catch (e) { toast(e.message, true); }
  }

  function recalcular() {
    clearTimeout(E.t);
    E.t = setTimeout(carregarPerfis, 600);
    if (E.caps && E.caps.itens && E.caps.itens.length) { clearTimeout(E.tc); E.tc = setTimeout(carregarCaps, 800); }
  }

  /* ---------------- capítulos ---------------- */
  function desenharCaps() {
    const box = $("#cap-box"); if (!box) return;
    const c = E.caps || { itens: [] }, tem = c.itens && c.itens.length;
    box.innerHTML = `
      <div class="tool-head"><span class="dot" style="background:#F43F5E"></span><strong>Capítulos do YouTube</strong>
        ${tem ? `<span class="hint">${c.fonte === "ia" ? "títulos pela IA" : "títulos automáticos"}</span>` : ""}</div>
      <p>${tem ? "Os tempos já são do vídeo editado. Toque no tempo para ouvir o trecho e no título para mudar." :
        "Divide o vídeo por assunto e dá nome a cada parte, pronto para colar na descrição do YouTube."}</p>
      ${c.aviso ? `<p class="cap-aviso">${esc(c.aviso)}</p>` : ""}
      ${tem ? `<ol class="caps">${c.itens.map((x, i) => `
        <li><button type="button" class="cap-t" data-seek="${x.t}" title="Ouvir a partir daqui">${fmt(x.t_editado)}</button>
          <input type="text" value="${esc(x.titulo)}" data-cap="${i}" maxlength="80" aria-label="Título do capítulo ${i + 1}">
          ${i ? `<button type="button" class="cap-x" data-capdel="${i}" aria-label="Tirar este capítulo">✕</button>` : "<span></span>"}</li>`).join("")}</ol>
        ${c.valido_youtube ? "" : `<p class="cap-aviso">O YouTube só mostra capítulos quando há pelo menos 3.</p>`}` : ""}
      <div class="row">
        <button type="button" class="btn small ${tem ? "" : "primary"}" data-capgen ${E.carregando ? "disabled" : ""}>
          ${E.carregando ? "Dividindo por assunto…" : tem ? "Gerar de novo" : "Gerar capítulos"}</button>
        ${tem ? `<button type="button" class="btn small primary" data-capcopy>Copiar para a descrição</button>` : ""}
      </div>
      ${!tem && !iaLigada() ? `<span class="hint">Sem IA os títulos saem da própria fala. Com o Claude ligado, a IA dá nomes melhores (centavos por vídeo).</span>` : ""}`;
    $("[data-capgen]", box).addEventListener("click", gerar);
    const cp = $("[data-capcopy]", box); if (cp) cp.addEventListener("click", copiar);
    $$("[data-seek]", box).forEach((b) => b.addEventListener("click", () => { const v = $("#video"); v.currentTime = +b.dataset.seek; v.play().catch(() => {}); }));
    $$("[data-cap]", box).forEach((inp) => {
      inp.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") { e.preventDefault(); inp.blur(); } });
      inp.addEventListener("change", () => { lerTitulos(); salvar(); });
    });
    $$("[data-capdel]", box).forEach((b) => b.addEventListener("click", () => { lerTitulos(); E.caps.itens.splice(+b.dataset.capdel, 1); salvar(); }));
  }

  async function carregarCaps() {
    if (!S.P) return;
    const pid = S.P.id;
    try { const c = await api("GET", `/api/projects/${pid}/capitulos`); if (S.P && S.P.id === pid) { E.caps = c; desenharCaps(); } } catch (_) {}
  }

  async function gerar() {
    if (E.caps && E.caps.itens.length && !confirm("Gerar de novo troca os capítulos atuais, inclusive os títulos que você mudou. Continuar?")) return;
    E.carregando = true; desenharCaps();
    try { E.caps = await api("POST", `/api/projects/${S.P.id}/capitulos`, { ia: true }); toast(`${E.caps.itens.length} capítulos criados`); }
    catch (e) { toast(e.message, true); }
    E.carregando = false; desenharCaps();
  }

  function lerTitulos() {
    $$("#cap-box [data-cap]").forEach((inp) => { const x = E.caps.itens[+inp.dataset.cap]; if (x && inp.value.trim()) x.titulo = inp.value.trim(); });
  }

  async function salvar() {
    const itens = E.caps.itens.map((x) => ({ t: x.t, titulo: x.titulo }));
    try { E.caps = await api("PUT", `/api/projects/${S.P.id}/capitulos`, { itens }); desenharCaps(); }
    catch (e) { toast(e.message, true); }
  }

  async function copiar() {
    const txt = (E.caps || {}).texto || "";
    try { await navigator.clipboard.writeText(txt); toast("Capítulos copiados. Cole na descrição do vídeo no YouTube."); }
    catch (_) { prompt("Copie os capítulos:", txt); }
  }

  /* ---------------- publicar: inserir capítulos na descrição ---------------- */
  async function publicar(r) {
    const box = $("#pub-caps"); box.classList.add("hidden");
    const completo = r.completo || /^editado-/.test(r.file || "");
    if (!completo) return;
    let c;
    try { c = await api("GET", `/api/projects/${r.project}/capitulos`); } catch (_) { return; }
    if (!c.itens || c.itens.length < 3) return;
    box.classList.remove("hidden");
    $("#pub-caps-info").textContent = `${c.itens.length} capítulos prontos (o YouTube mostra na barra do vídeo)`;
    $("#pub-caps-add").onclick = () => {
      const ta = $("#pub-caption");
      if (!ta.value.includes(c.texto)) ta.value = (ta.value.trim() ? ta.value.trim() + "\n\n" : "") + "Capítulos:\n" + c.texto;
      $("#pub-caps-info").textContent = "Inseridos no fim da legenda.";
    };
  }

  function montar() {
    E.perfis = null; E.caps = null; E.carregando = false;
    desenharPerfis(); desenharCaps();
    carregarPerfis(); carregarCaps();
  }

  window.E2 = { montar, recalcular, publicar };
})();
