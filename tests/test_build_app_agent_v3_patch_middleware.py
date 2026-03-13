from __future__ import annotations

import json
import shlex
from types import SimpleNamespace

import pytest

from graphs.build_app_agent_v3.patch_filesystem_middleware import (
    APPLY_PATCH_TOOL_DESCRIPTION,
    PatchFilesystemMiddleware,
    PatchFilesystemState,
    _compute_line_change_counts,
    apply_update_patch,
    parse_patch_content,
)


class _FakeBackend:
    def __init__(self, files: dict[str, str | bytes]) -> None:
        self.files = {
            path: content if isinstance(content, bytes) else content.encode("utf-8")
            for path, content in files.items()
        }

    def download_files(self, paths: list[str]) -> list[SimpleNamespace]:
        responses: list[SimpleNamespace] = []
        for path in paths:
            if path in self.files:
                responses.append(
                    SimpleNamespace(
                        error=None,
                        content=self.files[path],
                    )
                )
            else:
                responses.append(SimpleNamespace(error="file_not_found", content=None))
        return responses

    async def adownload_files(self, paths: list[str]) -> list[SimpleNamespace]:
        return self.download_files(paths)

    def upload_files(
        self, file_entries: list[tuple[str, bytes]]
    ) -> list[SimpleNamespace]:
        responses: list[SimpleNamespace] = []
        for path, raw_content in file_entries:
            self.files[path] = raw_content
            responses.append(SimpleNamespace(error=None, content=None))
        return responses

    async def aupload_files(
        self, file_entries: list[tuple[str, bytes]]
    ) -> list[SimpleNamespace]:
        return self.upload_files(file_entries)

    def execute(self, cmd: str) -> SimpleNamespace:
        tokens = shlex.split(cmd)
        target_path = tokens[-1] if tokens else ""
        self.files.pop(target_path, None)
        return SimpleNamespace(exit_code=0, output="")

    async def aexecute(self, cmd: str) -> SimpleNamespace:
        return self.execute(cmd)

    def read_text(self, path: str) -> str:
        return self.files[path].decode("utf-8")


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


def test_parse_patch_rejects_duplicate_file_sections() -> None:
    patch_content = """
*** Update File: app.py
<search>
old-1
</search>
<replace>
new-1
</replace>
*** Update File: app.py
<search>
old-2
</search>
<replace>
new-2
</replace>
""".strip()

    with pytest.raises(ValueError, match="appears multiple times"):
        parse_patch_content(patch_content)


def test_apply_patch_sync_returns_error_on_unmatched_search_without_writing() -> None:
    middleware = PatchFilesystemMiddleware()
    backend = _FakeBackend({"/workspace/a.scss": "alpha\nbeta\n"})
    patch_content = """
*** Begin Patch
*** Update File: a.scss
<search>
gamma
</search>
<replace>
delta
</replace>
*** End Patch
""".strip()

    result_raw = middleware._apply_patch_sync(backend, patch_content)
    result = json.loads(result_raw)

    assert result["ok"] is False
    assert result["error_code"] == "PATCH_APPLY_ERROR"
    assert result["message"].startswith("Reason: ")
    assert " Fix: " in result["message"]
    assert "Read the latest file" in result["message"]
    assert backend.read_text("/workspace/a.scss") == "alpha\nbeta\n"


def test_apply_patch_sync_rejects_update_for_missing_file() -> None:
    middleware = PatchFilesystemMiddleware()
    backend = _FakeBackend({})
    patch_content = """
*** Begin Patch
*** Update File: missing.scss
<search>
alpha
</search>
<replace>
beta
</replace>
*** End Patch
""".strip()

    result_raw = middleware._apply_patch_sync(backend, patch_content)
    result = json.loads(result_raw)

    assert result["ok"] is False
    assert result["error_code"] == "PATCH_TARGET_MISSING"
    assert result["message"].startswith("Reason: ")
    assert " Fix: " in result["message"]
    assert "Use `Add File`" in result["message"]
    assert backend.files == {}


def test_apply_patch_sync_rejects_add_for_existing_file() -> None:
    middleware = PatchFilesystemMiddleware()
    backend = _FakeBackend({"/workspace/existing.scss": "alpha\n"})
    patch_content = """
*** Begin Patch
*** Add File: existing.scss
alpha
*** End Patch
""".strip()

    result_raw = middleware._apply_patch_sync(backend, patch_content)
    result = json.loads(result_raw)

    assert result["ok"] is False
    assert result["error_code"] == "PATCH_TARGET_EXISTS"
    assert result["message"].startswith("Reason: ")
    assert " Fix: " in result["message"]
    assert "Use `Update File`" in result["message"]
    assert backend.read_text("/workspace/existing.scss") == "alpha\n"


def test_apply_update_patch_preserves_unicode_characters() -> None:
    patch_content = """
*** Update File: notes.txt
<search>
emoji: 😀
</search>
<replace>
emoji: 😁
</replace>
""".strip()
    original = "标题: 你好\nemoji: 😀\naccent: café\n"

    file_patches = parse_patch_content(patch_content)
    updated, applied = apply_update_patch(
        original,
        file_path=file_patches[0].path,
        hunks=file_patches[0].hunks,
    )

    assert applied == 1
    assert updated == "标题: 你好\nemoji: 😁\naccent: café\n"


def test_apply_update_patch_requires_exact_trailing_newline_match() -> None:
    patch_content = """
*** Update File: notes.txt
<search>
beta

</search>
<replace>
beta-updated
</replace>
""".strip()
    original = "alpha\nbeta"

    file_patches = parse_patch_content(patch_content)
    with pytest.raises(ValueError, match="PATCH_NO_MATCH"):
        apply_update_patch(
            original,
            file_path=file_patches[0].path,
            hunks=file_patches[0].hunks,
        )


def test_apply_update_patch_preserves_crlf_and_final_newline() -> None:
    patch_content = """
*** Update File: notes.txt
<search>
beta
</search>
<replace>
beta-updated
</replace>
""".strip()
    original = "alpha\r\nbeta\r\n"

    file_patches = parse_patch_content(patch_content)
    updated, applied = apply_update_patch(
        original,
        file_path=file_patches[0].path,
        hunks=file_patches[0].hunks,
    )

    assert applied == 1
    assert updated == "alpha\r\nbeta-updated\r\n"


def test_apply_update_patch_preserves_crlf_across_multiple_hunks() -> None:
    patch_content = """
*** Update File: notes.txt
<search>
alpha
</search>
<replace>
alpha-updated
</replace>
<search>
gamma
</search>
<replace>
gamma-updated
</replace>
""".strip()
    original = "alpha\r\nbeta\r\ngamma\r\n"

    file_patches = parse_patch_content(patch_content)
    updated, applied = apply_update_patch(
        original,
        file_path=file_patches[0].path,
        hunks=file_patches[0].hunks,
    )

    assert applied == 2
    assert updated == "alpha-updated\r\nbeta\r\ngamma-updated\r\n"


def test_apply_update_patch_preserves_missing_final_newline() -> None:
    patch_content = """
*** Update File: notes.txt
<search>
beta
</search>
<replace>
beta-updated
</replace>
""".strip()
    original = "alpha\nbeta"

    file_patches = parse_patch_content(patch_content)
    updated, applied = apply_update_patch(
        original,
        file_path=file_patches[0].path,
        hunks=file_patches[0].hunks,
    )

    assert applied == 1
    assert updated == "alpha\nbeta-updated"


def test_apply_patch_sync_dry_run_does_not_write_files() -> None:
    middleware = PatchFilesystemMiddleware()
    backend = _FakeBackend({"/workspace/a.scss": "alpha\nbeta\n"})
    patch_content = """
*** Begin Patch
*** Update File: a.scss
<search>
beta
</search>
<replace>
beta-updated
</replace>
*** End Patch
""".strip()

    result_raw = middleware._apply_patch_sync(backend, patch_content, dry_run=True)
    result = json.loads(result_raw)

    assert result["ok"] is True
    assert result["details"]["phase"] == "dry_run"
    assert backend.read_text("/workspace/a.scss") == "alpha\nbeta\n"


def test_patch_filesystem_state_schema_tracks_apply_patch_stats() -> None:
    assert PatchFilesystemMiddleware.state_schema is PatchFilesystemState
    assert "apply_patch_stats_v1" in PatchFilesystemState.__annotations__


def test_apply_patch_sync_tracks_net_changes_across_multiple_calls() -> None:
    middleware = PatchFilesystemMiddleware()
    backend = _FakeBackend({"/workspace/a.scss": "alpha\nbeta\ngamma\n"})
    runtime_state: dict[str, object] = {}
    first_patch = """
*** Begin Patch
*** Update File: a.scss
<search>
beta
</search>
<replace>
beta-updated
</replace>
*** End Patch
""".strip()
    second_patch = """
*** Begin Patch
*** Update File: a.scss
<search>
gamma
</search>
<replace>
gamma-updated
delta
</replace>
*** End Patch
""".strip()

    first_result = json.loads(
        middleware._apply_patch_sync(backend, first_patch, runtime_state=runtime_state)
    )
    second_result = json.loads(
        middleware._apply_patch_sync(
            backend,
            second_patch,
            runtime_state=runtime_state,
        )
    )

    first_diff = first_result["details"]["file_diffs"][0]
    second_diff = second_result["details"]["file_diffs"][0]

    assert first_diff["file_version"] == 1
    assert first_diff["net_added"] == 1
    assert first_diff["net_removed"] == 1
    assert second_diff["file_version"] == 2
    assert second_diff["delta_added"] == 2
    assert second_diff["delta_removed"] == 1
    assert second_diff["net_added"] == 3
    assert second_diff["net_removed"] == 2


def test_apply_patch_sync_uses_minimal_line_counts_for_search_replace_stats() -> None:
    middleware = PatchFilesystemMiddleware()
    original = """
.search-panel {
  width: 100%;
  &-body {
    background: #ffffff;
    border-radius: 3px;
    &-tree {
      &-group {
        h2 {
          background: #f5f7fa;
          border-radius: 3px 3px 0px 0px;
          font-family: PingFangSC-Medium;
          font-size: var(--el-font-size-base);
          color: var(--el-text-color-primary);
          padding: 0 24px;
          font-weight: 500;
          height: 36px;
          line-height: 36px;
          margin-bottom: 16px;
        }
        &-title {
          background: #f5f7fa;
          border-radius: 3px 3px 0px 0px;
          font-family: PingFangSC-Medium;
          font-size: var(--el-font-size-base);
          color: var(--el-text-color-primary);
          padding: 0 24px;
          font-weight: 500;
          height: 36px;
          line-height: 36px;
          margin-bottom: 16px;
        }
        &-name {
          padding: 0 24px;
          font-family: PingFangSC-Regular;
          font-size: var(--el-font-size-base);
          color: var(--el-text-color-primary);
          margin-bottom: 10px;
        }
        &-tags {
          padding: 0 24px;
          &--item {
            margin-right: 8px !important;
            margin-bottom: 12px !important;
          }
        }
        &__del {
          margin-top: 8px;
          text-align: right;
        }
        span {
          cursor: pointer;
        }
      }
    }
  }
}
""".strip()
    backend = _FakeBackend({"/workspace/tag-search.scss": f"{original}\n"})
    patch_content = """
*** Begin Patch
*** Update File: tag-search.scss
<search>
.search-panel {
  width: 100%;
  &-body {
    background: #ffffff;
    border-radius: 3px;
    &-tree {
      &-group {
        h2 {
          background: #f5f7fa;
          border-radius: 3px 3px 0px 0px;
          font-family: PingFangSC-Medium;
          font-size: var(--el-font-size-base);
          color: var(--el-text-color-primary);
          padding: 0 24px;
          font-weight: 500;
          height: 36px;
          line-height: 36px;
          margin-bottom: 16px;
        }
        &-title {
          background: #f5f7fa;
          border-radius: 3px 3px 0px 0px;
          font-family: PingFangSC-Medium;
          font-size: var(--el-font-size-base);
          color: var(--el-text-color-primary);
          padding: 0 24px;
          font-weight: 500;
          height: 36px;
          line-height: 36px;
          margin-bottom: 16px;
        }
        &-name {
          padding: 0 24px;
          font-family: PingFangSC-Regular;
          font-size: var(--el-font-size-base);
          color: var(--el-text-color-primary);
          margin-bottom: 10px;
        }
        &-tags {
          padding: 0 24px;
          &--item {
            margin-right: 8px !important;
            margin-bottom: 12px !important;
          }
        }
        &__del {
          margin-top: 8px;
          text-align: right;
        }
        span {
          cursor: pointer;
        }
      }
    }
  }
}
</search>
<replace>
.search-panel {
  width: 100%;

  &-body {
    background: #ffffff;
    border-radius: 6px;
    border: 1px solid var(--el-border-color-lighter);
    padding: 20px;

    &-tree {
      &-group {
        margin-bottom: 24px;
        padding-bottom: 16px;
        border-bottom: 1px solid var(--el-border-color-lighter);

        &:last-child {
          margin-bottom: 0;
          padding-bottom: 0;
          border-bottom: none;
        }

        h2 {
          background: var(--el-fill-color-lighter);
          border-radius: 4px;
          font-family: inherit;
          font-size: var(--el-font-size-medium);
          color: var(--el-text-color-primary);
          padding: 0 16px;
          font-weight: 600;
          height: 40px;
          line-height: 40px;
          margin-bottom: 16px;
          border: 1px solid var(--el-border-color-lighter);
        }

        &-title {
          background: var(--el-fill-color-lighter);
          border-radius: 4px;
          font-family: inherit;
          font-size: var(--el-font-size-medium);
          color: var(--el-text-color-primary);
          padding: 0 16px;
          font-weight: 600;
          height: 40px;
          line-height: 40px;
          margin-bottom: 16px;
          border: 1px solid var(--el-border-color-lighter);
        }

        &-name {
          padding: 0 16px;
          font-family: inherit;
          font-size: var(--el-font-size-base);
          color: var(--el-text-color-primary);
          margin-bottom: 12px;
          font-weight: 500;
        }

        &-tags {
          padding: 0 16px;
          display: flex;
          flex-wrap: wrap;
          gap: 8px;

          &--item {
            margin: 0 !important;

            .el-tag {
              border-radius: 4px;
              border-width: 1px;
              font-weight: 500;
              transition: all 0.15s ease;

              &:hover {
                border-color: var(--el-color-primary-light-5);
                color: var(--el-color-primary);
                background-color: var(--el-fill-color-light);
              }
            }
          }
        }

        &__del {
          margin-top: 12px;
          text-align: right;
          padding: 0 16px;

          .el-button {
            border: 1px solid var(--el-border-color);
            background-color: #fff;
            color: var(--el-text-color-regular);
            font-weight: 500;
            border-radius: 4px;

            &:hover {
              border-color: var(--el-color-primary-light-5);
              color: var(--el-color-primary);
              background-color: var(--el-fill-color-light);
            }
          }
        }

        span {
          cursor: pointer;
        }
      }
    }
  }
}
</replace>
*** End Patch
""".strip()

    result = json.loads(middleware._apply_patch_sync(backend, patch_content))

    assert result["ok"] is True
    file_diff = result["details"]["file_diffs"][0]
    assert file_diff["delta_added"] == 77
    assert file_diff["delta_removed"] == 24
    assert file_diff["net_added"] == 77
    assert file_diff["net_removed"] == 24


def test_compute_line_change_counts_handles_large_repetitive_files_exactly() -> None:
    old_text = "\n".join(["a"] * 2500 + ["x"] + ["a"] * 2500)
    new_text = "\n".join(["a"] * 2500 + ["y"] + ["a"] * 2500)

    added, removed = _compute_line_change_counts(old_text, new_text)

    assert added == 1
    assert removed == 1


def test_apply_patch_sync_move_to_preserves_unicode_and_crlf() -> None:
    middleware = PatchFilesystemMiddleware()
    backend = _FakeBackend({"/workspace/a.txt": "标题\r\nemoji: 😀\r\n"})
    patch_content = """
*** Begin Patch
*** Update File: a.txt
*** Move to: b.txt
<search>
emoji: 😀
</search>
<replace>
emoji: 😁
</replace>
*** End Patch
""".strip()

    result_raw = middleware._apply_patch_sync(backend, patch_content)
    result = json.loads(result_raw)

    assert result["ok"] is True
    assert "/workspace/a.txt" not in backend.files
    assert backend.read_text("/workspace/b.txt") == "标题\r\nemoji: 😁\r\n"


def test_apply_patch_sync_rejects_non_utf8_file_without_writing() -> None:
    middleware = PatchFilesystemMiddleware()
    backend = _FakeBackend({"/workspace/binary.txt": b"\xff\xfe\x00\x00"})
    patch_content = """
*** Begin Patch
*** Update File: binary.txt
<search>
alpha
</search>
<replace>
beta
</replace>
*** End Patch
""".strip()

    result_raw = middleware._apply_patch_sync(backend, patch_content)
    result = json.loads(result_raw)

    assert result["ok"] is False
    assert result["error_code"] == "PATCH_READ_ERROR"
    assert "not valid UTF-8 text" in result["details"]["fallbacks"][0]
    assert backend.files["/workspace/binary.txt"] == b"\xff\xfe\x00\x00"


def test_apply_patch_guidance_requires_smaller_retry_after_parse_error() -> None:
    assert "same file already hit `PATCH_PARSE_ERROR`" in APPLY_PATCH_TOOL_DESCRIPTION
    assert "MUST reduce scope to a smaller local block" in APPLY_PATCH_TOOL_DESCRIPTION
    assert "SCSS/CSS/Vue style files" in APPLY_PATCH_TOOL_DESCRIPTION


def test_apply_patch_sync_parse_error_returns_guidance_without_duplicate_text() -> None:
    middleware = PatchFilesystemMiddleware()
    backend = _FakeBackend({})
    patch_content = """
*** Begin Patch
*** Update File: search-form.scss
<search>
alpha
*** End Patch
""".strip()

    result_raw = middleware._apply_patch_sync(backend, patch_content)
    result = json.loads(result_raw)

    assert result["ok"] is False
    assert result["error_code"] == "PATCH_PARSE_ERROR"
    assert result["message"].startswith("Reason: ")
    assert " Fix: " in result["message"]
    assert (
        "Re-read the file and retry with a smaller complete patch" in result["message"]
    )
    assert (
        "Ensure `</search>` is on its own line before `<replace>`" in result["message"]
    )
    assert "legacy format" not in result["message"]
    assert result["details"]["fallbacks"] == ["parse_error:missing_search_close"]


def test_apply_update_patch_rejects_mixed_line_endings() -> None:
    patch_content = """
*** Update File: notes.txt
<search>
beta
</search>
<replace>
beta-updated
</replace>
""".strip()
    original = "alpha\r\nbeta\ngamma\r\n"

    file_patches = parse_patch_content(patch_content)
    with pytest.raises(ValueError, match="PATCH_FORMAT_ERROR"):
        apply_update_patch(
            original,
            file_path=file_patches[0].path,
            hunks=file_patches[0].hunks,
        )


def test_parse_delete_file_rejects_body_lines() -> None:
    patch_content = """
*** Delete File: notes.txt
unexpected
""".strip()

    with pytest.raises(ValueError, match="must not contain body lines"):
        parse_patch_content(patch_content)
