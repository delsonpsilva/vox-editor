"use strict";
/* v1.15.2 — Instalar o VOX Editor no celular.
   Android (Chrome, Edge, Samsung): botão "Instalar" abre a janela de instalação do próprio celular.
   iPhone/iPad (Safari): o iPhone não deixa um site instalar sozinho, então mostramos os 3 toques
   (Compartilhar > Adicionar à Tela de Início). Não aparece no programa do PC nem depois de instalado. */
(function () {
  const I = { evento: null };
  const CHAVE = "vox.pwa.depois";
  const ua = navigator.userAgent || "";
  const ios = /iphone|ipad|ipod/i.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const android = /android/i.test(ua);
  const celular = ios || android || window.matchMedia("(max-width: 900px) and (pointer: coarse)").matches;
  const instalado = () => window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const noPrograma = () => !!window.pywebview || /pywebview/i.test(ua) || ["127.0.0.1", "localhost"].includes(location.hostname);
  const safariIos = ios && !/crios|fxios|edgios|opios/i.test(ua);

  // a "service worker" deixa o Chrome oferecer a instalação; ela não guarda nada (a tela sempre vem nova do servidor)
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    I.evento = e;
    atualizar();
  });
  window.addEventListener("appinstalled", () => {
    I.evento = null;
    atualizar();
    if (window.toast) toast("Pronto! O VOX Editor está na tela do seu celular.");
  });

  function podeMostrar() {
    if (instalado() || noPrograma()) return false;
    return !!I.evento || celular;
  }

  function atualizar() {
    const mostrar = podeMostrar();
    const side = document.getElementById("pwa-side");
    if (side) side.classList.toggle("hidden", !mostrar);
    const ban = document.getElementById("pwa-banner");
    if (!ban) return;
    let adiado = 0;
    try { adiado = +localStorage.getItem(CHAVE) || 0; } catch (_) {}
    const recente = Date.now() - adiado < 7 * 864e5;  // "agora não" vale por 7 dias
    const ed = document.getElementById("view-editor");
    const naTela = !ed || ed.classList.contains("hidden");  // não atrapalha dentro do editor
    ban.classList.toggle("hidden", !(mostrar && celular && !recente && naTela));
  }

  function passos() {
    const caixa = document.getElementById("pwa-passos");
    const icone = (d) => `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
    const compart = icone('<path d="M12 3v12"/><path d="M8 7l4-4 4 4"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/>');
    const mais = icone('<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M12 8v8M8 12h8"/>');
    const pontos = icone('<circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/>');
    if (ios && !safariIos) {
      caixa.innerHTML = `<p>No iPhone, a instalação só funciona pelo <b>Safari</b>.</p>
        <ol class="pwa-ol"><li>Copie o endereço desta página: <b>${location.host}</b></li>
        <li>Abra no <b>Safari</b> e siga os passos que vão aparecer.</li></ol>`;
    } else if (ios) {
      caixa.innerHTML = `<ol class="pwa-ol">
        <li><span class="pwa-ic">${compart}</span> Toque em <b>Compartilhar</b> (o quadrado com a seta, embaixo da tela).</li>
        <li><span class="pwa-ic">${mais}</span> Role e toque em <b>Adicionar à Tela de Início</b>.</li>
        <li>Toque em <b>Adicionar</b>. O ícone do VOX Editor aparece junto com os seus apps.</li></ol>`;
    } else {
      caixa.innerHTML = `<ol class="pwa-ol">
        <li><span class="pwa-ic">${pontos}</span> Toque nos <b>três pontinhos</b> do Chrome (em cima, à direita).</li>
        <li>Toque em <b>Instalar app</b> (ou <b>Adicionar à tela inicial</b>).</li>
        <li>Confirme em <b>Instalar</b>. O ícone do VOX Editor aparece na tela do celular.</li></ol>
        <p class="hint">Se não aparecer a opção, abra este endereço no <b>Chrome</b>: ${location.host}</p>`;
    }
  }

  async function instalar() {
    if (I.evento) {
      const ev = I.evento;
      I.evento = null;
      ev.prompt();
      try {
        const r = await ev.userChoice;
        if (r && r.outcome !== "accepted") { try { localStorage.setItem(CHAVE, String(Date.now())); } catch (_) {} }
      } catch (_) {}
      atualizar();
      return;
    }
    passos();
    const d = document.getElementById("pwa-dlg");
    if (d && d.showModal) d.showModal();
  }

  function setup() {
    const b = document.getElementById("pwa-instalar");
    if (!b) return;
    b.addEventListener("click", instalar);
    document.getElementById("pwa-side").addEventListener("click", () => { document.body.classList.remove("drawer-open"); instalar(); });
    document.getElementById("pwa-fechar").addEventListener("click", () => {
      try { localStorage.setItem(CHAVE, String(Date.now())); } catch (_) {}
      atualizar();
    });
    window.addEventListener("hashchange", () => setTimeout(atualizar, 300));
    setTimeout(atualizar, 1200);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup); else setup();
  window.VOXInstalar = { instalar, atualizar };
})();
