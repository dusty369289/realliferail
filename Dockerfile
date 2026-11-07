# Real Life Rail, hosted mode: each visitor brings their own Realtime Trains key (kept encrypted in their
# browser); the server stores no key and no data. Needs REALLIFERAIL_SECRET (64 hex characters) at run time.
#   docker build -t realliferail .
#   docker run --rm -p 8080:8080 -e REALLIFERAIL_SECRET=$(python -c 'import secrets;print(secrets.token_hex(32))') \
#     --read-only --tmpfs /tmp --user 65534:65534 realliferail
# Dependencies come from requirements.lock (uv export, hashed, every release at least 7 days old when locked).
FROM python:3.15.1-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    REALLIFERAIL_HOME=/tmp/realliferail

COPY requirements.lock /app/requirements.lock
RUN pip install --no-compile --require-hashes -r /app/requirements.lock

COPY src /app/src

USER 65534:65534
WORKDIR /tmp
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=8)"]
CMD ["python", "-m", "realliferail.cli.main", "serve", "--hosted", "--host", "0.0.0.0", "--port", "8080"]
