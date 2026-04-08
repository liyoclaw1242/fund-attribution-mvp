FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy pipeline source into /app/pipeline/ so "from pipeline.x" imports work
COPY . ./pipeline/

HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8080/ || exit 1
CMD ["python", "-m", "pipeline.scheduler"]
