FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY kaos_sync ./kaos_sync

RUN pip install --no-cache-dir .

USER 1000:1000

ENTRYPOINT ["kaos-sync"]
