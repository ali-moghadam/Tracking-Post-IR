FROM python:3.12-slim

# Set working directory
WORKDIR /app

# curl_cffi wheels are pre-built; no compiler needed on slim.
# Only curl's runtime shared library is required on some distros.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Copy .env if present (optional – override with docker-compose or -e flags)
COPY .env* ./

# Non-root user for security
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 3001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3001"]
