FROM python:3.11-slim

# Hindre at Python skriver pyc-filer og bufrer stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Tidssone. Uten dette kjører containeren i UTC, og da bommer `date.today()`
# på kvelden norsk tid: et kjøp registrert 00:30 blir avvist som «framtidig
# dato», og månedsrapporten bytter måned et døgn for sent.
ENV TZ=Europe/Oslo
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Installer pip-avhengigheter først — cached layer hvis kun applikasjonskode endres
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Kopier applikasjon
COPY analyse/ ./analyse/
COPY templates/ ./templates/
COPY app.py .

# data/ bind-mountes fra host. På Linux må container-brukeren ha SAMME uid/gid
# som eieren av host-katalogen, ellers nektes skriving. Docker Desktop på
# macOS/Windows mapper dette automatisk, så feilen dukker først opp på Linux.
# Sett UID/GID i .env til `id -u`/`id -g` hvis din bruker ikke er 1000:1000.
ARG UID=1000
ARG GID=1000
RUN mkdir -p /app/data \
    && (getent group "$GID" || groupadd --gid "$GID" appuser) \
    && useradd --no-log-init --create-home --shell /bin/bash \
               --uid "$UID" --gid "$GID" appuser 2>/dev/null \
       || useradd --no-log-init --create-home --shell /bin/bash \
                  --uid "$UID" --gid "$GID" --non-unique appuser \
    && chown -R "$UID:$GID" /app
USER $UID:$GID

EXPOSE 5001

# Healthcheck — sjekker at forsiden svarer
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request as r; r.urlopen('http://localhost:5001/').close()" || exit 1

# Én worker med tråder fordi appen har in-process TTL-cache som ikke kan deles
# på tvers av prosesser. Tråder håndterer Yahoo-I/O parallelt.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5001", \
     "--workers", "1", \
     "--threads", "8", \
     "--worker-class", "gthread", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
