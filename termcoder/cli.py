#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import re
import subprocess
from pathlib import Path
import ollama
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

console = Console()

CONFIG_DIR = os.path.expanduser("~/.config/termcoder")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
HISTORY_DIR = os.path.join(CONFIG_DIR, "history")
MEMORY_FILE = os.path.join(CONFIG_DIR, "agent_memory.json")
IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache",
                "node_modules", "build", "dist", ".idea", ".vscode"}

DEFAULT_CONFIG = {
    "model": "qwen2.5-coder:3b",
    "ollama_host": "http://localhost:11434",
    "mode": "build",
    "temperature": 0.2,
    "max_context_files": 25,
    "max_history_messages": 30,
    "system_prompt_build": (
        "You are TermCoder BUILD, an autonomous local coding agent. Inspect the supplied "
        "workspace context and implement the user's request. Respond with a short summary "
        "followed by one unified diff in a ```diff fenced block. The diff must contain every "
        "file change needed and use paths relative to the workspace root. You may also include "
        "commands that are needed to finish the task in one ```bash fenced block. Do not only "
        "describe code and do not invent files outside the request."
    ),
    "system_prompt_chat": "You are TermCoder, an advanced and fast local technical assistant. Keep track of user instructions, preferences, and maintain accurate conversational continuity."
}

def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            if cfg.get("system_prompt_build") == (
                "You are TermCoder, an elite autonomous local AI software engineer. "
                "Write clean, production-grade code, remember user context, and execute tasks efficiently."
            ):
                cfg["system_prompt_build"] = DEFAULT_CONFIG["system_prompt_build"]
                save_config(cfg)
            return cfg
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

def load_persistent_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {"build": data.get("build", []), "chat": data.get("chat", [])}
        except (OSError, json.JSONDecodeError):
            console.print("[yellow]Could not read memory; starting with an empty history.[/yellow]")
    return {"build": [], "chat": []}

def save_persistent_memory(memory_data):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=4)
    except Exception as e:
        console.print(f"[bold red]Error saving memory:[/bold red] {e}")

def load_ascii_banner():
    banner_paths = ["logo-ascii.txt", os.path.join(os.path.dirname(__file__), "..", "logo-ascii.txt")]
    for path in banner_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                pass
    return "████████ ███████ ██████   ██   ██  ██████  ██████  ██████  ███████ \n   ██    ██      ██   ██   ██  ██  ██    ██ ██   ██ ██   ██ ██      \n   ██    █████   ██████    █████   ██    ██ ██   ██ ██   ██ █████   \n   ██    ██      ██   ██   ██  ██  ██    ██ ██   ██ ██   ██ ██      \n   ██    ███████ ██   ██  ██   ██ ⠙██████  ██████  ██████  ███████ "

def get_workspace_files():
    """Return workspace files while pruning generated and dependency directories."""
    files = []
    for root, dirs, filenames in os.walk("."):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        for filename in sorted(filenames):
            path = Path(root) / filename
            if not path.is_symlink():
                files.append(path)
    return sorted(files)


def get_context_limit(config):
    try:
        return max(1, min(200, int(config.get("max_context_files", 25))))
    except (TypeError, ValueError):
        return 25


def get_workspace_summary(max_files=25):
    file_tree = get_workspace_files()
    context_data = ""
    # Keep the prompt useful when a workspace contains many generated or binary files.
    readable_files = []
    for file_path in file_tree:
        try:
            if file_path.stat().st_size >= 30000:
                continue
            with file_path.open("rb") as f:
                sample = f.read(2048)
            if b"\0" in sample:
                continue
            readable_files.append(file_path)
        except OSError:
            continue

    context_data += "[Workspace file inventory]\n"
    context_data += "\n".join(f"- {path}" for path in file_tree[:max_files])
    context_data += "\n\n[Workspace file contents]\n"
    for file_path in readable_files[:max_files]:
        try:
            with file_path.open("r", encoding="utf-8", errors="ignore") as f:
                context_data += f"\n--- FILE: {file_path} ---\n{f.read()}\n"
        except (OSError, UnicodeError):
            continue
    return context_data


def _message_content(chunk):
    """Read streamed and non-streamed Ollama response objects."""
    message = chunk.get("message", {}) if isinstance(chunk, dict) else getattr(chunk, "message", {})
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", "")


def get_model_names(client):
    """Extract model names from all Ollama client response shapes."""
    response = client.list()
    models = response.get("models", []) if isinstance(response, dict) else getattr(response, "models", [])
    names = []
    for model in models or []:
        name = model.get("name") if isinstance(model, dict) else getattr(model, "model", None)
        if name:
            names.append(name)
    return sorted(names)


def print_help():
    console.print(Panel(
        "[bold]/help[/bold]      Muestra esta ayuda\n"
        "[bold]/files[/bold]     List files included in BUILD context\n"
        "[bold]/list[/bold]      Alias for /files\n"
        "[bold]/models[/bold]    List Ollama models\n"
        "[bold]/doctor[/bold]    Check Ollama, Git, and the workspace\n"
        "In BUILD, diffs are applied only after confirmation.\n"
        "[bold]/mode[/bold]      Switch between build and chat\n"
        "[bold]/model[/bold]     Change the active model\n"
        "[bold]/host[/bold]      Change the Ollama server\n"
        "[bold]/run[/bold]       Run a local command after confirmation\n"
        "[bold]/save[/bold]      Export session memory\n"
        "[bold]/clear-mem[/bold] Clear memory for the current mode\n"
        "[bold]exit[/bold]        Close TermCoder",
        title="TermCoder · Commands", border_style="cyan"
    ))


def extract_unified_diff(response):
    """Extract one model-generated unified diff from a fenced response."""
    fenced = re.search(r"```[ \t]*diff[ \t]*\r?\n(.*?)```", response, re.IGNORECASE | re.DOTALL)
    if fenced:
        diff = fenced.group(1).strip()
        if diff.startswith(("diff --git ", "--- ")):
            return diff

    # Some models omit the language marker while still returning a valid diff.
    raw = re.search(
        r"(?m)^(diff --git .+?)(?=\n```|\Z)",
        response,
        re.DOTALL,
    )
    return raw.group(1).strip() if raw else ""


def extract_shell_commands(response):
    """Extract explicitly fenced shell commands proposed by the model."""
    blocks = re.findall(
        r"```(?:bash|sh|shell)\s*\r?\n(.*?)```",
        response,
        re.IGNORECASE | re.DOTALL,
    )
    return [line.strip() for block in blocks for line in block.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def repair_new_file_diff(diff, repository_root=None):
    """Repair common model diffs that add files without /dev/null headers."""
    sections = [section for section in re.split(
        r"(?=^diff --git )", diff, flags=re.MULTILINE
    ) if section]
    if not sections or any(not section.startswith("diff --git ") for section in sections):
        return ""

    repaired = []
    for section in sections:
        match = re.search(r"^diff --git a/(.+?) b/(.+?)$", section, re.MULTILINE)
        if not match:
            return ""
        relative_path = Path(match.group(2))
        path_exists = (
            (Path(repository_root) / relative_path).exists()
            if repository_root else relative_path.exists()
        )
        if relative_path.is_absolute() or ".." in relative_path.parts or path_exists:
            return ""

        added_lines = []
        in_hunk = False
        for line in section.splitlines():
            if line.startswith("@@ "):
                in_hunk = True
                continue
            if not in_hunk or line.startswith(("diff --git ", "index ", "--- ", "+++ ")):
                continue
            if line.startswith("+") or line.startswith(" "):
                added_lines.append(line[1:])
            elif line.startswith("-") or line.startswith("\\"):
                continue
            else:
                return ""
        if not added_lines:
            return ""

        path = relative_path.as_posix()
        repaired.append(
            f"diff --git a/{path} b/{path}\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            f"+++ b/{path}\n"
            f"@@ -0,0 +1,{len(added_lines)} @@\n"
            + "\n".join(f"+{line}" for line in added_lines)
            + "\n"
        )
    return "\n".join(repaired)


def normalize_unified_diff(diff):
    """Add missing context prefixes in hunks from loosely formatted model output."""
    normalized = []
    in_hunk = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            in_hunk = False
        elif line.startswith("@@ "):
            in_hunk = True
        elif in_hunk and not line.startswith(("+", "-", " ", "\\")):
            line = f" {line}"
        normalized.append(line)
    return "\n".join(normalized) + "\n"


def request_model_response(client, config, messages):
    """Collect a streamed Ollama response while supporting dict and object chunks."""
    result = client.chat(
        model=config.get("model"),
        messages=messages,
        options={"temperature": float(config.get("temperature", 0.2))},
        stream=True,
    )
    return "".join(content for chunk in result if (content := _message_content(chunk)))


def apply_model_diff(diff):
    """Validate and optionally apply a model diff, with or without Git."""
    repository = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True, capture_output=True, check=False
    )
    use_git = repository.returncode == 0
    repository_root = repository.stdout.strip() if use_git else os.getcwd()
    candidate = normalize_unified_diff(diff)
    apply_command = (["git", "apply", "--whitespace=fix", "--recount", "-"]
                     if use_git else ["patch", "-p1", "-i", "-"])
    check_command = (["git", "apply", "--check", "--whitespace=fix", "--recount", "-"]
                     if use_git else ["patch", "--dry-run", "-p1", "-i", "-"])
    check = subprocess.run(check_command, input=candidate, text=True,
                           capture_output=True, check=False, cwd=repository_root)
    if check.returncode != 0:
        candidate = repair_new_file_diff(candidate, repository_root)
        if candidate:
            check = subprocess.run(check_command, input=candidate, text=True,
                                   capture_output=True, check=False, cwd=repository_root)
        if check.returncode != 0:
            detail = check.stderr.strip() or check.stdout.strip() or "invalid diff"
            console.print(f"[bold red]The proposed change cannot be applied:[/bold red] {detail}")
            return False

    console.print(Panel(candidate, title="BUILD proposed changes", border_style="yellow"))
    if not Confirm.ask("[bold yellow]Apply these changes to the workspace?[/bold yellow]", default=True):
        console.print("[dim]Changes discarded; no files were modified.[/dim]")
        return False

    applied = subprocess.run(
        apply_command, input=candidate, text=True, capture_output=True,
        check=False, cwd=repository_root,
    )
    if applied.returncode != 0:
        detail = applied.stderr.strip() or applied.stdout.strip() or "git apply failed"
        console.print(f"[bold red]Could not apply the changes:[/bold red] {detail}")
        return False
    console.print("[bold green]✔ Changes applied successfully.[/bold green]")
    return True

def execute_shell_command(command):
    console.print(f"\n[bold yellow]⚡ System Execution Request:[/bold yellow] [bright_white]{command}[/bright_white]")
    if Confirm.ask("[bold yellow]Do you want to run this local command?[/bold yellow]", default=False):
        try:
            res = subprocess.run(command, shell=True, text=True, capture_output=True, timeout=120)
            out = res.stdout if res.returncode == 0 else res.stderr
            return out.strip() if out else "Command executed successfully with no output text."
        except Exception as e:
            return f"Execution error: {e}"
    return "Command execution cancelled by user."

def print_header(config, memory_data):
    console.clear()
    banner = load_ascii_banner()
    console.print(f"[bold bright_cyan]{banner}[/bold bright_cyan]")
    
    mode = config.get("mode", "build")
    mode_str = "[bold green]BUILD (Autonomous Workspace Context)[/bold green]" if mode == "build" else "[bold cyan]CHAT (Clean General Mode)[/bold cyan]"
    
    build_msgs = max(0, len(memory_data.get("build", [])) - 1)
    chat_msgs = max(0, len(memory_data.get("chat", [])) - 1)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("[dim]Workspace[/dim]", f"[cyan]{os.getcwd()}[/cyan]")
    table.add_row("[dim]Platform Host[/dim]", f"[magenta]{config.get('ollama_host', 'http://localhost:11434')}[/magenta]")
    table.add_row("[dim]Active Model[/dim]", f"[bold bright_white]{config.get('model')}[/bold bright_white]")
    table.add_row("[dim]Engine Mode[/dim]", mode_str)
    table.add_row("[dim]Memory Status[/dim]", f"[yellow]Build: {build_msgs} msgs | Chat: {chat_msgs} msgs saved[/yellow]")
    table.add_row("[dim]Commands[/dim]", "[dim]/mode <build|chat> | /model <m> | /host <url> | /system <txt> | /run <cmd> | /git | /config | /clear-mem | /save | /clear | exit[/dim]")
    
    console.print(Panel(table, border_style="bright_black", title="TermCoder · Ultimate Persistent Agent", title_align="left"))
    console.print()

def main():
    config = load_config()
    client = ollama.Client(host=config.get("ollama_host", "http://localhost:11434"))
    
    persistent_memory = load_persistent_memory()
    print_header(config, persistent_memory)
    
    current_mode = config.get("mode", "build")
    sys_prompt = config.get("system_prompt_build") if current_mode == "build" else config.get("system_prompt_chat")
    
    if not persistent_memory[current_mode] or persistent_memory[current_mode][0].get('role') != 'system':
        persistent_memory[current_mode].insert(0, {'role': 'system', 'content': sys_prompt})
    else:
        persistent_memory[current_mode][0]['content'] = sys_prompt
        
    messages = persistent_memory[current_mode]

    while True:
        try:
            current_mode = config.get("mode", "build")
            prompt_symbol = "\n[bold bright_green]build›[/bold bright_green]" if current_mode == "build" else "\n[bold bright_cyan]chat›[/bold bright_cyan]"
            user_input = Prompt.ask(prompt_symbol)
            if not user_input.strip():
                continue
            
            cmd = user_input.strip().lower()
            if cmd in ['exit', 'quit', 'salir']:
                console.print("[dim]Closing session. Goodbye![/dim]")
                break
            
            if cmd == '/clear':
                print_header(config, persistent_memory)
                continue

            if cmd == '/help' or cmd == '/?':
                print_help()
                continue

            if cmd in ('/files', '/list'):
                files = get_workspace_files()
                table = Table("File", "Size", show_header=True)
                for path in files[:get_context_limit(config)]:
                    try:
                        size = f"{path.stat().st_size:,} bytes"
                    except OSError:
                        size = "inaccesible"
                    table.add_row(str(path), size)
                console.print(table if files else "[yellow]No text files found in the workspace.[/yellow]")
                continue

            if cmd == '/models':
                try:
                    model_names = get_model_names(client)
                    if model_names:
                        console.print(Panel("\n".join(model_names), title="Available Ollama models",
                                            border_style="cyan"))
                    else:
                        console.print("[yellow]Ollama has no installed models.[/yellow]")
                except Exception as e:
                    console.print(f"[bold red]Could not query Ollama:[/bold red] {e}")
                continue

            if cmd == '/doctor':
                console.print("[bold]TermCoder diagnostics[/bold]")
                console.print(f"Workspace: [green]{os.getcwd()}[/green]")
                console.print(f"Files detected: [green]{len(get_workspace_files())}[/green]")
                try:
                    model_names = get_model_names(client)
                    active = config.get("model")
                    status = "OK" if active in model_names else f"falta {active}"
                    console.print(f"Ollama: [green]OK[/green] ({status})")
                except Exception as e:
                    console.print(f"Ollama: [red]ERROR[/red] ({e})")
                try:
                    git = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                                         text=True, capture_output=True, check=False)
                    console.print(f"Git: [{'green' if git.returncode == 0 else 'yellow'}]"
                                  f"{'OK' if git.returncode == 0 else 'no es un repositorio'}[/]")
                except OSError as e:
                    console.print(f"Git: [red]ERROR[/red] ({e})")
                continue

            if cmd == '/clear-mem':
                persistent_memory[current_mode] = [{'role': 'system', 'content': sys_prompt}]
                save_persistent_memory(persistent_memory)
                print_header(config, persistent_memory)
                console.print(f"[bold yellow]✔ Persistent memory cleared for {current_mode.upper()} mode[/bold yellow]\n")
                messages = persistent_memory[current_mode]
                continue

            if cmd == '/config':
                console.print("\n[bold]Current Configuration (~/.config/termcoder/config.json):[/bold]")
                console.print(json.dumps(config, indent=4))
                console.print()
                continue

            if cmd == '/git':
                res = subprocess.run(["git", "status", "--short", "--branch"],
                                     text=True, capture_output=True, check=False)
                output = res.stdout.strip() or res.stderr.strip() or "No output from git status."
                console.print(Panel(output, title="Git Workspace Status", border_style="cyan"))
                continue

            # Handle commands that require arguments.
            if cmd == '/system':
                console.print("[bold red]Usage:[/bold red] provide text, for example: [cyan]/system You are a Python expert[/cyan]")
                continue

            if cmd == '/host':
                console.print(f"[bold]Current host:[/bold] [magenta]{config.get('ollama_host')}[/magenta]. Change it with: [cyan]/host http://localhost:11434[/cyan]")
                continue

            if cmd == '/model':
                console.print(f"[bold]Current model:[/bold] [bright_white]{config.get('model')}[/bright_white]. Change it with: [cyan]/model qwen2.5-coder:3b[/cyan]")
                continue

            if user_input.startswith("/system "):
                new_sys = user_input.split(" ", 1)[1].strip()
                if current_mode == "build":
                    config["system_prompt_build"] = new_sys
                else:
                    config["system_prompt_chat"] = new_sys
                save_config(config)
                sys_prompt = new_sys
                messages[0]['content'] = sys_prompt
                persistent_memory[current_mode] = messages
                save_persistent_memory(persistent_memory)
                console.print(f"[dim]✔ System prompt updated successfully for [{current_mode.upper()}].[/dim]")
                continue

            if user_input.startswith("/mode "):
                new_mode = user_input.split(" ", 1)[1].strip().lower()
                if new_mode in ["build", "chat"]:
                    config["mode"] = new_mode
                    save_config(config)
                    
                    current_mode = new_mode
                    sys_prompt = config.get("system_prompt_build") if current_mode == "build" else config.get("system_prompt_chat")
                    
                    if not persistent_memory[current_mode] or persistent_memory[current_mode][0].get('role') != 'system':
                        persistent_memory[current_mode].insert(0, {'role': 'system', 'content': sys_prompt})
                    else:
                        persistent_memory[current_mode][0]['content'] = sys_prompt
                        
                    messages = persistent_memory[current_mode]
                    
                    print_header(config, persistent_memory)
                    console.print(f"[dim]✔ Switched mode to: [bold white]{new_mode.upper()}[/bold white][/dim]")
                else:
                    console.print("[bold red]Error: Mode must be 'build' or 'chat'.[/bold red]")
                continue

            if user_input.startswith("/model "):
                new_model = user_input.split(" ", 1)[1].strip()
                config["model"] = new_model
                save_config(config)
                print_header(config, persistent_memory)
                console.print(f"[dim]✔ Active model changed to: [bold bright_white]{new_model}[/bold bright_white][/dim]")
                continue

            if user_input.startswith("/host "):
                new_host = user_input.split(" ", 1)[1].strip()
                config["ollama_host"] = new_host
                save_config(config)
                client = ollama.Client(host=new_host)
                print_header(config, persistent_memory)
                console.print(f"[dim]✔ Local backend host updated to: [magenta]{new_host}[/magenta][/dim]")
                continue

            if user_input.startswith("/run "):
                shell_cmd = user_input.split(" ", 1)[1].strip()
                output = execute_shell_command(shell_cmd)
                console.print(f"\n[bold]System Shell Output:[/bold]\n{output}\n")
                continue

            if cmd == "/save":
                path = os.path.join(HISTORY_DIR, f"session_{int(time.time())}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(persistent_memory, f, indent=4)
                console.print(f"[dim]💾 Full multi-mode memory successfully exported to: {path}[/dim]")
                continue

            if current_mode == "build":
                max_files = get_context_limit(config)
                payload = f"{user_input}\n\n[Automatic Workspace Files Context]:\n{get_workspace_summary(max_files)}"
            else:
                payload = user_input

            messages.append({'role': 'user', 'content': payload})

            try:
                max_hist = max(2, int(config.get("max_history_messages", 30)))
            except (TypeError, ValueError):
                max_hist = 30
            if len(messages) > max_hist:
                messages = [messages[0]] + messages[-(max_hist - 1):]

            start = time.time()
            console.print()
            console.print(f"[dim italic]── TermCoder [{current_mode.upper()}] · {config.get('model')} · Streaming... ──[/dim italic]\n")
            
            with console.status("[dim]Thinking locally...[/dim]", spinner="dots"):
                full_response = request_model_response(client, config, messages)

                if current_mode == "build" and not extract_unified_diff(full_response):
                    repair_messages = messages + [{
                        "role": "user",
                        "content": (
                            "The previous response did not contain an applicable diff. Correct it: "
                                "return only a one-line summary and a complete unified diff inside "
                                "```diff```. For new files, use --- /dev/null and +++ b/path. Do not include "
                                "tutorials, standalone files, or HTML/CSS/JavaScript blocks."
                        ),
                    }]
                    console.print("[dim]The model returned no diff; requesting a corrected response...[/dim]")
                    full_response = request_model_response(client, config, repair_messages)
            
            console.print(Markdown(full_response))
            elapsed = time.time() - start

            if current_mode == "build":
                model_diff = extract_unified_diff(full_response)
                if model_diff:
                    apply_model_diff(model_diff)
                else:
                    console.print(
                        "[yellow]BUILD did not produce an applicable diff. "
                        "Ask the model to implement the change, not just describe it.[/yellow]"
                    )
                for command in extract_shell_commands(full_response):
                    output = execute_shell_command(command)
                    console.print(f"\n[bold]BUILD command output:[/bold]\n{output}\n")
            messages.append({'role': 'assistant', 'content': full_response})
            
            persistent_memory[current_mode] = messages
            save_persistent_memory(persistent_memory)

        except KeyboardInterrupt:
            console.print("\n[dim]Session interrupted. Exiting...[/dim]")
            break
        except Exception as e:
            console.print(f"[bold red]Connection / Execution Error:[/bold red] {e}")

if __name__ == '__main__':
    main()
