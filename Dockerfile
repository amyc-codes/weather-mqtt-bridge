FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY weather_mqtt_bridge.py .
COPY config.yaml .

ENTRYPOINT ["python3", "weather_mqtt_bridge.py"]
CMD ["--config", "config.yaml"]
