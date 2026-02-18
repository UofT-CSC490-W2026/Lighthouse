FROM python:3.12-slim

# ENV HF_HOME=/models \
#     HUGGINGFACE_HUB_CACHE=/models/hub \
#     TRANSFORMERS_CACHE=/models/transformers \
#     HF_HUB_ENABLE_XET=0 \
#     HF_HUB_ENABLE_HF_TRANSFER=0 \
#     PIP_NO_CACHE_DIR=1

WORKDIR /app/mcp

# System dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       gcc \
       git \
       zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY mcp/requirements.txt /app/mcp/requirements.txt
COPY shared /app/shared

# # Force CPU-only torch to avoid huge CUDA wheels
# RUN pip install --no-cache-dir \
#       --index-url https://download.pytorch.org/whl/cpu \
#       "torch==2.9.1" \
#     && pip install --no-cache-dir -r requirements.txt \
#     && rm -rf /root/.cache/pip /tmp/*

# # Pre-download the BGE-M3 model
# RUN mkdir -p /models/bge-m3 && chmod -R 755 /models
# RUN python - <<'PY'
# from huggingface_hub import snapshot_download
# snapshot_download(
#     repo_id="BAAI/bge-m3",
#     local_dir="/models/bge-m3",
#     resume_download=True,
#     max_workers=1,
# )
# PY

# ENV PYTHONDONTWRITEBYTECODE=1 \
#     PYTHONUNBUFFERED=1 \
#     PIP_NO_CACHE_DIR=1 \
#     HF_HOME=/models \
#     HUGGINGFACE_HUB_CACHE=/models/hub \
#     TRANSFORMERS_CACHE=/models/transformers \
#     HF_HUB_ENABLE_XET=0 \
#     HF_HUB_ENABLE_HF_TRANSFER=0 \
#     TRANSFORMERS_OFFLINE=1 \
#     HF_HUB_OFFLINE=1 \
#     MODEL_DIR=/models/bge-m3

RUN pip install --no-cache-dir -r requirements.txt

COPY mcp/src/ /app/mcp/src/

EXPOSE 8000

ENV WORKERS=1
CMD ["sh", "-c", "gunicorn src.server:app --workers ${WORKERS} --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000"]
