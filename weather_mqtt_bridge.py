#!/usr/bin/env python3
"""weather-mqtt-bridge: Open-Meteo → MQTT weather data service.

Fetches weather forecasts from the Open-Meteo API for configured spots
and models, then publishes current values and full forecasts to MQTT.

Designed for LoxBerry / Loxone but works with any MQTT consumer.
"""

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt
import requests
import yaml

__version__ = "1.0.0"

logger = logging.getLogger("weather-mqtt-bridge")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "mqtt": {
        "broker": "localhost",
        "port": 1883,
        "username": None,
        "password": None,
        "client_id": "weather-mqtt-bridge",
        "base_topic": "weather",
        "retain": True,
        "qos": 1,
    },
    "spots": [],
    "models": ["ecmwf_ifs04"],
    "hourly_parameters": ["wind_speed_10m", "wind_direction_10m", "temperature_2m"],
    "preferred_model": "ecmwf_ifs04",
    "fetch_interval_minutes": 15,
    "conversions": {},
    "logging": {"level": "INFO", "file": None},
}


def load_config(path: str) -> Dict[str, Any]:
    """Load and merge config with defaults."""
    with open(path) as f:
        user = yaml.safe_load(f) or {}
    cfg = {**DEFAULT_CONFIG}
    for key in DEFAULT_CONFIG:
        if key in user:
            if isinstance(DEFAULT_CONFIG[key], dict) and isinstance(user[key], dict):
                cfg[key] = {**DEFAULT_CONFIG[key], **user[key]}
            else:
                cfg[key] = user[key]
    return cfg


# ---------------------------------------------------------------------------
# Open-Meteo client
# ---------------------------------------------------------------------------

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_openmeteo(
    lat: float, lon: float, params: List[str], models: List[str]
) -> Dict[str, Any]:
    """Fetch forecast from Open-Meteo for one spot."""
    resp = requests.get(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(params),
            "models": ",".join(models),
            "timezone": "UTC",
            "forecast_days": 7,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def find_current_index(times: List[str]) -> int:
    """Find the index of the forecast hour closest to now."""
    now = datetime.now(timezone.utc)
    best_idx = 0
    best_delta = float("inf")
    for i, t in enumerate(times):
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        delta = abs((now - dt).total_seconds())
        if delta < best_delta:
            best_delta = delta
            best_idx = i
    return best_idx


# ---------------------------------------------------------------------------
# MQTT publisher
# ---------------------------------------------------------------------------


class MQTTPublisher:
    """Thin wrapper around paho MQTT client."""

    def __init__(self, cfg: Dict[str, Any]):
        self.base = cfg["mqtt"]["base_topic"]
        self.retain = cfg["mqtt"]["retain"]
        self.qos = cfg["mqtt"]["qos"]
        self.client = mqtt.Client(
            client_id=cfg["mqtt"]["client_id"],
            protocol=mqtt.MQTTv311,
        )
        if cfg["mqtt"].get("username"):
            self.client.username_pw_set(
                cfg["mqtt"]["username"], cfg["mqtt"].get("password")
            )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self._connected = False
        self._broker = cfg["mqtt"]["broker"]
        self._port = cfg["mqtt"]["port"]

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("MQTT connected to %s:%s", self._broker, self._port)
            self._connected = True
        else:
            logger.error("MQTT connect failed: rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc):
        logger.warning("MQTT disconnected: rc=%s", rc)
        self._connected = False

    def connect(self):
        self.client.connect(self._broker, self._port, keepalive=60)
        self.client.loop_start()
        # Wait for connection
        for _ in range(50):
            if self._connected:
                return
            time.sleep(0.1)
        if not self._connected:
            raise ConnectionError(
                f"Could not connect to MQTT broker at {self._broker}:{self._port}"
            )

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, topic_parts: List[str], value: Any):
        topic = "/".join([self.base] + topic_parts)
        payload = str(value) if not isinstance(value, str) else value
        self.client.publish(topic, payload, qos=self.qos, retain=self.retain)

    def publish_json(self, topic_parts: List[str], data: Any):
        topic = "/".join([self.base] + topic_parts)
        payload = json.dumps(data, separators=(",", ":"))
        self.client.publish(topic, payload, qos=self.qos, retain=self.retain)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def apply_conversions(
    param: str, value: float, conversions: Dict
) -> List[tuple]:
    """Return list of (suffix, converted_value) for a parameter."""
    results = []
    conv_list = conversions.get(param, [])
    for conv in conv_list:
        results.append((conv["unit"], round(value * conv["factor"], 2)))
    return results


def process_spot(
    spot: Dict,
    models: List[str],
    params: List[str],
    preferred: str,
    publisher: MQTTPublisher,
    conversions: Dict,
) -> bool:
    """Fetch and publish data for one spot. Returns True on success."""
    slug = spot["slug"]
    lat, lon = spot["lat"], spot["lon"]

    logger.info("Fetching %s (%.2f, %.2f) — models: %s", slug, lat, lon, models)

    try:
        data = fetch_openmeteo(lat, lon, params, models)
    except requests.RequestException as e:
        logger.error("API error for %s: %s", slug, e)
        return False

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Open-Meteo returns per-model hourly blocks when multiple models requested.
    # With multiple models, keys are like "wind_speed_10m_ecmwf_ifs04".
    # With single model, keys are plain like "wind_speed_10m".
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        logger.warning("No time series for %s", slug)
        return False

    current_idx = find_current_index(times)
    current_time = times[current_idx] if current_idx < len(times) else now_iso

    # Determine which keys belong to which model
    model_data: Dict[str, Dict[str, Any]] = {}
    for model in models:
        model_data[model] = {}
        for param in params:
            # Try model-suffixed key first (multi-model response)
            key = f"{param}_{model}"
            if key in hourly:
                values = hourly[key]
            elif param in hourly:
                # Single model or shared key
                values = hourly[param]
            else:
                continue

            if current_idx < len(values) and values[current_idx] is not None:
                model_data[model][param] = values[current_idx]

            # Publish full forecast series
            forecast_series = [
                {"time": times[i], "value": values[i]}
                for i in range(len(values))
                if values[i] is not None
            ]
            publisher.publish_json([slug, model, param, "forecast"], forecast_series)

    # Publish current values per model
    for model, current in model_data.items():
        for param, value in current.items():
            publisher.publish([slug, model, param], round(value, 2))

            # Unit conversions
            for unit, conv_val in apply_conversions(param, value, conversions):
                publisher.publish([slug, model, f"{param}_{unit}"], conv_val)

        # Full current JSON for this model
        publisher.publish_json([slug, model, "current"], {
            "time": current_time,
            **current,
        })

    # Publish preferred model as "best"
    if preferred in model_data:
        best = model_data[preferred]
        for param, value in best.items():
            publisher.publish([slug, "best", param], round(value, 2))
            for unit, conv_val in apply_conversions(param, value, conversions):
                publisher.publish([slug, "best", f"{param}_{unit}"], conv_val)
        publisher.publish_json([slug, "best", "current"], {
            "time": current_time,
            "model": preferred,
            **best,
        })

    # Meta
    publisher.publish([slug, "meta", "last_update"], now_iso)
    publisher.publish([slug, "meta", "current_forecast_time"], current_time)
    publisher.publish([slug, "meta", "models"], ",".join(models))

    logger.info("Published %s — %d models, current: %s", slug, len(model_data), current_time)
    return True


def run_cycle(cfg: Dict[str, Any], publisher: MQTTPublisher) -> int:
    """Run one fetch-and-publish cycle for all spots. Returns success count."""
    ok = 0
    for spot in cfg["spots"]:
        if process_spot(
            spot,
            cfg["models"],
            cfg["hourly_parameters"],
            cfg["preferred_model"],
            publisher,
            cfg.get("conversions", {}),
        ):
            ok += 1
    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Open-Meteo → MQTT weather bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Fetch once and exit (no loop)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch data but don't publish to MQTT (print to stdout)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    args = parser.parse_args()

    # Load config
    cfg = load_config(args.config)

    # Logging
    level = "DEBUG" if args.verbose else cfg["logging"]["level"]
    handlers: list = [logging.StreamHandler(sys.stdout)]
    log_file = cfg["logging"].get("file")
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    if not cfg["spots"]:
        logger.error("No spots configured — nothing to do")
        sys.exit(1)

    logger.info(
        "weather-mqtt-bridge v%s starting — %d spots, %d models, interval %dm",
        __version__,
        len(cfg["spots"]),
        len(cfg["models"]),
        cfg["fetch_interval_minutes"],
    )

    if args.dry_run:
        logger.info("DRY RUN — fetching but not publishing")
        for spot in cfg["spots"]:
            try:
                data = fetch_openmeteo(
                    spot["lat"], spot["lon"],
                    cfg["hourly_parameters"], cfg["models"],
                )
                print(json.dumps(data, indent=2))
            except Exception as e:
                logger.error("Fetch failed for %s: %s", spot["slug"], e)
        return

    # MQTT
    publisher = MQTTPublisher(cfg)
    try:
        publisher.connect()
    except ConnectionError as e:
        logger.error(str(e))
        sys.exit(1)

    # Graceful shutdown
    running = True

    def _shutdown(signum, frame):
        nonlocal running
        logger.info("Shutting down (signal %s)...", signum)
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        if args.once:
            ok = run_cycle(cfg, publisher)
            logger.info("Single run complete: %d/%d spots OK", ok, len(cfg["spots"]))
        else:
            interval = cfg["fetch_interval_minutes"] * 60
            while running:
                ok = run_cycle(cfg, publisher)
                logger.info(
                    "Cycle done: %d/%d spots OK. Next in %dm.",
                    ok, len(cfg["spots"]), cfg["fetch_interval_minutes"],
                )
                # Sleep in small increments for responsive shutdown
                for _ in range(int(interval)):
                    if not running:
                        break
                    time.sleep(1)
    finally:
        publisher.disconnect()
        logger.info("Goodbye.")


if __name__ == "__main__":
    main()
