FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source and the root-level modules it imports
# (config package + interfaces.py used by service/routers/goal.py).
COPY service/ ./service/
COPY config/ ./config/
COPY interfaces.py ./interfaces.py

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/api/health || exit 1
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
