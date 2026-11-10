"""Public web tools (no API key): web search, weather forecast and exchange rates.

Every tool returns a dict and never raises; failures come back as {"ok": False, "error": ...}.
"""

from collections.abc import Callable
from typing import Any

import httpx

TIMEOUT_S = 8.0
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FX_URL = "https://api.frankfurter.dev/v1/latest"


def _error(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    try:
        from ddgs import DDGS

        hits = DDGS().text(query, max_results=max_results) or []
        results = [
            {"title": h.get("title", ""), "url": h.get("href") or h.get("url", ""), "snippet": h.get("body", "")}
            for h in hits
        ]
        return {"ok": True, "results": results}
    except Exception as exc:  # noqa: BLE001 - tools must never raise
        return _error(exc)


def _wmo_condition(code: int | None) -> str:
    if code is None:
        return "unknown"
    if code == 0:
        return "clear sky"
    if 1 <= code <= 3:
        return "partly cloudy"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67:
        return "rain"
    if 71 <= code <= 77:
        return "snow"
    if 80 <= code <= 82:
        return "rain showers"
    if 95 <= code <= 99:
        return "thunderstorm"
    return "unknown"


def get_weather(city: str, day_offset: int = 1) -> dict[str, Any]:
    try:
        day_offset = max(0, min(int(day_offset), 15))
        with httpx.Client(timeout=TIMEOUT_S) as http:
            geo = http.get(GEOCODE_URL, params={"name": city, "count": 1, "language": "en", "format": "json"})
            geo.raise_for_status()
            places = geo.json().get("results") or []
            if not places:
                return {"ok": False, "error": f"city '{city}' not found"}
            place = places[0]
            forecast = http.get(
                FORECAST_URL,
                params={
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                    "timezone": "auto",
                    "forecast_days": day_offset + 1,
                },
            )
            forecast.raise_for_status()
            daily = forecast.json()["daily"]
        return {
            "ok": True,
            "city": place.get("name", city),
            "country": place.get("country", ""),
            "date": daily["time"][day_offset],
            "temp_max_c": daily["temperature_2m_max"][day_offset],
            "temp_min_c": daily["temperature_2m_min"][day_offset],
            "precipitation_probability_pct": daily["precipitation_probability_max"][day_offset],
            "condition": _wmo_condition(daily["weather_code"][day_offset]),
            "source": "https://open-meteo.com",
        }
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def get_exchange_rate(base: str, quote: str = "BRL") -> dict[str, Any]:
    try:
        base, quote = base.strip().upper(), quote.strip().upper()
        resp = httpx.get(FX_URL, params={"base": base, "symbols": quote}, timeout=TIMEOUT_S)
        resp.raise_for_status()
        payload = resp.json()
        return {
            "ok": True,
            "base": base,
            "quote": quote,
            "rate": payload["rates"][quote],
            "date": payload.get("date", ""),
            "source": "https://frankfurter.dev",
        }
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


WEB_TOOLS: dict[str, tuple[Callable[..., dict[str, Any]], dict[str, Any]]] = {
    "web_search": (
        web_search,
        {
            "description": "Search the public web (DuckDuckGo) for up-to-date information.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    ),
    "get_weather": (
        get_weather,
        {
            "description": "Daily weather forecast for a city (Open-Meteo). day_offset 0=today, 1=tomorrow.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "day_offset": {"type": "integer", "minimum": 0, "maximum": 15},
                },
                "required": ["city"],
                "additionalProperties": False,
            },
        },
    ),
    "get_exchange_rate": (
        get_exchange_rate,
        {
            "description": "Latest reference exchange rate between two currencies (Frankfurter/ECB), e.g. EUR->BRL.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "base": {"type": "string", "description": "ISO 4217 code, e.g. EUR"},
                    "quote": {"type": "string", "description": "ISO 4217 code; default BRL"},
                },
                "required": ["base"],
                "additionalProperties": False,
            },
        },
    ),
}
