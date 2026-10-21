/* VOX Editor 1.7 — contas de pessoas na versão online: equipe e clientes com login próprio, limites e uso.
   Telas: "Contas" (só o responsável e os administradores) e "Minha conta" (cada pessoa: uso, trocar senha, sair).
   Usa as funções do app.js: $, $$, api, esc, toast, fmtSize, S, show, goHome. */
(function () {
  const ICONE = {
    contas: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17.5" cy="9" r="2.5"/><path d="M16 14.2c2.9.3 5 2.6 5 5.8"/></svg>',
    conta: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/></svg>',
    sair: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5"/><path d="M5 12h11"/></svg>',
  };
  const TIPOS = {
    admin: ["Administrador", "Faz tudo, como o responsável: configurações, redes, marca e contas."],
    equipe: ["Equipe", "Vê e edita todos os projetos e publica nas redes já conectadas. Não mexe em configurações."],
    cliente: ["Cliente", "Vê só os próprios projetos. Edita, corta, monta e baixa os vídeos. Não publica."],
  };
  const C = { eu: null, lista: [], editando: null };

  const dataBR = (t) => t ? new Date(t * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "nunca";
  const gb = (v) => (v || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 }) + " GB";
  const senhaAleatoria = () => {
    const a = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789";
    const r = crypto.getRandomValues(new Uint32Array(10));
    return Array.from(r, (n) => a[n % a.length]).join("");
  };
  function barra(usado, limite, un) {
    if (!limite) return `<div class="v17-uso"><span>${esc(usado)} ${un}</span><em>sem limite</em></div>`;
    const pct = Math.min(100, (usado / limite) * 100);
    return `<div class="v17-uso"><span>${esc(usado.toLocaleString("pt-BR"))} de ${esc(limite.toLocaleString("pt-BR"))} ${un}</span>
      <i class="v17-bar"><b style="width:${pct.toFixed(1)}%" class="${pct >= 90 ? "cheio" : ""}"></b></i></div>`;
  }

  /* ---------------- montar menu e páginas (uma vez) ---------------- */
  function montar() {
    if ($("#pg-usuarios")) return;
    const nav = $(".side-nav"), cfg = $(".side-nav [data-open-settings]");
    const a1 = document.createElement("a");
    a1.href = "#/usuarios"; a1.dataset.page = "usuarios"; a1.dataset.tip = "Contas"; a1.className = "v17-so-chefe hidden";
    a1.innerHTML = ICONE.contas + '<span class="lbl">Contas</span> <span class="count" id="nav-count-u"></span>';
    const a2 = document.createElement("a");
    a2.href = "#/conta"; a2.dataset.page = "conta"; a2.dataset.tip = "Minha conta"; a2.className = "v17-so-pessoa hidden";
    a2.innerHTML = ICONE.conta + '<span class="lbl">Minha conta</span>';
    const caixa = cfg ? cfg.parentNode : nav;  // v1.11: o menu é dividido em blocos (Criar, Publicar, Estilo, Sistema)
    caixa.insertBefore(a1, cfg); caixa.insertBefore(a2, cfg);
    const sair = document.createElement("button");
    sair.type = "button"; sair.className = "v17-sair hidden"; sair.dataset.tip = "Sair";
    sair.innerHTML = ICONE.sair + '<span class="lbl">Sair</span>';
    sair.addEventListener("click", sairDaConta);
    caixa.appendChild(sair);

    const pages = $("main.pages");
    pages.insertAdjacentHTML("beforeend", `
      <section class="page hidden" id="pg-usuarios">
        <header class="page-head">
          <div><h1>Contas</h1><p>Dê acesso à sua equipe e aos seus clientes. Cada pessoa entra com o próprio e-mail e senha; você decide o que ela pode fazer e quanto pode usar.</p></div>
          <button class="btn primary" id="v17-nova">+ Nova conta</button>
        </header>
        <section class="v17-tipos">
          ${Object.entries(TIPOS).map(([k, [n, d]]) => `<div class="v17-tipo"><b>${n}</b><span>${d}</span></div>`).join("")}
        </section>
        <section class="pane">
          <div class="row between"><h2>Pessoas com acesso</h2><span class="hint" id="v17-resumo"></span></div>
          <div id="v17-tabela"></div>
        </section>
      </section>
      <section class="page hidden" id="pg-conta">
        <header class="page-head"><div><h1>Minha conta</h1><p id="v17-conta-sub"></p></div></header>
        <section class="pane" id="v17-conta-uso"></section>
        <section class="pane" id="v17-conta-senha">
          <h2>Trocar a senha</h2>
          <form id="v17-form-senha" class="v17-form">
            <label class="field">Senha atual<input type="password" name="atual" autocomplete="current-password" required></label>
            <div class="grid2">
              <label class="field">Senha nova (mínimo 6)<input type="password" name="nova" autocomplete="new-password" minlength="6" required></label>
              <label class="field">Repita a senha nova<input type="password" name="nova2" autocomplete="new-password" minlength="6" required></label>
            </div>
            <div class="row"><button class="btn primary" type="submit">Trocar a senha</button><span class="hint" id="v17-senha-msg"></span></div>
          </form>
        </section>
        <section class="pane"><div class="row between"><div><h2>Sair</h2><p class="hint">Encerra o acesso neste aparelho.</p></div>
          <button class="btn" id="v17-sair2">Sair da conta</button></div></section>
      </section>`);
    document.body.insertAdjacentHTML("beforeend", `
      <dialog id="v17-dlg">
        <form method="dialog" id="v17-form" class="settings v17-form">
          <header class="row between"><h2 id="v17-dlg-tit">Nova conta</h2><button class="btn icon ghost" value="cancel" formnovalidate aria-label="Fechar">✕</button></header>
          <div class="grid2">
            <label class="field">Nome<input name="nome" maxlength="80" required></label>
            <label class="field">E-mail (é o login)<input name="email" type="email" maxlength="120" required autocomplete="off"></label>
          </div>
          <label class="field"><span class="lbl"><span id="v17-senha-lbl">Senha (mínimo 6)</span><button type="button" class="linkbtn" id="v17-gerar">Gerar senha</button></span>
            <input name="senha" type="text" minlength="6" autocomplete="new-password"></label>
          <label class="field">Tipo de conta
            <select name="papel">${Object.entries(TIPOS).map(([k, [n]]) => `<option value="${k}">${n}</option>`).join("")}</select></label>
          <p class="hint" id="v17-tipo-desc"></p>
          <div class="grid2">
            <label class="field">Limite de espaço (GB)<input name="limite_gb" type="number" min="0" step="0.5" placeholder="0 = sem limite"></label>
            <label class="field">Minutos de vídeo por mês<input name="limite_min" type="number" min="0" step="10" placeholder="0 = sem limite"></label>
          </div>
          <label class="field">Observação (só você vê)<input name="obs" maxlength="300" placeholder="Ex.: Igreja Central, plano Criador"></label>
          <label class="v17-check hidden" id="v17-ativo-box"><input type="checkbox" name="ativo"> Conta liberada (desmarque para bloquear o acesso)</label>
          <p class="err" id="v17-err"></p>
          <div class="row end"><button class="btn ghost" value="cancel" formnovalidate>Cancelar</button><button class="btn primary" id="v17-salvar" value="default">Salvar</button></div>
        </form>
      </dialog>
      <dialog id="v17-pronto">
        <form method="dialog" class="settings v17-form">
          <header class="row between"><h2>Conta criada</h2><button class="btn icon ghost" value="cancel" aria-label="Fechar">✕</button></header>
          <p>Mande estes dados para a pessoa. A senha não aparece de novo (dá para criar outra em Editar).</p>
          <pre id="v17-pronto-txt" class="v17-pre"></pre>
          <div class="row end"><button class="btn primary" type="button" id="v17-copiar">Copiar dados de acesso</button><button class="btn ghost" value="cancel">Fechar</button></div>
        </form>
      </dialog>
      <dialog id="v17-rem">
        <form method="dialog" class="settings v17-form">
          <header class="row between"><h2>Remover conta</h2><button class="btn icon ghost" value="cancel" aria-label="Fechar">✕</button></header>
          <p id="v17-rem-txt"></p>
          <div class="row end">
            <button class="btn ghost" value="cancel">Cancelar</button>
            <button class="btn" value="apagar" id="v17-rem-apagar">Remover e apagar os projetos</button>
            <button class="btn primary" value="manter">Remover e ficar com os projetos</button>
          </div>
        </form>
      </dialog>`);

    $("#v17-nova").addEventListener("click", () => abrirForm(null));
    $("#v17-gerar").addEventListener("click", () => { $("#v17-form").senha.value = senhaAleatoria(); });
    $("#v17-form").papel.addEventListener("change", (e) => ($("#v17-tipo-desc").textContent = TIPOS[e.target.value][1]));
    $("#v17-form").addEventListener("submit", salvarForm);
    $("#v17-copiar").addEventListener("click", () => {
      navigator.clipboard.writeText($("#v17-pronto-txt").textContent).then(() => toast("Dados copiados"), () => toast("Selecione o texto e copie", true));
    });
    $("#v17-form-senha").addEventListener("submit", trocarSenha);
    $("#v17-sair2").addEventListener("click", sairDaConta);
  }

  /* ---------------- quem sou eu: aplica o que cada tipo vê ---------------- */
  async function boot() {
    montar();
    try { C.eu = await api("GET", "/api/eu"); } catch (_) { C.eu = null; }
    aplicar();
    if (C.eu && C.eu.trocar_senha) pedirSenhaNova();
    return C.eu;
  }

  function aplicar() {
    const eu = C.eu || { papel: "dono", contas: false, login: false };
    const b = document.body;
    ["dono", "admin", "equipe", "cliente"].forEach((p) => b.classList.toggle("papel-" + p, eu.papel === p));
    const chefe = eu.papel === "dono" || eu.papel === "admin";
    b.classList.toggle("v17-restrito", !chefe);
    $$(".v17-so-chefe").forEach((el) => el.classList.toggle("hidden", !(chefe && eu.contas)));
    $$(".v17-so-pessoa").forEach((el) => el.classList.toggle("hidden", !eu.login));
    $$(".v17-sair").forEach((el) => el.classList.toggle("hidden", !eu.login));
    // títulos de grupo do menu que ficaram sem nenhum item visível
    $$(".side-nav .nav-group").forEach((g) => {
      let el = g.nextElementSibling, algum = false;
      while (el && !el.classList.contains("nav-group")) {
        if (getComputedStyle(el).display !== "none" && !el.classList.contains("hidden")) algum = true;
        el = el.nextElementSibling;
      }
      const bloco = g.closest(".nav-card");  // v1.11: esconde o bloco inteiro quando fica vazio
      (bloco || g).style.display = algum ? "" : "none";
    });
    if (eu.papel === "cliente") {  // publicar fica com o responsável: o botão vira um aviso
      window.openPublish = () => toast("Publicar nas redes fica com o responsável pela conta. Baixe o vídeo e envie para ele.", true);
    }
    const nome = $("#v17-quem");
    if (nome) nome.textContent = eu.papel === "dono" ? "" : `${eu.nome} · ${eu.papel_nome}`;
  }

  async function sairDaConta() {
    try { await api("POST", "/api/logout"); } catch (_) {}
    location.hash = "#/";
    location.reload();
  }

  /* ---------------- página Contas ---------------- */
  async function renderUsuarios() {
    const box = $("#v17-tabela");
    box.innerHTML = '<p class="hint">Carregando…</p>';
    let d;
    try { d = await api("GET", "/api/usuarios"); } catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
    C.lista = d.usuarios;
    $("#nav-count-u").textContent = d.usuarios.length || "";
    const ativos = d.usuarios.filter((u) => u.ativo).length;
    $("#v17-resumo").textContent = d.usuarios.length ? `${ativos} liberada${ativos === 1 ? "" : "s"} de ${d.usuarios.length} · ${d.projetos_do_dono} projeto${d.projetos_do_dono === 1 ? "" : "s"} seus` : "";
    if (!d.usuarios.length) {
      box.innerHTML = `<div class="empty-state">Ninguém além de você tem acesso ainda. Clique em <b>+ Nova conta</b> para dar acesso a alguém da equipe ou a um cliente.</div>`;
      return;
    }
    box.innerHTML = `<div class="v17-tab">
      <div class="v17-lin v17-cab"><span>Pessoa</span><span>Tipo</span><span>Projetos</span><span>Espaço</span><span>Minutos no mês</span><span>Último acesso</span><span></span></div>
      ${d.usuarios.map((u) => `
        <div class="v17-lin ${u.ativo ? "" : "v17-bloq"}" data-uid="${esc(u.id)}">
          <span class="v17-pessoa"><b>${esc(u.nome)}</b><em>${esc(u.email)}</em>${u.obs ? `<em class="v17-obs">${esc(u.obs)}</em>` : ""}</span>
          <span data-l="Tipo"><span class="chip v17-p-${esc(u.papel)}">${esc(u.papel_nome)}</span>${u.ativo ? "" : ' <span class="chip v17-chip-bloq">Bloqueada</span>'}</span>
          <span data-l="Projetos">${u.projetos}</span>
          <span data-l="Espaço">${barra(u.uso.espaco_gb, u.uso.limite_gb, "GB")}</span>
          <span data-l="Minutos">${barra(u.uso.minutos_mes, u.uso.limite_min, "min")}</span>
          <span data-l="Último acesso" class="hint">${esc(dataBR(u.ultimo_acesso))}</span>
          <span class="v17-acoes">
            <button class="btn small" data-ed>Editar</button>
            <button class="btn small ghost" data-bl>${u.ativo ? "Bloquear" : "Liberar"}</button>
            <button class="btn small ghost" data-rm aria-label="Remover">Remover</button>
          </span>
        </div>`).join("")}
    </div>`;
    $$(".v17-lin[data-uid]", box).forEach((row) => {
      const u = C.lista.find((x) => x.id === row.dataset.uid);
      $("[data-ed]", row).addEventListener("click", () => abrirForm(u));
      $("[data-bl]", row).addEventListener("click", async () => {
        try { await api("PUT", `/api/usuarios/${u.id}`, { ativo: !u.ativo }); toast(u.ativo ? "Conta bloqueada" : "Conta liberada"); renderUsuarios(); }
        catch (e) { toast(e.message, true); }
      });
      $("[data-rm]", row).addEventListener("click", () => remover(u));
    });
  }

  function abrirForm(u) {
    C.editando = u;
    const f = $("#v17-form");
    f.reset();
    $("#v17-err").textContent = "";
    $("#v17-dlg-tit").textContent = u ? `Editar: ${u.nome}` : "Nova conta";
    $("#v17-senha-lbl").textContent = u ? "Senha nova (deixe vazio para manter)" : "Senha (mínimo 6)";
    f.senha.required = !u;
    f.nome.value = u ? u.nome : "";
    f.email.value = u ? u.email : "";
    f.papel.value = u ? u.papel : "cliente";
    f.limite_gb.value = u && u.limite_gb ? u.limite_gb : "";
    f.limite_min.value = u && u.limite_min ? u.limite_min : "";
    f.obs.value = u ? u.obs || "" : "";
    f.ativo.checked = u ? !!u.ativo : true;
    $("#v17-ativo-box").classList.toggle("hidden", !u);
    if (!u) f.senha.value = senhaAleatoria();
    $("#v17-tipo-desc").textContent = TIPOS[f.papel.value][1];
    $("#v17-dlg").showModal();
    setTimeout(() => f.nome.focus(), 30);
  }

  async function salvarForm(e) {
    if (e.submitter && e.submitter.value === "cancel") return;
    e.preventDefault();
    const f = e.target, u = C.editando;
    const dados = { nome: f.nome.value, email: f.email.value, papel: f.papel.value, obs: f.obs.value,
      limite_gb: parseFloat(f.limite_gb.value) || 0, limite_min: parseFloat(f.limite_min.value) || 0 };
    if (f.senha.value) dados.senha = f.senha.value;
    if (u) dados.ativo = f.ativo.checked;
    try {
      const r = await api(u ? "PUT" : "POST", u ? `/api/usuarios/${u.id}` : "/api/usuarios", dados);
      $("#v17-dlg").close();
      renderUsuarios();
      if (!u || dados.senha) {
        $("#v17-pronto-txt").textContent = `Acesso ao ${(S.status && S.status.name) || "VOX Editor"}\nEndereço: ${location.origin}\nE-mail: ${r.email}\nSenha: ${dados.senha}`;
        $("#v17-pronto").querySelector("h2").textContent = u ? "Senha nova salva" : "Conta criada";
        $("#v17-pronto").showModal();
      } else toast("Conta salva");
    } catch (err) { $("#v17-err").textContent = err.message; }
  }

  function remover(u) {
    $("#v17-rem-txt").innerHTML = `A conta de <b>${esc(u.nome)}</b> (${esc(u.email)}) vai deixar de entrar. ` +
      (u.projetos ? `Ela tem <b>${u.projetos}</b> projeto${u.projetos === 1 ? "" : "s"}: você pode ficar com eles ou apagar junto.` : "Ela não tem projetos.");
    $("#v17-rem-apagar").classList.toggle("hidden", !u.projetos);
    const dlg = $("#v17-rem");
    dlg.returnValue = "";
    dlg.onclose = async () => {
      const v = dlg.returnValue;
      if (v !== "manter" && v !== "apagar") return;
      try { await api("DELETE", `/api/usuarios/${u.id}?projetos=${v}`); toast("Conta removida"); renderUsuarios(); }
      catch (e) { toast(e.message, true); }
    };
    dlg.showModal();
  }

  /* ---------------- página Minha conta ---------------- */
  async function renderConta() {
    try { C.eu = await api("GET", "/api/eu"); } catch (_) {}
    const eu = C.eu || {};
    $("#v17-conta-sub").textContent = eu.papel === "dono" ? "Usuário: admin · responsável por este VOX Editor." : `${eu.nome} · ${eu.email} · ${eu.papel_nome}`;
    const uso = eu.uso;
    $("#v17-conta-uso").innerHTML = uso ? `
      <h2>Seu uso</h2>
      <div class="grid2">
        <div><p class="hint">Espaço dos seus projetos</p>${barra(uso.espaco_gb, uso.limite_gb, "GB")}</div>
        <div><p class="hint">Vídeo analisado neste mês</p>${barra(uso.minutos_mes, uso.limite_min, "min")}</div>
      </div>
      <p class="hint">${TIPOS[eu.papel] ? esc(TIPOS[eu.papel][1]) : ""} Os minutos voltam a zero no dia 1º de cada mês. Para aumentar, fale com o responsável.</p>`
      : `<h2>Seu acesso</h2><p class="hint">Você é o <b>admin</b>: entra com o usuário admin e a sua senha, e pode tudo.${eu.contas ? " As contas da equipe e dos clientes ficam em Contas." : ""}</p>`;
    $("#v17-conta-senha").classList.remove("hidden");
  }

  async function trocarSenha(e) {
    e.preventDefault();
    const f = e.target, msg = $("#v17-senha-msg");
    if (f.nova.value !== f.nova2.value) { msg.className = "err"; msg.textContent = "As duas senhas novas não são iguais."; return; }
    try {
      if ((C.eu || {}).papel === "dono") await api("POST", "/api/security/password", { current: f.atual.value, new: f.nova.value });
      else await api("POST", "/api/eu/senha", { atual: f.atual.value, nova: f.nova.value });
      f.reset(); msg.className = "hint ok"; msg.textContent = "Senha trocada.";
    } catch (err) { msg.className = "err"; msg.textContent = err.message; }
  }

  /* ---------------- ganchos chamados pelo app.js ---------------- */
  const SO_CHEFE = ["modelos", "marca", "ia", "redes", "usuarios"];
  function onHome(page) {
    const eu = C.eu || { papel: "dono" };
    const chefe = eu.papel === "dono" || eu.papel === "admin";
    if ((!chefe && SO_CHEFE.includes(page)) || (eu.papel === "cliente" && page === "publicacoes")) {
      location.hash = "#/";  // tela que este tipo de conta não usa
      return;
    }
    if (page === "usuarios") renderUsuarios();
    if (page === "conta") renderConta();
  }

  function preparaLogin() {
    const u = $("#login-email");
    if (u && !u.value) u.value = "admin";
  }

  /* primeiro acesso com a senha padrão: pede uma senha nova antes de qualquer coisa */
  function pedirSenhaNova() {
    if (!$("#v17-primeira")) {
      document.body.insertAdjacentHTML("beforeend", `
        <dialog id="v17-primeira">
          <form id="v17-form-primeira" class="settings v17-form">
            <h2>Crie a sua senha</h2>
            <p>Você entrou com a senha padrão. Para proteger seus projetos, crie agora uma senha só sua.
              Daqui em diante, entre com o usuário <b>admin</b> e esta senha.</p>
            <label class="field">Senha nova (mínimo 6)<input type="password" name="nova" minlength="6" autocomplete="new-password" required></label>
            <label class="field">Repita a senha nova<input type="password" name="nova2" minlength="6" autocomplete="new-password" required></label>
            <p class="err" id="v17-primeira-err"></p>
            <div class="row end"><button class="btn primary" type="submit">Salvar a senha</button></div>
          </form>
        </dialog>`);
      const dlg = $("#v17-primeira");
      dlg.addEventListener("cancel", (e) => e.preventDefault());  // não fecha com Esc
      $("#v17-form-primeira").addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = e.target, err = $("#v17-primeira-err");
        if (f.nova.value !== f.nova2.value) { err.textContent = "As duas senhas não são iguais."; return; }
        try {
          await api("POST", "/api/security/password", { current: "", new: f.nova.value });
          dlg.close(); toast("Senha criada. Use admin e esta senha para entrar.");
          if (C.eu) C.eu.trocar_senha = false;
        } catch (er) { err.textContent = er.message; }
      });
    }
    if (!$("#v17-primeira").open) $("#v17-primeira").showModal();
  }

  window.V17 = { boot, aplicar, onHome, preparaLogin, eu: () => C.eu };
  montar();
})();
