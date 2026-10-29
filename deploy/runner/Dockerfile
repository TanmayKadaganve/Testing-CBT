FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ openjdk-17-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

ENV HOME=/tmp TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
WORKDIR /workspace
