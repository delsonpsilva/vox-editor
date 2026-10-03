# VOX Editor / Editor IA — versão online em container
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 PORT=8765 NO_BROWSER=1 EDITOR_DATA=/dados FORWARDED_ALLOW_IPS=*

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY backend backend
COPY frontend frontend
COPY fontes fontes
COPY assets assets

RUN useradd -m -u 1000 editor && mkdir -p /dados && chown editor:editor /dados
USER editor
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/status', timeout=4)" || exit 1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "backend.app"]
