FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHON_EXECUTABLE=/opt/venv/bin/python \
    HF_HOME=/cache/huggingface \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --timeout 120 --retries 10 \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        torch

RUN /opt/venv/bin/pip install --no-cache-dir --timeout 120 --retries 10 \
    sentence-transformers "pymongo>=4.16.0" "python-dotenv>=1.2.2"

WORKDIR /app

COPY gateway/package*.json /app/gateway/
RUN cd /app/gateway && npm ci --omit=dev

COPY gateway /app/gateway
COPY src /app/src
COPY scripts /app/scripts
COPY data/fixtures /app/data/fixtures
COPY data/cinder_and_salt /app/data/cinder_and_salt
COPY data/harbor_view /app/data/harbor_view
COPY data/iron_and_oak /app/data/iron_and_oak
COPY data/kettle_and_loom /app/data/kettle_and_loom
COPY data/northstar_auto /app/data/northstar_auto

RUN mkdir -p /tmp/capstone_demo_uploads /app/logs /cache/huggingface

WORKDIR /app/gateway
EXPOSE 4000

CMD ["node", "src/server.js"]
