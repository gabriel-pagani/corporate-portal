# STAGE 1
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

COPY ../requirements.txt .

RUN apt-get update && apt-get install -y build-essential gcc python3-dev libpq-dev libsasl2-dev libldap2-dev unixodbc-dev --no-install-recommends

RUN pip install --upgrade pip && pip install --prefix=/install -r requirements.txt

# STAGE 2
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y libpq5 libsasl2-2 libldap-2.5-0 unixodbc odbcinst tdsodbc --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY ../ .

EXPOSE 8000