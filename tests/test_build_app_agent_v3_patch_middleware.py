from __future__ import annotations

import pytest

from graphs.build_app_agent_v3.patch_filesystem_middleware import (
    apply_update_patch,
    parse_patch_content,
)


def test_parse_and_apply_patch_with_xml_blocks() -> None:
    patch_content = """
*** Update File: style.css
<search>
.dark-theme body {
  color: #ffffff;
}
</search>
<replace>
.dark-theme body {
  color: #e0e0e0;
}
</replace>
""".strip()
    original = """
.dark-theme body {
  color: #ffffff;
}
""".strip()

    file_patches = parse_patch_content(patch_content)

    assert len(file_patches) == 1
    assert file_patches[0].action == "Update"
    assert len(file_patches[0].hunks) == 1

    updated, applied = apply_update_patch(
        original,
        file_path=file_patches[0].path,
        hunks=file_patches[0].hunks,
    )

    assert applied == 1
    assert "color: #e0e0e0;" in updated
    assert "color: #ffffff;" not in updated


def test_parse_and_apply_patch_supports_legacy_markers() -> None:
    patch_content = """
*** Update File: number.txt
<<<<<<< SEARCH
1
=======
2
>>>>>>> REPLACE
""".strip()
    original = "1\n"

    file_patches = parse_patch_content(patch_content)
    updated, applied = apply_update_patch(
        original,
        file_path=file_patches[0].path,
        hunks=file_patches[0].hunks,
    )

    assert applied == 1
    assert updated == "2\n"


def test_parse_patch_tolerates_replace_without_search_close() -> None:
    patch_content = """
*** Update File: app.py
<search>
old
<replace>
new
</replace>
""".strip()

    file_patches = parse_patch_content(patch_content)
    assert len(file_patches) == 1
    assert len(file_patches[0].hunks) == 1
    assert file_patches[0].hunks[0].search_text == "old"
    assert file_patches[0].hunks[0].replace_text == "new"


def test_parse_patch_rejects_replace_without_search_block() -> None:
    patch_content = """
*** Update File: app.py
<replace>
new
</replace>
""".strip()

    with pytest.raises(
        ValueError, match="Found <replace> without a preceding </search>"
    ):
        parse_patch_content(patch_content)


def test_parse_patch_requires_at_least_one_xml_block() -> None:
    patch_content = """
*** Update File: app.py
def unchanged():
    return True
""".strip()

    with pytest.raises(
        ValueError, match="Must contain at least one <search>...</search>"
    ):
        parse_patch_content(patch_content)


def test_apply_update_patch_rejects_ambiguous_match() -> None:
    patch_content = """
*** Update File: app.py
<search>
return value
</search>
<replace>
return value + 1
</replace>
""".strip()
    original = """
def first(value):
    return value

def second(value):
    return value
""".strip()

    file_patches = parse_patch_content(patch_content)
    with pytest.raises(ValueError, match="PATCH_AMBIGUOUS_MATCH"):
        apply_update_patch(
            original,
            file_path=file_patches[0].path,
            hunks=file_patches[0].hunks,
        )
