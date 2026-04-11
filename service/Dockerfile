FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source and the root-level modules it imports.
# - config/: settings used by service + engine
# - interfaces.py: dataclasses used by service/routers/goal.py + engine/
# - engine/: Brinson attribution lib imported lazily by
#   service/services/attribution_service.py (from engine.brinson import ...)
COPY service/ ./service/
COPY config/ ./config/
COPY interfaces.py ./interfaces.py
COPY engine/ ./engine/

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/api/health || exit 1
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
