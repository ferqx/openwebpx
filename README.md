<p align="center">
  <img src="docs/images/banner.png" alt="OpenWebPX banner" />
</p>

<h1 align="center">OpenWebPX</h1>

<p align="center">
  <strong>Self-hosted Code Agent Infrastructure with Cloud Sandboxing.</strong>
</p>

<p align="center">
  <a href="https://github.com/ferqx/openwebpx/stargazers"><img src="https://img.shields.io/github/stars/ferqx/openwebpx" alt="GitHub stars"></a>
  <a href="https://github.com/ferqx/openwebpx/blob/main/LICENSE"><img src="https://img.shields.io/github/license/ferqx/openwebpx" alt="License"></a>
  <a href="https://github.com/ferqx/openwebpx/issues"><img src="https://img.shields.io/github/issues/ferqx/openwebpx" alt="Issues"></a>
</p>

---

**OpenWebPX** is a specialized, production-ready infrastructure for building and deploying **AI Code Agents**. It provides enterprise-grade **Cloud Sandboxing** capabilities, allowing agents to safely execute code, manage repositories, and perform complex development tasks in isolated, thread-bound environments.

**Dual Compatibility:** [LangGraph CLI](https://github.com/langchain-ai/langgraph-cli) | [Agent Chat UI](https://github.com/langchain-ai/agent-chat-ui) | [LangGraph Studio](https://github.com/langchain-ai/langgraph-studio) | [Aegra Ecosystem](https://github.com/ibbybuilds/aegra)

## 🚀 Quick Start

**Prerequisites:** Docker, Python 3.12+, `uv` (recommended)

```bash
git clone https://github.com/ibbybuilds/aegra.git
cd aegra
cp .env.example .env
# Set your OPENAI_API_KEY in .env

docker compose up
```

Access the API docs at [http://localhost:8000/docs](http://localhost:8000/docs).

## 🔥 Core Philosophy: The Code Agent Sandbox

OpenWebPX transforms the standard LangGraph server into a powerful development environment for AI.

| Capability | Enterprise Cloud Sandbox | Description |
|:--|:--|:--|
| **Execution** | **Thread-Bound Containers** | Each agent thread is automatically mapped to a dedicated Docker sandbox. |
| **Development** | **Native SCM Integration** | Full support for GitHub/GitLab to manage codebases and PRs/MRs. |
| **Safety** | **Policy-Guarded Access** | Granular control over file system operations and shell command execution. |
| **Persistence** | **Full Context Recovery** | Agents can resume complex development tasks with preserved environment state. |

## ✨ Features

- **Protocol Compliant**: Drop-in replacement for LangGraph Platform, compatible with all standard SDKs.
- **Isolated Sandboxing**: Secure, on-demand Docker containers for safe AI code execution.
- **Enterprise-Grade Auth**: Pluggable system supporting **LDAP**, OAuth2, JWT, and local Database.
- **Native SCM Power**: Built-in integration for GitHub and GitLab to automate repository management.
- **AI Code Review**: Webhook-triggered auditing of commits and pull requests via asynchronous agents.
- **Observability**: First-class integration with **Langfuse** for tracing and evaluation.

## 📚 Documentation & Logs

- **[Engineering Guide (INDEX.md)](project_docs/INDEX.md)**: Architectural deep-dives and SOPs.
- **[Development Changelogs](changelogs/)**: Chronological records of project evolution.
  - **[Latest Update (2026-03-20)](changelogs/2026-03-20.md)**: Engineering documentation system launch.

---

## 📄 License

Apache 2.0 - see [LICENSE](LICENSE).

<p align="center">
  <strong>⭐ Star OpenWebPX if it helps you build AI Code Agents on your own terms ⭐</strong>
</p>
