FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Xvfbインストール
RUN apt-get update && apt-get install -y xvfb && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium

COPY . .

ENV PORT=10000
ENV DISPLAY=:99

CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x720x24 & gunicorn -b 0.0.0.0:10000 --timeout 300 --workers 1 --capture-output --log-level info auth_notification_system:app"]
