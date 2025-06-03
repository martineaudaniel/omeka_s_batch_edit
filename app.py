"""Omeka S Batch Editor — Streamlit GUI.

Interactive front-end that lets curators **add, replace, or remove metadata in
bulk** on items (and optionally their media) stored in an Omeka S site.  The
app builds a :class:`engine.Recipe` from the user’s input, shows a dry-run
preview, and finally sends the patch requests through
:class:`engine.OmekaClient`.

Transient UI state (authenticated client, cached look-ups, current operation
table, …) lives in ``st.session_state`` so that Streamlit’s reruns do not wipe
user input.

Run from the project root:

```bash
streamlit run app.py
"""

import streamlit as st

from engine import OmekaClient
from recipes import Recipe, run_recipe

st.set_page_config(page_title="Omeka S Batch Editor", layout="wide")

# ── sidebar · credentials ────────────────────────────────────────────────────
st.sidebar.title("Connect to Omeka S")
api_url = st.sidebar.text_input("API URL", value="https://encyclo-technes.org/en/base/api")
key_id = st.sidebar.text_input("Key identity")
key_cred = st.sidebar.text_input("Key credential", type="password")
if st.sidebar.button("Connect"):
    st.session_state.client = OmekaClient(api_url, key_id, key_cred)

client: OmekaClient = st.session_state.get("client")
if not client:
    st.stop()

# ── step 1 · item sets & filters ─────────────────────────────────────────────
st.header("Step 1 · Select targets")

itemsets = {s["o:id"]: s.get("dcterms:title", [{}])[0].get("@value", "Untitled") for s in client.list_item_sets()}

chosen_sets = st.multiselect(
    "Item sets:",
    options=list(itemsets),
    format_func=lambda i: f"{i} – {itemsets[i]}",
)
if not chosen_sets:
    st.warning("Pick at least one item set.")
    st.stop()

with st.expander("Filters (optional)"):
    # pull resource classes once
    if "classes" not in st.session_state:
        st.session_state.classes = client._get_all("resource_classes")
    class_map = {c["o:id"]: c["o:local_name"] for c in st.session_state.classes}

    class_id = st.selectbox(
        "Keep only items of class …",
        options=[None, *list(class_map)],
        format_func=lambda i: "— any —" if i is None else f"{i} – {class_map[i]}",
        index=0,
    )

    exclude_titles = st.text_area(
        "Exclude titles (one per line, case-insensitive)",
        placeholder="Introduction\nSommaire",
    ).splitlines()

    include_media = st.checkbox(
        "Also apply to every medium attached to the kept items",
        value=False,
    )

# ── step 2 · build / edit operations ─────────────────────────────────────────
st.header("Step 2 · Describe the changes")

# Persist the rule list across reruns
OPS_KEY = "ops"
if OPS_KEY not in st.session_state:
    st.session_state[OPS_KEY] = []

###############################################################################
# Helper widgets – reactive, no st.form
###############################################################################

# --- cache properties and value lists ---------------------------------------
if "property_terms" not in st.session_state:
    props_json = client._get_all("properties")
    st.session_state.property_terms = sorted(p["o:term"] for p in props_json)

st.session_state.setdefault("value_cache", {})


def cached_values(term: str) -> list[str]:
    """Return distinct values for *term*, cached per Streamlit session."""
    cache = st.session_state.value_cache
    if term not in cache:
        cache[term] = client.list_property_values(term)  # new helper in engine
    return cache[term]


# --- interactive widgets -----------------------------------------------------
c1, c2, c3, c4 = st.columns([1.2, 3, 3, 1.2])

# 1 · Action
new_action = c1.selectbox("Action", ["add", "replace", "remove"], key="new_action")

# 2 · Property + optional custom term
term_options = st.session_state.property_terms + ["<custom term…>"]
term_choice = c2.selectbox(
    "Property (type to search)",
    options=term_options,
    key="new_property_select",
)

if term_choice == "<custom term…>":
    new_property = c2.text_input("Custom property term", key="new_property_custom").strip()
    value_options = []
else:
    new_property = term_choice
    value_options = cached_values(new_property)

# 3 · Value (choices depend on property); always reactive
if value_options:
    value_choice = c3.selectbox(
        "Value (choose or start typing)",
        options=value_options + ["<custom value…>"],
        key=f"value_choice_{new_property}",
    )
    if value_choice == "<custom value…>":
        new_value = c3.text_input("Custom value", key=f"value_custom_{new_property}")
    else:
        new_value = value_choice
else:
    new_value = c3.text_input("Value", key="value_custom_free")

# 4 · Language
new_lang = c4.text_input("Lang (fr / en …)", key="new_lang")

# --- add-row button ----------------------------------------------------------
if st.button("➕ Add row"):
    if not new_property:
        st.warning("Property cannot be empty.")
    else:
        st.session_state[OPS_KEY].append(
            {
                "Action": new_action,
                "Property": new_property,
                "Value": new_value,
                "Language": new_lang,
            },
        )
        st.success("Row added – see list below 👇", icon="✅")

###############################################################################
# Read-only list / delete rows
###############################################################################
ops_list = st.session_state[OPS_KEY]

if ops_list:
    st.markdown("### Current rule set")
    md_table = "| # | Action | Property | Value | Lang |\n|---|---|---|---|---|\n"
    for idx, row in enumerate(ops_list, 1):
        md_table += f"| {idx} | {row['Action']} | {row['Property']} | {row['Value']} | {row['Language']} |\n"
    st.markdown(md_table)

    del_idx = st.number_input(
        "Row # to delete (blank = nothing)",
        min_value=1,
        max_value=len(ops_list),
        step=1,
        format="%d",
    )
    if st.button("🗑️  Delete row"):
        if 1 <= del_idx <= len(ops_list):
            removed = st.session_state[OPS_KEY].pop(int(del_idx) - 1)
            st.info(f"Deleted row {del_idx}: {removed}")
            st.experimental_rerun()
else:
    st.info("No rules yet – add some above.")

# Export for use in Step 3
ops = st.session_state[OPS_KEY].copy()

# ── step 3 · preview / commit ───────────────────────────────────────────────
st.header("Step 3 · Preview then apply")
dry_run = st.checkbox("Dry-run (preview only)", value=True)

if st.button("Run"):
    recipe = Recipe(
        item_set_ids=chosen_sets,
        resource_types=["items"],  # media added later if include_media True
        ops=ops,
        resource_class_id=class_id,
        exclude_titles=[t for t in exclude_titles if t.strip()],
        include_media=include_media,
    )
    report = run_recipe(client, recipe, dry_run=dry_run)

    st.subheader("Result")
    st.json(report, expanded=False)

    if not dry_run:
        if report["errors"]:
            st.error(f"Finished with {len(report['errors'])} error(s).")
        else:
            st.success(f"Updated {len(report['updated'])} resource(s) successfully!")
