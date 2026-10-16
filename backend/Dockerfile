# syntax=docker/dockerfile:1
# C.L.I.P backend image for the demo deployment. Build context: backend/.
#
# Installs the package with `pip install .`: no dev extras and no `extraction`
# extra (docling pulls in gigabytes of ML dependencies and is not needed to run
# a class). Material extraction falls back to the lightweight parsers.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Non-root, with a fixed uid so a bind-mounted volume can be given to it.
RUN useradd --system --uid 10001 --create-home --home-dir /home/clip clip \
    && mkdir -p /srv/clip /data/uploads \
    && chown -R clip:clip /srv/clip /data

WORKDIR /srv/clip

# Dependencies and the package first, so a change to a migration does not
# reinstall everything. The package is installed into site-packages; only the
# files Alembic needs are kept in the working directory.
COPY pyproject.toml ./
COPY app ./app
RUN pip install .  && rm -rf ./app

COPY alembic.ini ./
COPY migrations ./migrations

# Applies migrations, then replaces the shell with uvicorn so SIGTERM reaches it
# and the lifespan shutdown (drain jobs, stop session timers) runs.
#
# Exactly one worker: a live session's question timer is held in the process
# that runs it, and the backend refuses to start in production with more.
COPY --chmod=0755 <<'EOF' /usr/local/bin/clip-entrypoint
#!/bin/sh
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers
EOF

USER clip

# Uploaded material. Mount a volume here to keep it. Reports are held in
# memory and need no storage.
ENV UPLOAD_STORAGE_DIR=/data/uploads
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/clip-entrypoint"]
