FROM python:3.11-slim

# Hindre at Python skriver pyc-filer og bufrer stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Installer pip-avhengigheter først — cached layer hvis kun applikasjonskode endres
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Kopier applikasjon
COPY analyse/ ./analyse/
COPY templates/ ./templates/
COPY app.py .

# Opprett data-katalog som mountes inn fra host, og kjør som ikke-root-bruker
RUN mkdir -p /app/data \
    && useradd --create-home --shell /bin/bash --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

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
