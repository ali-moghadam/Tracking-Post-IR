FROM python:3.13-slim

# Set working directory
WORKDIR /app

# System deps: curl_cffi runtime + Playwright/Chromium dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4 \
    # Chromium / Playwright system libraries
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    libx11-6 libxcb1 libxext6 libxshmfence1 \
    fonts-liberation wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Chromium browser binary for Playwright
RUN playwright install chromium

# Copy application source
COPY app/ ./app/
COPY main.py .

# Copy .env if present (optional – override with docker-compose or -e flags)
COPY .env* ./

EXPOSE 3001

CMD ["python", "main.py"]
