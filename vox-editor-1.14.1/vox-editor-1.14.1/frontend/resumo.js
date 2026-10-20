"use strict";
/* v1.14 — Resumo do Culto: vários vídeos e fotos viram um resumão com música, na ordem do culto, aberto na Montagem.
   Os arquivos começam a subir assim que são escolhidos (2 de cada vez), enquanto a pessoa escolhe as opções. */
(function () {
  const R = { pid: null, itens: [], formato: "9:16", duracao: "60", ritmo: "calmo", st: null, ocupado: false,
    remotos: 0, refazendo: null, enviando: 0 };
  const SIMULTANEOS = 2;
  const PREF = "vox.resumo.opcoes";
  const guardar = (o) => { try { localStorage.setItem(PREF, JSON.stringify(o)); } catch (_) {} };
  const lerPref = () => { try { return JSON.parse(localStorage.getItem(PREF) || "{}") || {}; } catch (_) { return {}; } };
  const tipoDe = (f) => {
    const n = (f.name || "").toLowerCase();
    if ((f.type || "").startsWith("video/") || /\.(mp4|mov|m4v|mkv|webm|avi|mts|3gp)$/.test(n)) return "video";
    if ((f.type || "").startsWith("image/") || /\.(jpe?g|png|webp|bmp|gif|heic|heif)$/.test(n)) return "image";
    if ((f.type || "").startsWith("audio/") || /\.(mp3|m4a|aac|wav|ogg|opus|flac|wma)$/.test(n)) return "audio";
    return "";
  };

  const opcoes = () => ({
    formato: R.formato, duracao: R.duracao, ritmo: R.ritmo, evento: $("#rs-evento").value || "culto",
    data: $("#rs-data").value || "", musica: $("#rs-musica").value, cor: $("#rs-cor").value,
    enquadramento: $("#rs-enq").value, som_original: $("#rs-som").checked, legenda: $("#rs-legenda").checked,
    legenda_estilo: $("#rs-leg-estilo").value || "palavra_ativa", rotulos: $("#rs-rotulos").checked,
    abertura: $("#rs-abertura").checked, encerramento: $("#rs-encerramento").checked, logo: $("#rs-logo").checked,
    ordem: $("#rs-ordem").checked ? "hora" : "envio", usar_ia: $("#rs-ia").checked && !$("#rs-ia").disabled,
    titulo: $("#rs-nome").value.trim(),
  });

  function aplicar(o) {
    if (!o) return;
    const chip = (sel, v) => { if (!v) return; $$(sel + " .chip-btn").forEach((b) => b.classList.toggle("active", b.dataset.v === String(v))); };
    if (o.formato) { R.formato = o.formato; chip("#rs-formato", o.formato); }
    if (o.duracao) { R.duracao = String(Math.round(+o.duracao)); chip("#rs-duracao", R.duracao); }
    if (o.ritmo) { R.ritmo = o.ritmo; chip("#rs-ritmo", o.ritmo); }
    const sel = (id, v) => { const el = $(id); if (v != null && [...el.options].some((x) => x.value === v)) el.value = v; };
    sel("#rs-evento", o.evento); sel("#rs-cor", o.cor); sel("#rs-enq", o.enquadramento); sel("#rs-leg-estilo", o.legenda_estilo);
    if (o.musica != null) { sel("#rs-musica", o.musica); R.escolheuMusica = true; }
    const ck = (id, v) => { if (typeof v === "boolean" && !$(id).disabled) $(id).checked = v; };
    ck("#rs-som", o.som_original); ck("#rs-legenda", o.legenda); ck("#rs-rotulos", o.rotulos); ck("#rs-abertura", o.abertura);
    ck("#rs-encerramento", o.encerramento); ck("#rs-logo", o.logo);
    if (o.ordem) $("#rs-ordem").checked = o.ordem !== "envio";
    $("#rs-leg-box").classList.toggle("hidden", !$("#rs-legenda").checked);
    exemploRotulos();
  }

  /* ---------------- estado e opções ---------------- */
  async function carregar() {
    try { R.st = await api("GET", "/api/resumo/status"); } catch (e) { toast(e.message, true); return; }
    const st = R.st;
    const ev = $("#rs-evento"), e0 = ev.value || "culto";
    ev.innerHTML = Object.entries(st.eventos).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    ev.value = e0;
    const le = $("#rs-leg-estilo"), l0 = le.value || "palavra_ativa";
    le.innerHTML = Object.entries(st.estilos_legenda || {}).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    le.value = l0;
    montarMusicas();
    const mc = st.marca || {};
    $("#rs-marca-msg").innerHTML = mc.logo || mc.handle ? `(${[mc.logo && "logo", mc.handle && "seu @"].filter(Boolean).join(" e ")})`
      : `— coloque sua logo e seu @ em <a href="#/marca">Marca</a>`;
    $("#rs-logo").disabled = !mc.logo;
    if (!mc.logo) $("#rs-logo").checked = false;
    $("#rs-ia").disabled = !st.ia;
    if (!st.ia) $("#rs-ia").checked = false;
    $("#rs-ia-msg").innerHTML = st.ia ? `(${esc(st.ia_nome || "IA")} ligada — custa centavos)`
      : `— sem IA o programa escolhe sozinho. Para ligar: <a href="#/ia">Inteligência artificial</a>`;
    if (!st.transcricao) {
      $("#rs-som").closest("label").querySelector(".hint").textContent = "(a transcrição não está instalada: entram trechos do louvor; as frases da pregação precisam dela)";
    }
    if (!$("#rs-data").value) {
      const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
      $("#rs-data").value = d.toISOString().slice(0, 10);
    }
    if (!R.prefAplicada) { aplicar(lerPref()); R.prefAplicada = true; }
    meus();
  }

  function montarMusicas() {
    const st = R.st || {}, mus = $("#rs-musica"), m0 = mus.value;
    const enviada = R.itens.find((x) => x.tipo === "audio" && x.st === "ok");
    mus.innerHTML = (enviada || R.temMusicaEnviada ? `<option value="__enviada__">A música que eu enviei${enviada ? " (" + esc(enviada.f.name) + ")" : ""}</option>` : "") +
      `<option value="__auto__">Automática (biblioteca livre, combina com o culto)</option><option value="">Sem música (som dos vídeos)</option>` +
      ((st.musicas || []).length ? `<optgroup label="Minhas músicas">${st.musicas.map((n) => `<option>${esc(n)}</option>`).join("")}</optgroup>` : "");
    if (!R.escolheuMusica) mus.value = enviada || R.temMusicaEnviada ? "__enviada__" : "__auto__";
    else mus.value = [...mus.options].some((o) => o.value === m0) ? m0 : (enviada ? "__enviada__" : "__auto__");
  }

  function exemploRotulos() {
    const ev = $("#rs-evento").value;
    $("#rs-rot-ex").textContent = ["casamento", "aniversario", "evento"].includes(ev) ? "(Música, Oração, Mensagem)" : "(Louvor, Oração, Palavra)";
    if (R.st && R.st.titulos && !$("#rs-nome").value) $("#rs-nome").placeholder = "Ex.: " + (R.st.titulos[ev] || "Culto da Família");
  }

  /* ---------------- arquivos ---------------- */
  async function garantirProjeto() {
    if (R.pid) return R.pid;
    if (R.criandoProjeto) return R.criandoProjeto;
    R.criandoProjeto = api("POST", "/api/resumo/novo", { name: $("#rs-nome").value.trim() || "Resumo do culto", formato: R.formato })
      .then((r) => { R.pid = r.id; R.criandoProjeto = null; return r.id; })
      .catch((e) => { R.criandoProjeto = null; throw e; });
    return R.criandoProjeto;
  }

  function adicionar(lista) {
    const novos = [];
    for (const f of lista) {
      const tipo = tipoDe(f);
      if (!tipo) { toast(`“${f.name}” não é vídeo, foto nem música.`, true); continue; }
      if (/\.(heic|heif)$/i.test(f.name)) {
        toast("Foto HEIC do iPhone ainda não é aceita. No iPhone: Ajustes > Câmera > Formatos > “Mais compatível”.", true);
        continue;
      }
      if (R.itens.some((x) => x.f.name === f.name && x.f.size === f.size && x.st !== "erro")) continue;
      const it = { f, tipo, st: "fila", pct: 0, url: tipo === "audio" ? "" : URL.createObjectURL(f) };
      R.itens.push(it); novos.push(it);
    }
    if (!novos.length) return;
    desenhar();
    garantirProjeto().then(bombear).catch((e) => { novos.forEach((x) => { x.st = "erro"; x.erro = e.message; }); desenhar(); toast(e.message, true); });
  }

  function bombear() {
    while (R.enviando < SIMULTANEOS) {
      const it = R.itens.find((x) => x.st === "fila");
      if (!it) break;
      enviar(it);
    }
    desenhar();
  }

  function enviar(it) {
    R.enviando++;
    it.st = "enviando";
    const xhr = new XMLHttpRequest();
    it.xhr = xhr;
    xhr.open("POST", `/api/resumo/${R.pid}/arquivo`);
    xhr.setRequestHeader("x-filename", encodeURIComponent(it.f.name));
    if (it.f.lastModified) xhr.setRequestHeader("x-modificado", String(it.f.lastModified));
    xhr.setRequestHeader("x-fuso", String(new Date().getTimezoneOffset()));
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) { it.pct = e.loaded / e.total; desenharItem(it); contar(); } };
    const fim = () => { R.enviando--; it.xhr = null; bombear(); };
    xhr.onload = () => {
      if (xhr.status === 200) {
        it.md = JSON.parse(xhr.responseText); it.st = "ok"; it.pct = 1;
        if (it.tipo === "audio") montarMusicas();
      } else {
        let m = xhr.statusText; try { m = JSON.parse(xhr.responseText).detail || m; } catch (_) {}
        it.st = "erro"; it.erro = m || "Falhou";
      }
      fim();
    };
    xhr.onerror = () => { it.st = "erro"; it.erro = "A conexão caiu durante o envio."; fim(); };
    xhr.onabort = () => { fim(); };
    xhr.send(it.f);
  }

  async function remover(it) {
    if (it.xhr) { it.xhr.abort(); }
    R.itens = R.itens.filter((x) => x !== it);
    if (it.url) URL.revokeObjectURL(it.url);
    desenhar();
    if (it.md && R.pid) {
      try { await api("DELETE", `/api/projects/${R.pid}/midias/${it.md.id}`); } catch (e) { toast(e.message, true); }
    }
    if (it.tipo === "audio") montarMusicas();
  }

  function contar() {
    const ok = R.itens.filter((x) => x.st !== "erro");
    const n = (t) => ok.filter((x) => x.tipo === t).length;
    const tam = ok.reduce((a, x) => a + x.f.size, 0);
    const pend = R.itens.filter((x) => x.st === "fila" || x.st === "enviando");
    const pct = pend.length ? Math.round(100 * pend.reduce((a, x) => a + x.pct * x.f.size, 0) / Math.max(1, pend.reduce((a, x) => a + x.f.size, 0))) : 100;
    const partes = [];
    if (n("video")) partes.push(`${n("video")} vídeo${n("video") === 1 ? "" : "s"}`);
    if (n("image")) partes.push(`${n("image")} foto${n("image") === 1 ? "" : "s"}`);
    if (n("audio")) partes.push(`${n("audio")} música${n("audio") === 1 ? "" : "s"}`);
    if (R.remotos) partes.unshift(`${R.remotos} já no resumo`);
    $("#rs-conta").innerHTML = (partes.join(" · ") || "Nenhum arquivo") + (tam ? ` · ${fmtSize(tam)}` : "") +
      (pend.length ? ` · <b>enviando ${pend.length}… ${pct}%</b>` : ok.length ? " · <b class=\"ok\">tudo enviado ✓</b>" : "");
    $("#rs-info").classList.toggle("hidden", !R.itens.length && !R.pid);
    if (R.esperando) $("#rs-criar").textContent = pend.length ? `Esperando os envios (${pct}%)…` : "Criando…";
  }

  const ICONE_SOM = '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>';

  function htmlItem(it) {
    const mid = it.tipo === "video" ? `<video src="${it.url}" muted preload="metadata" playsinline></video>`
      : it.tipo === "image" ? `<img src="${it.url}" alt="" loading="lazy">` : `<span class="rs-som">${ICONE_SOM}</span>`;
    const tag = it.tipo === "video" ? "vídeo" : it.tipo === "image" ? "foto" : "música";
    const est = it.st === "ok" ? `<span class="rs-st ok" title="Enviado">✓</span>`
      : it.st === "erro" ? `<span class="rs-st erro" title="${esc(it.erro || "")}">!</span>` : "";
    const barra = it.st === "enviando" || it.st === "fila" ? `<i class="rs-barra"><b style="width:${Math.round(it.pct * 100)}%"></b></i>` : "";
    return `${mid}<span class="rs-tag">${tag}</span>${est}${barra}
      <button type="button" class="rs-x" aria-label="Tirar ${esc(it.f.name)}" title="Tirar">×</button>
      <span class="rs-nome" title="${esc(it.f.name)}">${it.st === "erro" ? esc(it.erro || "Falhou") : esc(it.f.name)}</span>`;
  }

  function desenharItem(it) {
    if (!it.el) return;
    const b = it.el.querySelector(".rs-barra b");
    if (b) b.style.width = Math.round(it.pct * 100) + "%";
  }

  function desenhar() {
    const box = $("#rs-lista");
    const vivos = new Set(R.itens);
    [...box.children].forEach((el) => { if (!vivos.has(el._it)) el.remove(); });
    R.itens.forEach((it) => {
      const chave = it.st + (it.erro || "");
      if (!it.el) {
        it.el = document.createElement("div");
        it.el.className = "rs-item";
        it.el._it = it;
        it.el.addEventListener("click", (e) => { if (e.target.closest(".rs-x")) remover(it); });
        box.appendChild(it.el);
      }
      if (it.el._chave !== chave) {
        it.el.innerHTML = htmlItem(it);
        it.el._chave = chave;
        it.el.classList.toggle("erro", it.st === "erro");
      }
    });
    contar();
  }

  function recomecar() {
    if (R.ocupado) return;
    R.itens.forEach((it) => { if (it.xhr) it.xhr.abort(); if (it.url) URL.revokeObjectURL(it.url); });
    R.itens = []; R.pid = null; R.remotos = 0; R.refazendo = null; R.temMusicaEnviada = false; R.escolheuMusica = false;
    $("#rs-lista").innerHTML = "";
    $("#rs-refazendo").classList.add("hidden");
    $("#rs-andamento").classList.add("hidden");
    $("#rs-criar").textContent = "Criar o resumo";
    $("#rs-nome").value = "";
    montarMusicas();
    desenhar();
  }

  /* ---------------- criar e acompanhar ---------------- */
  function andamento(tit, pct, msg) {
    $("#rs-andamento").classList.remove("hidden");
    $("#rs-and-tit").textContent = tit;
    $("#rs-and-pct").textContent = Math.round(pct * 100) + "%";
    $("#rs-and-bar").style.width = Math.round(pct * 100) + "%";
    $("#rs-and-msg").textContent = msg || "";
  }

  async function criar() {
    if (R.ocupado) return;
    const validos = R.itens.filter((x) => x.st !== "erro" && x.tipo !== "audio");
    if (!validos.length && !R.remotos) { toast("Escolha os vídeos e as fotos do culto primeiro.", true); $("#rs-arquivos").click(); return; }
    if (R.refazendo && !confirm("Refazer cria uma montagem nova para este resumo (o que você mudou à mão nele se perde). Continuar?")) return;
    R.ocupado = true; $("#rs-criar").disabled = true;
    const o = opcoes();
    guardar({ formato: o.formato, duracao: o.duracao, ritmo: o.ritmo, evento: o.evento, cor: o.cor, enquadramento: o.enquadramento,
      som_original: o.som_original, legenda: o.legenda, legenda_estilo: o.legenda_estilo, rotulos: o.rotulos,
      abertura: o.abertura, encerramento: o.encerramento, logo: o.logo, ordem: o.ordem });
    try {
      R.esperando = true; contar();
      while (R.itens.some((x) => x.st === "fila" || x.st === "enviando")) await new Promise((ok) => setTimeout(ok, 500));
      R.esperando = false;
      await garantirProjeto();
      if (!R.itens.some((x) => x.st === "ok" && x.tipo !== "audio") && !R.remotos) throw new Error("Nenhum vídeo ou foto foi enviado. Confira os arquivos com “!”.");
      $("#rs-criar").textContent = "Criando…";
      const r = await api("POST", `/api/resumo/${R.pid}/criar`, { name: $("#rs-nome").value.trim(), opcoes: o });
      await acompanhar(r);
    } catch (e) { toast(e.message, true); }
    R.esperando = false; R.ocupado = false; $("#rs-criar").disabled = false;
    $("#rs-criar").textContent = R.refazendo ? "Refazer o resumo" : "Criar o resumo";
  }

  async function acompanhar(r) {
    andamento("Montando o resumo…", 0, "Na fila…");
    for (;;) {
      await new Promise((ok) => setTimeout(ok, 900));
      let js;
      try { js = await api("GET", "/api/jobs/" + r.id); } catch (_) { continue; }
      const j = js.find((x) => x.id === r.job);
      if (!j) continue;
      andamento(j.status === "na fila" ? `Na fila${j.posicao ? " (" + j.posicao + "º)" : ""}…` : "Montando o resumo…", j.pct || 0, j.msg);
      if (j.status === "concluido") {
        const res = j.result || {};
        const partes = [fmtDur(res.duracao)];
        if (res.videos) partes.push(`${res.videos} pedaço${res.videos === 1 ? "" : "s"} de vídeo`);
        if (res.fotos) partes.push(`${res.fotos} foto${res.fotos === 1 ? "" : "s"}`);
        if (res.momentos) partes.push(`${res.momentos} momento${res.momentos === 1 ? "" : "s"} com som original`);
        if ((res.partes || []).length) partes.push(res.partes.join(", "));
        if (res.musica) partes.push(res.ritmo_musica ? "música com cortes no ritmo" : "com música");
        if (res.ia) partes.push("escolhas da IA");
        andamento("Pronto!", 1, partes.join(" · ") + (res.aviso ? " — " + res.aviso : ""));
        if (res.aviso) toast(res.aviso, true); else toast("Resumo montado! Abrindo na Montagem…");
        setTimeout(() => { location.hash = "#/p/" + r.id + "/montagem"; }, res.aviso ? 6000 : 1200);
        return;
      }
      if (j.status === "erro" || j.status === "cancelado") {
        andamento("Não deu certo", 0, j.error || "Cancelado");
        toast(j.error || "Cancelado", true);
        return;
      }
    }
  }

  /* ---------------- seus resumos (refazer) ---------------- */
  async function meus() {
    let lst = [];
    try { lst = await api("GET", "/api/resumo/lista"); } catch (_) { return; }
    lst = lst.filter((x) => x.id !== R.pid || x.resultado);
    $("#rs-meus").classList.toggle("hidden", !lst.length);
    const quando = (t) => t ? new Date(t * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }) : "";
    $("#rs-meus-lista").innerHTML = lst.map((x) => {
      const r = x.resultado || {};
      const info = [`${x.videos} vídeo${x.videos === 1 ? "" : "s"}`, `${x.fotos} foto${x.fotos === 1 ? "" : "s"}`,
        r.duracao ? fmtDur(r.duracao) : "ainda não montado", (x.opcoes || {}).formato, quando(x.feito || x.updated)].filter(Boolean).join(" · ");
      return `<div class="rs-meu" data-id="${x.id}">
        <div><b>${esc(x.name)}</b><span class="hint">${esc(info)}</span></div>
        <div class="row"><button type="button" class="btn small ghost" data-rs="abrir"${r.duracao ? "" : " disabled"}>Abrir</button>
        <button type="button" class="btn small" data-rs="refazer">Refazer</button></div></div>`;
    }).join("");
    R.lista = lst;
  }

  function refazer(id) {
    const x = (R.lista || []).find((y) => y.id === id);
    if (!x || R.ocupado) return;
    recomecar();
    R.pid = id; R.remotos = x.arquivos; R.refazendo = id;
    R.temMusicaEnviada = (x.opcoes || {}).musica === "__enviada__";
    $("#rs-nome").value = x.name;
    montarMusicas();
    aplicar(x.opcoes || {});
    $("#rs-refazendo").innerHTML = `Refazendo <b>${esc(x.name)}</b> (${x.arquivos} arquivos). Mude as opções e clique em <b>Refazer o resumo</b> — ou arraste mais arquivos para juntar.`;
    $("#rs-refazendo").classList.remove("hidden");
    $("#rs-criar").textContent = "Refazer o resumo";
    desenhar();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /* ---------------- ligar tudo ---------------- */
  function setup() {
    if (!$("#pg-resumo")) return;
    const chips = (sel, chave) => $$(sel + " .chip-btn").forEach((b) => b.addEventListener("click", () => {
      R[chave] = b.dataset.v;
      $$(sel + " .chip-btn").forEach((x) => x.classList.toggle("active", x === b));
    }));
    chips("#rs-formato", "formato"); chips("#rs-duracao", "duracao"); chips("#rs-ritmo", "ritmo");
    $("#rs-arquivos").addEventListener("change", (e) => { adicionar([...e.target.files]); e.target.value = ""; });
    const drop = $("#rs-drop");
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("sobre"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("sobre"); }));
    drop.addEventListener("drop", (e) => adicionar([...(e.dataTransfer.files || [])]));
    $("#rs-criar").addEventListener("click", criar);
    $("#rs-novo").addEventListener("click", recomecar);
    $("#rs-legenda").addEventListener("change", () => $("#rs-leg-box").classList.toggle("hidden", !$("#rs-legenda").checked));
    $("#rs-evento").addEventListener("change", exemploRotulos);
    $("#rs-musica").addEventListener("change", () => { R.escolheuMusica = true; });
    $("#rs-meus-lista").addEventListener("click", (e) => {
      const b = e.target.closest("[data-rs]"), card = e.target.closest(".rs-meu");
      if (!b || !card) return;
      if (b.dataset.rs === "abrir") location.hash = "#/p/" + card.dataset.id + "/montagem";
      if (b.dataset.rs === "refazer") refazer(card.dataset.id);
    });
    window.addEventListener("beforeunload", (e) => {
      if (R.itens.some((x) => x.st === "enviando" || x.st === "fila")) { e.preventDefault(); e.returnValue = ""; }
    });
  }

  function onHome(page) { if (page === "resumo") carregar(); }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup); else setup();
  window.V114 = { onHome };
})();
