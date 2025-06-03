"""Pure-Python helpers for calculating and applying metadata changes.

`mutations.py` keeps **all logic that manipulates Omeka S resource
dictionaries entirely in memory**—no HTTP, no Streamlit.  It therefore
sits neatly between:

* :pymod:`engine` - low-level REST client (fetch / PATCH).
* :pymod:`recipes` - orchestration layer that decides *which* resources
  to mutate.

Provided functions
------------------
diff(a, b)
    Return the subset of key-value pairs whose value differs between two
    dictionaries—useful for a concise preview before pushing an update.
apply_ops(resource, ops)
    Execute GUI-style *add / replace / remove* rows against a resource
    dict and return the mutated copy.
"""

import copy
from typing import Any


def diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Return only the key–value pairs that changed from *a* to *b*.

    Args:
        a (dict[str, Any]): The *baseline* dictionary.
        b (dict[str, Any]): The *updated* dictionary to compare against *a*.

    Returns:
        dict[str, Any]: A dictionary containing only the keys whose value in
        **b** differs from the value (or absence) in **a**.  The mapping is
        empty if the two inputs are identical.
    """
    return {k: b[k] for k in b if a.get(k) != b[k]}


def apply_ops(resource: dict[str, Any], ops: list[dict[str, str]]) -> dict[str, Any]:
    """Apply *add / replace / remove* operations to an Omeka S resource.

    Each operation row is a four-field mapping produced by the GUI:

    * ``"Action"``  – One of ``"add"``, ``"replace"``, or ``"remove"``
      (case-insensitive).
    * ``"Property"`` – Full RDF term whose value list is to be edited
      (e.g. ``"dcterms:title"``).
    * ``"Value"``    – Literal string to insert, overwrite with, or match
      for removal.  May be an empty string.
    * ``"Language"`` – ISO 639-1 language code associated with the value
      (``""`` or missing → no language).

    The function works on a deep copy of *resource* so the original object
    is left untouched.

    Args:
        resource (dict[str, Any]): Omeka S resource JSON as returned by the
            REST API.
        ops (list[dict[str, str]]): Sequence of operation rows, each with the
            keys described above.

    Returns:
        dict[str, Any]: A new resource dictionary reflecting the requested
        additions, replacements, or removals.

    Example:
        >>> apply_ops(
        ...     {"dcterms:title": [{"@value": "Old", "@language": "en"}]},
        ...     [{"Action": "replace",
        ...       "Property": "dcterms:title",
        ...       "Value": "New",
        ...       "Language": "en"}]
        ... )
        {'dcterms:title': [{'@value': 'New', '@language': 'en'}]}
    """
    new_res = copy.deepcopy(resource)
    for op in ops:
        term = op["Property"]
        action = op["Action"].lower()
        lang = op.get("Language") or None
        value = op.get("Value") or ""

        if action == "add":
            new_res.setdefault(term, []).append({"@value": value, "@language": lang})
        elif action == "replace":
            new_res[term] = [{"@value": value, "@language": lang}]
        elif action == "remove":
            new_res[term] = [v for v in new_res.get(term, []) if v.get("@value") != value or (lang and v.get("@language") != lang)]
    return new_res
