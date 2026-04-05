# Lions Roar – Telegram monitor (uses Telethon session mounted at runtime)
FROM python:3.12-slim

ENV TZ=Asia/Jerusalem

WORKDIR /app

COPY requirements.txt .
RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && apt-get install -y --no-install-recommends gcc tzdata \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt && rm requirements.txt

COPY main.py .
COPY lions_roar.session .
COPY components/ ./components/

CMD ["python", "-u", "main.py"]
