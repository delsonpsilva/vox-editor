"use strict";
/* v1.10 — História → Vídeo: texto, áudio gravado ou narração ao vivo viram uma Montagem pronta. */
(function () {
  const H = { modo: "texto", formato: "9:16", st: null, ocupado: false, vivo: null };
  const opcoes = () => ({
    formato: H.formato, voz: $("#hs-voz").value || "francisca", visual: $("#hs-visual").value,
    estilo: $("#hs-estilo").value || "realista",
    legenda: $("#hs-legenda").checked, usar_ia: $("#hs-ia").checked && !$("#hs-ia").disabled,
    musica: $("#hs-musica").value, velocidade: +$("#hs-vel").value,
    legenda_estilo: $("#hs-leg-estilo").value || "palavra_ativa", abertura: $("#hs-abertura").checked,
    encerramento: $("#hs-encerramento").checked, logo: $("#hs-logo").checked, retranscrever: $("#hs-retrans").checked,
  });

  /* ---------------- estado e opções ---------------- */
  async function carregar() {
    try { H.st = await api("GET", "/api/historia/status"); } catch (e) { toast(e.message, true); return; }
    const st = H.st, voz = $("#hs-voz"), atual = voz.value;
    voz.innerHTML = st.vozes.map((v) => `<option value="${esc(v.id)}"${v.ok ? "" : " disabled"}>${esc(v.nome)}${v.ok ? "" : " — indisponível aqui"}</option>`).join("");
    voz.value = atual && st.vozes.some((v) => v.id === atual && v.ok) ? atual : (st.vozes.find((v) => v.ok) || {}).id || "nenhuma";
    const mus = $("#hs-musica"), m0 = mus.value || "__auto__";
    mus.innerHTML = `<option value="__auto__">Automática (biblioteca livre, combina com a história)</option><option value="">Sem música</option>` +
      (st.musicas.length ? `<optgroup label="Minhas músicas">${st.musicas.map((n) => `<option>${esc(n)}</option>`).join("")}</optgroup>` : "");
    mus.value = [...mus.options].some((o) => o.value === m0) ? m0 : "__auto__";
    const es = $("#hs-estilo"), e0 = es.value || "realista";
    es.innerHTML = Object.entries(st.estilos || {}).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    es.value = e0;
    const le = $("#hs-leg-estilo"), l0 = le.value || "palavra_ativa";
    le.innerHTML = Object.entries(st.estilos_legenda || {}).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    le.value = l0;
    const mc = st.marca || {};
    $("#hs-marca-msg").innerHTML = mc.logo || mc.handle ? `(${[mc.logo && "logo", mc.handle && "seu @"].filter(Boolean).join(" e ")})`
      : `— coloque sua logo e seu @ em <a href="#/marca">Marca</a>`;
    $("#hs-logo").disabled = !mc.logo;
    if (!mc.logo) $("#hs-logo").checked = false;
    $("#hs-ia").disabled = !st.ia;
    if (st.ia && !H.iaTocado) $("#hs-ia").checked = true;
    if (!st.ia) $("#hs-ia").checked = false;
    $("#hs-ia-msg").textContent = st.ia ? `(${st.ia_nome || "IA"} ligada)` : "— cole a chave grátis do Gemini em “Deixar completo”, aqui embaixo";
    const ok = (b) => (b ? "✓ ligada" : "falta");
    $("#hs-ok-pexels").textContent = ok(st.pexels); $("#hs-ok-pexels").classList.toggle("on", st.pexels);
    $("#hs-ok-gemini").textContent = ok(st.gemini); $("#hs-ok-gemini").classList.toggle("on", st.gemini);
    const faltam = [!st.pexels && "Pexels", !st.gemini && "Gemini"].filter(Boolean);
    $("#hs-chaves-res").textContent = faltam.length ? `— falta: ${faltam.join(" e ")}` : "— tudo ligado ✓";
    if (faltam.length && !H.abriuChaves) { $("#hs-chaves").open = true; H.abriuChaves = true; }
    avisoVisual();
  }

  function avisoVisual() {
    const st = H.st || {}, v = $("#hs-visual").value, el = $("#hs-visual-msg");
    $("#hs-estilo-box").classList.toggle("hidden", v !== "ia");
    let t = "";
    if (v === "fotos" && !st.bancos) t = "Sem a chave do Pexels, as fotos vêm do Openverse (livres, mas variam de qualidade). Com a chave, ficam bem melhores.";
    if (v === "videos" && !st.bancos) t = "Vídeos precisam da chave grátis do Pexels (ou Pixabay). Sem ela, as cenas usam fotos livres.";
    if (v === "ia") t = st.gemini ? "Cada cena ganha uma imagem nova criada pela IA, no mesmo estilo. Leva uns 10 s por cena e o Google cobra centavos por imagem (precisa de faturamento ativo). Se não der, a cena usa foto grátis."
      : "Cole a chave do Gemini em “Deixar completo”. Sem ela, as cenas usam fotos grátis.";
    el.textContent = t; el.classList.toggle("hidden", !t);
  }

  async function salvarChaves() {
    const d = { pexels: $("#hs-k-pexels").value.trim(), gemini: $("#hs-k-gemini").value.trim() };
    if (!d.pexels && !d.gemini) { $("#hs-k-msg").textContent = "Cole pelo menos uma chave."; return; }
    $("#hs-k-msg").textContent = "Salvando…";
    try {
      await api("POST", "/api/historia/chaves", d);
      $("#hs-k-pexels").value = ""; $("#hs-k-gemini").value = "";
      let msg = "Salvo!";
      if (d.gemini) {
        const t = await api("POST", "/api/historia/testar-gemini");
        msg += " " + t.msg;
      }
      $("#hs-k-msg").textContent = msg;
      H.iaTocado = false;
      await carregar();
    } catch (e) { $("#hs-k-msg").textContent = e.message; }
  }

  function trocaModo(m) {
    if (H.vivo && H.vivo.gravando && m !== "vivo") { toast("Termine ou pause a narração ao vivo antes de trocar.", true); return; }
    H.modo = m;
    if (!H.ocupado) $("#hs-andamento").classList.add("hidden");
    $$("[data-hmodo]").forEach((b) => b.classList.toggle("active", b.dataset.hmodo === m));
    $$("[data-hpainel]").forEach((p) => p.classList.toggle("hidden", p.dataset.hpainel !== m || (m === "texto" && !!H.rot)));
    $("#hs-roteiro").classList.toggle("hidden", !(m === "texto" && H.rot));
    $$("[data-so]").forEach((el) => el.classList.toggle("hidden", el.dataset.so !== m));
    $("#hs-criar").classList.toggle("hidden", m === "vivo");
  }

  function contar() {
    const n = ($("#hs-texto").value.match(/\S+/g) || []).length;
    const min = n / 150;
    $("#hs-conta").textContent = `${n} palavra${n === 1 ? "" : "s"}` + (n ? ` · vídeo de uns ${min < 1 ? Math.max(5, Math.round(min * 60)) + " segundos" : min.toFixed(1).replace(".", ",") + " minutos"}` : "");
  }

  /* ---------------- andamento da tarefa ---------------- */
  function andamento(tit, pct, msg) {
    $("#hs-andamento").classList.remove("hidden");
    $("#hs-and-tit").textContent = tit;
    $("#hs-and-pct").textContent = Math.round(pct * 100) + "%";
    $("#hs-and-bar").style.width = Math.round(pct * 100) + "%";
    $("#hs-and-msg").textContent = msg || "";
  }

  async function acompanhar(r) {
    H.ocupado = true; $("#hs-criar").disabled = true;
    andamento("Montando o vídeo…", 0, "Na fila…");
    try {
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 900));
        const js = await api("GET", "/api/jobs/" + r.id);
        const j = js.find((x) => x.id === r.job);
        if (!j) continue;
        andamento(j.status === "na fila" ? "Na fila…" : "Montando o vídeo…", j.pct || 0, j.msg);
        if (j.status === "concluido") {
          const res = j.result || {};
          const partes = [`${res.cenas} cena${res.cenas === 1 ? "" : "s"}`, fmtDur(res.duracao)];
          if (res.fotos) partes.push(`${res.fotos} imagem${res.fotos === 1 ? "" : "ns"}`);
          if (res.videos) partes.push(`${res.videos} vídeo${res.videos === 1 ? "" : "s"}`);
          if (res.musica) partes.push("com música");
          if (res.modo === "ia") partes.push("cenas pela IA");
          andamento("Pronto!", 1, partes.join(" · ") + (res.aviso ? " — " + res.aviso : ""));
          if (res.aviso) toast(res.aviso, true); else toast("Vídeo montado! Abrindo na Montagem…");
          setTimeout(() => { location.hash = "#/p/" + r.id + "/montagem"; }, res.aviso ? 5000 : 900);
          break;
        }
        if (j.status === "erro" || j.status === "cancelado") {
          andamento("Não deu certo", 0, j.error || "Cancelado");
          toast(j.error || "Cancelado", true);
          break;
        }
      }
    } catch (e) { toast(e.message, true); }
    H.ocupado = false; $("#hs-criar").disabled = false;
  }

  async function criar() {
    if (H.ocupado) return;
    try {
      if (H.modo === "texto") {
        const texto = $("#hs-texto").value.trim();
        if ((texto.match(/\S+/g) || []).length < 3) { toast("Escreva ou cole a história primeiro.", true); return; }
        if ($("#hs-revisar").checked) { await abrirRoteiro(texto); return; }
        const r = await api("POST", "/api/historia/texto", { texto, name: $("#hs-nome").value.trim(), opcoes: opcoes() });
        acompanhar(r);
      } else if (H.modo === "audio") {
        const f = $("#hs-arquivo").files[0];
        if (!f) { toast("Escolha o áudio da narração.", true); return; }
        H.ocupado = true; $("#hs-criar").disabled = true;
        andamento("Enviando o áudio…", 0, f.name);
        const r = await enviar(f);
        H.ocupado = false;
        acompanhar(r);
      }
    } catch (e) { H.ocupado = false; $("#hs-criar").disabled = false; toast(e.message, true); }
  }

  function enviar(f) {
    return new Promise((ok, falha) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/historia/audio");
      xhr.setRequestHeader("x-filename", encodeURIComponent(f.name));
      xhr.setRequestHeader("x-opcoes", encodeURIComponent(JSON.stringify({ ...opcoes(), name: $("#hs-nome-a").value.trim() })));
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) andamento("Enviando o áudio…", e.loaded / e.total, f.name); };
      xhr.onload = () => {
        if (xhr.status === 200) return ok(JSON.parse(xhr.responseText));
        let m = xhr.statusText; try { m = JSON.parse(xhr.responseText).detail || m; } catch (_) {}
        falha(new Error(m));
      };
      xhr.onerror = () => falha(new Error("A conexão caiu durante o envio."));
      xhr.send(f);
    });
  }

  /* ---------------- revisar as cenas (roteiro) ---------------- */
  const NOME_GRAF = { barras: "barras", pizza: "pizza", linha: "linha", numero: "número" };

  async function abrirRoteiro(texto) {
    H.ocupado = true; $("#hs-criar").disabled = true;
    andamento("Dividindo em cenas…", 0.3, $("#hs-ia").checked && !$("#hs-ia").disabled ? "A IA está lendo a história…" : "Lendo a história…");
    try {
      const r = await api("POST", "/api/historia/roteiro", { texto, opcoes: opcoes() });
      H.rot = { texto, humor: r.humor, cenas: r.cenas, modo: r.modo };
      $("#hs-andamento").classList.add("hidden");
      desenharRoteiro();
      $("[data-hpainel=texto]").classList.add("hidden");
      $("#hs-roteiro").classList.remove("hidden");
      $("#hs-roteiro").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) { toast(e.message, true); $("#hs-andamento").classList.add("hidden"); }
    H.ocupado = false; $("#hs-criar").disabled = false;
  }

  function lerRoteiro() {
    $$("#hs-cenas .hs-cena-card").forEach((card, i) => {
      const c = H.rot.cenas[i]; if (!c) return;
      c.texto = $("[data-c=texto]", card).value; c.busca = $("[data-c=busca]", card).value; c.destaque = $("[data-c=destaque]", card).value;
    });
  }

  function desenharRoteiro() {
    const R = H.rot;
    $("#hs-rot-info").textContent = `${R.cenas.length} cenas · ${R.modo === "ia" ? "divididas pela IA" : "divisão automática"} · música: ${R.humor}`;
    $("#hs-cenas").innerHTML = R.cenas.map((c, i) => `
      <div class="hs-cena-card">
        <div class="row between"><b>Cena ${i + 1}</b><div class="row">
          ${i < R.cenas.length - 1 ? `<button type="button" class="btn ghost small" data-junta="${i}">Juntar com a próxima</button>` : ""}
          ${R.cenas.length > 1 ? `<button type="button" class="btn ghost small" data-apaga="${i}">Apagar</button>` : ""}</div></div>
        <label class="field">O que é dito <textarea data-c="texto" rows="3">${esc(c.texto)}</textarea></label>
        <div class="grid2">
          <label class="field">Imagem: o que buscar <input data-c="busca" value="${esc(c.busca)}" placeholder="ex.: pastor ovelhas campo"></label>
          <label class="field">Título na tela (opcional) <input data-c="destaque" value="${esc(c.destaque)}" placeholder="vazio = sem título"></label>
        </div>
        ${c.grafico ? `<div class="row"><span class="chip">Gráfico de ${NOME_GRAF[c.grafico.tipo] || "barras"}: ${esc(c.grafico.titulo || (c.grafico.rotulos || []).join(", "))}</span>
          <button type="button" class="btn ghost small" data-semgraf="${i}">Tirar o gráfico</button></div>` : ""}
      </div>`).join("");
    $$("[data-junta]").forEach((b) => b.addEventListener("click", () => {
      lerRoteiro(); const i = +b.dataset.junta, a = H.rot.cenas[i], z = H.rot.cenas[i + 1];
      a.texto = (a.texto + " " + z.texto).trim(); a.grafico = a.grafico || z.grafico; a.destaque = a.destaque || z.destaque;
      H.rot.cenas.splice(i + 1, 1); desenharRoteiro();
    }));
    $$("[data-apaga]").forEach((b) => b.addEventListener("click", () => { lerRoteiro(); H.rot.cenas.splice(+b.dataset.apaga, 1); desenharRoteiro(); }));
    $$("[data-semgraf]").forEach((b) => b.addEventListener("click", () => { lerRoteiro(); H.rot.cenas[+b.dataset.semgraf].grafico = null; desenharRoteiro(); }));
  }

  async function montarRoteiro() {
    if (H.ocupado || !H.rot) return;
    lerRoteiro();
    const cenas = H.rot.cenas.filter((c) => c.texto.trim());
    if (!cenas.length) { toast("Todas as cenas ficaram vazias.", true); return; }
    try {
      const r = await api("POST", "/api/historia/texto", { texto: H.rot.texto, cenas, name: $("#hs-nome").value.trim(),
        opcoes: { ...opcoes(), humor: H.rot.humor } });
      $("#hs-roteiro").classList.add("hidden"); $("[data-hpainel=texto]").classList.remove("hidden");
      H.rot = null;
      acompanhar(r);
    } catch (e) { toast(e.message, true); }
  }

  /* ---------------- ao vivo ---------------- */
  const SR = 16000;
  const CORES = [["#402060", "#d25a28"], ["#0a2846", "#28a0aa"], ["#3c1428", "#e68c3c"], ["#14321e", "#96be50"], ["#281e14", "#dcaa5a"], ["#0f1937", "#785ac8"]];

  function fundo(k, img) {
    const el = $("#hs-fundo"), [a, b] = CORES[k % CORES.length];
    el.style.backgroundImage = img ? `url("${img}")` : `linear-gradient(135deg, ${a}, ${b})`;
    el.classList.remove("zoom"); void el.offsetWidth; el.classList.add("zoom");
  }

  async function comecar() {
    const V = H.vivo;
    if (V && V.pausado) { V.pausado = false; $("#hs-pausar").textContent = "Pausar"; msg("Ouvindo…"); return; }
    if (V && V.gravando) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { toast("Esta janela não tem acesso ao microfone. Abra pelo INICIAR-NAVEGADOR.bat.", true); return; }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    } catch (e) {
      const motivo = { NotAllowedError: "O acesso ao microfone foi bloqueado (pela janela do programa ou pelo Windows).",
        NotFoundError: "Nenhum microfone foi encontrado. Confira se ele está conectado.",
        NotReadableError: "O microfone está ocupado por outro programa (feche OBS, WhatsApp, chamadas) e tente de novo.",
        SecurityError: "O acesso ao microfone foi bloqueado." }[e.name] || ("Erro do microfone: " + (e.message || e.name));
      $("#hs-mic-erro").textContent = motivo;
      $("#hs-mic-ajuda").classList.remove("hidden");
      toast(motivo, true);
      return;
    }
    $("#hs-mic-ajuda").classList.add("hidden");
    let r;
    try { r = await api("POST", "/api/historia/ao-vivo", { formato: H.formato, name: $("#hs-nome").value.trim() || "Narração ao vivo" }); }
    catch (e) { stream.getTracks().forEach((t) => t.stop()); toast(e.message, true); return; }
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const mudo = ctx.createGain(); mudo.gain.value = 0;
    src.connect(proc); proc.connect(mudo); mudo.connect(ctx.destination);
    H.vivo = { pid: r.id, stream, ctx, proc, gravando: true, pausado: false, buf: [], len: 0, silencio: 0,
      fila: [], enviando: false, texto: "", cena: [], ncena: 0, segs: 0, atraso: 0 };
    const razao = ctx.sampleRate / SR;
    proc.onaudioprocess = (e) => {
      const W = H.vivo; if (!W || !W.gravando || W.pausado) return;
      const inp = e.inputBuffer.getChannelData(0);
      const n = Math.floor(inp.length / razao), out = new Int16Array(n);
      let soma = 0;
      for (let i = 0; i < n; i++) {
        const a = Math.floor(i * razao), b = Math.min(inp.length, Math.floor((i + 1) * razao));
        let v = 0; for (let k = a; k < b; k++) v += inp[k]; v /= Math.max(1, b - a);
        soma += v * v;
        out[i] = Math.max(-32768, Math.min(32767, v * 32767));
      }
      const rms = Math.sqrt(soma / Math.max(1, n));
      $("#hs-nivel").style.width = Math.min(100, rms * 600) + "%";
      W.buf.push(out); W.len += n; W.segs += n / SR;
      W.silencio = rms < 0.012 ? W.silencio + n / SR : 0;
      if ((W.len >= SR * 2.5 && W.silencio >= 0.45) || W.len >= SR * 9) despejar();
    };
    $("#hs-transc").innerHTML = ""; $("#hs-leg").textContent = "Pode falar…";
    $("#hs-andamento").classList.add("hidden");
    $("#hs-gravar").classList.add("hidden"); $("#hs-pausar").classList.remove("hidden"); $("#hs-terminar").classList.remove("hidden");
    $("#hs-pausar").textContent = "Pausar";
    $("#hs-palco").classList.add("ao-vivo");
    fundo(0); $("#hs-cena").textContent = "Cena 1";
    msg("Ouvindo… fale normalmente; o texto aparece em poucos segundos.");
  }

  function despejar() {
    const W = H.vivo; if (!W || !W.len) return;
    const tudo = new Int16Array(W.len); let o = 0;
    W.buf.forEach((b) => { tudo.set(b, o); o += b.length; });
    W.buf = []; W.len = 0; W.silencio = 0;
    W.fila.push(tudo);
    enviarFila();
  }

  async function enviarFila() {
    const W = H.vivo; if (!W || W.enviando) return;
    W.enviando = true;
    while (W.fila.length) {
      const b = W.fila.shift();
      W.atraso = W.fila.reduce((s, x) => s + x.length, 0) / SR;
      try {
        const r = await fetch(`/api/historia/${W.pid}/ao-vivo/pedaco`, { method: "POST", body: b.buffer, headers: { "Content-Type": "application/octet-stream" } });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        const js = await r.json();
        recebe(js.palavras || []);
      } catch (e) { msg("Falha ao transcrever um trecho: " + e.message); }
      if (W.gravando && !W.pausado) msg(W.atraso > 6 ? `Ouvindo… (a transcrição está ${Math.round(W.atraso)} s atrás)` : "Ouvindo…");
    }
    W.enviando = false;
  }

  function msg(t) { $("#hs-vivo-msg").textContent = t; }

  function recebe(palavras) {
    const W = H.vivo; if (!palavras.length) return;
    const txt = palavras.map((p) => p.w).join(" ");
    const span = document.createElement("span"); span.textContent = txt + " ";
    $("#hs-transc").appendChild(span); $("#hs-transc").scrollTop = 1e9;
    W.texto += " " + txt;
    const ult = W.texto.trim().split(/\s+/).slice(-6).join(" ");
    $("#hs-leg").textContent = ult.toUpperCase();
    W.cena.push(...palavras.map((p) => p.w));
    const fimFrase = /[.?!…]$/.test(palavras[palavras.length - 1].w);
    if (W.cena.length >= 26 || (W.cena.length >= 12 && fimFrase)) {
      const trecho = W.cena.join(" "); W.cena = []; W.ncena++;
      $("#hs-cena").textContent = "Cena " + (W.ncena + 1);
      api("POST", "/api/historia/previa", { texto: trecho, formato: H.formato })
        .then((p) => { fundo(W.ncena, p.imagem); $("#hs-cena").textContent = `Cena ${W.ncena + 1} · ${p.busca}`; })
        .catch(() => fundo(W.ncena));
    }
  }

  function pausar() {
    const W = H.vivo; if (!W) return;
    W.pausado = !W.pausado;
    if (W.pausado) { despejar(); msg("Pausado. A pausa não entra no vídeo."); $("#hs-pausar").textContent = "Continuar"; }
    else { msg("Ouvindo…"); $("#hs-pausar").textContent = "Pausar"; }
  }

  function pararMic() {
    const W = H.vivo; if (!W) return;
    try { W.proc.disconnect(); W.ctx.close(); } catch (_) {}
    W.stream.getTracks().forEach((t) => t.stop());
    $("#hs-nivel").style.width = "0";
  }

  async function terminar() {
    const W = H.vivo; if (!W) return;
    W.gravando = false;
    despejar();
    pararMic();
    $("#hs-pausar").classList.add("hidden"); $("#hs-terminar").classList.add("hidden");
    $("#hs-palco").classList.remove("ao-vivo");
    msg("Terminando a transcrição dos últimos segundos…");
    while (W.enviando || W.fila.length) await new Promise((ok) => setTimeout(ok, 300));
    if (W.segs < 2) { toast("A gravação ficou curta demais.", true); reset(); return; }
    try {
      const r = await api("POST", `/api/historia/${W.pid}/ao-vivo/terminar`, { opcoes: opcoes() });
      msg("Gravação encerrada. Montando o vídeo…");
      H.vivo = null;
      $("#hs-gravar").classList.remove("hidden");
      await acompanhar(r);
    } catch (e) { toast(e.message, true); reset(); }
  }

  function reset() {
    H.vivo = null;
    $("#hs-gravar").classList.remove("hidden"); $("#hs-pausar").classList.add("hidden"); $("#hs-terminar").classList.add("hidden");
    $("#hs-palco").classList.remove("ao-vivo");
  }

  /* ---------------- ligar a tela ---------------- */
  function setup() {
    $$("[data-hmodo]").forEach((b) => b.addEventListener("click", () => trocaModo(b.dataset.hmodo)));
    $$("#hs-formato .chip-btn").forEach((b) => b.addEventListener("click", () => {
      if (H.vivo && H.vivo.gravando) { toast("O formato não muda durante a gravação.", true); return; }
      H.formato = b.dataset.v;
      $$("#hs-formato .chip-btn").forEach((x) => x.classList.toggle("active", x === b));
      $("#hs-palco").dataset.fmt = H.formato;
    }));
    $("#hs-texto").addEventListener("input", contar);
    $("#hs-vel").addEventListener("input", () => {
      const v = +$("#hs-vel").value;
      $("#hs-vel-v").textContent = v === 0 ? "normal" : (v > 0 ? "+" : "") + v + "%";
    });
    $("#hs-arquivo").addEventListener("change", () => {
      const f = $("#hs-arquivo").files[0];
      $("#hs-arquivo-nome").textContent = f ? `${f.name} (${fmtSize(f.size)})` : "Escolha o áudio da narração";
    });
    $("#hs-criar").addEventListener("click", criar);
    $("#hs-visual").addEventListener("change", avisoVisual);
    $("#hs-legenda").addEventListener("change", () => $("#hs-leg-box").classList.toggle("hidden", !$("#hs-legenda").checked));
    $("#hs-rot-montar").addEventListener("click", montarRoteiro);
    $("#hs-rot-voltar").addEventListener("click", () => { H.rot = null; $("#hs-roteiro").classList.add("hidden"); $("[data-hpainel=texto]").classList.remove("hidden"); });
    $("#hs-revisar").addEventListener("change", () => { $("#hs-criar").textContent = $("#hs-revisar").checked ? "Dividir em cenas para revisar" : "Criar o vídeo"; });
    $("#hs-ia").addEventListener("change", () => { H.iaTocado = true; });
    $("#hs-k-salvar").addEventListener("click", salvarChaves);
    $("#hs-mic-config").addEventListener("click", () => api("POST", "/api/historia/microfone/config").catch((e) => toast(e.message, true)));
    $("#hs-mic-tentar").addEventListener("click", comecar);
    $("#hs-gravar").addEventListener("click", comecar);
    $("#hs-pausar").addEventListener("click", pausar);
    $("#hs-terminar").addEventListener("click", terminar);
    window.addEventListener("beforeunload", (e) => { if (H.vivo && H.vivo.gravando) { e.preventDefault(); e.returnValue = ""; } });
    trocaModo("texto");
  }

  function onHome(page) { if (page === "historia") carregar(); }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup); else setup();
  window.V19 = { onHome };
})();
