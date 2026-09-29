# syntax=docker/dockerfile:1
FROM python:3.12-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Africa/Johannesburg
RUN apk add --no-cache tzdata && adduser -D -H -u 1001 appuser
WORKDIR /app
COPY app/relay.py .
USER appuser
# Healthy while the watch loop runs, regardless of printer state; printer
# up/down is reported in the logs and by the listener opening/closing.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD python -c "import os,sys,time; sys.exit(0 if time.time()-os.path.getmtime('/tmp/relay-heartbeat')<60 else 1)"
ENTRYPOINT ["python", "relay.py"]
