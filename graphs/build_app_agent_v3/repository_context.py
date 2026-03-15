"""Build a compact repository snapshot prompt for model calls."""

from __future__ import annotations

import logging
import os
import re
import shlex
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import tiktoken

from backends.docker import DockerBackend

try:
    import tree_sitter_javascript
    import tree_sitter_python
    import tree_sitter_typescript
    from tree_sitter import Language, Node, Parser

    _TREE_SITTER_AVAILABLE = True
except ModuleNotFoundError:
    tree_sitter_javascript = None
    tree_sitter_python = None
    tree_sitter_typescript = None
    Language = Any
    Node = Any
    Parser = Any
    _TREE_SITTER_AVAILABLE = False

_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".vue"}
_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}
_PRIORITY_PREFIXES = (
    "app/",
    "graphs/",
    "middleware/",
    "backends/",
    "tests/",
)
_LANGUAGES: dict[str, Language] = (
    {
        ".py": Language(tree_sitter_python.language()),
        ".js": Language(tree_sitter_javascript.language()),
        ".jsx": Language(tree_sitter_javascript.language()),
        ".ts": Language(tree_sitter_typescript.language_typescript()),
        ".tsx": Language(tree_sitter_typescript.language_tsx()),
    }
    if _TREE_SITTER_AVAILABLE
    else {}
)
_PARSER_CACHE: dict[str, Parser] = {}
_TOKEN_ENCODER = tiktoken.get_encoding("o200k_base")
_VUE_MACROS = {
    "defineProps",
    "defineEmits",
    "defineExpose",
    "defineModel",
    "defineSlots",
}
_VUE_SCRIPT_RE = re.compile(
    r"<script(?P<attrs>[^>]*)>(?P<content>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_VUE_LANG_RE = re.compile(r'lang\s*=\s*["\'](?P<lang>[^"\']+)["\']', re.IGNORECASE)
logger = logging.getLogger(__name__)


def _debug_print(message: str) -> None:
    if os.getenv("OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_DEBUG", "").strip() not in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }:
        return
    print(f"[build_app_agent_v3.repository_context] {message}")


def _read_positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _read_non_negative_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        parsed = float(raw_value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _read_section_budget_env(name: str, default: int, max_tokens: int) -> int:
    value = _read_positive_int_env(name, default)
    return min(value, max_tokens)


def _count_tokens(text: str) -> int:
    return len(_TOKEN_ENCODER.encode(text))


def _default_root() -> Path:
    raw_root = os.getenv("OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_ROOT", "").strip()
    if raw_root:
        return Path(raw_root).resolve()
    return Path.cwd().resolve()


def _should_skip_dir(path: Path) -> bool:
    return path.name in _IGNORED_DIRS


def _sort_key(path: Path) -> tuple[int, int, str]:
    relative = path.as_posix()
    prefix_rank = len(_PRIORITY_PREFIXES)
    for index, prefix in enumerate(_PRIORITY_PREFIXES):
        if relative.startswith(prefix):
            prefix_rank = index
            break
    return (prefix_rank, relative.count("/"), relative)


def _iter_visible_children(path: Path) -> list[Path]:
    children = [
        child
        for child in path.iterdir()
        if not (child.is_dir() and _should_skip_dir(child))
    ]
    return sorted(children, key=lambda child: (not child.is_dir(), child.name.lower()))


def _render_tree(root: Path, *, max_depth: int, max_entries: int) -> list[str]:
    if max_entries <= 0:
        return []

    lines = [f"{root.name}/"]
    remaining = max_entries - 1

    def visit(path: Path, prefix: str, depth: int) -> None:
        nonlocal remaining
        if remaining <= 0 or depth >= max_depth:
            return

        children = _iter_visible_children(path)
        for index, child in enumerate(children):
            if remaining <= 0:
                break
            connector = "└── " if index == len(children) - 1 else "├── "
            suffix = "/" if child.is_dir() else ""
            lines.append(f"{prefix}{connector}{child.name}{suffix}")
            remaining -= 1
            if child.is_dir():
                extension = "    " if index == len(children) - 1 else "│   "
                visit(child, prefix + extension, depth + 1)

    visit(root, "", 0)
    if remaining <= 0:
        lines.append("... (truncated)")
    return lines


def _render_tree_from_paths(
    *,
    root_name: str,
    relative_paths: list[str],
    max_depth: int,
    max_entries: int,
) -> list[str]:
    if max_entries <= 0:
        return []

    tree: dict[str, dict[str, Any]] = {}
    for relative_path in relative_paths:
        stripped = relative_path.strip().strip("/")
        if not stripped:
            continue
        parts = [part for part in stripped.split("/") if part]
        node = tree
        for index, part in enumerate(parts):
            is_last = index == len(parts) - 1
            entry = node.setdefault(
                part,
                {"children": {}, "is_dir": not is_last},
            )
            if not is_last:
                entry["is_dir"] = True
                node = entry["children"]

    lines = [f"{root_name}/"]
    remaining = max_entries - 1

    def visit(children: dict[str, dict[str, Any]], prefix: str, depth: int) -> None:
        nonlocal remaining
        if remaining <= 0 or depth >= max_depth:
            return

        names = sorted(
            children,
            key=lambda name: (
                not bool(children[name]["is_dir"]),
                name.lower(),
            ),
        )
        for index, name in enumerate(names):
            if remaining <= 0:
                break
            child = children[name]
            connector = "└── " if index == len(names) - 1 else "├── "
            suffix = "/" if child["is_dir"] else ""
            lines.append(f"{prefix}{connector}{name}{suffix}")
            remaining -= 1
            if child["is_dir"]:
                extension = "    " if index == len(names) - 1 else "│   "
                visit(child["children"], prefix + extension, depth + 1)

    visit(tree, "", 0)
    if remaining <= 0:
        lines.append("... (truncated)")
    return lines


def _get_parser(suffix: str) -> Parser | None:
    if not _TREE_SITTER_AVAILABLE:
        return None
    language = _LANGUAGES.get(suffix)
    if language is None:
        return None
    parser = _PARSER_CACHE.get(suffix)
    if parser is not None:
        return parser
    parser = Parser(language)
    _PARSER_CACHE[suffix] = parser
    return parser


def _resolve_vue_script_suffix(attributes: str) -> str:
    match = _VUE_LANG_RE.search(attributes)
    if match is None:
        return ".js"
    lang = match.group("lang").strip().lower()
    if lang in {"ts", "typescript"}:
        return ".ts"
    if lang == "tsx":
        return ".tsx"
    if lang in {"jsx", "javascriptreact"}:
        return ".jsx"
    return ".js"


def _find_identifier_text(node: Node, source: bytes) -> str | None:
    identifier = node.child_by_field_name("name")
    if identifier is not None:
        text = source[identifier.start_byte : identifier.end_byte].decode("utf-8")
        if text:
            return text

    for child in node.children:
        if child.type == "identifier":
            text = source[child.start_byte : child.end_byte].decode("utf-8")
            if text:
                return text
    return None


def _describe_python_node(node: Node, source: bytes) -> str | None:
    if node.type == "class_definition":
        name = _find_identifier_text(node, source)
        return f"class {name}" if name else None
    if node.type == "function_definition":
        name = _find_identifier_text(node, source)
        if not name:
            return None
        is_async = any(child.type == "async" for child in node.children)
        return f"async def {name}" if is_async else f"def {name}"
    if node.type == "expression_statement":
        for child in node.children:
            if child.type != "assignment":
                continue
            target = child.child_by_field_name("left")
            if target is None:
                continue
            name = source[target.start_byte : target.end_byte].decode("utf-8")
            if name.isupper():
                return f"const {name}"
    return None


def _unwrap_export(node: Node) -> Node:
    if node.type != "export_statement":
        return node
    for child in node.children:
        if child.type != "export":
            return child
    return node


def _describe_js_like_node(node: Node, source: bytes) -> str | None:
    target = _unwrap_export(node)
    if target.type == "expression_statement":
        for child in target.children:
            if child.type != "call_expression":
                continue
            macro = _describe_vue_macro_call(child, source)
            if macro:
                return macro
    if target.type in {"class_declaration", "interface_declaration"}:
        name = _find_identifier_text(target, source)
        if not name:
            return None
        label = "class" if target.type == "class_declaration" else "interface"
        return f"{label} {name}"
    if target.type == "function_declaration":
        name = _find_identifier_text(target, source)
        if not name:
            return None
        is_async = any(child.type == "async" for child in target.children)
        return f"async function {name}" if is_async else f"function {name}"
    if target.type == "type_alias_declaration":
        name = _find_identifier_text(target, source)
        return f"type {name}" if name else None
    if target.type == "enum_declaration":
        name = _find_identifier_text(target, source)
        return f"enum {name}" if name else None
    if target.type in {"lexical_declaration", "variable_declaration"}:
        for child in target.children:
            if child.type != "variable_declarator":
                continue
            initializer = child.child_by_field_name("value")
            if initializer is not None and initializer.type == "call_expression":
                macro = _describe_vue_macro_call(initializer, source)
                if macro:
                    return macro
            name = _find_identifier_text(child, source)
            if name:
                return f"const {name}"
    return None


def _describe_vue_macro_call(node: Node, source: bytes) -> str | None:
    function_node = node.child_by_field_name("function")
    if function_node is None:
        return None
    name = source[function_node.start_byte : function_node.end_byte].decode("utf-8")
    if name not in _VUE_MACROS:
        return None
    return f"macro {name}"


def _extract_symbols_from_source(
    *,
    source: bytes,
    suffix: str,
    max_symbols: int,
) -> list[str]:
    parser = _get_parser(suffix)
    if parser is None:
        return []

    try:
        tree = parser.parse(source)
    except Exception:
        return []

    symbols: list[str] = []
    seen: set[str] = set()
    for child in tree.root_node.children:
        symbol = (
            _describe_python_node(child, source)
            if suffix == ".py"
            else _describe_js_like_node(child, source)
        )
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
        if len(symbols) >= max_symbols:
            break
    return symbols


def _extract_vue_symbols(source: bytes, *, max_symbols: int) -> list[str]:
    text = source.decode("utf-8", errors="ignore")
    symbols: list[str] = []
    seen: set[str] = set()

    for match in _VUE_SCRIPT_RE.finditer(text):
        script_suffix = _resolve_vue_script_suffix(match.group("attrs"))
        script_content = match.group("content").strip()
        if not script_content:
            continue
        script_symbols = _extract_symbols_from_source(
            source=script_content.encode("utf-8"),
            suffix=script_suffix,
            max_symbols=max_symbols,
        )
        for symbol in script_symbols:
            if symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
            if len(symbols) >= max_symbols:
                return symbols
    return symbols


def _extract_symbols(path: Path, *, max_symbols: int) -> list[str]:
    suffix = path.suffix.lower()
    try:
        source = path.read_bytes()
    except OSError:
        return []
    if suffix == ".vue":
        return _extract_vue_symbols(source, max_symbols=max_symbols)
    return _extract_symbols_from_source(
        source=source,
        suffix=suffix,
        max_symbols=max_symbols,
    )


def _extract_symbols_from_bytes(
    *,
    path: str,
    content: bytes,
    max_symbols: int,
) -> list[str]:
    suffix = Path(path).suffix.lower()
    if suffix == ".vue":
        return _extract_vue_symbols(content, max_symbols=max_symbols)
    return _extract_symbols_from_source(
        source=content,
        suffix=suffix,
        max_symbols=max_symbols,
    )


def _build_file_list_command() -> str:
    ignore_globs = " ".join(
        f"-g {shlex.quote(f'!{name}/**')}" for name in sorted(_IGNORED_DIRS)
    )
    return f"cd /workspace && rg --files --hidden {ignore_globs}"


def _list_workspace_files(backend: DockerBackend) -> list[str]:
    command = _build_file_list_command()
    _debug_print(f"listing workspace files with command: {command}")
    try:
        result = backend.execute(command)
    except Exception as exc:
        _debug_print(f"workspace file list execute raised: {type(exc).__name__}: {exc}")
        raise
    _debug_print(f"workspace file list exit_code={result.exit_code}")
    if result.exit_code != 0:
        preview = result.output[:1000] if isinstance(result.output, str) else ""
        _debug_print(f"workspace file list failed output={preview!r}")
        return []
    files = [line.strip() for line in result.output.splitlines() if line.strip()]
    _debug_print(f"workspace file list count={len(files)} sample={files[:10]}")
    return files


def _collect_signature_lines_from_workspace(
    *,
    backend: DockerBackend,
    relative_paths: list[str],
    max_files: int,
    max_symbols_per_file: int,
) -> list[str]:
    candidates = [
        path for path in relative_paths if Path(path).suffix.lower() in _SOURCE_SUFFIXES
    ]
    selected = sorted(candidates, key=lambda path: _sort_key(Path(path)))[:max_files]
    _debug_print(
        "collecting workspace signatures "
        f"candidates={len(candidates)} selected={len(selected)} sample={selected[:10]}"
    )
    responses = backend.download_files([f"/workspace/{path}" for path in selected])

    lines: list[str] = []
    for response, relative_path in zip(responses, selected, strict=False):
        if response.error is not None or response.content is None:
            _debug_print(
                f"skipping signature extraction for {relative_path}: error={response.error}"
            )
            continue
        symbols = _extract_symbols_from_bytes(
            path=relative_path,
            content=response.content,
            max_symbols=max_symbols_per_file,
        )
        if not symbols:
            _debug_print(f"no symbols extracted for {relative_path}")
            continue
        lines.append(f"{relative_path}: {', '.join(symbols)}")
    _debug_print(f"workspace signature line count={len(lines)}")
    return lines


def _collect_signature_lines(
    root: Path,
    *,
    max_files: int,
    max_symbols_per_file: int,
) -> list[str]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        if any(_should_skip_dir(parent) for parent in path.parents if parent != root):
            continue
        candidates.append(path.relative_to(root))

    lines: list[str] = []
    for relative_path in sorted(candidates, key=_sort_key)[:max_files]:
        symbols = _extract_symbols(
            root / relative_path, max_symbols=max_symbols_per_file
        )
        if not symbols:
            continue
        lines.append(f"{relative_path.as_posix()}: {', '.join(symbols)}")
    return lines


def _render_section(title: str, lines: list[str]) -> str:
    return f"{title}\n```text\n" + "\n".join(lines) + "\n```"


def _fit_section_to_budget(
    *,
    title: str,
    lines: list[str],
    remaining_budget: int,
) -> str | None:
    if remaining_budget <= 0 or not lines:
        return None

    full_section = _render_section(title, lines)
    if _count_tokens(full_section) <= remaining_budget:
        return full_section

    truncation_line = "... (truncated)"
    left = 0
    right = len(lines)
    best: str | None = None

    while left <= right:
        middle = (left + right) // 2
        candidate_lines = lines[:middle]
        if middle < len(lines):
            candidate_lines = [*candidate_lines, truncation_line]
        candidate = _render_section(title, candidate_lines)
        if _count_tokens(candidate) <= remaining_budget:
            best = candidate
            left = middle + 1
        else:
            right = middle - 1
    return best


def build_repository_context_prompt(root: Path | None = None) -> str | None:
    """Return a compact repository snapshot for appending to the system prompt."""
    if not _TREE_SITTER_AVAILABLE:
        _debug_print("local repository context disabled: tree-sitter unavailable")
        return None
    root_path = (root or _default_root()).resolve()
    if not root_path.exists() or not root_path.is_dir():
        _debug_print(f"local repository context root invalid: {root_path}")
        return None
    max_tokens = _read_positive_int_env(
        "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_TOKENS", 3000
    )
    signature_budget = _read_section_budget_env(
        "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_SIGNATURE_MAX_TOKENS",
        2000,
        max_tokens,
    )
    tree_budget = _read_section_budget_env(
        "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_TREE_MAX_TOKENS",
        max(1, max_tokens - signature_budget),
        max_tokens,
    )

    tree_lines = _render_tree(
        root_path,
        max_depth=_read_positive_int_env(
            "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_DEPTH", 4
        ),
        max_entries=_read_positive_int_env(
            "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_TREE_ENTRIES", 160
        ),
    )
    if not tree_lines:
        _debug_print("local repository context tree is empty")
        return None

    signature_lines = _collect_signature_lines(
        root_path,
        max_files=_read_positive_int_env(
            "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_SIGNATURE_FILES", 40
        ),
        max_symbols_per_file=_read_positive_int_env(
            "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_SYMBOLS_PER_FILE", 8
        ),
    )

    sections = [
        "以下是当前工作区的仓库快照，用于帮助你在调用工具前更快定位相关代码。若快照与实时读取结果冲突，以你刚读取到的文件内容为准。",
    ]
    prompt = "\n\n".join(sections)
    base_tokens = _count_tokens(prompt)
    if base_tokens >= max_tokens:
        return prompt
    separator_tokens = _count_tokens("\n\n")

    if signature_lines:
        signature_section = _fit_section_to_budget(
            title="【代码签名与结构】",
            lines=signature_lines,
            remaining_budget=min(
                signature_budget,
                max_tokens - base_tokens - separator_tokens,
            ),
        )
        if signature_section:
            sections.append(signature_section)

    current_tokens = _count_tokens("\n\n".join(sections))
    tree_remaining_budget = min(
        tree_budget,
        max_tokens - current_tokens - separator_tokens,
    )
    if tree_remaining_budget > 0:
        tree_section = _fit_section_to_budget(
            title="【目录结构】",
            lines=tree_lines,
            remaining_budget=tree_remaining_budget,
        )
        if tree_section:
            sections.append(tree_section)

    prompt = "\n\n".join(sections)
    if _count_tokens(prompt) > max_tokens:
        _debug_print("local repository context exceeded total token budget")
        return None
    _debug_print(
        "local repository context built "
        f"tokens={_count_tokens(prompt)} signatures={len(signature_lines)} tree_lines={len(tree_lines)}"
    )
    logger.info(
        "Generated repository context prompt for build_app_agent_v3",
        extra={"repository_context_prompt": prompt},
    )
    return prompt


def build_repository_context_prompt_from_backend(
    backend: DockerBackend,
) -> str | None:
    if not _TREE_SITTER_AVAILABLE:
        _debug_print("backend repository context disabled: tree-sitter unavailable")
        return None
    _debug_print("building repository context from Docker backend")
    relative_paths = _list_workspace_files(backend)

    if not relative_paths:
        _debug_print("backend repository context aborted: workspace file list is empty")
        return None

    source_paths = [
        path for path in relative_paths if Path(path).suffix.lower() in _SOURCE_SUFFIXES
    ]
    if not source_paths:
        _debug_print(
            "backend repository context aborted: workspace contains no supported source files"
        )
        return None

    max_tokens = _read_positive_int_env(
        "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_TOKENS", 3000
    )
    signature_budget = _read_section_budget_env(
        "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_SIGNATURE_MAX_TOKENS",
        2000,
        max_tokens,
    )
    tree_budget = _read_section_budget_env(
        "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_TREE_MAX_TOKENS",
        max(1, max_tokens - signature_budget),
        max_tokens,
    )
    tree_lines = _render_tree_from_paths(
        root_name="workspace",
        relative_paths=relative_paths,
        max_depth=_read_positive_int_env(
            "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_DEPTH", 4
        ),
        max_entries=_read_positive_int_env(
            "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_TREE_ENTRIES", 160
        ),
    )
    if not tree_lines:
        _debug_print("backend repository context aborted: rendered tree is empty")
        return None
    signature_lines = _collect_signature_lines_from_workspace(
        backend=backend,
        relative_paths=source_paths,
        max_files=_read_positive_int_env(
            "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_SIGNATURE_FILES", 40
        ),
        max_symbols_per_file=_read_positive_int_env(
            "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_SYMBOLS_PER_FILE", 8
        ),
    )

    sections = [
        "以下是当前容器 /workspace 的仓库快照，用于帮助你在调用工具前更快定位相关代码。若快照与实时读取结果冲突，以你刚读取到的文件内容为准。",
    ]
    prompt = "\n\n".join(sections)
    base_tokens = _count_tokens(prompt)
    if base_tokens >= max_tokens:
        _debug_print(
            f"backend repository context base prompt already exceeds budget tokens={base_tokens}"
        )
        return prompt
    separator_tokens = _count_tokens("\n\n")

    if signature_lines:
        signature_section = _fit_section_to_budget(
            title="【代码签名与结构】",
            lines=signature_lines,
            remaining_budget=min(
                signature_budget,
                max_tokens - base_tokens - separator_tokens,
            ),
        )
        if signature_section:
            sections.append(signature_section)

    current_tokens = _count_tokens("\n\n".join(sections))
    tree_remaining_budget = min(
        tree_budget,
        max_tokens - current_tokens - separator_tokens,
    )
    if tree_remaining_budget > 0:
        tree_section = _fit_section_to_budget(
            title="【目录结构】",
            lines=tree_lines,
            remaining_budget=tree_remaining_budget,
        )
        if tree_section:
            sections.append(tree_section)

    prompt = "\n\n".join(sections)
    if _count_tokens(prompt) > max_tokens:
        _debug_print("backend repository context exceeded total token budget")
        return None
    _debug_print(
        "backend repository context built "
        f"tokens={_count_tokens(prompt)} signatures={len(signature_lines)} tree_lines={len(tree_lines)}"
    )
    logger.info(
        "Generated repository context prompt for build_app_agent_v3",
        extra={"repository_context_prompt": prompt},
    )
    return prompt


class RepositoryContextPromptBuilder:
    """Build and cache repository snapshot prompts for repeated model calls."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        cache_ttl_seconds: float | None = None,
        backend_factory: Callable[[Any], DockerBackend] | None = None,
    ) -> None:
        self.root = (root or _default_root()).resolve()
        self.backend_factory = backend_factory or (
            lambda runtime: DockerBackend(runtime)
        )
        self.cache_ttl_seconds = (
            _read_non_negative_float_env(
                "OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_CACHE_TTL_SECONDS",
                5.0,
            )
            if cache_ttl_seconds is None
            else max(0.0, cache_ttl_seconds)
        )
        self._cached_prompts: dict[str, tuple[float, str | None]] = {}

    @staticmethod
    def _resolve_cache_key(runtime: Any) -> str | None:
        state = getattr(runtime, "state", None)
        if not isinstance(state, dict):
            return None
        container_id = state.get("container_id")
        if isinstance(container_id, str) and container_id.strip():
            return f"docker:{container_id.strip()}"
        return None

    def __call__(self, runtime: Any = None) -> str | None:
        if runtime is None:
            _debug_print("builder returning None: runtime is missing")
            logger.info(
                "Repository context prompt unavailable: runtime is missing",
            )
            return None

        cache_key = self._resolve_cache_key(runtime)
        if cache_key is None:
            _debug_print(
                "builder returning None: runtime.state.container_id is missing"
            )
            logger.info(
                "Repository context prompt unavailable: container_id is missing from runtime state",
            )
            return None

        try:
            backend = self.backend_factory(runtime)
        except Exception:
            _debug_print("builder returning None: backend_factory raised")
            logger.exception(
                "Repository context prompt unavailable: failed to initialize Docker backend",
            )
            return None

        def prompt_builder() -> str | None:
            return build_repository_context_prompt_from_backend(backend)

        now = time.monotonic()
        cached = self._cached_prompts.get(cache_key)
        if cached is not None and now - cached[0] <= self.cache_ttl_seconds:
            _debug_print(
                f"builder cache hit cache_key={cache_key} prompt_available={cached[1] is not None}"
            )
            logger.info(
                "Repository context prompt cache hit",
                extra={
                    "repository_context_cache_key": cache_key,
                    "repository_context_prompt_available": cached[1] is not None,
                },
            )
            return cached[1]

        try:
            _debug_print(f"builder cache miss cache_key={cache_key}, building prompt")
            prompt = prompt_builder()
        except Exception:
            _debug_print(
                f"builder returning None: prompt builder raised cache_key={cache_key}"
            )
            logger.exception(
                "Repository context prompt unavailable: failed while building prompt",
                extra={"repository_context_cache_key": cache_key},
            )
            prompt = None
        if prompt is None:
            _debug_print(f"builder built empty prompt cache_key={cache_key}")
            logger.info(
                "Repository context prompt unavailable: prompt builder returned empty result",
                extra={"repository_context_cache_key": cache_key},
            )
        else:
            _debug_print(
                f"builder built prompt cache_key={cache_key} tokens={_count_tokens(prompt)}"
            )
        self._cached_prompts[cache_key] = (now, prompt)
        return prompt
