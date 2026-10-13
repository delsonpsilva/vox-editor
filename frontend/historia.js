"use strict";
/* v1.9 — História → Vídeo: texto, áudio gravado ou narração ao vivo viram uma Montagem pronta. */
(function () {
  const H = { modo: "texto", formato: "9:16", st: null, ocupado: false, vivo: null };
  const opcoes = () => ({
    formato: H.formato, voz: $("#hs-voz").value || "francisca", visual: $("#hs-visual").value,
    legenda: $("#hs-legenda").checked, usar_ia: $("#hs-ia").checked && !$("#hs-ia").disabled,
    musica: $("#hs-musica").value, velocidade: +$("#hs-vel").value,
  });

  /* ---------------- estado e opções ---------------- */
  async function carregar() {
    try { H.st = await api("GET", "/api/historia/status"); } catch (e) { toast(e.message, true); return; }
    const st = H.st, voz = $("#hs-voz"), atual = voz.value;
    voz.innerHTML = st.vozes.map((v) => `<option value="${esc(v.id)}"${v.ok ? "" : " disabled"}>${esc(v.nome)}${v.ok ? "" : " — indisponível aqui"}</option>`).join("");
    voz.value = atual && st.vozes.some((v) => v.id === atual && v.ok) ? atual : (st.vozes.find((v) => v.ok) || {}).id || "nenhuma";
    const mus = $("#hs-musica"), m0 = mus.value;
    mus.innerHTML = `<option value="">Sem música</option>` + st.musicas.map((n) => `<option>${esc(n)}</option>`).join("");
    if (st.musicas.includes(m0)) mus.value = m0;
    $("#hs-sem-banco").classList.toggle("hidden", st.bancos);
    if (!st.bancos && $("#hs-visual").value !== "cores") $("#hs-visual").value = "cores";
    $("#hs-ia").disabled = !st.ia;
    $("#hs-ia").checked = st.ia && $("#hs-ia").checked;
    $("#hs-ia-msg").textContent = st.ia ? "" : "(ligue uma IA em Inteligência artificial; sem ela a divisão é automática e grátis)";
  }

  function trocaModo(m) {
    if (H.vivo && H.vivo.gravando && m !== "vivo") { toast("Termine ou pause a narração ao vivo antes de trocar.", true); return; }
    H.modo = m;
    if (!H.ocupado) $("#hs-andamento").classList.add("hidden");
    $$("[data-hmodo]").forEach((b) => b.classList.toggle("active", b.dataset.hmodo === m));
    $$("[data-hpainel]").forEach((p) => p.classList.toggle("hidden", p.dataset.hpainel !== m));
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
          andamento("Pronto!", 1, `${res.cenas} cena${res.cenas === 1 ? "" : "s"} · ${fmtDur(res.duracao)}${res.modo === "ia" ? " · cenas escolhidas pela IA" : ""}`);
          if (res.aviso) toast(res.aviso, true); else toast("Vídeo montado! Abrindo na Montagem…");
          setTimeout(() => { location.hash = "#/p/" + r.id + "/montagem"; }, res.aviso ? 1800 : 700);
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
      toast("Não consegui usar o microfone. Permita o acesso (e confira em Configurações do Windows → Privacidade → Microfone).", true);
      return;
    }
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
