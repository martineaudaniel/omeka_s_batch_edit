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

from dataclasses import dataclass
from typing import Any

from engine import OmekaClient
from mutations import apply_ops, diff


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
    ops: list[dict[str, str]]  # rows from data editor
    resource_class_id: int | None = None  # filter by class (e.g. Text)
    exclude_titles: list[str] = None
    include_media: bool = False  # also touch each item's media

    # ---------- selector ---------------------------------------------------- #
    def select_items(self, client: OmekaClient) -> list[dict[str, Any]]:
        """Collect items that satisfy the recipe's set and filter criteria.

        The method performs three sequential filters:

        1. **Item-set membership** - All items belonging to every ID in
        :pyattr:`item_set_ids`.
        2. **Resource class** - If :pyattr:`resource_class_id` is not *None*,
        keep only items whose ``o:resource_class.o:id`` matches that value.
        3. **Title blacklist** - If :pyattr:`exclude_titles` is provided, drop
        items whose first ``dcterms:title`` literal (case-folded, trimmed)
        appears in the blacklist.

        Args:
            client (OmekaClient): Authenticated REST client used to fetch items
                via ``GET /api/items?item_set_id=…``.

        Returns:
            list[dict[str, Any]]: Items that survive all active filters.  The
            order is the concatenation of item-set results; no guarantee of
            uniqueness across overlapping item sets.

        Notes:
            * Title comparison is *case-insensitive* and ignores leading or
            trailing whitespace in both the item title and the blacklist
            entries.
        """
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
        """Return the resources targeted by this recipe.

        The method first delegates to :meth:`select_items` to obtain the
        **items** that match the recipe's filters (item-set IDs, resource
        class, title blacklist).  If ``self.include_media`` is *True*, it then
        fetches every medium attached to those items, de-duplicates them by
        ``o:id``, and appends the resulting **media** block to the list.

        Args:
            client (OmekaClient): Authenticated REST client used to retrieve
                items and, when requested, their media.

        Returns:
            list[dict[str, Any]]: A list of Omeka S resource dictionaries.
            The list always starts with the filtered items; media resources are
            appended afterwards and each resource appears **at most once**
            regardless of how many item sets or items reference it.

        Notes:
            * Media are fetched through the low-level
            ``GET /api/media?item_id=...`` endpoint exposed by
            :pyfunc:`OmekaClient._get_all`.
            * De-duplication is necessary because the same medium may be
            attached to multiple selected items.
        """
        resources = self.select_items(client)

        if self.include_media:
            media_block: list[dict[str, Any]] = []
            for it in resources:
                media_block += client._get_all("media", item_id=it["o:id"])
            # de-duplicate by id
            seen = set()
            media_block = [m for m in media_block if not (m["o:id"] in seen or seen.add(m["o:id"]))]
            resources += media_block

        return resources


# ---------- executor (same as before) --------------------------------------- #
def run_recipe(client: OmekaClient, recipe: Recipe, dry_run: bool = True):
    """Execute a :class:`~recipes.Recipe` against an Omeka S site.

    The function iterates over all resources selected by
    :pyfunc:`Recipe.select`, applies the recipe’s operation rows with
    :pyfunc:`engine.apply_ops`, and either **(a)** collects a preview diff
    (dry-run) or **(b)** sends a ``PATCH`` to the server.

    Args:
        client (OmekaClient): Authenticated REST client.
        recipe (Recipe): Description of the batch job—targets plus mutation
            operations.
        dry_run (bool, optional): When ``True`` (default) no data are written
            back; the function returns only a list of prospective changes.
            When ``False`` each modified resource is patched in place.

    Returns:
        dict[str, list[dict[str, Any]]]: A report with two keys:

        * ``"updated"`` - In *dry-run* mode: dictionaries containing
          ``id``, ``type``, ``title``, and ``diff`` for every would-be
          change.
          In *write* mode: dictionaries containing only ``id`` for each
          successfully patched resource.
        * ``"errors"`` - Dictionaries of the form
          ``{"id": <int>, "msg": <str>}`` for resources whose PATCH request
          raised an exception.

    Notes:
        * Media resources use the same ``/items/{id}`` endpoint in Omeka S
          ≤ 2.1, so the function detects them via ``o:type == "media"`` and
          calls :pyfunc:`OmekaClient.patch_item` accordingly.
        * Exceptions from the HTTP layer are swallowed and recorded under
          ``"errors"`` to allow the batch to continue processing the
          remaining resources.

    Example:
        >>> report = run_recipe(client, recipe, dry_run=True)
        >>> len(report["updated"]), len(report["errors"])
        (42, 0)
    """
    report = {"updated": [], "errors": []}
    for res in recipe.select(client):
        updated = apply_ops(res, recipe.ops)
        if updated == res:
            continue

        if dry_run:
            report["updated"].append(
                {
                    "id": res["o:id"],
                    "type": res["o:type"],
                    "title": res.get("dcterms:title", [{}])[0].get("@value", ""),
                    "diff": diff(res, updated),
                },
            )
            continue

        try:
            if res["o:type"] == "media":
                client.patch_item(
                    res["o:id"],
                    updated,
                )  # same endpoint works for media in Omeka S ≤ 2.1
            else:
                client.patch_item(res["o:id"], updated)
            report["updated"].append({"id": res["o:id"]})
        except Exception as exc:
            report["errors"].append({"id": res["o:id"], "msg": str(exc)})

    return report
