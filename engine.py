"""Minimal Omeka S REST client and metadata-mutation helpers.

The module provides two layers:

* **`OmekaClient`** - a synchronous wrapper around the Omeka S JSON API
  that handles authentication, automatic pagination, and simple
  ``PATCH`` updates.

* **`diff`** and **`apply_ops`** - pure-Python utilities that build and
  preview *add / replace / remove* operations on a resource **in
  memory** before the changes are sent back through `OmekaClient`.
"""

from typing import Any

import requests


class OmekaClient:
    """Thin wrapper around the Omeka S REST API."""

    def __init__(self, base_url: str, key_id: str, key_cred: str):
        if not base_url.endswith("/api"):
            base_url = base_url.rstrip("/") + "/api"
        self.base = base_url
        self.s = requests.Session()
        self.s.headers["Content-Type"] = "application/json"
        self.s.params = {"key_identity": key_id, "key_credential": key_cred}

    def list_property_values(
        self,
        term: str,
        limit: int = 5_000,
    ) -> list[str]:
        """Return ≤ *limit* distinct literal/label values for *term*."""
        values: set[str] = set()
        prop_id = self._get_all("properties", term=term)[0]["o:id"]

        try:  # fast path
            for v in self._get_all("values", property=prop_id):
                values.add(v.get("@value") or v.get("o:label") or "")
        except requests.HTTPError:  # fallback scan
            page = 1  # Omeka pages are 1-based
            scanned = 0
            while len(values) < limit and scanned < limit:
                block = self._get_all(  # ← keep a reference
                    "items",
                    **{"property[0][property]": term, "page": page},
                )
                if not block:  # ← NEW: stop at first empty page
                    break

                for it in block:
                    scanned += 1
                    for v in it.get(term, []):
                        values.add(v.get("@value") or v.get("o:label") or "")
                page += 1
        return sorted(values)[:limit]

    # ---------- low-level helpers ---------- #
    def _get_all(self, endpoint: str, **params) -> list[dict[str, Any]]:
        page, out = 1, []
        while True:
            r = self.s.get(f"{self.base}/{endpoint}", params={**params, "page": page})
            r.raise_for_status()
            block = r.json()
            if not block:
                break
            out.extend(block)
            page += 1
        return out

    def list_item_sets(self):
        return self._get_all("item_sets")

    def list_items(self, **params):
        return self._get_all("items", **params)

    def patch_item(self, item_id: int, payload: dict[str, Any]):
        return self.s.patch(f"{self.base}/items/{item_id}", json=payload)
