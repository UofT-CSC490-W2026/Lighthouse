FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/pipeline

COPY pipeline/requirements.txt /app/pipeline/requirements.txt
COPY shared /app/shared
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline/src /app/pipeline/src

CMD ["python", "-m", "src.worker"]
