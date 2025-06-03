# Omeka S Batch Editor – Streamlit GUI

Bulk-edit metadata on an Omeka S site **without writing a line of code**.  
The app lets you pick a set of items (and optionally their media), compose
“add / replace / remove” rules, preview the diff, then push it back to Omeka S
in one click.

<div align="center">
  <img src="docs/screenshot.png" width="700" alt="Streamlit GUI overview">
</div>

---

## Quick start

```bash
# 1 · clone & install
git clone https://github.com/your-org/omeka-batch-editor.git
cd omeka-batch-editor
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # streamlit, requests, …

# 2 · run the GUI
streamlit run app.py
```

Fill in your API URL, Key identity, Key credential, and start
editing.

## Repository layout & design philosophy

| File                   | Layer              | Responsibility                                                                                                                                                                                           |
| ---------------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`app.py`**           | **GUI**            | Streamlit widgets, `st.session_state`, rules table, calling the domain layer and rendering results.                                                                                                      |
| **`recipes.py`**       | **Orchestration**  | `Recipe` dataclass + `run_recipe`. Decides **which** resources to touch, applies mutation helpers, and handles dry-run vs. write-through.                                                                |
| **`mutations.py`**     | **Domain logic**   | Pure-Python helpers: <br>• `apply_ops` — apply add/replace/remove rows to a resource dict. <br>• `diff` — report what changed.                                                                           |
| **`engine.py`**        | **Infrastructure** | `OmekaClient` – thin, synchronous REST wrapper: <br>• pagination (`_get_all`) <br>• item-set/items/media listing <br>• `patch_item` <br>• `list_property_values` (fast values endpoint → fallback scan). |
| **`requirements.txt`** | —                  | Runtime dependencies (Streamlit, Requests, …).                                                                                                                                                           |
| **`pyproject.toml`**   | —                  | Developer tooling: Ruff linter/formatter, Google-style docstring rules.                                                                                                                                  |

### Layering rules

1. **`engine`** is the bottom layer and never imports anything else.
2. **`mutations`** is pure logic and depends only on the standard library.
3. **`recipes`** depends on both `engine` and `mutations` but contains no GUI code.
4. **`app`** is the single Streamlit entry point and imports everything.

This separation keeps unit tests fast (no HTTP or Streamlit required) and makes
each layer reusable for a CLI or scheduled job later.

### Development notes

- **Lint/format on save** – `pyproject.toml` enables Ruff for _all_ rules except
  the long-line check (`E501`) and enforces Google-style docstrings.
- **Docstrings** – Every public class/function has a complete Google-style
  docstring so that IDE tool-tips are helpful and `pydoclint` stays quiet.
- **Python 3.12** is required (due to `list[str]`-style type hints).

### License

MIT – see `LICENSE`.
