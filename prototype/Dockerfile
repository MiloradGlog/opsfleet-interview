# Retail Data Analysis chat assistant — prototype image.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application code + seed Golden Trios (runtime state lives in a mounted /app/data).
COPY retail_agent/ ./retail_agent/
COPY data/golden_trios.json ./data/golden_trios.json

# Interactive CLI. Override the user with: docker run ... retail-data-agent --user manager_b
ENTRYPOINT ["python", "-m", "retail_agent.cli"]
CMD ["--user", "manager_a"]
