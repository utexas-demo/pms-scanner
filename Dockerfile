FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scanner/ ./scanner/

# Default watch directory — override at runtime via WATCH_DIR env var
ENV WATCH_DIR=/data/incoming

VOLUME ["/data/incoming"]

CMD ["python", "-m", "scanner"]
