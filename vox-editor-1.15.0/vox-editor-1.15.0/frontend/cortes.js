/* VOX Editor 1.6 — Edição automática 2.0 (parte 2): nota de cada corte com os motivos
   e título, legenda e hashtags sugeridos para cada rede (YouTube Shorts, Instagram Reels, TikTok e Facebook Reels).
   Usa as funções do app.js ($, $$, api, esc, toast, S, saveBrand). */
(function () {
  const REDES = ["youtube", "instagram", "tiktok", "facebook"];
  const NOME = { youtube: "YouTube", instagram: "Instagram", tiktok: "TikTok", facebook: "Facebook" };
  const COR = { youtube: "#FF3040", instagram: "#E1306C", tiktok: "#25F4EE", facebook: "#3B8CFF" };
  const LIM = { youtube: { t: 100, l: 4900, h: 5 }, instagram: { l: 2200, h: 5, teto: 5 }, tiktok: { l: 2200, h: 5 }, facebook: { l: 2200, h: 3 } };
  const CRIT = [["gancho", "Gancho", 30], ["ideia", "Ideia completa", 25], ["emocao", "Emoção", 20], ["ritmo", "Ritmo", 15], ["duracao", "Duração", 10]];
  const FONTE = { auto: "sugestão automática", ia: "escrito pela IA", editado: "editado por você" };
  const V = { clip: null, rede: "youtube", t: null, ocupado: false, pub: null };
  const iaLigada = () => { const ai = (S.cfg || {}).ai || {}; return ai.provider && ai.provider !== "none" && ai.api_key_set; };
  const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };
  const ler = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };
  const semAcento = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  /* ---------------- hashtags (mesmas regras do servidor) ---------------- */
  function tag(p) {
    const t = String(p || "").trim().replace(/^#+/, "").toLowerCase().replace(/[^\p{L}\p{N}_]+/gu, "");
    return t.length >= 2 ? "#" + t : "";
  }
  function limpar(lista) {
    const out = [], vistos = new Set();
    (Array.isArray(lista) ? lista : [lista]).forEach((x) => String(x || "").split(/[\s,;]+/).forEach((parte) => {
      const t = tag(parte), k = semAcento(t);
      if (t && !vistos.has(k)) { vistos.add(k); out.push(t); }
    }));
    return out;
  }
  function textoFinal(item, fixas, net) {
    let proprias = limpar(item.hashtags || []), fx = limpar(fixas || []);
    const teto = (LIM[net] || {}).teto;
    if (teto) {
      fx = fx.slice(0, teto);
      const ch = new Set(fx.map(semAcento));
      proprias = proprias.filter((x) => !ch.has(semAcento(x))).slice(0, Math.max(0, teto - fx.length));
    }
    const tags = limpar([...proprias, ...fx]), leg = String(item.legenda || "").trim();
    return tags.length ? (leg + (leg ? "\n\n" : "") + tags.join(" ")).trim() : leg;
  }

  /* ---------------- chips no cartão do corte ---------------- */
  function chips(c) {
    const m = ((c.avaliacao || {}).motivos) || [];
    if (!m.length) return "";
    const bons = m.filter((x) => x.ok).slice(0, 2), alerta = m.find((x) => !x.ok);
    const lista = [...bons, ...(alerta ? [alerta] : [])];
    return `<div class="motivos">${lista.map((x) => `<span class="mtv ${x.ok ? "ok" : "al"}" title="${esc(x.dica || "")}">${x.ok ? "" : "! "}${esc(x.t)}</span>`).join("")}</div>`;
  }

  /* ---------------- nota do corte ---------------- */
  function desenharNota(c) {
    const box = $("#s-nota");
    const av = c && c.avaliacao;
    if (!av || !av.nota) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const deg = Math.round(av.nota * 3.6);
    box.innerHTML = `
      <div class="nota-top">
        <div class="nota-ring n-${av.nivel}" style="--deg:${deg}deg" aria-hidden="true"><b>${av.nota}</b></div>
        <div class="nota-tx"><strong>Nota do corte: <span class="t-${av.nivel}">${esc(av.rotulo)}</span></strong>
          <span class="hint">${av.ia ? `Junta a análise do programa (${av.local}) com a nota da IA (${av.ia})` : "Calculada pelo programa, sem gastar API"}</span></div>
      </div>
      <div class="crit">${CRIT.map(([k, n, mx]) => {
        const v = (av.criterios || {})[k] || 0;
        return `<div class="crit-row"><span>${n}</span><i><b style="width:${Math.round((v / mx) * 100)}%"></b></i><em>${v}/${mx}</em></div>`;
      }).join("")}</div>
      <ul class="mtv-list">${(av.motivos || []).map((m) => `
        <li class="${m.ok ? "ok" : "al"}"><span class="mi" aria-hidden="true">${m.ok ? "✓" : "!"}</span>
          <span><b>${esc(m.t)}</b>${m.dica ? `<em>${esc(m.dica)}</em>` : ""}</span></li>`).join("")}</ul>
      ${c.reason && av.ia ? `<p class="hint nota-ia">A IA diz: ${esc(c.reason)}</p>` : ""}`;
  }

  /* ---------------- textos por rede ---------------- */
  function itemAtual() { return ((V.clip || {}).redes || {})[V.rede] || { titulo: "", legenda: "", hashtags: [] }; }

  function desenharRedes(c) {
    const box = $("#s-redes");
    if (!c || !c.redes || !c.redes.youtube) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const it = itemAtual(), lim = LIM[V.rede], fixas = c.hashtags_fixas || [];
    const nTags = limpar(it.hashtags).length;
    box.innerHTML = `
      <div class="row between"><strong>Texto para cada rede</strong><span class="hint rd-fonte">${esc(FONTE[c.redes_fonte] || "")}</span></div>
      <div class="pr-tabs" role="tablist" aria-label="Rede">${REDES.map((n) => `
        <button type="button" role="tab" class="pr-tab" aria-selected="${n === V.rede}" data-rede="${n}">
          <i style="background:${COR[n]}"></i>${NOME[n]}</button>`).join("")}</div>
      ${lim.t ? `<label class="field"><span class="lbl">Título <b class="cnt" data-cnt="titulo">${(it.titulo || "").length}/${lim.t}</b></span>
        <input type="text" data-rf="titulo" maxlength="${lim.t}" value="${esc(it.titulo || "")}"></label>` : ""}
      <label class="field"><span class="lbl">${V.rede === "youtube" ? "Descrição" : "Legenda"} <b class="cnt" data-cnt="legenda">${(it.legenda || "").length}</b></span>
        <textarea data-rf="legenda" rows="4" maxlength="${lim.l}">${esc(it.legenda || "")}</textarea></label>
      <label class="field"><span class="lbl">Hashtags <b class="cnt ${nTags > lim.h ? "over" : ""}" data-cnt="hashtags">${nTags} de até ${lim.h}</b></span>
        <input type="text" data-rf="hashtags" value="${esc(limpar(it.hashtags).join(" "))}" placeholder="#fé #pregação"></label>
      ${fixas.length ? `<p class="hint rd-fixas">+ fixas da marca: ${esc(fixas.join(" "))}${V.rede === "instagram" && limpar([...it.hashtags, ...fixas]).length > 5 ? " (o Instagram aceita só 5: as últimas sugeridas saem)" : ""}</p>` : ""}
      <div class="row rd-acts">
        <button type="button" class="btn small primary" data-rcopy>Copiar texto pronto</button>
        ${iaLigada() ? `<button type="button" class="btn small" data-ria ${V.ocupado ? "disabled" : ""}>${V.ocupado ? "Escrevendo…" : "Reescrever com IA"}</button>` : ""}
        ${c.redes_fonte && c.redes_fonte !== "auto" ? `<button type="button" class="btn small ghost" data-rauto>Voltar ao automático</button>` : ""}
      </div>
      ${iaLigada() ? "" : `<p class="hint">Sem IA, os textos saem da própria fala do corte. Com o Claude ligado, ele escreve títulos e legendas mais criativos (centavos).</p>`}
      <details class="rd-fixas-cfg" ${fixas.length ? "" : "open"}>
        <summary>Hashtags fixas da marca</summary>
        <input type="text" id="rd-fixas" value="${esc(fixas.join(" "))}" placeholder="#minhaigreja #nomedocanal" aria-label="Hashtags fixas da marca">
        <span class="hint">Vão no fim do texto de todas as redes, em todos os cortes.</span>
      </details>`;
    $$("[data-rede]", box).forEach((b) => b.addEventListener("click", () => { V.rede = b.dataset.rede; guardar("vox-rede", V.rede); desenharRedes(V.clip); }));
    $(".pr-tabs", box).addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const i = REDES.indexOf(V.rede);
      V.rede = REDES[(i + (e.key === "ArrowRight" ? 1 : REDES.length - 1)) % REDES.length];
      desenharRedes(V.clip); const b = $(`[data-rede="${V.rede}"]`, box); if (b) b.focus();
    });
    $$("[data-rf]", box).forEach((inp) => {
      inp.addEventListener("keydown", (e) => e.stopPropagation());
      inp.addEventListener("input", () => editar(inp.dataset.rf, inp.value));
      if (inp.dataset.rf === "hashtags") inp.addEventListener("blur", () => { inp.value = limpar(inp.value).join(" "); });
    });
    $("[data-rcopy]", box).addEventListener("click", copiar);
    const ia = $("[data-ria]", box); if (ia) ia.addEventListener("click", () => refazer(true));
    const au = $("[data-rauto]", box); if (au) au.addEventListener("click", () => refazer(false));
    const fx = $("#rd-fixas");
    fx.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") { e.preventDefault(); fx.blur(); } });
    fx.addEventListener("change", salvarFixas);
  }

  function editar(campo, valor) {
    const c = V.clip; if (!c) return;
    const it = c.redes[V.rede] = { ...itemAtual() };
    if (campo === "hashtags") it.hashtags = limpar(valor);
    else it[campo] = valor;
    const cnt = $(`#s-redes [data-cnt="${campo}"]`);
    if (cnt) {
      if (campo === "hashtags") { const n = it.hashtags.length; cnt.textContent = `${n} de até ${LIM[V.rede].h}`; cnt.classList.toggle("over", n > LIM[V.rede].h); }
      else cnt.textContent = campo === "titulo" ? `${valor.length}/${LIM[V.rede].t}` : String(valor.length);
    }
    clearTimeout(V.t);
    const id = c.id, redes = JSON.parse(JSON.stringify(c.redes));
    V.pendente = true;
    V.flush = async () => {
      clearTimeout(V.t);
      if (!V.pendente) return;
      V.pendente = false;
      try {
        S.P = await api("PUT", `/api/projects/${S.P.id}/clips/${id}`, { redes });
        const novo = S.P.clips.find((x) => x.id === id);
        if (novo && V.clip && V.clip.id === id) { V.clip = novo; const f = $("#s-redes .rd-fonte"); if (f) f.textContent = FONTE[novo.redes_fonte] || ""; }
      } catch (e) { toast(e.message, true); }
    };
    V.t = setTimeout(V.flush, 700);
  }

  async function copiar() {
    const c = V.clip; if (!c) return;
    const it = itemAtual(), txt = textoFinal(it, c.hashtags_fixas, V.rede);
    const tudo = V.rede === "youtube" && it.titulo ? `${it.titulo}\n\n${txt}` : txt;
    try { await navigator.clipboard.writeText(tudo); toast(`Texto do ${NOME[V.rede]} copiado`); }
    catch (_) { prompt("Copie o texto:", tudo); }
  }

  async function refazer(ia) {
    const c = V.clip; if (!c) return;
    if (!ia && !confirm("Voltar às sugestões automáticas? O que você escreveu nas 4 redes deste corte será trocado.")) return;
    V.ocupado = ia; if (ia) desenharRedes(c);
    try {
      const r = await api("POST", `/api/projects/${S.P.id}/clips/${c.id}/redes`, { ia });
      S.P = r.projeto;
      V.clip = S.P.clips.find((x) => x.id === c.id) || null;
      toast(ia ? "A IA escreveu os textos das 4 redes" : "Sugestões automáticas de volta");
    } catch (e) { toast(e.message, true); }
    V.ocupado = false; desenharRedes(V.clip);
  }

  async function salvarFixas() {
    const fixas = limpar($("#rd-fixas").value);
    await saveBrand({ hashtags: fixas.join(" ") }, false);
    if (!S.P) return;
    try { S.P = await api("GET", `/api/projects/${S.P.id}`); } catch (_) { return; }
    if (V.clip) V.clip = S.P.clips.find((x) => x.id === V.clip.id) || null;
    desenharRedes(V.clip);
    toast(fixas.length ? "Hashtags fixas salvas" : "Hashtags fixas removidas");
  }

  /* ---------------- seleção e atualização ---------------- */
  function selecionar(c) {
    if ((!c || !V.clip || V.clip.id !== c.id) && V.pendente && V.flush) V.flush();  // salva o que estava sendo digitado
    V.clip = c;
    desenharNota(c); desenharRedes(c);
  }

  function atualizar() {
    if (!V.clip || !S.P) return;
    const novo = (S.P.clips || []).find((x) => x.id === V.clip.id);
    if (!novo) { selecionar(null); return; }
    const editando = document.activeElement && document.activeElement.closest && document.activeElement.closest("#s-redes");
    if (editando || V.pendente) { V.clip = { ...novo, redes: V.clip.redes }; desenharNota(novo); return; }
    if (JSON.stringify(novo.avaliacao) !== JSON.stringify(V.clip.avaliacao)) desenharNota(novo);
    const mudouTexto = JSON.stringify([novo.redes, novo.redes_fonte, novo.hashtags_fixas]) !== JSON.stringify([V.clip.redes, V.clip.redes_fonte, V.clip.hashtags_fixas]);
    V.clip = novo;
    if (mudouTexto) desenharRedes(novo);
  }

  /* ---------------- publicar: texto próprio de cada rede ---------------- */
  function pubSalvarAtual() {
    if (!V.pub || !V.pub.rede) return;
    V.pub.txt[V.pub.rede] = { title: $("#pub-title").value, caption: $("#pub-caption").value };
  }

  function pubMostrar(net) {
    pubSalvarAtual();
    V.pub.rede = net;
    const t = V.pub.txt[net] || { title: "", caption: "" };
    $("#pub-title").value = t.title || V.pub.txt.youtube.title || "";
    $("#pub-caption").value = t.caption || "";
    $("#pub-title-wrap").classList.toggle("hidden", net !== "youtube");
    $$("#pub-redes-tabs [data-prede]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.prede === net)));
  }

  function pubMarcarTabs() {
    const marcadas = new Set($$("#pub-nets input:checked").map((x) => x.value));
    $$("#pub-redes-tabs [data-prede]").forEach((b) => b.classList.toggle("off", !marcadas.has(b.dataset.prede)));
    if (V.pub && !$("#pub-mesmo").checked && !marcadas.has(V.pub.rede)) {
      const prox = REDES.find((n) => marcadas.has(n) && V.pub.txt[n]);
      if (prox) pubMostrar(prox);
    }
  }

  async function publicar(r, alvos) {
    V.pub = null;
    const box = $("#pub-redes");
    box.classList.add("hidden"); $("#pub-title-wrap").classList.remove("hidden");
    $("#pub-mesmo").checked = false;
    if (!r.clip || !r.project) return;
    let d;
    try { d = await api("GET", `/api/projects/${r.project}/clips/${r.clip}/redes`); } catch (_) { return; }
    if (!d || !d.prontos || !d.prontos.youtube) return;
    const nets = REDES.filter((n) => alvos && alvos[n]);
    if (!nets.length) return;
    V.pub = { txt: {}, rede: null };
    nets.forEach((n) => (V.pub.txt[n] = { title: d.prontos[n].titulo || d.prontos.youtube.titulo || "", caption: d.prontos[n].legenda || "" }));
    $("#pub-redes-info").textContent = d.fonte === "ia" ? "· escrito pela IA" : d.fonte === "editado" ? "· do jeito que você deixou" : "· sugerido pelo programa";
    $("#pub-redes-tabs").innerHTML = nets.map((n) => `<button type="button" role="tab" class="pr-tab" data-prede="${n}" aria-selected="false"><i style="background:${COR[n]}"></i>${NOME[n]}</button>`).join("");
    $$("#pub-redes-tabs [data-prede]").forEach((b) => b.addEventListener("click", () => pubMostrar(b.dataset.prede)));
    box.classList.remove("hidden");
    const marcadas = $$("#pub-nets input:checked").map((x) => x.value);
    V.pub.rede = null;
    pubMostrar(nets.find((n) => marcadas.includes(n)) || nets[0]);
    pubMarcarTabs();
  }

  function textosPublicar(nets) {
    if (!V.pub || $("#pub-redes").classList.contains("hidden") || $("#pub-mesmo").checked) return null;
    pubSalvarAtual();
    const out = {};
    nets.filter((n) => V.pub.txt[n]).forEach((n) => (out[n] = { title: V.pub.txt[n].title || V.pub.txt.youtube && V.pub.txt.youtube.title || "", caption: V.pub.txt[n].caption }));
    return Object.keys(out).length ? out : null;
  }

  function setup() {
    S.sort = ler("vox-ordem") === "nota" ? "nota" : "video";
    V.rede = REDES.includes(ler("vox-rede")) ? ler("vox-rede") : "youtube";
    $$("#s-sort .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.v === S.sort);
      b.addEventListener("click", () => {
        S.sort = b.dataset.v; guardar("vox-ordem", S.sort);
        $$("#s-sort .seg-btn").forEach((x) => x.classList.toggle("active", x === b));
        if (S.P) renderClipGrid();
      });
    });
    $("#pub-nets").addEventListener("change", pubMarcarTabs);
    $("#pub-mesmo").addEventListener("change", () => {
      const mesmo = $("#pub-mesmo").checked;
      $("#pub-redes-tabs").classList.toggle("hidden", mesmo);
      if (!V.pub) return;
      if (mesmo) { pubSalvarAtual(); $("#pub-title-wrap").classList.remove("hidden"); $("#pub-title").value = (V.pub.txt.youtube || {}).title || $("#pub-title").value; }
      else { const r = V.pub.rede; V.pub.rede = null; pubMostrar(r); }
    });
  }

  window.V16 = { chips, selecionar, atualizar, publicar, textosPublicar, textoFinal, limpar };
  setup();
})();
