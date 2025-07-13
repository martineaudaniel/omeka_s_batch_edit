"""High-level batch-editing “recipes” for Omeka S resources.

The module acts as the *glue layer* between the Streamlit GUI and the low-level
client in :pymod:`engine`.  A **Recipe** object defines *what to touch* (item
sets, class filter, title blacklist, optional media expansion) and *how to
mutate* those resources (rows of **add / replace / remove** operations).
:func:`run_recipe` then executes the recipe against an authenticated
:class:`engine.OmekaClient`, producing a concise report of successes and
errors.

Example:
-------
```python
from engine import OmekaClient
from recipes import Recipe, run_recipe

client = OmekaClient(BASE_URL, KEY_ID, KEY_CRED)

recipe = Recipe(
    item_set_ids=[12, 34],
    resource_types=["items"],
    ops=[{"Action": "add",
          "Property": "dcterms:creator",
          "Value": "Jane Doe",
          "Language": "en"}],
    include_media=True,
)

report = run_recipe(client, recipe, dry_run=False)
print(report["updated"], report["errors"])
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine import OmekaClient
from mutations import apply_ops, diff

# ────────────────────────────────────────────────────────────────────────────
# Helper
# ────────────────────────────────────────────────────────────────────────────


def _rtype(res: dict[str, Any]) -> str:
    """Return ``"item"`` or ``"media"`` for an Omeka S resource *res*.

    Priority:
    1. legacy scalar ``o:type`` (≤ 2.0)
    2. membership in the ``@type`` list (≥ 2.1)
    """
    if "o:type" in res:
        return res["o:type"]
    atypes = res.get("@type", [])
    return "media" if any(t.endswith("Media") for t in atypes) else "item"


# ────────────────────────────────────────────────────────────────────────────
# Data structure
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class Recipe:
    """Encapsulates *what to edit* and *how to edit it* in a batch job.

    A **Recipe** holds two kinds of information:

    1. **Selection criteria** - which resources to touch:
       * ``item_set_ids``: one or more Omeka S item-set IDs.
       * ``resource_class_id``: optional filter by resource class
         (e.g. *Text*).
       * ``exclude_titles``: case-insensitive blacklist of item titles.
       * ``include_media``: whether the media attached to each kept
         item should also be processed.
    2. **Mutation instructions** - a table of *add / replace / remove*
       operations stored in :pyattr:`ops`.

    The public helpers :meth:`select_items` and :meth:`select` turn the
    criteria into concrete resource JSON blocks, while
    :func:`run_recipe` applies the operations and (optionally) sends the
    resulting ``PATCH`` requests.

    Parameters
    ----------
    item_set_ids : list[int]
        IDs of the item sets whose items form the initial target pool.
    resource_types : list[str]
        Human-readable list such as ``["items"]`` or
        ``["items", "media"]``.  Presently for documentation only; the
        actual media inclusion is governed by ``include_media``.
    ops : list[dict[str, str]]
        Operation rows emitted by the Streamlit editor.  Each row
        contains the keys
        ``{"Action", "Property", "Value", "Language"}``.
    resource_class_id : int | None, optional
        Keep only items whose ``o:resource_class.o:id`` matches this
        value.  *None* ⇒ no class filter.
    exclude_titles : list[str] | None, optional
        Drop items whose first ``dcterms:title`` literal, stripped and
        case-folded, is in this list.
    include_media : bool, default ``False``
        When *True*, append every medium attached to the kept items,
        de-duplicated by ``o:id``.

    Notes:
    -----
    The dataclass is **not** frozen; callers may adjust attributes
    before passing the instance to :func:`run_recipe`.
    """

    item_set_ids: list[int]
    resource_types: list[str]  # "items", "media"
    ops: list[dict[str, str]]
    resource_class_id: int | None = None
    exclude_titles: list[str] | None = None
    include_media: bool = False

    # ---------- selector ---------------------------------------------------- #
    def select_items(self, client: OmekaClient) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for set_id in self.item_set_ids:
            items += client.list_items(item_set_id=set_id)

        if self.resource_class_id:
            items = [it for it in items if it.get("o:resource_class", {}).get("o:id") == self.resource_class_id]

        if self.exclude_titles:
            excl = {t.lower().strip() for t in self.exclude_titles}
            items = [it for it in items if it.get("dcterms:title", [{}])[0].get("@value", "").lower().strip() not in excl]

        return items

    def select(self, client: OmekaClient) -> list[dict[str, Any]]:
        resources = self.select_items(client)

        if self.include_media:
            media_block: list[dict[str, Any]] = []
            for it in resources:
                media_block += client._get_all("media", item_id=it["o:id"])

            # De-duplicate by id
            seen = set()
            media_block = [m for m in media_block if not (m["o:id"] in seen or seen.add(m["o:id"]))]
            resources += media_block

        return resources


# ────────────────────────────────────────────────────────────────────────────
# Executor
# ────────────────────────────────────────────────────────────────────────────
def run_recipe(client: OmekaClient, recipe: Recipe, dry_run: bool = True):
    """Execute a :class:`Recipe` against an Omeka S site."""
    report: dict[str, list[dict[str, Any]]] = {"updated": [], "errors": []}

    for res in recipe.select(client):
        updated = apply_ops(res, recipe.ops)
        if updated == res:
            continue  # no change → skip

        if dry_run:
            report["updated"].append(
                {
                    "id": res["o:id"],
                    "type": _rtype(res),
                    "title": res.get("dcterms:title", [{}])[0].get("@value", ""),
                    "diff": diff(res, updated),
                },
            )
            continue

        # ---------- write mode ------------------------------------------------
        try:
            endpoint = "media" if _rtype(res) == "media" else "items"
            client.s.patch(f"{client.base}/{endpoint}/{res['o:id']}", json=updated)
            report["updated"].append({"id": res["o:id"]})
        except Exception as exc:  # noqa: BLE001 — keep batch going
            report["errors"].append({"id": res["o:id"], "msg": str(exc)})

    return report
