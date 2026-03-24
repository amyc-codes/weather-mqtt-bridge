# weather-mqtt-bridge 🌤️→📡

Open-Meteo → MQTT weather data bridge. Fetches forecasts and publishes to MQTT for Loxone, Home Assistant, Grafana, or anything that speaks MQTT.

**Free. No API key. No rate limits.**

## Quick Start

```bash
# Install dependencies
pip3 install -r requirements.txt

# Edit config
cp config.yaml my-config.yaml
nano my-config.yaml

# Test (fetch once, print to stdout)
python3 weather_mqtt_bridge.py --config my-config.yaml --dry-run

# Run once (publish to MQTT)
python3 weather_mqtt_bridge.py --config my-config.yaml --once --verbose

# Run as daemon (fetches every 15 min)
python3 weather_mqtt_bridge.py --config my-config.yaml
```

## MQTT Topics

All topics under `weather/` (configurable):

```
weather/{spot}/{model}/{param}              = current value (retained)
weather/{spot}/{model}/{param}/forecast     = full 7-day JSON series
weather/{spot}/{model}/current              = all current values as JSON
weather/{spot}/best/{param}                 = preferred model value
weather/{spot}/best/current                 = preferred model JSON
weather/{spot}/meta/last_update             = ISO timestamp
weather/{spot}/meta/models                  = comma-separated model list
```

### Example

```
weather/salzburg/ecmwf_ifs04/wind_speed_10m         = 12.5
weather/salzburg/ecmwf_ifs04/wind_speed_10m_kn       = 6.75
weather/salzburg/ecmwf_ifs04/wind_speed_10m_ms       = 3.47
weather/salzburg/ecmwf_ifs04/wind_gusts_10m          = 22.1
weather/salzburg/ecmwf_ifs04/temperature_2m          = 8.3
weather/salzburg/ecmwf_ifs04/current                 = {"time":"2026-03-24T10:00","wind_speed_10m":12.5,...}
weather/salzburg/best/wind_speed_10m                 = 12.5
weather/salzburg/meta/last_update                    = 2026-03-24T10:15:00Z
```

## Config Reference

```yaml
mqtt:
  broker: localhost           # MQTT broker host
  port: 1883                  # MQTT broker port
  username: null              # Optional auth
  password: null
  client_id: weather-mqtt-bridge
  base_topic: weather         # Root topic prefix
  retain: true                # Retained messages (recommended)
  qos: 1                      # Quality of service

spots:
  - slug: salzburg            # Used in topic path
    name: Salzburg
    lat: 47.80
    lon: 13.04

models:                       # Open-Meteo model names
  - ecmwf_ifs04               # ECMWF IFS 0.4°
  - gfs_seamless              # GFS (NOAA)
  - icon_seamless             # ICON (DWD)

hourly_parameters:            # What to fetch
  - wind_speed_10m
  - wind_direction_10m
  - wind_gusts_10m
  - temperature_2m
  - precipitation
  - pressure_msl
  - cloud_cover

preferred_model: ecmwf_ifs04  # Published under "best" topic
fetch_interval_minutes: 15

conversions:                  # Auto-publish unit conversions
  wind_speed_10m:
    - unit: ms                # km/h → m/s
      factor: 0.27778
    - unit: kn                # km/h → knots
      factor: 0.53996
```

## Available Models

| Model | Provider | Resolution | Coverage |
|-------|----------|-----------|----------|
| `ecmwf_ifs04` | ECMWF | 0.4° (~44km) | Global |
| `gfs_seamless` | NOAA | Blended | Global |
| `icon_seamless` | DWD | Blended | Global |
| `icon_eu` | DWD | 7km | Europe |
| `icon_d2` | DWD | 2.2km | Germany/Austria |
| `meteofrance_arome_france` | Météo-France | 1.3km | France/Alps |

See [Open-Meteo docs](https://open-meteo.com/en/docs) for the full list.

## Available Parameters

| Parameter | Unit | Description |
|-----------|------|-------------|
| `wind_speed_10m` | km/h | Wind speed at 10m |
| `wind_direction_10m` | ° | Wind direction |
| `wind_gusts_10m` | km/h | Wind gusts |
| `temperature_2m` | °C | Temperature at 2m |
| `apparent_temperature` | °C | Feels-like temperature |
| `precipitation` | mm | Precipitation |
| `precipitation_probability` | % | Rain probability |
| `pressure_msl` | hPa | Sea-level pressure |
| `cloud_cover` | % | Cloud cover |
| `relative_humidity_2m` | % | Relative humidity |

## Deployment

### LoxBerry (Raspberry Pi)

```bash
# SSH into LoxBerry
ssh loxberry@192.168.68.74

# Make sure Mosquitto is installed
sudo apt install -y mosquitto mosquitto-clients

# Clone and install
git clone https://github.com/amyc-codes/weather-mqtt-bridge.git
cd weather-mqtt-bridge
chmod +x install.sh
./install.sh

# Edit config for your setup
sudo nano /opt/weather-mqtt-bridge/config.yaml

# Start
sudo systemctl start weather-mqtt-bridge
journalctl -u weather-mqtt-bridge -f
```

### Docker

```bash
docker build -t weather-mqtt-bridge .
docker run -d --name weather-mqtt \
  -v $(pwd)/config.yaml:/app/config.yaml \
  --network host \
  weather-mqtt-bridge
```

### Loxone Integration

The Loxone Miniserver Gen2 supports MQTT natively:
1. In Loxone Config, add an MQTT connection to your broker
2. Subscribe to topics like `weather/salzburg/best/temperature_2m`
3. Create virtual inputs bound to the MQTT topics

For Gen1, use the LoxBerry MQTT Gateway plugin to bridge MQTT → UDP.

## CLI Options

```
usage: weather_mqtt_bridge.py [-h] [--config CONFIG] [--once] [--verbose] [--dry-run] [--version]

  --config, -c   Path to config file (default: config.yaml)
  --once         Fetch once and exit
  --verbose, -v  Debug logging
  --dry-run      Fetch but don't publish (print JSON to stdout)
  --version      Show version
```

## License

MIT
