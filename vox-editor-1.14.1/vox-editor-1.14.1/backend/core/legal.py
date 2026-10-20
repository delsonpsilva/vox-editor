"""Páginas públicas exigidas pelas redes para aprovar os apps oficiais: Termos de uso, Política de privacidade e
Exclusão de dados. Abrem sem senha em /termos, /privacidade e /exclusao-de-dados.

Os dados do responsável (nome, e-mail, cidade...) vêm de Configurações → Páginas públicas (seção "legal")."""
from __future__ import annotations

import html
import re
from urllib.parse import quote

from . import store

VIGENCIA = "5 de outubro de 2026"   # mude quando o texto mudar de verdade (as redes olham esta data)

PAGINAS = {
    "termos": "Termos de uso",
    "privacidade": "Política de privacidade",
    "exclusao-de-dados": "Exclusão de dados",
}


def _dados(base: str) -> dict:
    cfg = store.load_config()
    leg = cfg.get("legal") or {}
    nome_app = ((cfg.get("app") or {}).get("name") or "VOX Editor").strip()
    if nome_app == "Editor IA":
        nome_app = "VOX Editor"
    cor = (cfg.get("app") or {}).get("accent") or "#FF8A3D"
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", cor):
        cor = "#FF8A3D"
    return {
        "app": nome_app,
        "site": base.rstrip("/"),
        "resp": (leg.get("responsavel") or "").strip() or f"a equipe do {nome_app}",
        "doc": (leg.get("documento") or "").strip(),
        "email": (leg.get("email") or "").strip(),
        "cidade": (leg.get("cidade") or "").strip(),
        "cor": cor,
    }


def _contato(d: dict) -> str:
    if d["email"]:
        e = html.escape(d["email"])
        return f'<a href="mailto:{e}">{e}</a>'
    return "pelo canal de atendimento informado na contratação"


def _termos(d: dict) -> str:
    a, c = d["app"], _contato(d)
    foro = f"da comarca de {html.escape(d['cidade'])}" if d["cidade"] else "do domicílio do responsável pelo serviço"
    return f"""
<p class="lead">Estes termos valem para quem usa o {a} — o programa para computador e a versão online em
<a href="{d['site']}">{d['site']}</a>. Ao usar o {a}, você concorda com eles.</p>

<h2>1. O que é o {a}</h2>
<p>O {a} é um editor de vídeo. Ele transcreve a fala, corta silêncios e erros, gera cortes curtos com legenda,
permite montar vídeos com camadas (textos, fotos, músicas, transições e efeitos) e, se você quiser, publica os
vídeos prontos nas suas contas do YouTube, Facebook, Instagram e TikTok ou em destinos próprios (seu site, sua web TV).</p>

<h2>2. Sua conta e seu acesso</h2>
<p>O acesso à versão online é protegido por senha. Você é responsável por guardar a sua senha e por tudo o que
for feito com ela. Se suspeitar de uso indevido, avise {c} imediatamente.</p>

<h2>3. Seus vídeos são seus</h2>
<p>Você continua dono de tudo o que envia e cria no {a}. Você declara que tem o direito de usar cada vídeo, foto,
música e texto que coloca no editor, inclusive os baixados por link, e que é o responsável pelo que publica nas
redes. Nós não usamos o seu conteúdo para nenhum outro fim além de prestar o serviço para você.</p>

<h2>4. Publicação nas redes sociais</h2>
<p>Quando você conecta uma rede, o {a} recebe uma autorização da própria rede (você entra na sua conta pela página
oficial dela; o {a} nunca vê nem guarda a sua senha). O {a} só publica os vídeos que você aprovar, na data e na
conta que você escolher. Cada rede tem as suas regras e pode recusar, limitar ou remover uma publicação; ao
publicar, você também concorda com os termos dela, como os
<a href="https://www.youtube.com/t/terms" rel="noopener">Termos de Serviço do YouTube</a>.
Você pode desconectar uma rede a qualquer momento em <b>Redes sociais</b>.</p>

<h2>5. Uso permitido</h2>
<p>Não é permitido usar o {a} para: publicar conteúdo ilegal, que viole direitos autorais ou de imagem, que
incentive violência ou ódio, ou que engane as pessoas; enviar spam; tentar acessar dados de outras pessoas; ou
sobrecarregar e atacar o serviço. Contas que fizerem isso podem ser suspensas.</p>

<h2>6. Inteligência artificial e serviços de terceiros</h2>
<p>Algumas funções usam serviços de terceiros que você escolhe ligar (por exemplo, provedores de IA para
transcrição ou análise de texto, e bancos de vídeos grátis como Pexels e Pixabay). Os resultados da IA podem conter
erros: confira o vídeo antes de publicar. Mídias de bancos grátis seguem as licenças desses bancos.</p>

<h2>7. Planos e pagamento</h2>
<p>A versão online pode ser oferecida por planos. Preço, limites e forma de pagamento são os combinados na
contratação. O programa para computador e as funções sem custo podem mudar ou deixar de ser gratuitas, com aviso.</p>

<h2>8. Disponibilidade e responsabilidade</h2>
<p>Trabalhamos para o serviço ficar no ar o tempo todo, mas ele pode ter pausas para manutenção ou falhas fora do
nosso controle (internet, servidores, mudanças nas redes sociais). Guarde cópias dos seus vídeos importantes: o
botão <b>Baixar projeto completo (.vox)</b> serve para isso. Na medida permitida pela lei, não respondemos por
perdas indiretas, lucros cessantes ou por decisões das redes sociais sobre as suas publicações.</p>

<h2>9. Encerramento</h2>
<p>Você pode parar de usar o {a} quando quiser e pedir a exclusão dos seus dados (veja
<a href="{d['site']}/exclusao-de-dados">Exclusão de dados</a>). Podemos encerrar o acesso de quem descumprir estes
termos.</p>

<h2>10. Mudanças e lei aplicável</h2>
<p>Estes termos podem ser atualizados; a data no topo mostra a versão em vigor. Eles seguem as leis do Brasil,
incluindo o Código de Defesa do Consumidor e a Lei Geral de Proteção de Dados (Lei 13.709/2018). Fica eleito o foro
{foro}, sem prejuízo do foro do consumidor.</p>

<h2>11. Contato</h2>
<p>Dúvidas sobre estes termos: {c}.</p>
"""


def _privacidade(d: dict) -> str:
    a, c = d["app"], _contato(d)
    return f"""
<p class="lead">Esta política explica quais dados o {a} trata, para quê, com quem compartilha e como você controla
tudo isso. Ela segue a Lei Geral de Proteção de Dados (LGPD — Lei 13.709/2018).</p>

<h2>1. Quem é o responsável</h2>
<p>O controlador dos dados é {html.escape(d['resp'])}{(' (' + html.escape(d['doc']) + ')') if d['doc'] else ''}.
Contato para assuntos de privacidade (encarregado): {c}.</p>

<h2>2. Quais dados tratamos</h2>
<ul>
<li><b>Vídeos, fotos, músicas e textos</b> que você envia ou importa por link, e o que o editor gera a partir deles
(transcrição da fala, cortes, legendas, vídeos exportados).</li>
<li><b>Autorizações das redes sociais</b> que você conecta: os códigos de acesso (tokens) entregues pela própria rede,
o nome e a identificação da conta, do canal ou da página escolhida. <b>Nunca</b> recebemos nem guardamos a senha das
suas redes.</li>
<li><b>Configurações</b> do editor: marca, modelos, agenda de postagem, destinos próprios e as chaves de serviços que
você mesmo cadastrar.</li>
<li><b>Dados técnicos mínimos</b>: endereço IP nas tentativas de login (para bloquear quem erra a senha muitas vezes)
e um cookie de sessão que mantém você conectado.</li>
</ul>
<p>Não usamos cookies de publicidade nem ferramentas de rastreamento, e não vendemos dados.</p>

<h2>3. Para que usamos</h2>
<ul>
<li>Editar, transcrever, cortar e exportar os seus vídeos (execução do serviço que você pediu).</li>
<li>Publicar nas suas redes e destinos <b>somente</b> os vídeos que você aprovar, na data escolhida.</li>
<li>Manter o serviço seguro e funcionando (legítimo interesse e cumprimento de obrigações legais).</li>
</ul>

<h2>4. Dados das redes sociais (YouTube, Facebook, Instagram e TikTok)</h2>
<p>O {a} pede às redes apenas as permissões necessárias para publicar por você:</p>
<ul>
<li><b>YouTube (Google):</b> enviar vídeos ao seu canal e ler o nome do canal. O {a} usa os Serviços de API do
YouTube; ao conectar, você também concorda com os
<a href="https://www.youtube.com/t/terms" rel="noopener">Termos de Serviço do YouTube</a> e com a
<a href="https://policies.google.com/privacy" rel="noopener">Política de Privacidade do Google</a>.</li>
<li><b>Facebook e Instagram (Meta):</b> listar as páginas que você administra e a conta do Instagram ligada a elas,
e publicar vídeos nelas.</li>
<li><b>TikTok:</b> ler as informações básicas do perfil e publicar vídeos.</li>
</ul>
<p>O uso e a transferência de informações recebidas das APIs do Google seguem a
<a href="https://developers.google.com/terms/api-services-user-data-policy" rel="noopener">Política de Dados do
Usuário dos Serviços de API do Google</a>, incluindo os requisitos de Uso Limitado. Esses dados servem só para as
publicações que você pede: não são usados para publicidade, não são vendidos e não são lidos por pessoas, a não ser
com a sua permissão, por segurança ou por exigência da lei.</p>

<h2>5. Com quem compartilhamos</h2>
<ul>
<li>Com a <b>rede ou destino</b> que você escolher ao publicar (o vídeo, o título e a legenda).</li>
<li>Com <b>provedores de IA</b>, apenas se você ligar essas funções (por exemplo: transcrição pela API do Groq ou da
OpenAI; análise do texto pela Anthropic/Claude ou OpenAI). Vai só o necessário: o áudio para transcrever ou o texto
da transcrição. Sem chave cadastrada, tudo é feito no próprio servidor ou computador.</li>
<li>Com os <b>bancos de mídia grátis</b> (Pexels e Pixabay), apenas as palavras que você digitar na busca.</li>
<li>Com o <b>provedor do servidor</b> onde a versão online fica hospedada, que guarda os arquivos em nosso nome.</li>
<li>Com autoridades, quando a lei obrigar.</li>
</ul>

<h2>6. Onde e por quanto tempo guardamos</h2>
<p>Na versão online, os dados ficam no nosso servidor; no programa para computador, ficam só no seu computador
(pasta <b>dados</b>) e não são enviados a nós, a não ser que você use <b>Enviar para o online</b>. Guardamos os
projetos enquanto você os mantiver: você pode excluir um projeto quando quiser. As autorizações das
redes ficam guardadas até você desconectar a rede ou cancelar o acesso. Ao encerrar a conta, apagamos os dados em até
30 dias, salvo o que a lei mandar guardar.</p>

<h2>7. Segurança</h2>
<p>Usamos conexão criptografada (https), senha de acesso com bloqueio contra tentativas repetidas, e as chaves e
autorizações ficam somente no servidor: nunca são enviadas ao navegador. Nenhum sistema é 100% invulnerável; se
houver um incidente que possa causar risco a você, avisaremos.</p>

<h2>8. Seus direitos</h2>
<p>Pela LGPD, você pode a qualquer momento: confirmar se tratamos seus dados, acessá-los, corrigi-los, pedir a
portabilidade (o arquivo <b>.vox</b> já leva o projeto completo), pedir a exclusão, saber com quem compartilhamos e
revogar o consentimento. Basta escrever para {c}. Respondemos em até 15 dias. Você também pode reclamar à
Autoridade Nacional de Proteção de Dados (ANPD).</p>

<h2>9. Como cancelar o acesso das redes</h2>
<p>No {a}: <b>Redes sociais → Desconectar</b>. Direto nas redes:
<a href="https://myaccount.google.com/permissions" rel="noopener">Google (permissões da conta)</a>,
<a href="https://www.facebook.com/settings?tab=business_tools" rel="noopener">Facebook (integrações comerciais)</a> e,
no TikTok, Configurações e privacidade → Segurança → Apps e serviços.
Veja também <a href="{d['site']}/exclusao-de-dados">Exclusão de dados</a>.</p>

<h2>10. Crianças</h2>
<p>O {a} não é destinado a menores de 18 anos sem a autorização e o acompanhamento dos pais ou responsáveis.</p>

<h2>11. Mudanças</h2>
<p>Esta política pode ser atualizada; a data no topo mostra a versão em vigor. Mudanças importantes serão
avisadas no próprio editor.</p>
"""


def _exclusao(d: dict) -> str:
    a, c = d["app"], _contato(d)
    pedido = (f'<a href="mailto:{html.escape(d["email"])}?subject={quote("Exclusão de dados")}">'
              f'{html.escape(d["email"])}</a>') if d["email"] else c
    return f"""
<p class="lead">Você pode apagar os seus dados do {a} a qualquer momento. Escolha o caminho que preferir.</p>

<h2>1. Desconectar uma rede social</h2>
<ol>
<li>Entre no {a}.</li>
<li>Abra <b>Redes sociais</b> no menu.</li>
<li>Clique em <b>Desconectar</b> na rede desejada. A autorização daquela rede é apagada do servidor na hora.</li>
</ol>
<p>Você também pode cancelar direto na rede:
<a href="https://myaccount.google.com/permissions" rel="noopener">Google/YouTube</a>,
<a href="https://www.facebook.com/settings?tab=business_tools" rel="noopener">Facebook e Instagram</a> (remova o
app {a}) ou, no TikTok, Configurações e privacidade → Segurança → Apps e serviços.</p>

<h2>2. Apagar vídeos e projetos</h2>
<p>Em <b>Projetos</b>, abra o menu ⋯ do projeto e escolha <b>Excluir projeto</b>. O vídeo original, a transcrição,
a montagem, os cortes e os vídeos exportados daquele projeto são apagados do servidor.</p>

<h2>3. Pedir a exclusão de todos os seus dados</h2>
<p>Envie um e-mail para {pedido} com o assunto <b>"Exclusão de dados"</b>, informando o endereço do editor que você
usa e, se for o caso, o nome da conta ou página conectada. Confirmamos o recebimento e apagamos tudo — projetos,
vídeos, configurações e autorizações das redes — em até 15 dias, enviando a confirmação ao final. Só guardamos o que
a lei obrigar, pelo prazo que ela mandar.</p>

<p class="small">Mais detalhes na <a href="{d['site']}/privacidade">Política de privacidade</a>.</p>
"""


_CORPO = {"termos": _termos, "privacidade": _privacidade, "exclusao-de-dados": _exclusao}


def pagina(slug: str, base: str) -> str:
    d = _dados(base)
    d["app"] = html.escape(d["app"])
    titulo = PAGINAS[slug]
    corpo = _CORPO[slug](d)
    links = " · ".join(f'<a href="{d["site"]}/{s}"{" aria-current=page" if s == slug else ""}>{t}</a>'
                       for s, t in PAGINAS.items())
    resp = html.escape(d["resp"]) + (f" · {html.escape(d['doc'])}" if d["doc"] else "") \
        + (f" · {html.escape(d['cidade'])}" if d["cidade"] else "")
    return f"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{titulo} — {d['app']}</title>
<meta name="description" content="{titulo} do {d['app']}, editor de vídeo com cortes inteligentes.">
<link rel="icon" href="/icone-192.png">
<style>
:root{{--ac:{d['cor']};--bg:#ffffff;--tx:#1d1f24;--mu:#5d6370;--ln:#e6e8ec;--card:#f7f8fa}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111215;--tx:#e9eaee;--mu:#a2a7b2;--ln:#262931;--card:#181a1f}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);font:16px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
header{{border-bottom:1px solid var(--ln)}}
.wrap{{max-width:760px;margin:0 auto;padding:0 16px}}
.top{{display:flex;align-items:center;gap:10px;padding:16px 0}}
.top b{{font-size:17px}} .dot{{width:28px;height:28px;border-radius:8px;background:var(--ac)}}
nav{{font-size:14px;padding-bottom:12px;color:var(--mu)}}
nav a{{color:var(--mu);text-decoration:none}} nav a[aria-current]{{color:var(--tx);font-weight:600}}
h1{{font-size:clamp(26px,5vw,34px);line-height:1.2;margin:32px 0 4px}}
.vig{{color:var(--mu);font-size:14px;margin:0 0 24px}}
.lead{{font-size:17px;background:var(--card);border-left:3px solid var(--ac);padding:14px 16px;border-radius:0 8px 8px 0}}
h2{{font-size:19px;margin:32px 0 8px}}
a{{color:var(--ac)}} li{{margin:4px 0}} .small{{font-size:14px;color:var(--mu)}}
footer{{border-top:1px solid var(--ln);margin-top:48px;padding:20px 0 32px;font-size:14px;color:var(--mu)}}
</style></head>
<body>
<header><div class="wrap"><div class="top"><span class="dot"></span><b>{d['app']}</b></div><nav>{links}</nav></div></header>
<main class="wrap">
<h1>{titulo}</h1>
<p class="vig">Em vigor desde {VIGENCIA}</p>
{corpo}
</main>
<footer><div class="wrap">{d['app']} — {resp}<br>{links}</div></footer>
</body></html>"""
