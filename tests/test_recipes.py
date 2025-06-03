from engine import OmekaClient
from recipes import Recipe


class DummyClient(OmekaClient):  # inherits just for type compatibility
    def __init__(self):
        pass  # no HTTP session

    # ---- stubs -------------------------------------------------------------
    def list_items(self, **params):
        """Return three fake items, one per call; filter by item_set_id."""
        set_id = params.get("item_set_id")
        items = {
            1: [
                {
                    "o:id": 1,
                    "o:resource_class": {"o:id": 10},
                    "dcterms:title": [{"@value": "Keep me"}],
                    "o:type": "items",
                },
            ],
            2: [
                {
                    "o:id": 2,
                    "o:resource_class": {"o:id": 20},
                    "dcterms:title": [{"@value": "Drop me"}],
                    "o:type": "items",
                },
            ],
        }
        return items.get(set_id, [])

    def _get_all(self, endpoint, **params):
        """Return two media for item 1."""
        if endpoint == "media":
            return [
                {"o:id": 99, "o:type": "media"},
                {"o:id": 99, "o:type": "media"},  # duplicate on purpose
            ]
        raise AssertionError("Unexpected endpoint")


def test_select_items_filters_class_and_titles():
    client = DummyClient()
    r = Recipe(
        item_set_ids=[1, 2],
        resource_types=["items"],
        ops=[],
        resource_class_id=10,
        exclude_titles=["drop me"],  # lower-case to test ci compare
    )
    items = r.select_items(client)
    assert [it["o:id"] for it in items] == [1]


def test_select_with_media_deduplicates():
    client = DummyClient()
    r = Recipe(
        item_set_ids=[1],
        resource_types=["items"],
        ops=[],
        include_media=True,
    )
    resources = r.select(client)
    ids = [r["o:id"] for r in resources]
    # item 1 + one unique medium
    assert sorted(ids) == [1, 99]
    assert ids.count(99) == 1  # deduplicated
