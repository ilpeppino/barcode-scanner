FROM python:3.12-slim

# System deps (optional but good practice)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG IMAGE_TAG=unknown
ENV IMAGE_TAG=$IMAGE_TAG
LABEL org.opencontainers.image.version=${IMAGE_TAG}

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV PORT=5000
EXPOSE 5000

# Run gunicorn WITH TLS (certs will be mounted at /app/certs)
CMD ["gunicorn", \
     "--certfile", "/app/certs/dsplay418.crt", \
     "--keyfile", "/app/certs/dsplay418.key", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--timeout", "120", \
     "app:app"]