# syntax=docker/dockerfile:1
ARG OLLAMA_VERSION=0.40.16
FROM ollama/ollama:${OLLAMA_VERSION}

USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 mailresponder \
    && useradd --uid 10001 --gid 10001 --home-dir /data --no-create-home --shell /usr/sbin/nologin mailresponder \
    && install -d -m 0700 -o mailresponder -g mailresponder /data \
    && python3 -c "import sys, sqlite3; assert sys.version_info >= (3, 11); sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE probe USING fts5(content)')"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OLLAMA_HOST=127.0.0.1:11434 \
    OLLAMA_NO_CLOUD=1 \
    OLLAMA_NUM_PARALLEL=1 \
    OLLAMA_MAX_LOADED_MODELS=1 \
    OLLAMA_CONTEXT_LENGTH=4096 \
    AMR_PORT=8765 \
    AMR_DOWNLOAD_MODEL=1

WORKDIR /app
COPY run.py ./run.py
COPY mailresponder/ ./mailresponder/
COPY static/ ./static/

USER mailresponder
VOLUME ["/data"]
EXPOSE 8765
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=10s --start-period=30m --retries=3 \
    CMD ["python3", "-m", "mailresponder.container", "healthcheck"]
ENTRYPOINT ["python3", "-m", "mailresponder.container"]
CMD ["serve"]
