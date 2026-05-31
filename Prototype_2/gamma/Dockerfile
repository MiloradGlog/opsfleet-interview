FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first (layer cache).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source. secrets/ and .env are excluded via .dockerignore and mounted/passed
# at runtime instead, so no credentials ever enter the image.
COPY retail_agent ./retail_agent
COPY trios.json ./
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
