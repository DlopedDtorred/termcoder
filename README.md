
<p align="center">
  <img src="Logo.jpeg" alt="TermCoder Logo" width="160" height="160">
</p>

# TermCoder

**The Autonomous Local AI Software Engineer & Terminal Assistant.**
Powered by Ollama, running entirely offline, securely, and fast inside your terminal.

---

## What is TermCoder?

TermCoder is a feature-rich, persistent, interactive CLI agent designed to bridge local Large Language Models (like `qwen2.5-coder`) directly with your workspace. Unlike standard chat interfaces, TermCoder automatically indexes your active workspace files, keeps a multi-mode persistent memory, supports real-time streaming, and lets you execute shell commands or git checks on the fly.

---

## Key Features

- **Real-Time Streaming:** Each generated text fragment is displayed as it arrives from Ollama, so responses progress naturally instead of appearing all at once.
- **Local text-to-speech:** Responses can be read aloud through `espeak-ng`, `espeak`, or `spd-say` when one is installed. Voice is enabled by default and can be controlled with `/voice`.
- **Automatic Workspace Contexting (build mode):** Recursively inspects your project directory and injects relevant text files as context for your queries automatically.
- **Any file type:** BUILD can create, modify, and delete source code, configuration, scripts, documentation, data files, tests, and other text-based project files through unified diffs.
- **Dual Engine Modes:** 
  - `build`: Deep workspace awareness tailored for software development and refactoring.
  - `chat`: Clean general-purpose mode for quick technical answers and conversations.
- **Sliding Memory Window:** Smart message history trimming to protect smaller local models from context window saturation.
- **Integrated Interactive Commands:** Full control over your session without leaving the prompt (`/system`, `/mode`, `/model`, `/host`, `/run`, `/search`, `/git`, `/save`, `/clear`).
- **Confirmed system commands:** BUILD and CHAT can run shell commands proposed by the model or entered with `/run`; every command requires confirmation and runs in the current workspace with the system environment.
- **Software management:** BUILD and CHAT detect the available system package manager, search meaningful words in software requests to resolve the real package name, and can install or uninstall packages, always with confirmation.
- **System information and packages:** `/doctor` reports the system and detected package managers; `/packages [search]` lists installed packages from the active manager. TermCoder always asks for confirmation before changing the system.
- **Web search:** BUILD and CHAT can search the public web automatically when a request needs current information, or manually with `/search <consulta>`, without an API key.
- **Persistent State:** Automatically saves session memory across runs to `~/.config/termcoder/agent_memory.json`.

---

## Installation

Clone the repository and install it in editable mode using pip:

```bash
git clone [https://github.com/dlopeddtorred/termcoder.git](https://github.com/dlopeddtorred/termcoder.git)
cd termcoder
pip install --editable .
```
Make sure you have Ollama running locally with your desired coding model pulled:
```bash
ollama pull qwen2.5-coder:3b
```
## Usage
Launch TermCoder simply by running:
```bash
termcoder
```

> [!TIP]
> Use build mode when working inside a codebase so TermCoder can automatically read your project structure and files.Use build mode when working inside a codebase so TermCoder can automatically read your project structure and files. Switch to chat mode for general technical questions using /mode chat.

> [!NOTE]
> Configuration files and persistent histories are safely stored locally under ~/.config/termcoder/.

You can also request installation naturally in CHAT or BUILD, for example `instalame claude code`.
TermCoder selects an available package manager or the official installer, then asks for confirmation
before executing it. Installation requests do not modify the workspace.

## Interactive Command Reference

| Command | Description | Example |
| :--- | :--- | :--- |
| `/help` | Show all available interactive commands. | `/help` |
| `/mode <build\|chat>` | Switch between workspace-aware and general chat modes. | `/mode chat` |
| `/model <model_name>` | Change the active local model on the fly. | `/model qwen2.5-coder:7b` |
| `/host <url>` | Change the Ollama backend host URL. | `/host http://localhost:11434` |
| `/system <prompt>` | Update the active system prompt instantly. | `/system You are a senior DevOps engineer` |
| `/run <command>` | Execute a local shell command with confirmation. | `/run pytest` |
| `/install <package>` | Search and install a program using the detected package manager, with confirmation. Product names may contain spaces. | `/install visual studio codium` |
| `/uninstall <package>` | Remove a package using the detected package manager, with confirmation. | `/uninstall ripgrep` |
| `/packages [search]` | List installed packages, optionally filtered by name. | `/packages python` |
| `/doctor` | Show workspace, OS, kernel, architecture, Python, package managers, Ollama, and Git diagnostics. | `/doctor` |
| `/search <query>` | Search the public web and display the results. | `/search Python 3.13 novedades` |
| `/voice [on\|off]` | Check or enable/disable local spoken responses. | `/voice on` |
| `/git` | Check current git workspace status. | `/git` |
| `/config` | View current configuration file settings. | `/config` |
| `/clear-mem` | Wipe persistent memory for the current mode. | `/clear-mem` |
| `/save` | Export full multi-mode memory to a timestamped JSON file. | `/save` |
| `/clear` | Clear terminal screen and redraw header banner. | `/clear` |
| `exit` / `quit` | Close the session gracefully. | `exit` |

## License
Distributed under the MIT License. See LICENSE for more information.
