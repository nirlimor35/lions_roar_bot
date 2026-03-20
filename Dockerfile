# Lions Roar – Telegram monitor (uses Telethon session mounted at runtime)
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY components/ ./components/

ENV TG_SESSION_NAME=alerts_session

CMD ["python", "-u", "main.py"]
