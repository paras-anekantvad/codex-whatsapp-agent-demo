FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY codex-whatsapp-agent-demo/pyproject.toml /app/pyproject.toml
COPY codex-whatsapp-agent-demo/README.md /app/README.md
COPY codex-whatsapp-agent-demo/src /app/src
RUN uv sync --no-dev

COPY codex-whatsapp-agent-demo/sidecar/package.json /app/sidecar/package.json
COPY codex-whatsapp-agent-demo/sidecar/src /app/sidecar/src
RUN cd /app/sidecar && npm install --omit=dev

COPY codex-whatsapp-agent-demo/start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 8000
EXPOSE 3001

CMD ["/app/start.sh"]
