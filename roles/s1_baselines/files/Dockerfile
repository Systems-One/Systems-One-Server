# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates gcc g++ freetds-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir "pymssql==2.3.2"

COPY compute_baselines.py /app/compute_baselines.py
COPY migrations/ /app/migrations/

# No CMD: running with no subcommand prints usage and exits 2 instead of writing anything.
ENTRYPOINT ["python3", "/app/compute_baselines.py"]
