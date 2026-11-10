import httpx
import respx

from app.tools import web_tools
from app.tools.web_tools import WEB_TOOLS, get_exchange_rate, get_weather, web_search


def test_web_tools_shape():
    assert set(WEB_TOOLS) == {"web_search", "get_weather", "get_exchange_rate"}
    for fn, spec in WEB_TOOLS.values():
        assert callable(fn) and {"description", "input_schema"} <= set(spec)


@respx.mock
def test_get_weather_tomorrow():
    respx.get(web_tools.GEOCODE_URL).mock(
        return_value=httpx.Response(
            200, json={"results": [{"name": "Porto Alegre", "country": "Brazil", "latitude": -30.03, "longitude": -51.23}]}
        )
    )
    forecast = respx.get(web_tools.FORECAST_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2026-11-10", "2026-11-11"],
                    "temperature_2m_max": [28.0, 31.5],
                    "temperature_2m_min": [18.0, 20.1],
                    "precipitation_probability_max": [10, 70],
                    "weather_code": [0, 63],
                }
            },
        )
    )
    res = get_weather("Porto Alegre")
    assert res["ok"] and res["date"] == "2026-11-11"
    assert res["temp_max_c"] == 31.5 and res["condition"] == "rain"
    assert res["precipitation_probability_pct"] == 70
    assert forecast.calls.last.request.url.params["forecast_days"] == "2"


@respx.mock
def test_get_weather_unknown_city():
    respx.get(web_tools.GEOCODE_URL).mock(return_value=httpx.Response(200, json={}))
    res = get_weather("Atlantis")
    assert res["ok"] is False and "not found" in res["error"]


@respx.mock
def test_get_exchange_rate():
    route = respx.get(web_tools.FX_URL).mock(
        return_value=httpx.Response(200, json={"base": "EUR", "date": "2026-11-10", "rates": {"BRL": 6.12}})
    )
    res = get_exchange_rate("eur")
    assert res == {
        "ok": True, "base": "EUR", "quote": "BRL", "rate": 6.12, "date": "2026-11-10", "source": "https://frankfurter.dev"
    }
    assert route.calls.last.request.url.params["symbols"] == "BRL"


@respx.mock
def test_exchange_rate_error_never_raises():
    respx.get(web_tools.FX_URL).mock(side_effect=httpx.ConnectError("boom"))
    res = get_exchange_rate("EUR")
    assert res["ok"] is False and "boom" in res["error"]


def test_web_search(monkeypatch):
    class FakeDDGS:
        def text(self, query, max_results=5):
            return [{"title": "Getnet", "href": "https://site.getnet.com.br", "body": "Maquininhas"}][:max_results]

    import ddgs

    monkeypatch.setattr(ddgs, "DDGS", FakeDDGS)
    res = web_search("getnet")
    assert res == {"ok": True, "results": [{"title": "Getnet", "url": "https://site.getnet.com.br", "snippet": "Maquininhas"}]}


def test_web_search_error(monkeypatch):
    class BrokenDDGS:
        def text(self, *a, **kw):
            raise RuntimeError("rate limited")

    import ddgs

    monkeypatch.setattr(ddgs, "DDGS", BrokenDDGS)
    assert web_search("x")["ok"] is False
