import pytest

from mutations import apply_ops, diff


def test_diff_only_changed_keys():
    base = {"title": "Old", "year": 1990}
    updated = {"title": "New", "year": 1990, "author": "Smith"}

    assert diff(base, updated) == {"title": "New", "author": "Smith"}
    assert diff(base, base) == {}  # identical → empty dict


@pytest.mark.parametrize(
    "ops, expected",
    [
        (
            # add
            [
                {
                    "Action": "add",
                    "Property": "dcterms:title",
                    "Value": "Hello",
                    "Language": "en",
                },
            ],
            [  # original value *plus* the newly added one
                {"@value": "Foo", "@language": None},
                {"@value": "Hello", "@language": "en"},
            ],
        ),
        (
            # replace
            [
                {
                    "Action": "replace",
                    "Property": "dcterms:title",
                    "Value": "World",
                    "Language": "fr",
                },
            ],
            [{"@value": "World", "@language": "fr"}],
        ),
        (
            # remove
            [
                {
                    "Action": "remove",
                    "Property": "dcterms:title",
                    "Value": "Foo",
                    "Language": "",
                },
            ],
            [],  # removed
        ),
    ],
)
def test_apply_ops(ops, expected):
    """Check each action type in isolation."""
    before = {"dcterms:title": [{"@value": "Foo", "@language": None}]}
    after = apply_ops(before, ops)
    assert after["dcterms:title"] == expected
