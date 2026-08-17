FROM python:3.13-alpine

LABEL org.opencontainers.image.title="Raven Ledger backend" \
  org.opencontainers.image.version="1.76.3" \
  org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
# pg_dump/pg_restore/psql drive backups and test restores. Alpine keeps the
# runtime small without pulling Perl into a service that never executes it.
# A minimum version keeps release caches from reusing a client layer after the
# Alpine security repository has moved forward. Newer compatible patch
# releases remain eligible automatically.
RUN apk add --no-cache \
  'postgresql17-client>=17.11-r0' \
  'libpq>=18.5-r0'
RUN addgroup --system raven \
  && adduser --system --ingroup raven raven \
  && mkdir -p /backups \
  && chown raven:raven /backups
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir -r requirements.txt \
  && python -m pip uninstall -y setuptools msgpack \
  && python -m pip uninstall -y pip
COPY backend/alembic.ini .
COPY backend/migrations ./migrations
COPY backend/app ./app
COPY backend/start.py .
COPY LICENSE NOTICE ./
USER raven
EXPOSE 8000
CMD ["python", "start.py"]
