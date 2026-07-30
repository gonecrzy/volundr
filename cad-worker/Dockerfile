FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/xdg-cache \
    VOLUNDR_CAD_WORKSPACE_DIR=/work/jobs

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --system --group --home /home/volundr-cad volundr-cad \
    && mkdir -p /work/jobs /tmp \
    && chown -R volundr-cad:volundr-cad /work /home/volundr-cad

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/volundr_cad ./volundr_cad

RUN pip install --no-cache-dir .

USER volundr-cad

CMD ["python", "-m", "app.workers.cad_worker"]
