from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import tiktoken
from deepagents.backends.protocol import FileDownloadResponse

from graphs.build_app_agent_v3.repository_context import (
    RepositoryContextPromptBuilder,
    _build_file_list_command,
    build_repository_context_prompt,
    build_repository_context_prompt_from_backend,
)


def test_build_repository_context_prompt_includes_tree_and_symbols(
    tmp_path: Path,
) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "graphs").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "class Service:\n    pass\n\n\ndef build_app():\n    return Service()\n",
        encoding="utf-8",
    )
    (tmp_path / "graphs" / "agent.ts").write_text(
        "export class Agent {}\nexport async function runAgent() {}\n",
        encoding="utf-8",
    )

    prompt = build_repository_context_prompt(tmp_path)

    assert prompt is not None
    assert "【目录结构】" in prompt
    assert "app/" in prompt
    assert "main.py" in prompt
    assert "【代码签名与结构】" in prompt
    assert "app/main.py: class Service, def build_app" in prompt
    assert "graphs/agent.ts: class Agent, async function runAgent" in prompt


def test_build_repository_context_prompt_extracts_typescript_declarations(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "types.ts").write_text(
        "export interface Config {}\n"
        "export type Mode = 'dev' | 'prod'\n"
        "export enum Status { Ready }\n",
        encoding="utf-8",
    )

    prompt = build_repository_context_prompt(tmp_path)

    assert prompt is not None
    assert "src/types.ts: interface Config, type Mode, enum Status" in prompt


def test_build_repository_context_prompt_extracts_vue_script_symbols(
    tmp_path: Path,
) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "App.vue").write_text(
        "<template><div /></template>\n"
        '<script setup lang="ts">\n'
        "interface Props {}\n"
        "defineProps<Props>()\n"
        "defineEmits<{ save: [id: string] }>()\n"
        "defineModel<string>()\n"
        "defineSlots<{ default(props: { id: string }): any }>()\n"
        "</script>\n"
        "<script>\n"
        "defineExpose({ open: () => {} })\n"
        "export async function loadApp() {}\n"
        "</script>\n",
        encoding="utf-8",
    )

    prompt = build_repository_context_prompt(tmp_path)

    assert prompt is not None
    assert (
        "frontend/App.vue: interface Props, macro defineProps, macro defineEmits, macro defineModel, macro defineSlots, macro defineExpose, async function loadApp"
        in prompt
    )


def test_repository_context_prompt_builder_caches_until_ttl_expires(
    tmp_path: Path,
) -> None:
    backend = _FakeContainerBackend()
    backend._files["src/main.ts"] = b"export function first() {}\n"
    builder = RepositoryContextPromptBuilder(
        root=tmp_path,
        cache_ttl_seconds=60.0,
        backend_factory=lambda _runtime: backend,
    )

    runtime = SimpleNamespace(state={"container_id": "cid-1"})
    first_prompt = builder(runtime)
    backend._files["src/main.ts"] = b"export function second() {}\n"
    cached_prompt = builder(runtime)

    assert first_prompt == cached_prompt
    assert first_prompt is not None
    assert "function first" in first_prompt
    assert "function second" not in cached_prompt


def test_build_file_list_command_uses_rg_glob_flags() -> None:
    command = _build_file_list_command()

    assert "rg --files --hidden" in command
    assert "-g '!.git/**'" in command
    assert "-g '!node_modules/**'" in command


def test_build_repository_context_prompt_respects_token_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for index in range(40):
        target = tmp_path / f"file_{index}.py"
        target.write_text(
            f"class Service{index}:\n    pass\n\n\ndef build_{index}():\n    return {index}\n",
            encoding="utf-8",
        )

    monkeypatch.setenv("OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_TOKENS", "120")
    prompt = build_repository_context_prompt(tmp_path)

    assert prompt is not None
    encoder = tiktoken.get_encoding("o200k_base")
    assert len(encoder.encode(prompt)) <= 120
    assert "【代码签名与结构】" in prompt
    assert "... (truncated)" in prompt


def test_build_repository_context_prompt_respects_section_budgets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "app").mkdir()
    for index in range(30):
        target = tmp_path / "app" / f"module_{index}.py"
        target.write_text(
            f"class Service{index}:\n    pass\n\n\ndef build_{index}():\n    return {index}\n",
            encoding="utf-8",
        )

    monkeypatch.setenv("OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_TOKENS", "180")
    monkeypatch.setenv(
        "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_SIGNATURE_MAX_TOKENS", "120"
    )
    monkeypatch.setenv("OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_TREE_MAX_TOKENS", "40")

    prompt = build_repository_context_prompt(tmp_path)

    assert prompt is not None
    encoder = tiktoken.get_encoding("o200k_base")
    assert len(encoder.encode(prompt)) <= 180
    assert "【代码签名与结构】" in prompt
    assert "【目录结构】" in prompt
    assert prompt.count("... (truncated)") >= 1


class _FakeContainerBackend:
    def __init__(self) -> None:
        self.id = "docker:test-container"
        self._files = {
            "src/App.vue": b'<script setup lang="ts">\ndefineProps<{ msg: string }>()\n</script>\n',
            "src/main.ts": b"export async function bootstrap() {}\n",
        }

    def execute(self, command: str):
        assert "rg --files" in command
        return SimpleNamespace(
            exit_code=0,
            output="src/App.vue\nsrc/main.ts\nREADME.md\n",
        )

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            relative = path.removeprefix("/workspace/")
            content = self._files.get(relative)
            responses.append(
                FileDownloadResponse(
                    path=path,
                    content=content,
                    error=None if content is not None else "file_not_found",
                )
            )
        return responses


def test_repository_context_prompt_builder_prefers_container_workspace() -> None:
    builder = RepositoryContextPromptBuilder(
        root=Path("/tmp/fallback"),
        cache_ttl_seconds=60.0,
        backend_factory=lambda _runtime: _FakeContainerBackend(),
    )

    prompt = builder(SimpleNamespace(state={"container_id": "cid-1"}))

    assert prompt is not None
    assert "当前容器 /workspace 的仓库快照" in prompt
    assert "workspace/" in prompt
    assert "src/App.vue: macro defineProps" in prompt
    assert "src/main.ts: async function bootstrap" in prompt


def test_build_repository_context_prompt_from_backend_logs_prompt(
    caplog,
) -> None:
    caplog.set_level("INFO")
    prompt = build_repository_context_prompt_from_backend(_FakeContainerBackend())

    assert prompt is not None
    assert "Generated repository context prompt for build_app_agent_v3" in caplog.text
    assert any(
        record.__dict__.get("repository_context_prompt", "").startswith(
            "以下是当前容器 /workspace 的仓库快照"
        )
        for record in caplog.records
    )


class _FakeNonCodeContainerBackend:
    def execute(self, command: str):
        assert "rg --files" in command
        return SimpleNamespace(
            exit_code=0,
            output="README.md\nassets/logo.png\ndocs/guide.md\n",
        )

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        raise AssertionError("download_files should not be called without source files")


def test_build_repository_context_prompt_from_backend_returns_none_without_source_files() -> (
    None
):
    prompt = build_repository_context_prompt_from_backend(
        _FakeNonCodeContainerBackend()
    )

    assert prompt is None


def test_repository_context_prompt_builder_returns_none_without_runtime() -> None:
    builder = RepositoryContextPromptBuilder(root=Path("/tmp/fallback"))

    prompt = builder()

    assert prompt is None


def test_repository_context_prompt_builder_logs_reason_without_runtime(
    caplog,
) -> None:
    caplog.set_level("INFO")
    builder = RepositoryContextPromptBuilder(root=Path("/tmp/fallback"))

    prompt = builder()

    assert prompt is None
    assert "Repository context prompt unavailable: runtime is missing" in caplog.text


def test_repository_context_prompt_builder_returns_none_when_runtime_backend_unavailable() -> (
    None
):
    builder = RepositoryContextPromptBuilder(
        root=Path("/tmp/fallback"),
        cache_ttl_seconds=60.0,
        backend_factory=lambda _runtime: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    prompt = builder(SimpleNamespace(state={"container_id": "cid-1"}))

    assert prompt is None


def test_repository_context_prompt_builder_returns_none_without_container_id() -> None:
    builder = RepositoryContextPromptBuilder(
        root=Path("/tmp/fallback"),
        cache_ttl_seconds=60.0,
        backend_factory=lambda _runtime: (_ for _ in ()).throw(
            AssertionError("backend_factory should not be called without container_id")
        ),
    )

    prompt = builder(SimpleNamespace(state={}))

    assert prompt is None
