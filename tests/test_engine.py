import requests

from engine import OmekaClient


def _client(monkeypatch):
    """Return an OmekaClient with all networking stubbed out."""
    client = OmekaClient("https://demo/api", "id", "cred")

    # Monkey-patch the private _get_all to avoid real HTTP
    def fake_get_all(endpoint, **params):
        if endpoint == "properties":
            return [{"o:id": 111}]  # prop_id looked up once
        if endpoint == "values":
            return [{"@value": "A"}, {"o:label": "B"}, {"@value": "A"}]
        raise AssertionError("Unexpected endpoint")

    monkeypatch.setattr(client, "_get_all", fake_get_all)
    return client


def test_list_property_values_fast(monkeypatch):
    client = _client(monkeypatch)

    values = client.list_property_values("dcterms:title")
    assert values == ["A", "B"]  # unique + sorted


def test_list_property_values_fallback(monkeypatch):
    """Simulate the /values endpoint raising HTTPError → fallback scan."""
    client = OmekaClient("https://demo/api", "id", "cred")

    calls = {"page": 0}

    def fake_get_all(endpoint, **params):
        if endpoint == "properties":
            return [{"o:id": 222}]
        if endpoint == "values":
            raise requests.HTTPError("simulate 404")  # force fallback
        if endpoint == "items":
            page = params.get("page")
            calls["page"] = page
            # first page returns one item with two values, second page empty
            if page == 1:
                return [
                    {"dcterms:title": [{"@value": "X"}]},
                    {"dcterms:title": [{"o:label": "Y"}]},
                ]
            return []  # stop pagination
        raise AssertionError("Unexpected endpoint")

    monkeypatch.setattr(client, "_get_all", fake_get_all)

    assert client.list_property_values("dcterms:title", limit=10) == ["X", "Y"]
    assert calls["page"] == 2  # proved that pagination happened
