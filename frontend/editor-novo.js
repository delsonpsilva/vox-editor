/* VOX Editor 1.6 — a cara nova da tela principal dentro do editor (abas Edição, Cortes e Montagem):
   menu lateral em ícones (o mesmo da tela principal), barra do topo com o caminho, busca rápida (Ctrl+K) e Atividade.
   Usa as funções do app.js ($, $$, S, openSettings) e do inicio.js (V14). */
(function () {
  function montarMenu() {
    const rail = $("#ed-rail");
    const nav = $(".side-nav").cloneNode(true);
    nav.removeAttribute("aria-label");
    $$("[id]", nav).forEach((el) => el.removeAttribute("id"));
    $$(".count, .nav-group", nav).forEach((el) => el.remove());
    $$("a[data-page]", nav).forEach((a) => {
      a.title = a.dataset.tip || "";
      a.classList.toggle("active", a.dataset.page === "projetos");
    });
    const cfg = $("[data-open-settings]", nav);
    if (cfg) { cfg.title = "Configurações"; cfg.addEventListener("click", openSettings); }
    rail.innerHTML = `<a class="er-brand" href="#/" title="Início" aria-label="Início"><span class="logo app-logo"></span></a>`;
    // grupos separados por um traço, como no menu recolhido da tela principal
    const grupos = [["inicio", "projetos", "exportados"], ["publicacoes", "redes"], ["modelos", "marca"], ["ia"]];
    grupos.forEach((g, i) => {
      if (i) rail.insertAdjacentHTML("beforeend", `<span class="er-sep" aria-hidden="true"></span>`);
      g.forEach((pg) => { const a = $(`a[data-page="${pg}"]`, nav); if (a) rail.appendChild(a); });
    });
    if (cfg) rail.appendChild(cfg);
  }

  const nomeApp = () => (S.status || {}).name || "Editor IA";

  function setup() {
    montarMenu();
    $("#ed-search").addEventListener("click", () => { if (window.V14) V14.abrirBusca(); });
    // ao entrar no editor: atualiza a Atividade (badge) e o título da janela
    const obs = new MutationObserver(() => {
      const visivel = !$("#view-editor").classList.contains("hidden");
      if (visivel && !obs._on && window.V14 && V14.atualizar) V14.atualizar();
      if (!visivel && obs._on) document.title = nomeApp();
      obs._on = visivel;
    });
    obs.observe($("#view-editor"), { attributes: true, attributeFilter: ["class"] });
    const nome = $("#ed-name");
    new MutationObserver(() => {
      if (!$("#view-editor").classList.contains("hidden") && nome.textContent) document.title = nome.textContent + " · " + nomeApp();
    }).observe(nome, { childList: true, characterData: true, subtree: true });
  }

  setup();
})();
