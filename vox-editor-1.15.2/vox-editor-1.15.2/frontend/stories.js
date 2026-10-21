"use strict";
/* v1.15 — Stories do Culto: vídeo ou foto + evento + modelo = story 9:16 com a capa do culto, postado nos Stories.
   As prévias são feitas pelo próprio programa (mesmo caminho da exportação): o que aparece aqui é o que sai. */
(function () {
  const T = { st: null, pid: null, itens: [], antigos: [], sel: new Set(), foco: null, modelo: "ouro", cor: "dourado",
    logo: "", evento: "", previas: {}, gen: 0, timer: null, ocupado: false, enviando: 0, carregado: false };
  const PREF = "vox.stories.opcoes";
  const guardar = (o) => { try { localStorage.setItem(PREF, JSON.stringify(o)); } catch (_) {} };
  const lerPref = () => { try { return JSON.parse(localStorage.getItem(PREF) || "{}") || {}; } catch (_) { return {}; } };
  const tipoDe = (f) => {
    const n = (f.name || "").toLowerCase();
    if ((f.type || "").startsWith("video/") || /\.(mp4|mov|m4v|mkv|webm|avi|mts|3gp)$/.test(n)) return "video";
    if ((f.type || "").startsWith("image/") || /\.(jpe?g|png|webp|bmp|gif|heic|heif)$/.test(n)) return "image";
    return "";
  };
  const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
  const extenso = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || ""); return m ? `${m[3]} de ${MESES[+m[2] - 1]} de ${m[1]}` : ""; };
  const hojeIso = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
  const semAcento = (t) => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  /* ---------------- opções ---------------- */
  function opcoes() {
    const l3 = [$("#st-l3").value.trim(), $("#st-data").checked ? extenso($("#st-dia").value) : ""].filter(Boolean).join(" · ");
    return { modelo: T.modelo, cor: T.cor, linha1: $("#st-l1").value.trim(), destaque: $("#st-l2").value.trim(), linha3: l3,
      logo: T.logo, enquadrar: $("#st-enq").value, tamanho: $("#st-tam").value, evento: T.evento, data_na_tela: $("#st-data").checked,
      fonte_destaque: T.fd || "", fonte_linha1: $("#st-fonte1").value || "" };
  }
  function lembrar() {
    const o = opcoes();
    guardar({ modelo: o.modelo, cor: o.cor, logo: o.logo, enquadrar: o.enquadrar, tamanho: o.tamanho, data_na_tela: o.data_na_tela,
      fonte_destaque: o.fonte_destaque, fonte_linha1: o.fonte_linha1,
      redes: $$("#st-redes input:checked").map((x) => x.value), auto: $("#st-auto") ? $("#st-auto").checked : true });
  }

  async function carregar() {
    let st;
    try { st = await api("GET", "/api/stories/status"); } catch (e) { toast(e.message, true); return; }
    T.st = st; T.pid = st.pid;
    if (!T.carregado) {
      const p = Object.assign({}, st.ultimo || {}, lerPref());
      if (p.modelo) T.modelo = p.modelo;
      if (p.cor) T.cor = p.cor;
      if (p.logo != null) T.logo = p.logo;
      T.fd = p.fonte_destaque || ""; T.f1pref = p.fonte_linha1 || "";
      $("#st-enq").innerHTML = Object.entries(st.enquadrar).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
      $("#st-tam").innerHTML = Object.entries(st.tamanhos).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
      if (p.enquadrar) $("#st-enq").value = p.enquadrar;
      if (p.tamanho) $("#st-tam").value = p.tamanho;
      $("#st-data").checked = !!p.data_na_tela;
      $("#st-dia").value = hojeIso();
      T.prefRedes = p.redes; T.prefAuto = p.auto;
      T.carregado = true;
    }
    if (!st.logos.some((l) => l.id === T.logo) && T.logo !== "nenhum") T.logo = st.logos.length ? st.logos[0].id : "nenhum";
    desenharEventos(); desenharCores(); desenharLogos(); desenharRedes(); desenharModelos(); desenharFontes();
    if (!T.evento && !$("#st-l2").value) escolherEvento(st.sugestao[0], true);
    else desenharSug();
    listar();
  }

  /* ---------------- eventos ---------------- */
  const evPorId = (id) => { for (const g of (T.st || {}).grupos || []) for (const e of g.eventos) if (e.id === id) return e; return null; };
  const nomeEv = (e) => [e.linha1, e.destaque].filter(Boolean).join(" ");

  function desenharSug() {
    const sug = (T.sugestao || (T.st || {}).sugestao || []).map(evPorId).filter(Boolean);
    $("#st-sug").innerHTML = sug.length ? `<span class="hint">Sugeridos${T.sugData ? " para " + esc(T.sugData) : " para hoje"}:</span>` +
      sug.map((e) => `<button type="button" class="chip-btn ${e.id === T.evento ? "active" : ""}" data-ev="${e.id}">${esc(nomeEv(e))}</button>`).join("") : "";
  }

  function desenharEventos() {
    const q = semAcento($("#st-busca").value.trim());
    const html = (T.st.grupos || []).map((g) => {
      const evs = g.eventos.filter((e) => !q || semAcento(nomeEv(e)).includes(q));
      if (!evs.length) return "";
      return `<div class="st-grupo"><span class="st-gnome">${esc(g.nome)}</span><div class="st-evs">` +
        evs.map((e) => `<button type="button" class="st-ev ${e.meu ? "meu" : ""} ${e.id === T.evento ? "active" : ""}" data-ev="${e.id}">${e.linha1 ? `<small>${esc(e.linha1)}</small>` : ""}<b${e.fonte_destaque ? ` style="font-family:'vox-${e.fonte_destaque}'"` : ""}>${esc(e.destaque)}</b>${e.meu ? `<span class="st-ev-x" data-ev-x="${e.id}" role="button" aria-label="Apagar meu evento">×</span>` : ""}</button>`).join("") +
        `</div></div>`;
    }).join("");
    $("#st-eventos").innerHTML = html + `<div class="st-grupo"><span class="st-gnome">Outro</span><div class="st-evs">
      <button type="button" class="st-ev ${T.evento === "outro" ? "active" : ""}" data-ev="outro"><small>Não achou?</small><b>+ Criar evento</b></button></div></div>`;
  }

  function escolherEvento(id, silencioso) {
    if (!id) return;
    T.evento = id;
    if (id === "outro") {
      $("#st-l1").value = ""; $("#st-l2").value = ""; $("#st-l1").focus();
      toast("Escreva o nome do evento, escolha a letra e toque em “Salvar como meu evento”.");
    } else {
      const e = evPorId(id);
      if (!e) return;
      $("#st-l1").value = e.linha1; $("#st-l2").value = e.destaque;
      if (e.meu) {  // meu evento traz as letras que foram salvas com ele
        T.fd = e.fonte_destaque || "";
        $("#st-fonte1").value = [...$("#st-fonte1").options].some((o) => o.value === e.fonte_linha1) ? e.fonte_linha1 : "";
      }
    }
    desenharFontes(); botaoSalvar();
    $$("#st-eventos .st-ev, #st-sug .chip-btn").forEach((b) => b.classList.toggle("active", b.dataset.ev === id));
    desenharSug();
    if (!silencioso) agendarPrevias(150);
    else agendarPrevias(50);
  }

  /* ---------------- cores, logos e redes ---------------- */
  function desenharCores() {
    $("#st-cores").innerHTML = T.st.cores.map((c) => `<button type="button" class="st-cor ${c.id === T.cor ? "active" : ""}" data-cor="${c.id}" title="${esc(c.nome)}" aria-label="${esc(c.nome)}" style="--c:${c.hex}"></button>`).join("");
  }

  function desenharLogos() {
    const ls = T.st.logos || [];
    $("#st-logos").innerHTML = ls.map((l) => `<div class="st-logo ${l.id === T.logo ? "active" : ""}" data-logo="${l.id}" title="${esc(l.nome)}">
        <img src="/api/stories/logos/${l.id}?v=${Date.now() % 1e6}" alt="${esc(l.nome)}">
        ${l.id !== "marca" ? `<button type="button" class="st-logo-x" data-logo-x="${l.id}" aria-label="Apagar logo">×</button>` : ""}</div>`).join("") +
      `<div class="st-logo st-sem ${T.logo === "nenhum" ? "active" : ""}" data-logo="nenhum" title="Sem logo"><span>Sem logo</span></div>
       <button type="button" class="st-logo st-add" id="st-logo-add" title="Enviar logo da igreja"><span>+ Enviar logo</span></button>`;
  }

  function desenharRedes() {
    const r = T.st.redes || {};
    const pref = T.prefRedes;
    $("#st-redes").innerHTML = Object.entries(r).map(([k, n]) => `<label class="hs-check ${n.conectado ? "" : "off"}">
        <input type="checkbox" value="${k}" ${n.conectado ? "" : "disabled"} ${n.conectado && (!pref || pref.includes(k)) ? "checked" : ""}>
        <span>${esc(n.nome)} <em class="hint">${n.conectado ? esc(n.conta) : n.aviso ? esc(n.aviso) : "não conectado"}</em></span></label>`).join("") +
      (Object.values(r).some((n) => n.conectado) ? `<label class="hs-check"><input type="checkbox" id="st-auto" ${T.prefAuto === false ? "" : "checked"}> <span>Postar assim que ficar pronto <em class="hint">(desmarque para só criar e baixar)</em></span></label>`
        : `<p class="hint">Conecte o Instagram/Facebook em <a href="#/redes">Redes sociais</a> para postar sozinho. Sem isso, o story fica pronto para baixar.</p>`);
  }

  function redesEscolhidas() {
    const auto = $("#st-auto");
    if (!auto || !auto.checked) return [];
    return $$("#st-redes input[value]:checked").map((x) => x.value);
  }

  async function enviarLogo(f) {
    if (!f) return;
    try {
      const r = await fetch("/api/stories/logos", { method: "POST", headers: { "x-filename": encodeURIComponent(f.name) }, body: f });
      const js = await r.json();
      if (!r.ok) throw new Error(js.detail || "Não deu certo");
      T.st.logos = js.logos; T.logo = js.novo.id;
      desenharLogos(); agendarPrevias(50); lembrar();
      toast("Logo guardado. Ele fica salvo para os próximos stories.");
    } catch (e) { toast(e.message, true); }
  }

  /* ---------------- letras (fontes) ---------------- */
  const carregadas = new Set();
  function carregarFonte(f) {
    if (carregadas.has(f.id) || !window.FontFace) return;
    carregadas.add(f.id);
    const url = f.arquivo ? "/fontes/" + encodeURIComponent(f.arquivo) : "/api/stories/fontes/" + f.id;
    new FontFace("vox-" + f.id, `url(${url})`).load().then((ff) => { document.fonts.add(ff); }).catch(() => {});
  }

  function desenharFontes() {
    if (!T.st || !T.st.fontes) return;
    const fs = T.st.fontes;
    if (T.fd && !fs.some((f) => f.id === T.fd)) T.fd = "";
    fs.forEach(carregarFonte);
    const grupos = {};
    fs.forEach((f) => (grupos[f.grupo] = grupos[f.grupo] || []).push(f));
    const sel = $("#st-fonte1"), v1 = sel.value || T.f1pref || "";
    sel.innerHTML = `<option value="">Automática (do modelo)</option>` + Object.entries(grupos).map(([g, lst]) =>
      `<optgroup label="${esc(g)}">${lst.map((f) => `<option value="${f.id}">${esc(f.nome)}</option>`).join("")}</optgroup>`).join("");
    sel.value = [...sel.options].some((o) => o.value === v1) ? v1 : "";
    T.f1pref = "";
    $("#st-fontes").innerHTML = `<button type="button" class="st-fonte ${!T.fd ? "active" : ""}" data-fonte=""><span class="st-amostra">Aa</span><small>Automática</small></button>` +
      Object.entries(grupos).map(([g, lst]) => `<span class="st-fgrupo">${esc(g)}</span>` + lst.map((f) =>
        `<button type="button" class="st-fonte ${f.id === T.fd ? "active" : ""}" data-fonte="${f.id}" title="${esc(f.nome)}">
          <span class="st-amostra" style="font-family:'vox-${f.id}',serif"></span><small>${esc(f.nome)}</small>
          ${f.id.startsWith("u-") ? `<span class="st-ev-x" data-fonte-x="${f.id}" role="button" aria-label="Apagar letra">×</span>` : ""}</button>`).join("")).join("");
    amostras();
  }

  function amostras() {
    const t = ($("#st-l2").value.trim() || "Culto").slice(0, 14);
    $$("#st-fontes .st-fonte[data-fonte]:not([data-fonte='']) .st-amostra").forEach((el) => { el.textContent = t; });
  }

  async function enviarFonte(f) {
    if (!f) return;
    if (!/\.(ttf|otf)$/i.test(f.name)) { toast("Envie um arquivo de fonte .ttf ou .otf (de sites como fonts.google.com).", true); return; }
    try {
      const r = await fetch("/api/stories/fontes", { method: "POST", headers: { "x-filename": encodeURIComponent(f.name) }, body: f });
      const js = await r.json();
      if (!r.ok) throw new Error(js.detail || "Não deu certo");
      T.st.fontes = js.fontes; T.fd = js.novo.id;
      desenharFontes(); botaoSalvar(); lembrar(); agendarPrevias(50);
      toast("Letra guardada: " + js.novo.nome);
    } catch (e) { toast(e.message, true); }
  }

  /* ---------------- meus eventos ---------------- */
  function botaoSalvar() {
    const b = $("#st-salvar-ev");
    const tem = !!$("#st-l2").value.trim();
    const meu = (T.evento || "").startsWith("m-");
    const livre = !T.evento || T.evento === "outro";
    b.classList.toggle("hidden", !(tem && (livre || meu)));
    b.textContent = meu ? "★ Salvar as letras neste evento" : "★ Salvar como meu evento";
  }

  async function salvarEvento() {
    const o = opcoes();
    if (!o.destaque) { toast("Escreva o nome em destaque.", true); $("#st-l2").focus(); return; }
    try {
      const r = await api("POST", "/api/stories/eventos", { linha1: o.linha1, destaque: o.destaque, fonte_destaque: o.fonte_destaque, fonte_linha1: o.fonte_linha1 });
      Object.assign(T.st, { grupos: r.status.grupos, sugestao: r.status.sugestao });
      T.evento = r.novo.id;
      $("#st-busca").value = "";
      desenharEventos(); desenharSug(); botaoSalvar();
      toast("Salvo em “Meus eventos”. Da próxima vez é só tocar nele.");
    } catch (e) { toast(e.message, true); }
  }

  /* ---------------- arquivos ---------------- */
  function adicionar(lista) {
    for (const f of lista) {
      const tipo = tipoDe(f);
      if (!tipo) { toast(`“${f.name}” não é vídeo nem foto.`, true); continue; }
      if (/\.(heic|heif)$/i.test(f.name)) { toast("Foto HEIC do iPhone ainda não é aceita. No iPhone: Ajustes > Câmera > Formatos > “Mais compatível”.", true); continue; }
      if (T.itens.some((x) => x.f && x.f.name === f.name && x.f.size === f.size && x.st !== "erro")) continue;
      T.itens.push({ f, tipo, st: "fila", pct: 0, url: URL.createObjectURL(f), chave: "n" + Math.random().toString(36).slice(2, 8) });
      if (f.lastModified && T.itens.length === 1) sugerirPorData(new Date(f.lastModified));
    }
    bombear(); desenharArqs();
  }

  async function sugerirPorData(d) {
    const iso = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    if (iso === hojeIso()) return;
    $("#st-dia").value = iso;
    try {
      const r = await api("GET", "/api/stories/sugestao?data=" + iso);
      T.sugestao = r.sugestao; T.sugData = extenso(iso).replace(/ de \d{4}$/, "");
      if (!T.mexeuEvento) escolherEvento(r.sugestao[0], true); else desenharSug();
    } catch (_) {}
  }

  function bombear() {
    while (T.enviando < 2) {
      const it = T.itens.find((x) => x.st === "fila");
      if (!it) break;
      enviar(it);
    }
  }

  function enviar(it) {
    T.enviando++; it.st = "enviando";
    const xhr = new XMLHttpRequest(); it.xhr = xhr;
    xhr.open("POST", "/api/stories/arquivo");
    xhr.setRequestHeader("x-filename", encodeURIComponent(it.f.name));
    if (it.f.lastModified) xhr.setRequestHeader("x-modificado", String(it.f.lastModified));
    xhr.setRequestHeader("x-fuso", String(new Date().getTimezoneOffset()));
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) { it.pct = e.loaded / e.total; desenharArq(it); } };
    const fim = () => { T.enviando--; it.xhr = null; bombear(); desenharArqs(); };
    xhr.onload = () => {
      if (xhr.status === 200) {
        it.md = JSON.parse(xhr.responseText); it.st = "ok"; it.pct = 1;
        if (T.autoSel) { T.sel.delete(T.autoSel); if (T.foco === T.autoSel) T.foco = null; T.autoSel = null; }  // o antigo marcado sozinho sai
        T.sel.add(it.md.id);
        if (!T.foco) { T.foco = it.md.id; agendarPrevias(50); }
      } else {
        let m = xhr.statusText; try { m = JSON.parse(xhr.responseText).detail || m; } catch (_) {}
        it.st = "erro"; it.erro = m || "Falhou";
        toast(`${it.f.name}: ${it.erro}`, true);
      }
      fim();
    };
    xhr.onerror = () => { it.st = "erro"; it.erro = "A conexão caiu durante o envio."; fim(); };
    xhr.onabort = () => { fim(); };
    xhr.send(it.f);
  }

  const durTxt = (s) => s ? (s >= 60 ? `${Math.floor(s / 60)}min${String(Math.round(s % 60)).padStart(2, "0")}` : `${Math.round(s)} s`) : "";

  function htmlArq(it) {
    const id = it.md ? it.md.id : "";
    const marcado = id && T.sel.has(id);
    const midia = it.url ? (it.tipo === "video" ? `<video src="${it.url}#t=1" muted preload="metadata"></video>` : `<img src="${it.url}" alt="">`)
      : `<img src="/api/stories/itens/${id}/quadro" alt="" loading="lazy">`;
    const partes = it.md && it.tipo === "video" && it.md.duracao > 60 ? ` · ${Math.min(15, Math.ceil(it.md.duracao / 59))} partes` : "";
    return `<div class="st-arq ${marcado ? "sel" : ""} ${it.st === "erro" ? "erro" : ""} ${id && id === T.foco ? "foco" : ""}" data-k="${it.chave}" data-id="${id}" title="${esc(it.f ? it.f.name : it.md.nome)}">
      ${midia}
      <span class="rs-tag">${it.tipo === "video" ? "Vídeo" + (it.md ? " " + durTxt(it.md.duracao) : "") + partes : "Foto"}</span>
      ${it.st === "ok" ? `<span class="st-check" aria-hidden="true">${marcado ? "✓" : ""}</span>` : ""}
      ${it.st === "enviando" || it.st === "fila" ? `<span class="rs-barra"><b style="width:${Math.round(it.pct * 100)}%"></b></span>` : ""}
      ${it.st === "erro" ? `<span class="rs-nome">${esc(it.erro || "Erro")}</span>` : ""}
      <button type="button" class="rs-x" data-x aria-label="Tirar">×</button></div>`;
  }

  function todos() { return [...T.itens, ...T.antigos.filter((a) => !T.itens.some((x) => x.md && x.md.id === a.md.id))]; }

  function desenharArqs() {
    const lst = todos();
    $("#st-arqs").innerHTML = lst.map(htmlArq).join("");
    $("#st-arqs-dica").classList.toggle("hidden", lst.filter((x) => x.st === "ok").length < 2);
    contarCriar();
  }

  function desenharArq(it) {
    const el = $(`#st-arqs [data-k="${it.chave}"]`);
    if (el) el.outerHTML = htmlArq(it);
  }

  function contarCriar() {
    const n = [...T.sel].length, b = $("#st-criar");
    if (T.ocupado) return;
    b.textContent = n > 1 ? `Criar ${n} stories` : "Criar story";
  }

  /* ---------------- prévias dos modelos ---------------- */
  function desenharModelos() {
    const tem = !!T.foco;
    $("#st-mod-hint").textContent = tem ? "Clique para escolher — ou em “Criar com este”" : "Envie um vídeo ou foto para ver as prévias";
    $("#st-modelos").innerHTML = T.st.modelos.map((m) => `<div class="st-mod ${m.id === T.modelo ? "active" : ""}" data-mod="${m.id}" tabindex="0" role="button" aria-label="${esc(m.nome)}">
        <div class="st-tela">${T.previas[m.id] ? `<img src="${T.previas[m.id]}" alt="">` : `<span class="st-carr">${tem ? "Preparando…" : ""}</span>`}</div>
        <div class="st-mod-rod"><b>${esc(m.nome)}</b><span class="hint">${esc(m.desc)}</span>
        <button type="button" class="btn small primary" data-criar-com="${m.id}" ${tem ? "" : "disabled"}>Criar com este</button></div></div>`).join("");
  }

  function agendarPrevias(ms) {
    clearTimeout(T.timer);
    T.timer = setTimeout(previas, ms == null ? 450 : ms);
  }

  async function previas() {
    if (!T.foco || !T.st) { desenharModelos(); return; }
    if ($("#st-modelos [data-criar-com][disabled]") || !$("#st-modelos .st-mod")) desenharModelos();
    const gen = ++T.gen;
    const o = opcoes();
    if (!o.destaque) return;
    $$("#st-modelos .st-tela").forEach((t) => t.classList.add("carregando"));
    const ordem = [T.modelo, ...T.st.modelos.map((m) => m.id).filter((x) => x !== T.modelo)];
    let i = 0;
    const um = async () => {
      while (i < ordem.length) {
        const m = ordem[i++];
        try {
          const r = await fetch("/api/stories/previa", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ item: T.foco, ...o, modelo: m }) });
          if (gen !== T.gen) return;
          if (!r.ok) { let msg = r.statusText; try { msg = (await r.json()).detail || msg; } catch (_) {} throw new Error(msg); }
          const url = URL.createObjectURL(await r.blob());
          if (T.previas[m]) URL.revokeObjectURL(T.previas[m]);
          T.previas[m] = url;
          const tela = $(`#st-modelos [data-mod="${m}"] .st-tela`);
          if (tela) { tela.innerHTML = `<img src="${url}" alt="">`; tela.classList.remove("carregando"); }
        } catch (e) {
          if (gen === T.gen && m === T.modelo) toast(e.message, true);
        }
      }
    };
    await Promise.all([um(), um(), um()]);
  }

  /* ---------------- criar ---------------- */
  async function criar(modelo) {
    if (T.ocupado) return;
    if (modelo) { T.modelo = modelo; $$("#st-modelos .st-mod").forEach((x) => x.classList.toggle("active", x.dataset.mod === modelo)); }
    if (T.itens.some((x) => x.st === "fila" || x.st === "enviando")) { toast("Espere terminar de enviar os arquivos.", true); return; }
    const ids = [...T.sel];
    if (!ids.length) { toast("Envie (ou marque) o vídeo ou a foto primeiro.", true); $("#st-arquivos").click(); return; }
    const o = opcoes();
    if (!o.destaque) { toast("Escolha o evento ou escreva o destaque.", true); $("#st-l2").focus(); return; }
    const postar = redesEscolhidas();
    lembrar();
    T.ocupado = true; $("#st-criar").disabled = true; $("#st-criar").textContent = "Criando…";
    try {
      const r = await api("POST", "/api/stories/criar", { itens: ids, opcoes: o, postar });
      await acompanhar(r, postar);
    } catch (e) { toast(e.message, true); andamento(null); }
    T.ocupado = false; $("#st-criar").disabled = false; contarCriar();
  }

  function andamento(tit, pct, msg) {
    const box = $("#st-andamento");
    if (tit == null) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    $("#st-and-tit").textContent = tit;
    $("#st-and-pct").textContent = Math.round((pct || 0) * 100) + "%";
    $("#st-and-bar").style.width = Math.round((pct || 0) * 100) + "%";
    $("#st-and-msg").textContent = msg || "";
  }

  async function acompanhar(r, postar) {
    andamento("Criando os stories…", 0, "Na fila…");
    box().scrollIntoView({ behavior: "smooth", block: "nearest" });
    for (;;) {
      await new Promise((ok) => setTimeout(ok, 900));
      let js;
      try { js = await api("GET", "/api/jobs/" + r.pid); } catch (_) { continue; }
      const j = js.find((x) => x.id === r.job);
      if (!j) continue;
      andamento(j.status === "na fila" ? `Na fila${j.posicao ? " (" + j.posicao + "º)" : ""}…` : "Criando os stories…", j.pct || 0, j.msg);
      if (j.status === "concluido") {
        const res = j.result || {};
        const n = res.quantos || 0;
        let msg = `${n} stor${n === 1 ? "y pronto" : "ies prontos"}`;
        if (postar.length && res.postados) msg += " e enviado" + (n === 1 ? "" : "s") + " para os Stories (acompanhe em Publicações)";
        andamento("Pronto!", 1, msg + (res.aviso ? " — " + res.aviso : ""));
        toast(res.aviso || (msg + "!"), !!res.aviso);
        if (window.refreshQueueCount) refreshQueueCount();
        listar();
        setTimeout(() => andamento(null), 9000);
        return;
      }
      if (j.status === "erro" || j.status === "cancelado") { andamento("Não deu certo", 0, j.error || "Cancelado"); toast(j.error || "Cancelado", true); return; }
    }
  }
  const box = () => $("#st-andamento");

  /* ---------------- prontos e anteriores ---------------- */
  async function listar() {
    let r;
    try { r = await api("GET", "/api/stories/itens"); } catch (_) { return; }
    T.pid = r.pid;
    const meus = new Set(T.itens.filter((x) => x.md).map((x) => x.md.id));
    T.antigos = r.itens.filter((x) => !meus.has(x.id)).slice(0, 12).map((md) => ({ md, tipo: md.tipo, st: "ok", chave: "a" + md.id, antigo: true }));
    if (!T.foco && T.antigos.length && !T.itens.length) { T.foco = T.autoSel = T.antigos[0].md.id; T.sel.add(T.foco); agendarPrevias(50); }
    desenharArqs();
    const prontos = [];
    for (const it of r.itens) for (const s of it.saidas || []) prontos.push({ ...s, item: it });
    prontos.sort((a, b) => b.created - a.created);
    $("#st-prontos-pane").classList.toggle("hidden", !prontos.length);
    const quando = (t) => new Date(t * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
    $("#st-prontos").innerHTML = prontos.slice(0, 24).map((s, i) => `<div class="st-pronto" data-i="${i}">
        <div class="st-pthumb" data-play="${i}"><img src="/api/projects/${r.pid}/renders/${encodeURIComponent(s.file)}/thumb" alt="" loading="lazy"><span class="st-play">▶</span></div>
        <div class="st-pinfo"><b>${esc(s.label.replace(/^Story: /, ""))}</b><span class="hint">${durTxt(s.duration)} · ${quando(s.created)}</span>
          <div class="st-pbts">
            <a class="btn small" href="/api/projects/${r.pid}/renders/${encodeURIComponent(s.file)}" download="${esc(s.file)}">Baixar vídeo</a>
            ${s.jpg ? `<a class="btn small ghost" href="/api/projects/${r.pid}/renders/${encodeURIComponent(s.jpg)}" download="${esc(s.jpg)}">Baixar foto</a>` : ""}
            <button type="button" class="btn small primary" data-pub="${i}">Publicar</button>
            <button type="button" class="btn small ghost st-del" data-del="${i}">Excluir</button>
          </div></div></div>`).join("");
    T.prontos = prontos;
    T.todosItens = r.itens;
    desenharResumo();
  }

  /* ---------------- resumo do culto com os arquivos dos stories ---------------- */
  const mesmoDia = (t) => { const a = new Date(t * 1000), b = new Date(); return a.toDateString() === b.toDateString(); };
  function itensDoResumo() {
    const lst = T.todosItens || [];
    const hoje = lst.filter((x) => mesmoDia(x.criado));
    if (hoje.length) return { ids: hoje.map((x) => x.id), lista: hoje, hoje: true };
    const marc = lst.filter((x) => T.sel.has(x.id));
    return { ids: marc.map((x) => x.id), lista: marc, hoje: false };
  }
  function desenharResumo() {
    const r = itensDoResumo();
    const pane = $("#st-resumo-pane");
    pane.classList.toggle("hidden", r.lista.length < 2);
    if (r.lista.length < 2) return;
    const v = r.lista.filter((x) => x.tipo === "video").length, f = r.lista.length - v;
    const partes = [v && `${v} vídeo${v === 1 ? "" : "s"}`, f && `${f} foto${f === 1 ? "" : "s"}`].filter(Boolean).join(" e ");
    $("#st-res-txt").textContent = `Junte ${r.hoje ? "os" : "os marcados:"} ${partes}${r.hoje ? " dos stories de hoje" : ""} num resumão com música, títulos e a sua marca. Abre na Montagem para você ajustar.`;
    const ia = (T.st || {}).ia || {};
    $("#st-res-ia").innerHTML = ia.ligada
      ? `Inteligência artificial <b class="ok">ligada</b> (${esc(ia.nome)}${ia.modelo ? " · " + esc(ia.modelo) : ""}): ela escolhe as frases mais fortes da pregação e o título.`
      : `Inteligência artificial <b>desligada</b>: o programa monta sozinho. Para frases e título escolhidos pela IA, coloque a chave em <a href="#/ia">Inteligência artificial</a>.`;
  }

  async function fazerResumo() {
    if (T.ocupado) return;
    const r = itensDoResumo();
    if (r.ids.length < 2) { toast("Precisa de pelo menos 2 vídeos ou fotos.", true); return; }
    const dur = ($("#st-res-dur .chip-btn.active") || {}).dataset.v || "60";
    const ritmo = ($("#st-res-ritmo .chip-btn.active") || {}).dataset.v || "calmo";
    const titulo = [$("#st-l1").value.trim(), $("#st-l2").value.trim()].filter(Boolean).join(" ") || "Resumo do Culto";
    T.ocupado = true; const b = $("#st-res-criar"); b.disabled = true; b.textContent = "Montando…";
    try {
      const j = await api("POST", "/api/stories/resumo", { itens: r.ids, opcoes: { duracao: dur, ritmo, titulo, evento: T.evento,
        data: $("#st-dia").value || "", cor: ritmo === "animado" ? "vivo" : "cinema" } });
      andamento("Montando o resumo do culto…", 0, "Na fila…");
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 1000));
        let js; try { js = await api("GET", "/api/jobs/" + j.id); } catch (_) { continue; }
        const x = js.find((y) => y.id === j.job); if (!x) continue;
        andamento(x.status === "na fila" ? "Na fila…" : "Montando o resumo do culto…", x.pct || 0, x.msg);
        if (x.status === "concluido") {
          const res = x.result || {};
          andamento("Resumo pronto!", 1, res.aviso || "Abrindo na Montagem…");
          toast(res.aviso || "Resumo montado! Abrindo na Montagem…", !!res.aviso);
          setTimeout(() => { location.hash = "#/p/" + j.id + "/montagem"; }, res.aviso ? 5000 : 1200);
          break;
        }
        if (x.status === "erro" || x.status === "cancelado") { andamento("Não deu certo", 0, x.error || "Cancelado"); toast(x.error || "Cancelado", true); break; }
      }
    } catch (e) { toast(e.message, true); }
    T.ocupado = false; b.disabled = false; b.textContent = "Fazer o resumo do culto";
  }

  /* ---------------- ligar tudo ---------------- */
  function setup() {
    if (!$("#pg-stories")) return;
    $("#st-arquivos").addEventListener("change", (e) => { adicionar([...e.target.files]); e.target.value = ""; });
    const drop = $("#st-drop");
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("sobre"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("sobre"); }));
    drop.addEventListener("drop", (e) => adicionar([...(e.dataTransfer.files || [])]));

    $("#st-arqs").addEventListener("click", async (e) => {
      const card = e.target.closest(".st-arq");
      if (!card) return;
      const k = card.dataset.k, it = todos().find((x) => x.chave === k);
      if (!it) return;
      if (e.target.closest("[data-x]")) {
        if (it.xhr) it.xhr.abort();
        if (it.md) {
          T.sel.delete(it.md.id);
          if (it.antigo && !(await ask("Apagar este arquivo?", "O vídeo/foto enviado sai da lista. Os stories que já saíram dele continuam em Exportados.", null, "Apagar"))) return;
          try { await api("DELETE", "/api/stories/itens/" + it.md.id); } catch (_) {}
          if (T.foco === it.md.id) { T.foco = [...T.sel][0] || null; T.previas = {}; agendarPrevias(50); }
        }
        T.itens = T.itens.filter((x) => x !== it);
        T.antigos = T.antigos.filter((x) => x !== it);
        if (it.url) URL.revokeObjectURL(it.url);
        desenharArqs(); desenharModelos();
        return;
      }
      if (!it.md) return;
      const id = it.md.id;
      T.autoSel = null;
      if (T.sel.has(id) && T.foco === id) T.sel.delete(id);
      else { T.sel.add(id); }
      if (T.sel.has(id) && T.foco !== id) { T.foco = id; agendarPrevias(50); }
      if (!T.sel.has(T.foco)) { const n = [...T.sel][0]; if (n && n !== T.foco) { T.foco = n; agendarPrevias(50); } }
      desenharArqs();
    });

    const cliqueEv = async (e) => {
      const x = e.target.closest("[data-ev-x]");
      if (x) {
        e.stopPropagation();
        if (!(await ask("Apagar este evento?", "Ele sai de “Meus eventos”. Os stories já feitos continuam.", null, "Apagar"))) return;
        try { T.st = Object.assign(T.st, (await api("DELETE", "/api/stories/eventos/" + x.dataset.evX)).status); } catch (err) { toast(err.message, true); return; }
        if (T.evento === x.dataset.evX) T.evento = "";
        desenharEventos(); desenharSug(); botaoSalvar(); return;
      }
      const b = e.target.closest("[data-ev]"); if (b) { T.mexeuEvento = true; escolherEvento(b.dataset.ev); }
    };
    $("#st-eventos").addEventListener("click", cliqueEv);
    $("#st-sug").addEventListener("click", cliqueEv);
    $("#st-busca").addEventListener("input", desenharEventos);
    $("#st-busca").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); const b = $("#st-eventos .st-ev"); if (b) { T.mexeuEvento = true; escolherEvento(b.dataset.ev); } }
    });
    ["#st-l1", "#st-l2", "#st-l3"].forEach((s) => $(s).addEventListener("input", () => {
      if (T.evento && T.evento !== "outro") { const e = evPorId(T.evento); if (e && (e.linha1 !== $("#st-l1").value || e.destaque !== $("#st-l2").value)) { T.evento = ""; desenharEventos(); desenharSug(); } }
      botaoSalvar(); amostras();
      agendarPrevias();
    }));
    $("#st-data").addEventListener("change", () => agendarPrevias(50));
    $("#st-fontes").addEventListener("click", async (e) => {
      const x = e.target.closest("[data-fonte-x]");
      if (x) {
        e.stopPropagation();
        if (!(await ask("Apagar esta letra?", "Ela sai da lista de letras dos stories.", null, "Apagar"))) return;
        try { T.st.fontes = (await api("DELETE", "/api/stories/fontes/" + x.dataset.fonteX)).fontes; } catch (err) { toast(err.message, true); return; }
        if (T.fd === x.dataset.fonteX) T.fd = "";
        desenharFontes(); agendarPrevias(50); lembrar(); return;
      }
      const b = e.target.closest("[data-fonte]"); if (!b) return;
      T.fd = b.dataset.fonte; desenharFontes(); botaoSalvar(); lembrar(); agendarPrevias(50);
    });
    $("#st-fonte1").addEventListener("change", () => { botaoSalvar(); lembrar(); agendarPrevias(50); });
    $("#st-fonte-add").addEventListener("click", () => $("#st-fonte-arq").click());
    $("#st-fonte-arq").addEventListener("change", (e) => { enviarFonte(e.target.files[0]); e.target.value = ""; });
    $("#st-salvar-ev").addEventListener("click", salvarEvento);
    $("#st-dia").addEventListener("change", () => { if (!$("#st-data").checked) $("#st-data").checked = true; agendarPrevias(50); });
    $("#st-enq").addEventListener("change", () => { lembrar(); agendarPrevias(50); });
    $("#st-tam").addEventListener("change", lembrar);
    $("#st-cores").addEventListener("click", (e) => {
      const b = e.target.closest("[data-cor]"); if (!b) return;
      T.cor = b.dataset.cor; desenharCores(); lembrar(); agendarPrevias(50);
    });
    $("#st-logos").addEventListener("click", async (e) => {
      if (e.target.closest("#st-logo-add")) { $("#st-logo-arq").click(); return; }
      const x = e.target.closest("[data-logo-x]");
      if (x) {
        e.stopPropagation();
        if (!(await ask("Apagar este logo?", "Ele sai da lista de logos dos stories.", null, "Apagar"))) return;
        try { T.st.logos = await api("DELETE", "/api/stories/logos/" + x.dataset.logoX); } catch (err) { toast(err.message, true); return; }
        if (T.logo === x.dataset.logoX) T.logo = T.st.logos.length ? T.st.logos[0].id : "nenhum";
        desenharLogos(); agendarPrevias(50); lembrar();
        return;
      }
      const b = e.target.closest("[data-logo]"); if (!b) return;
      T.logo = b.dataset.logo; desenharLogos(); lembrar(); agendarPrevias(50);
    });
    $("#st-logo-arq").addEventListener("change", (e) => { enviarLogo(e.target.files[0]); e.target.value = ""; });
    $("#st-redes").addEventListener("change", lembrar);
    $("#st-modelos").addEventListener("click", (e) => {
      const c = e.target.closest("[data-criar-com]");
      if (c) { e.stopPropagation(); criar(c.dataset.criarCom); return; }
      const m = e.target.closest("[data-mod]"); if (!m) return;
      T.modelo = m.dataset.mod; lembrar();
      $$("#st-modelos .st-mod").forEach((x) => x.classList.toggle("active", x === m));
    });
    $("#st-modelos").addEventListener("keydown", (e) => {
      const m = e.target.closest("[data-mod]");
      if (m && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); m.click(); }
    });
    $("#st-criar").addEventListener("click", () => criar());
    $("#st-limpar").addEventListener("click", async () => {
      const n = (T.prontos || []).length;
      if (!n || !(await ask(`Excluir ${n === 1 ? "o story pronto" : "todos os " + n + " stories prontos"}?`, "Saem daqui e de Exportados. Os que estão agendados em Publicações ficam.", null, "Excluir todos"))) return;
      try {
        const r = await api("POST", "/api/stories/prontos/limpar", {});
        toast(`${r.apagados} excluído${r.apagados === 1 ? "" : "s"}` + (r.ficaram ? ` · ${r.ficaram} ficou(aram) porque está(ão) agendado(s)` : ""));
      } catch (err) { toast(err.message, true); }
      listar();
    });
    ["#st-res-dur", "#st-res-ritmo"].forEach((sel) => $$(sel + " .chip-btn").forEach((b) => b.addEventListener("click", () =>
      $$(sel + " .chip-btn").forEach((x) => x.classList.toggle("active", x === b)))));
    $("#st-res-criar").addEventListener("click", fazerResumo);
    $("#st-prontos").addEventListener("click", async (e) => {
      const d = e.target.closest("[data-del]");
      if (d) {
        const s = T.prontos[+d.dataset.del];
        if (!(await ask("Excluir este story?", "O vídeo" + (s.jpg ? " e a foto" : "") + " saem daqui e de Exportados. O arquivo original que você enviou continua.", null, "Excluir"))) return;
        try { await api("DELETE", "/api/stories/prontos/" + encodeURIComponent(s.file)); toast("Story excluído."); } catch (err) { toast(err.message, true); }
        listar();
        return;
      }
      const p = e.target.closest("[data-pub]");
      if (p) {
        const s = T.prontos[+p.dataset.pub];
        openPublish({ project: T.pid, file: s.file, label: s.label, duration: s.duration, platform: "ig_stories", story: true, project_name: "Stories do culto" });
        return;
      }
      const v = e.target.closest("[data-play]");
      if (v) {
        const s = T.prontos[+v.dataset.play];
        v.innerHTML = `<video src="/api/projects/${T.pid}/renders/${encodeURIComponent(s.file)}" controls autoplay playsinline></video>`;
        v.removeAttribute("data-play");
      }
    });
    window.addEventListener("beforeunload", (e) => {
      if (T.itens.some((x) => x.st === "enviando" || x.st === "fila")) { e.preventDefault(); e.returnValue = ""; }
    });
  }

  function onHome(page) { if (page === "stories") carregar(); }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup); else setup();
  window.V115 = { onHome };
})();
