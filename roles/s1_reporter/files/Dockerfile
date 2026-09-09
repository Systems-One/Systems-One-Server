# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1
RUN apt-get update \
  && apt-get install -y --no-install-recommends gcc g++ freetds-dev \
  && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip wheel --wheel-dir /wheels -r /tmp/requirements.txt

FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib
ENV TZ=Africa/Johannesburg
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates libsybdb5 tzdata \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --system --uid 10001 --create-home reporter
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels
WORKDIR /app
COPY app/ /app/
USER reporter
ENTRYPOINT ["python", "-m", "s1_reporter"]
