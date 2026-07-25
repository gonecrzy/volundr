FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VOLUNDR_CAD_WORKSPACE_DIR=/work/jobs

RUN apt-get update \
    && apt-get install -y --no-install-recommends openscad \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app

RUN pip install --no-cache-dir .

CMD ["python", "-m", "app.workers.cad_worker"]
