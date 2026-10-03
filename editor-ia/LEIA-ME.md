# Editor IA — edição de vídeo com cortes inteligentes

Sistema profissional de edição automática: transcreve a fala, corta silêncios, suaviza respirações,
remove vícios de linguagem, sugere cortes para Reels/Shorts, gera legendas palavra por palavra
e renderiza com aceleração por GPU. Funciona **no PC (Windows)** e **online (VPS)** com o mesmo código.

## Instalar no Windows

1. Extraia esta pasta onde quiser (ex.: `C:\EditorIA`).
2. Dê dois cliques em **INSTALAR.bat** e aguarde (instala Python, bibliotecas, FFmpeg e o modelo de transcrição).
3. Abra pelo atalho **Editor IA** na área de trabalho. O painel abre sozinho no navegador.

Requisitos: Windows 10/11 64 bits, 8 GB de RAM. Com placa NVIDIA, a transcrição e a renderização ficam muito mais rápidas.

## Instalar na VPS (versão online)

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
