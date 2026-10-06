# VOX Editor — edição de vídeo com cortes inteligentes e montagem manual (versão 1.6)

## Novidades da versão 1.6 — a cara nova dentro do editor e a nota de cada corte

- **Editor com a cara nova** (abas Edição, Cortes e Montagem): o mesmo menu lateral da tela principal, em ícones, para
  ir a qualquer tela sem voltar; barra do topo com o caminho (Projetos › nome do projeto), as abas com ícones, busca
  rápida (Ctrl+K) e Atividade. Painéis, cartões e títulos no mesmo visual da tela inicial. No celular, a barra fica compacta.
- **Nota de cada corte, com os motivos** (edição automática 2.0, parte 2): cada corte e resumo ganha uma nota de 0 a 100
  e os motivos — "gancho forte", "pergunta que prende", "ideia completa", "frase marcante", "ritmo bom", "duração certa" —
  e também os alertas: "começa no meio de uma ideia", "termina no meio da frase", "muitas pausas", "curto demais".
  A nota é calculada no próprio programa, sem gastar API; com o Claude ligado, entra também a nota da IA.
  Ao lado da prévia, a nota por critério (gancho, ideia completa, emoção, ritmo e duração) e a explicação de cada motivo.
  Botão **Melhor nota** para ver os melhores cortes primeiro.
- **Título, legenda e hashtags para cada rede**: YouTube Shorts (título + descrição), Instagram Reels, TikTok e
  Facebook Reels, cada um do seu jeito e com as hashtags do assunto do vídeo (#shorts, #reels, #fyp entram sozinhas;
  o Instagram respeita o limite de 5). Dá para editar, **Copiar texto pronto**, **Reescrever com IA** (centavos) e
  voltar ao automático. **Hashtags fixas da marca** vão no fim de todos os textos.
- **Publicar**: ao publicar um corte exportado, cada rede já sai com o próprio texto (abas por rede no diálogo).
  Quem preferir marca "Mesmo texto em todas".


## Novidades da versão 1.5 — edição automática 2.0

- **Perfil da edição** (aba Edição): Pregação e culto, Reels dinâmico, Aula e estudo, Podcast e entrevista e Só o
  essencial. Um clique ajusta silêncios, ritmo, respirações e vícios; cada perfil mostra antes a duração final do seu
  vídeo. Pode virar padrão dos projetos novos.
- **Capítulos do YouTube**: divisão automática por assunto, com títulos tirados da fala (ou pela IA, se ligada).
  Tempos do vídeo editado, editáveis, nas regras do YouTube, com "Copiar para a descrição" e inserção direta ao
  publicar o vídeo editado.
- **Menu lateral** rola quando a janela é baixa.


## Novidades da versão 1.4 — cara nova

- **Barra do topo** em todas as telas do menu: **busca rápida (Ctrl+K)** para achar projetos, telas e ações;
  botão **Novo** (enviar vídeo, link, montagem 9:16 / 16:9 / 1:1, abrir .vox, trazer do online); e **Atividade**,
  com o andamento de análises, exportações, downloads, remoção de fundo e as próximas postagens.
- **Menu lateral** em grupos (Criar, Publicar, Estilo, Sistema), que recolhe só nos ícones (Ctrl+B).
- **Tela inicial** redesenhada: console com as abas Enviar vídeo, Importar por link e Montar do zero; painel de
  números; "Em andamento"; Próximas publicações e Atalhos ao lado dos projetos.
- No celular, barra do topo compacta com busca e botão +.


## Novidades da versão 1.3 — páginas públicas para aprovar os apps das redes

- **/termos, /privacidade e /exclusao-de-dados** abrem sem senha (o resto do editor continua protegido). Textos em
  português, de acordo com a LGPD e com as exigências do YouTube (Uso Limitado das APIs do Google), da Meta e do TikTok.
  Também respondem em /termos-de-uso, /politica-de-privacidade, /terms, /privacy e /data-deletion.
- **Configurações → Páginas públicas:** responsável, CPF/CNPJ (opcional), e-mail de contato e cidade. Vão junto no
  "Copiar configurações para o online".
- A tela de login do online mostra os links de Termos e Privacidade, e o `sudo vox-apps` mostra os três links para
  colar nos formulários dos apps.


## Novidades da versão 1.2 — o super pacote da Montagem

### Transições entre os pedaços
- Em cada corte da linha do tempo (dois pedaços colados) aparece um botãozinho **+**. Toque nele (ou em Ajustes →
  **Transição de entrada**) e escolha: Dissolver, Pelo preto, Pelo branco, Deslizar (esquerda, direita, cima, baixo),
  Empurrar, Zoom entrando, Zoom saindo e Girar. A duração vai de 0,2 a 3 segundos.
- **Usar em todos os cortes desta trilha:** aplica a mesma transição em todos os cortes de uma vez (ótimo para a
  trilha principal que veio da edição automática).
- A transição não muda o tempo do vídeo nem a sincronia do som: o pedaço anterior continua por baixo enquanto o novo entra.

### Animação (quadros-chave)
- Ajustes → **Animação**. Animações prontas: Aparecer, Crescer, Pop, Subir, Da esquerda, Da direita (entrar);
  Zoom lento, Afastar lento, Passear (durante); Sumir, Diminuir, Descer, Sair à direita (sair).
- Quadros-chave livres: **◆ Marcar aqui** (ou tecla **K**), leve o cursor para outro ponto e mude posição, tamanho,
  giro ou opacidade (no painel ou arrastando na prévia). O pedaço anda de um jeito para o outro, com movimento suave,
  constante, chegando devagar ou saindo devagar. Os losangos amarelos na linha do tempo levam o cursor até o quadro-chave.
- Funciona em vídeos, fotos, cores e textos. Dividir e aparar mantêm o movimento.

### Filtros e cor
- Ajustes → **Filtros e cor**: 10 filtros prontos (Vivo, Cinema, Quente, Frio, Dourado, Vintage, Preto e branco,
  Drama, Suave) e ajuste fino de brilho, contraste, saturação, temperatura, preto e branco, sépia, desfoque e vinheta.

### Fundo verde (chroma key)
- Ajustes → **Fundo verde**: tira o pano verde (ou azul) de quem grava na frente dele. Controle de quanto da cor tirar
  e da borda suave.

### Remover fundo com IA (sem pano verde)
- Ajustes → **Remover fundo com IA** em qualquer vídeo ou foto. A IA recorta a pessoa e tira o resto. Roda no próprio
  PC/servidor, sem pagar API. Só o trecho usado na linha do tempo é processado; quando termina, o pedaço é trocado
  sozinho pela versão sem fundo. Coloque um vídeo, foto ou cor numa trilha abaixo para aparecer atrás.
- Na primeira vez o modelo de IA é baixado sozinho. Qualidade em **Inteligência artificial**: Caprichada (168 MB,
  recomendado, contorno muito melhor em pessoas) ou Rápida (4,5 MB).

### Vídeos e fotos grátis (Pexels e Pixabay)
- Montagem → aba **Grátis**: busque vídeos e fotos livres (inclusive para vídeo monetizado), veja a prévia passando o
  mouse e toque para colocar no cursor. O crédito (opcional) fica pronto em Ajustes.
- Cada banco pede uma chave grátis, colocada uma vez em **Inteligência artificial** (no menu). As chaves vão junto no
  "Copiar configurações para o online".

### O que se vê é o que sai
- A prévia faz exatamente as mesmas contas da exportação (transições, animação, filtros, vinheta, fundo verde e
  transparência), conferido quadro a quadro.


## Novidades da versão 1.1 — publicar sem configurar app e destinos próprios

### Apps oficiais do VOX: o usuário só clica em Conectar
- O dono do sistema cadastra **uma vez** os apps do VOX em cada rede (YouTube, Facebook/Instagram, TikTok) com o
  comando **`sudo vox-apps`** na VPS. O comando pergunta os dados no próprio terminal e grava sozinho
  (`sudo vox-apps --ver` mostra o que está cadastrado).
- Depois disso, em Redes sociais, cada rede cadastrada mostra **"Pronto: clique em Conectar"**: a pessoa entra com a
  própria conta e o acesso fica **salvo no servidor e renovado sozinho** (não precisa logar de novo).
- Quem quiser continua podendo usar o próprio app (botão **App próprio**); ele tem prioridade sobre o do VOX.
- Contas conectadas lembram por qual app entraram, para renovar o acesso sempre pelo mesmo app.

### Destinos próprios (fora das redes sociais)
Em Redes sociais → **Destinos próprios**. Cada destino aparece no botão **Publicar**, junto das redes, e pode ser
agendado na mesma fila. Botão **Testar** confere a ligação antes de usar.
- **Transmissão ao vivo (RTMP):** o vídeo é transmitido ao vivo para a sua web TV ou servidor de streaming
  (MediaCP, Wowza, Owncast, YouTube Live…).
- **Enviar arquivo (FTP/FTPS):** o MP4 vai para uma pasta do seu site/servidor (ex.: a pasta da playlist da web TV).
- **Avisar meu site (webhook):** o VOX manda um POST em JSON com título, legenda e um link para baixar o vídeo
  (válido por 7 dias, só para aquele arquivo).
- **Copiar para uma pasta:** copia o vídeo para uma pasta do computador/servidor.
- Senhas e chaves dos destinos ficam só no servidor; o navegador nunca recebe.


## Novidades da versão 1.0 — Montagem: o editor manual com camadas

### Onde fica
- **Em qualquer projeto já analisado:** no topo do editor, aba **Montagem** (ao lado de Edição e Cortes & Resumos).
  Na primeira vez, o vídeo entra na trilha principal **já com a edição automática aplicada** (cada trecho mantido vira
  um pedaço). Em Ajustes (sem nada selecionado) há o botão **Recomeçar da edição automática**.
- **Projeto em branco:** na tela inicial, em **Montar do zero**, escolha Vertical 9:16, Horizontal 16:9 ou Quadrado 1:1.
  Não passa por análise: é só montar.

### O que dá para fazer
- **Camadas sem limite:** trilhas de vídeo/imagem, texto e áudio. A de cima aparece por cima. Cada trilha pode ser
  escondida, silenciada ou travada. Botão **+ Trilha** cria mais; clique direito no nome de uma trilha vazia remove.
- **Biblioteca:** envie vídeos, fotos (JPG, PNG, WEBP) e músicas (MP3, M4A, WAV…). Toque numa mídia para colocar no
  cursor ou arraste para a trilha que quiser. Também dá para soltar arquivos direto em cima da Montagem.
  Vídeos que o navegador não toca (iPhone/HEVC, .mkv, 4K) ganham uma cópia leve só para a prévia; a exportação usa o
  original.
- **Textos prontos:** Título, Legenda, Nome na tela, Versículo, Chamada e Texto simples, com 5 fontes, cor, contorno,
  fundo atrás do texto e maiúsculas.
- **Fundos:** cores sólidas (16 prontas ou qualquer cor), usadas como fundo ou como faixa (ajuste largura e altura).
- **Ferramentas:** dividir no cursor (**S**), duplicar (**Ctrl+D**), apagar (**Delete**), desfazer/refazer sem limite
  (**Ctrl+Z / Ctrl+Y**), aparar puxando as pontas, arrastar para outra trilha, zoom (**Ctrl + roda do mouse**).
- **Ímã:** encaixa nos cortes e no cursor, e mantém a **trilha principal sem buracos** (apagou um pedaço, o resto
  encosta). Desligue o ímã para posição livre.
- **Ajustes de cada pedaço:** posição, tamanho, giro, opacidade, entrada e saída suave, encaixe (inteiro ou preenchendo
  a tela), volume e velocidade (0,25× a 4×). Na prévia, arraste para mover e puxe a bolinha do canto para aumentar;
  ao passar pelo centro ele "gruda" no meio.
- **Prévia na hora**, desenhada no próprio aparelho, e **exportação** em MP4 (com a placa de vídeo, quando houver),
  com as mesmas contas da prévia. O vídeo exportado aparece em Ajustes → Exportados da montagem e na página Exportados,
  pronto para **Publicar**.
- **Celular:** a mesma Montagem, com a prévia em cima, a linha do tempo embaixo e Mídias, Texto, Fundos e Ajustes em
  gavetas. No celular, o primeiro toque num pedaço seleciona; com ele selecionado, arraste para mover ou aparar.
- Tudo é salvo sozinho. A montagem vai junto no pacote **.vox** e no **Enviar para o online**.

### Próximas fases (já planejadas)
Transições, efeitos, keyframes e bancos de vídeos/fotos/músicas livres (Pexels e Pixabay); depois remoção de fundo
com IA, edição automática 2.0, app Android e transmissão ao vivo com caracteres na tela.


## Novidades da versão 0.9 — celular, PC ↔ online, destaques e áudio de estúdio

### Começar no PC e continuar no celular (ou ao contrário)
- **Enviar para o online:** no menu ⋯ do projeto (ou em Exportar, dentro do editor) clique em **Enviar para o online**.
  Vai o projeto completo: vídeo, transcrição, edição, cortes e vídeos exportados. No online ele abre do jeito que estava,
  **sem nova análise e sem gastar API**. Antes, coloque o endereço e a senha do online em **Configurações → Versão online**.
- **Trazer do online:** em Projetos, botão **Trazer do online** (só no programa do PC).
- **Importar projeto (.vox):** em qualquer instalação (PC ou online), em Projetos. O arquivo .vox é baixado pelo menu ⋯
  do projeto → **Baixar projeto completo (.vox)**. Serve também como cópia de segurança de um projeto.
- **Copiar configurações para o online:** em Configurações → Versão online. Leva as chaves de IA, a transcrição, a marca,
  a logo, os modelos, as músicas e a agenda. As **contas das redes não vão**: conecte-as no online, que fica ligado
  24 horas e faz a autopostagem (assim o mesmo vídeo nunca sai duas vezes).
- Os dados do PC e do online continuam separados: limpar espaço num não apaga nada no outro.

### Senha no programa do PC
- Em **Configurações → Senha do programa**. Com a senha ligada, o editor pede a senha ao abrir. Para tirar ou trocar,
  é preciso a senha atual. Só um código embaralhado (hash) fica salvo, nunca a senha.

### Editor no celular
- O editor online agora se adapta ao celular: menu embaixo, menu completo numa gaveta (botão **Mais**), vídeo sempre à
  vista enquanto rola a transcrição, botões e campos maiores para o dedo e janelas que ocupam a tela.
- Dá para **instalar como app**: no Chrome do celular, abra o editor online → menu ⋮ → **Adicionar à tela inicial**
  (no iPhone: Compartilhar → Adicionar à Tela de Início).

### Destaques automáticos (nos cortes)
- **Palavras-chave coloridas na legenda** (cor escolhida por você). Sem IA usa uma lista de palavras de fé e números;
  com o Claude ligado, a IA escolhe as palavras de cada corte. A escolha fica guardada: cada trecho só é perguntado à IA
  uma vez.
- **Emojis nos momentos marcantes:** aparecem acima da legenda, com animação suave, um de cada vez. São 83 emojis
  escolhidos para pregações e falas (licença livre Twemoji).
- **Zoom nos momentos fortes:** quando a voz enfatiza uma frase, a câmera aproxima devagar e volta.
- Tudo liga e desliga no estúdio de cortes (seção **Destaques**) e pode virar padrão em **Modelos**.

### Áudio de estúdio
- **Voz de estúdio:** tira o ronco grave, o chiado constante (ar-condicionado, ventilador, eco da igreja), dá presença à
  voz e segura os picos.
- **Música de fundo:** envie suas músicas (MP3, M4A, WAV…) no estúdio. A música **abaixa sozinha quando a pessoa fala** e
  sobe nas pausas, entra e sai com suavidade e repete se o vídeo for maior. O volume final continua no padrão das redes.
  Use só músicas que você tem direito de usar.

## Novidades da versão 0.8.1 — versão online na VPS e atualização pelo GitHub

- **Como as versões andam:** o código anda sempre num sentido só, **PC → GitHub → VPS**. Toda melhoria é feita
  e testada no PC; a VPS só recebe versões prontas. Os **dados não se misturam**: o PC e o site têm cada um os seus
  projetos, contas e configurações.
- **PUBLICAR.bat (no PC):** envia o código desta pasta para o seu repositório privado no GitHub. A pasta `dados`
  (projetos, vídeos, contas, chaves) **nunca** é enviada. Na primeira vez ele pede o endereço do repositório e abre
  uma janela para entrar na conta do GitHub.
- **`sudo vox-atualizar` (na VPS):** baixa a versão nova do GitHub, guarda uma cópia das configurações e contas,
  reconstrói o container e confere se ligou. Se a versão nova não ligar, **volta sozinho** para a anterior.
  `sudo vox-atualizar --voltar` volta para a versão de antes da última atualização.
- **Junto de outro sistema com Caddy em container** (ex.: painel Vox): o instalador acrescenta só o domínio do
  editor no Caddy que já existe. Antes de valer, o próprio Caddy confere o arquivo numa cópia; se der erro, nada é
  trocado. O recarregamento é sem queda, e fica uma cópia do arquivo original ao lado dele.
- **Os dados ficam fora da pasta do código** (`/srv/voxeditor/dados`), então atualizar nunca mexe neles.
- **Senha mais protegida na internet:** depois de 5 senhas erradas em 15 minutos, aquele endereço precisa esperar.
- **Swap de segurança:** se a VPS não tiver memória de reserva, o instalador cria 4 GB.

### Primeira instalação na VPS (uma vez só)
1. No PC, crie um repositório **privado e vazio** em https://github.com/new e dê dois cliques no **PUBLICAR.bat**.
2. Na VPS, cole o conteúdo do arquivo **COLAR-NA-VPS.txt** no terminal. Ele pede o endereço do repositório, mostra
   uma chave para você colar no GitHub (só leitura), baixa o código e abre o instalador.

### Atualizações depois
1. No PC: troque os arquivos pela versão nova, teste e dê dois cliques no **PUBLICAR.bat**.
2. Na VPS: `sudo vox-atualizar`

## Novidades da versão 0.8 — programa de verdade, link do YouTube e versão online

- **Janela própria:** o programa abre na janela dele, com nome e ícone (a logo enviada em Marca vira o ícone),
  sem barra do navegador e sem a janela preta. Usa o motor do Edge (WebView2), que já vem no Windows 10/11.
  - Os botões "Baixar" abrem a janela "Salvar como" do Windows.
  - Clicar na faixa da tela inicial abre a janela do Windows para escolher o vídeo, e o programa usa o arquivo
    direto, sem copiar duas vezes.
  - Ao fechar com publicações agendadas ou trabalhos em andamento, ele pergunta se você quer minimizar e continuar.
  - O login das redes sociais abre no seu navegador (o Google não deixa fazer login dentro de outros programas);
    ao terminar, a conta aparece sozinha no programa.
  - Se a janela própria não abrir, use o **INICIAR-NAVEGADOR.bat** (modo antigo).
- **Importar pelo link:** cole o link do YouTube (ou de outros sites de vídeo) na tela inicial e clique em Importar.
  Quem baixa é o próprio programa: é grátis e não usa API. Vem em até 1080p. Use em vídeos seus ou que você tem
  permissão para editar. Se o YouTube mudar algo e o download falhar, o programa atualiza o baixador sozinho.
- **Inteligência artificial no menu:** escolha Claude ou GPT, cole a chave, teste a conexão e veja o custo
  estimado. A transcrição (no computador ou por API) também fica ali.
- **Versão online em container (Docker):** para rodar na mesma VPS de outro sistema sem atrapalhar.
  Veja "Instalar na VPS em container" abaixo.

## Instalar na VPS em container (recomendado quando a VPS já tem outro sistema)

1. Envie a pasta do programa para a VPS (por exemplo, para `/opt/editor-ia`).
2. Rode:  `sudo bash /opt/editor-ia/scripts/instalar-online.sh`
3. Responda às perguntas no próprio terminal: domínio, e-mail, senha, quantos núcleos e quanta memória o editor
   pode usar. O instalador faz o resto:
   - instala o Docker, se faltar;
   - liga o editor num container **com limite de processador e memória** (o outro sistema fica com o resto)
     e com prioridade baixa;
   - coloca o **https**: se as portas 80/443 estiverem livres, usa um container próprio (Caddy); se a VPS já tiver
     Nginx ou Apache, só acrescenta o domínio neles, sem mexer no resto.
4. Para atualizar depois:  `sudo bash scripts/instalar-online.sh --atualizar`  (projetos e configurações ficam).

Dica: na versão online, a transcrição pela API do Groq (em Inteligência artificial → Transcrição) tira quase todo o
peso do servidor. Na versão online, o YouTube às vezes pede "verificação de robô" para servidores; se acontecer,
importe pelo programa do PC.

## Novidades da versão 0.7 — menu completo e autopostagem

- **Menu novo:** Publicações, Modelos e Redes sociais saíram de dentro das janelas e viraram páginas do menu.
- **Modelos:** escolha a moldura, o estilo da legenda, o tamanho, a altura e o layout padrão. Todo projeto novo já
  nasce assim. O botão "Aplicar também aos projetos existentes" atualiza os antigos.
- **Redes sociais:** conecte YouTube, Instagram, Facebook e TikTok pelo login oficial de cada rede (o programa nunca
  guarda senha). Ali também ficam os selos com o seu @.
- **Autopostagem:** em Exportados, clique em "Publicar nas redes", escolha as redes, revise a legenda e clique em
  "Aprovar e colocar na fila". O vídeo é postado sozinho no próximo horário livre da agenda, agora ou numa data
  escolhida. Na página Publicações você vê a fila, o que já foi publicado (com link) e o que deu erro (com
  "Tentar de novo").
- **Horários da agenda:** defina os dias e horas de postagem (ex.: seg/qua/sex às 19:00). Cada rede usa um
  horário livre por vez.
- **Erros de fala:** além de silêncios e vícios, o editor agora corta palavras quebradas ("o pro- o problema") e
  frases repetidas ("eu vou eu vou"), sem precisar de IA.
- **Limpeza da fala com IA (opcional, precisa da chave do Claude):** a IA lê a transcrição e marca recomeços,
  correções, gaguejos, repetições e comentários fora do assunto. Os cortes aparecem em verde-água na transcrição
  e você pode desfazer qualquer um clicando na palavra.

### Ressalvas das redes (regras delas, não do programa)
- **O programa precisa estar aberto** para postar no horário. Para postar 24 horas sem o computador ligado, use a
  versão online na VPS.
- **YouTube e TikTok:** enquanto o seu app não passar pela auditoria/aprovação de cada rede, os vídeos entram como
  **privados**. Depois da aprovação, saem públicos.
- **Instagram:** precisa ser conta Profissional ligada a uma Página do Facebook. Limite de 100 posts por dia.
- **TikTok:** pode exigir endereço com https (domínio próprio na VPS).
- **Status do WhatsApp:** não existe forma oficial de postar automaticamente; continue baixando e postando à mão.
- O passo a passo para criar o app de cada rede está no botão **Configurar app**, na página Redes sociais.

## Novidades da versão 0.6 — tela inicial de estúdio

- **Menu lateral** com Início, Projetos, Exportados, Marca e Configurações.
- **Projetos com miniatura real** e uma mini linha do tempo mostrando o que ficou e o que foi cortado.
  Menu de cada projeto: abrir edição, abrir cortes, ver exportados, **renomear** e **excluir**. Busca e ordenação.
- **Exportados**: biblioteca com todos os vídeos prontos, de todos os projetos, com filtro por projeto e por destino;
  assista ali mesmo ou baixe.
- **Marca**: coloque **o nome, a frase, a logo e a cor do programa** (o sistema fica com a sua cara) e edite o kit de marca dos vídeos.
- **Espaço usado** no disco e botão **Liberar espaço** (apaga só arquivos temporários).
- Solte o vídeo em qualquer lugar da tela inicial para criar um projeto.

## Novidades da versão 0.5 — selos das redes e legenda sob medida

- **Legenda**: tamanho padrão menor e controle fino de **tamanho (50%–150%)** e **altura na tela** (de bem embaixo até o topo).
- **Selos das redes sociais**: TikTok, Instagram, YouTube, Facebook, WhatsApp e Site, cada um com o seu @ e um convite
  ("SIGA NO TIKTOK", "INSCREVA-SE NO YOUTUBE"…). O selo entra deslizando, fica alguns segundos, sai e volta de tempos em tempos.
  Pode mostrar só a rede do destino da exportação ou todas, alternando. Ícone genérico de "seguir" por padrão;
  envie o ícone oficial do kit de marca de cada rede para usá-lo no lugar.
- **Logo pessoal (marca d'água estilo TV)**: posição (4 cantos ou automática), tamanho e transparência.

## Novidades da versão 0.4 — molduras, marca e capa

- **5 molduras** (em Cortes & Resumos › Visual › Moldura), com prévia real do seu vídeo:
  Tela cheia · Tarja no topo · Moldura podcast (título em cima, vídeo no meio, legenda numa faixa embaixo) ·
  Rodapé (faixa embaixo com a legenda por dentro) · Cartão (vídeo em destaque sobre o fundo desfocado).
- **Selo chamativo** em cada corte ("PALAVRA DE HOJE", "ASSISTA ATÉ O FIM"…): a IA sugere um por corte, e você pode editar.
- **Sua marca**: @perfil, logo, cores da tarja, do texto e do fundo — vale para todos os cortes.
- **Barra de progresso** no vídeo (segura a pessoa até o fim).
- **Capa (thumbnail)** de cada corte: melhor quadro com rosto, título GRANDE com palavra em destaque, pronta para baixar.

## Novidades da versão 0.3 — emendas inteligentes e imagem melhor

- **Nenhum corte no meio de palavra**: um detector de voz profissional (Silero VAD, offline) mapeia onde há fala.
  Todo corte é encaixado no vale de silêncio mais próximo, conferido pelo som — não só pelo horário da transcrição.
- **Cortes e resumos começam e terminam em pausas reais**: o trecho é aberto até a palavra terminar.
- **Vícios e repetições só são cortados quando a emenda fica limpa**; na dúvida, a palavra é mantida (nada de fala picotada).
- **Ritmo das pausas** (Natural, Dinâmico, Rápido): mantém um respiro natural, maior depois de ponto final.
- **Emendas suaves**: cruzamento de áudio maior quando junta partes distantes do vídeo.
- **Zoom alternado nas emendas** (opcional): o "pulo" vira um corte de câmera intencional.
- **Resumos com contexto**: montados com blocos de ideia completos, sem frases soltas nem trechos que começam com "e", "mas", "isso"...
- **Imagem**: remove faixas pretas automaticamente, amplia com filtro de alta qualidade, limpa o ruído e devolve a nitidez;
  codificação com mais qualidade e cores corretas no celular.
- **Enquadramento** segue o orador principal e ignora rostos borrados ou de passagem.
- **Título** nunca é cortado no meio da palavra.

Projetos antigos são atualizados sozinhos ao abrir.

## Novidades da versão 0.2

- **Estúdio de Cortes & Resumos**: escolha a rede (Status do WhatsApp, Stories, Reels, Shorts, Facebook, TikTok ou 16:9),
  a duração (30s, 60s, 90s, 2 min ou livre), se quer **cortes** (trechos contínuos) ou **resumos** (os melhores momentos
  do vídeo inteiro juntos, abrindo com a frase mais forte) e quantos. A IA gera tudo com título e texto para a publicação.
- **Divisão automática em partes** para Status e Stories (vídeos acima do limite viram parte 1, parte 2…, cortando nas pausas).
- **Enquadramento inteligente 9:16**: segue o rosto de quem fala, centraliza ou usa o vídeo inteiro com fundo desfocado.
- **Galeria com 9 estilos de legenda** (Palavra em foco, Caixa na palavra, Karaokê, Uma palavra por vez, Impacto, Neon,
  Faixa de fundo, Clássica, Minimalista), com prévia real gerada a partir do seu vídeo, e ajuste de fonte, cor, tamanho e posição.
- **Título escrito no vídeo** (gancho) nos primeiros segundos ou o tempo todo.
- **Exportar todos** de uma vez, numa fila.
- Fontes incluídas: Poppins, Anton, Bebas Neue e Archivo Black (licença livre OFL, em `fontes/`).

**Atualizar da 0.1:** feche o Editor IA, extraia o zip por cima da pasta atual e rode o **ATUALIZAR.bat**.

Sistema profissional de edição automática: transcreve a fala, corta silêncios, suaviza respirações,
remove vícios de linguagem, sugere cortes para Reels/Shorts, gera legendas palavra por palavra
e renderiza com aceleração por GPU. Funciona **no PC (Windows)** e **online (VPS)** com o mesmo código.

## Instalar no Windows

1. Extraia esta pasta onde quiser (ex.: `C:\EditorIA`).
2. Dê dois cliques em **INSTALAR.bat** e aguarde (instala Python, bibliotecas, FFmpeg e o modelo de transcrição).
3. Abra pelo atalho **Editor IA** na área de trabalho. O painel abre sozinho no navegador.

Requisitos: Windows 10/11 64 bits, 8 GB de RAM. Com placa NVIDIA, a transcrição e a renderização ficam muito mais rápidas.

## Instalar na VPS sem container (VPS só para o editor)

```bash
sudo bash scripts/instalar-vps.sh
```

O instalador pergunta a porta, a senha de acesso e o modelo, cria o serviço e libera o firewall.
Na Oracle Cloud, libere a mesma porta na *Security List* da VCN.

## Como usar

1. Arraste o vídeo para o painel. A análise roda sozinha (transcrição + detecções).
2. Ajuste no painel esquerdo: limite de silêncio, margem, respirações (abaixar ou cortar), vícios, legendas e volume.
3. Na transcrição: clique num corte para desfazê-lo; selecione palavras e aperte **Delete** para cortar;
   dê dois cliques numa palavra para corrigir a legenda.
4. A prévia já toca **com os cortes aplicados**, sem precisar renderizar.
5. **Renderizar vídeo** gera o MP4 final. Nos **Cortes IA**, exporte cada trecho em 9:16 com legenda.
6. **Exportar** gera XML (Premiere/DaVinci), EDL, SRT e a transcrição.

## APIs (opcionais — tudo funciona sem elas)

Em **Configurações**:

| Função | Grátis (padrão) | Com API |
|---|---|---|
| Transcrição | faster-whisper no próprio PC | Groq (`whisper-large-v3-turbo`, muito barato) ou OpenAI |
| Cortes inteligentes | análise local da transcrição | Claude (Anthropic) ou qualquer API compatível com OpenAI |

As chaves ficam só em `dados/config.json` no seu computador/servidor e nunca são enviadas ao navegador.

## Estrutura

```
backend/
  app.py              servidor + API (FastAPI)
  core/store.py       projetos e configurações
  core/jobs.py        filas de análise e renderização
  core/pipeline.py    fluxo completo: análise, recálculo, render, exportação
  engine/audio.py     medição do áudio, silêncios e respirações
  engine/transcribe.py transcrição local ou por API, com tempo por palavra
  engine/edits.py     lista de cortes, vícios, mapa de tempo
  engine/smartcuts.py cortes para Reels/Shorts (IA ou heurística)
  engine/subtitles.py legendas SRT e ASS (destaque palavra a palavra)
  engine/render.py    áudio com precisão de amostra + vídeo em uma passada (GPU)
  engine/exports.py   XML Premiere/DaVinci e EDL
frontend/             painel (HTML/CSS/JS, funciona offline)
fontes/               coloque aqui fontes .ttf/.otf para as legendas
dados/                projetos, modelos e configurações (criado automaticamente)
```

## Detalhes técnicos que garantem o resultado profissional

- Cortes alinhados à grade de quadros: áudio e vídeo terminam juntos mesmo com centenas de cortes.
- Cruzamento suave de 12 ms em cada emenda de áudio (sem estalos).
- Respirações detectadas por volume + "planicidade" do espectro, fora das palavras; atenuadas com rampas de 30 ms.
- "é", "tipo", "né" só são cortados quando estão soltos entre pausas (o "é" verbo é mantido).
- Normalização de volume em duas passadas (padrão −14 LUFS).
- Prévia leve automática para arquivos pesados (4K, HEVC, MKV) e envio em fluxo contínuo (arquivos de vários GB).
- Detecta e testa NVENC, Quick Sync e AMF; usa o processador se a GPU não estiver disponível.

## Renomear o app

Edite `"name"` em `dados/config.json` (seção `app`) e reinicie.
