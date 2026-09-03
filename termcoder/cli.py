#!/usr/init/env python3
# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import subprocess
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

DEFAULT_CONFIG = {
    "model": "qwen2.5-coder:3b",
    "ollama_host": "http://localhost:11434",
    "mode": "build",
    "temperature": 0.2,
    "max_context_files": 25,
    "max_history_messages": 30,
    "system_prompt_build": "You are TermCoder, an elite autonomous local AI software engineer. Write clean, production-grade code, remember user context, and execute tasks efficiently.",
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
            return cfg
    except:
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
        except:
            pass
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
            except:
                pass
    return "████████ ███████ ██████   ██   ██  ██████  ██████  ██████  ███████ \n   ██    ██      ██   ██   ██  ██  ██    ██ ██   ██ ██   ██ ██      \n   ██    █████   ██████    █████   ██    ██ ██   ██ ██   ██ █████   \n   ██    ██      ██   ██   ██  ██  ██    ██ ██   ██ ██   ██ ██      \n   ██    ███████ ██   ██  ██   ██ ⠙██████  ██████  ██████  ███████ "

def get_workspace_summary(max_files=25):
    file_tree = []
    for root, dirs, filenames in os.walk('.'):
        if any(exc in root for exc in ['.git', 'venv', '__pycache__', '.pytest_cache', 'node_modules', 'build', 'dist', '.idea', '.vscode']):
            continue
        for f in filenames:
            file_tree.append(os.path.join(root, f))
    
    context_data = ""
    for file_path in file_tree[:max_files]:
        try:
            if os.path.getsize(file_path) < 30000:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    context_data += f"\n--- FILE: {file_path} ---\n{f.read()}\n"
        except:
            pass
    return context_data

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

            if cmd == '/clear-mem':
                persistent_memory[current_mode] = [{'role': 'system', 'content': sys_prompt}]
                save_persistent_memory(persistent_memory)
                print_header(config, persistent_memory)
                console.print(f"[bold yellow]✔ Memoria persistente borrada para el modo {current_mode.upper()}[/bold yellow]\n")
                messages = persistent_memory[current_mode]
                continue

            if cmd == '/config':
                console.print("\n[bold]Current Configuration (~/.config/termcoder/config.json):[/bold]")
                console.print(json.dumps(config, indent=4))
                console.print()
                continue

            if cmd == '/git':
                res = subprocess.run("git status", shell=True, text=True, capture_output=True)
                console.print(Panel(res.stdout.strip() or "No output from git status.", title="Git Workspace Status", border_style="cyan"))
                continue

            # Gestión correcta de comandos con argumentos vacíos
            if cmd == '/system':
                console.print("[bold red]Uso incorrecto:[/bold red] Debes indicar texto. Ejemplo: [cyan]/system Eres un experto en Python[/cyan]")
                continue

            if cmd == '/host':
                console.print(f"[bold]Host actual:[/bold] [magenta]{config.get('ollama_host')}[/magenta]. Uso para cambiar: [cyan]/host http://localhost:11434[/cyan]")
                continue

            if cmd == '/model':
                console.print(f"[bold]Modelo actual:[/bold] [bright_white]{config.get('model')}[/bright_white]. Uso para cambiar: [cyan]/model qwen2.5-coder:3b[/cyan]")
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
                max_files = config.get("max_context_files", 25)
                payload = f"{user_input}\n\n[Automatic Workspace Files Context]:\n{get_workspace_summary(max_files)}"
            else:
                payload = user_input

            messages.append({'role': 'user', 'content': payload})

            max_hist = config.get("max_history_messages", 30)
            if len(messages) > max_hist:
                messages = [messages[0]] + messages[-(max_hist - 1):]

            start = time.time()
            console.print()
            console.print(f"[dim italic]── TermCoder [{current_mode.upper()}] · {config.get('model')} · Streaming... ──[/dim italic]\n")
            
            full_response = ""
            with console.status("[dim]Thinking locally...[/dim]", spinner="dots"):
                stream = client.chat(
                    model=config.get("model"), 
                    messages=messages,
                    options={"temperature": config.get("temperature", 0.2)},
                    stream=True
                )
            
            for chunk in stream:
                content = chunk['message']['content']
                full_response += content
                sys.stdout.write(content)
                sys.stdout.flush()
            
            print("\n")
            elapsed = time.time() - start
            
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
