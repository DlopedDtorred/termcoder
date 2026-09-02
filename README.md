████████ ███████ ██████  ███    ███  ██████  ██████  ██████  ███████ ██████  
   ██    ██      ██   ██ ████  ████ ██      ██    ██ ██   ██ ██      ██   ██ 
   ██    █████   ██████  ██ ████ ██ ██      ██    ██ ██   ██ █████   ██████  
   ██    ██      ██   ██ ██  ██  ██ ██      ██    ██ ██   ██ ██      ██   ██ 
   ██    ███████ ██   ██ ██      ██  ██████  ██████  ██████  ███████ ██   ██ 
                                                                             
                                                                             
# 💻 TermCoder

An autonomous, minimalist, and **100% local** software development agent designed to run in any terminal (Linux, macOS, and Windows). Powered entirely by **Ollama** and open-weights models.

---

## 🚀 Key Features

- **100% Private & Local:** Zero external API calls, zero telemetry, fully disconnected from the cloud.
- **Cross-Platform:** Works seamlessly across Linux, macOS, and Windows terminals.
- **Sober TUI Design:** Clean command-line interface inspired by professional design standards, built with `rich`.
- **File Context Injector:** Easily inject code files on the fly using `/file <path>` so the model can inspect your real workspace code.
- **Dynamic Model Management:** Switch models on the fly without restarting your session via `/model <name>`.
- **Workspace Navigation:** Explore structured project files using `/list`.
- **Shell Command Execution:** Run local tests, install dependencies, or check scripts securely via `/run <command>`.
- **Session History Persistence:** Save your current agent session to JSON using `/save`.

---

## 🛠️ Installation

1. Ensure Ollama is running on your machine:
   - Linux/macOS: `sudo systemctl enable --now ollama`
   - Windows: Make sure the Ollama app is running in your system tray.

2. Clone your repository and enter the directory:
   ```bash
   git clone git@github.com:DlopedDtorred/termcode.git
   cd termcode
   ```
    Install it in local editable mode:
    ```bash

    pip install --editable .
    ``
## 💡 Usage & Commands

Once installed, execute the global command inside any code workspace directory:
Bash

termcoder

Session Commands:

    /model <name>: Switches the active Ollama model (e.g., qwen2.5-coder:3b).

    /file <path>: Reads and includes a text or code file into the chat context.

    /list: Displays files in the current working directory.

    /run <cmd>: Executes a secure local shell command and shows its output.

    /save: Exports the current conversation history to JSON.

    exit, quit or salir: Ends the TermCoder session.

## 📄 License

Distributed under the MIT License.
