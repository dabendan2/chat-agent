---
name: chat-agent
description: "Expert guide for the Chat Agent System - A modular multi-channel messaging automation platform (LINE, etc.)."
version: 4.5.0
tags: [messaging, automation, chat, line, ai-agent, media-extraction, image-gen, tdd, multimodal]
---

# Chat Agent System

A modular platform for automated communication across multiple channels (LINE, etc.), driven by a decoupled AI Engine.

## 🚀 Tool Usage (MCP & CLI)
The project-specific MCP server is named `chat_agent`.

### 🛠️ Execution via CLI (mcporter)
The `chat_agent` tools are exposed via an MCP server. Always use the `terminal` tool with `background: true` to invoke the `mcporter` CLI for conversation tasks.

- **run_task**: Starts a background monitoring engine. Supports **Automatic Pre-emption**: if a task for the same chat is already running, the new instance will `SIGKILL` the old one and take over the lock.
- **remove_task**: Safely terminates background tasks and cleans up locks. Use this instead of manual `kill` or `pkill` commands.
    ```bash
    mcporter call chat_agent.remove_task chat_name:"NAME"
    ```

**MANDATORY for `run_task`**:
1.  **Environment Variable**: You MUST `export ONE_HOUR_TIMEOUT_SET_CONFIRMED=YES`.
2.  **Timeout Flag**: You MUST append `--timeout 3600000` to the `mcporter` command.
3.  **Terminal Timeout**: The `terminal` tool call MUST also include `timeout: 3600`.

### 🛡️ Operational Protocols

- **Hard Rule #0: 社交禮儀協議 (Social Etiquette Protocol)**: 
    - **最高指導原則**：所有自動化任務必須優先遵守 `src/core/prompts/etiquette.md`。
    - **核心要求**：嚴禁「單回合多動作」（One-Turn, One-Action）、嚴禁「資訊轟炸」、必須「分階段同步」。
    - **違規處置**：若偵測到 AI 生成內容包含多個社交階段，必須強制截斷並重新重構。

- **Process Identification & Management**:
    - **Stable Naming**: Processes use `setproctitle` to set a fixed title: `chat-agent:{channel}:{chat_name}`.
    - **Reliable Cleanup**: `remove_task` uses this stable title for precision killing.
    - **Automatic Pre-emption**: `PIDLock.acquire()` will `SIGKILL` any existing agent process holding the lock for that chat before proceeding.

- **Spamming Prevention (Log-based)**:
    - The `ChatEngine` reads the physical log file (`~/.chat-agent/logs/{chat_name}.log`) as the SSOT for message counting.
    - This bypasses "memory reset" issues on restarts and "rendering delay" in the UI.

- **Identity & Safety Enforcement**:
    - **Prefix Decoupling**: Engine and Drivers handle the `[Hermes]` prefix automatically.
    - **Multi-line Fragmentation**: Every single bubble in a multi-line message is forced to have a prefix to prevent identity chain breaks.

### 🔍 History Retrieval & Verification
- **Workflow**: 
    1.  **Resolve ID**: `find_chats(keyword="NAME")`.
    2.  **Fetch Messages**: `get_messages(chat_name="NAME")`.
- **Verification Triad**: 
  1. Check `tail -n 20` of the chat log.
  2. Call `chat_agent.open_chat` for a 1600x1000+ screenshot.
  3. Use `vision_analyze` to confirm physical presence of messages and prefixes.

## 🛠 Project Structure
```text
src/
├── core/                # AI reasoning & history management
│   ├── engine.py
│   ├── run_engine.py    # Generic engine runner
│   └── prompts/         # LLM System Prompts (etiquette.md is here)
├── channels/            # Platform implementations (LINE driver)
├── utils/               # Shared tools (Locker, Config, Browser)
└── mcp_server.py        # Generalized MCP entry point
```

## 📚 Maintenance
- **Logs**: `~/.chat-agent/logs/{chat_name}.log`
- **Tests**: `./venv/bin/python -m pytest tests/`
- **Zombie Process Protection**: Test suites must include `proc.wait()` after `SIGKILL` to prevent zombie artifacts.
