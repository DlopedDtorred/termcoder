#!/usr/bin/env python3
import os
import sys
import json
import time
import subprocess
import ollama
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

console = Console()

CONFIG_DIR = os.path.expanduser("~/.config/termcoder")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
HISTORY_DIR = os.path.join(CONFIG_DIR, "history")

DEFAULT_CONFIG = {
    "model": "qwen2.5-coder:3b",
    "system_prompt": "You are TermCoder, an expert, concise, and technical senior software development assistant running locally. You help write robust, clean, efficient code and debug issues directly."
}

def load_config():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(HISTORY_DIR):
        os.makedirs(HISTORY_DIR, exist_ok=True)
        
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return DEFAULT_CONFIG

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

# Corrected ASCII Banner for TERMCODER
ASCII_BANNER = """
████████ ███████ ██████  ███    ███  ██████  ██████  ██████  ███████ ██████  
   ██    ██      ██   ██ ████  ████ ██      ██    ██ ██   ██ ██      ██   ██ 
   ██    █████   ██████  ██ ████ ██ ██      ██    ██ ██   ██ █████   ██████  
   ██    ██      ██   ██ ██  ██  ██ ██      ██    ██ ██   ██ ██      ██   ██ 
   ██    ███████ ██   ██ ██      ██  ██████  ██████  ██████  ███████ ██   ██ 
"""

def read_local_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {path}: {e}"

def list_workspace_files():
    files = []
    for root, dirs, filenames in os.walk('.'):
        if any(exc in root for exc in ['.git', 'venv', '__pycache__', '.pytest_cache', 'node_modules']):
            continue
        for f in filenames:
            files.append(os.path.join(root, f))
    return files[:50]

def execute_shell_command(command):
    console.print(f"[dim]⚡ Running secure shell command: [bold bright_white]{command}[/bold bright_white][/dim]")
    try:
        result = subprocess.run(command, shell=True, text=True, capture_output=True, timeout=30)
        output = result.stdout if result.returncode == 0 else result.stderr
        return output.strip() if output else "Command executed successfully with no output."
    except Exception as e:
        return f"Error executing command: {e}"

def main():
    config = load_config()
    model = config.get("model", "qwen2.5-coder:3b")
    
    console.print(f"[bold bright_black]{ASCII_BANNER}[/bold bright_black]")
    
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("[dim]Workspace[/dim]", f"[cyan]{os.getcwd()}[/cyan]")
    table.add_row("[dim]Active Model[/dim]", f"[bold bright_white]{model}[/bold bright_white]")
    table.add_row("[dim]Pro Commands[/dim]", "[dim]/model <name> | /file <path> | /list | /run <cmd> | /save | exit[/dim]")
    
    console.print(Panel(table, border_style="bright_black", title="TermCoder Advanced Workspace", title_align="left"))
    console.print()

    messages = [{'role': 'system', 'content': config.get("system_prompt")}]
    attached_files_context = ""

    while True:
        try:
            user_input = Prompt.ask("[bold bright_cyan]›[/bold bright_cyan]")
            if not user_input.strip():
                continue
            
            cmd = user_input.strip().lower()
            if cmd in ['exit', 'quit', 'salir']:
                console.print("[dim]Closing TermCoder session. Goodbye![/dim]")
                break
            
            if user_input.startswith("/model "):
                new_model = user_input.split(" ", 1)[1].strip()
                config["model"] = new_model
                save_config(config)
                model = new_model
                console.print(f"[dim]✔ Model successfully switched to:[/dim] [bold bright_white]{model}[/bold bright_white]\n")
                continue

            if user_input.startswith("/file "):
                file_path = user_input.split(" ", 1)[1].strip()
                file_content = read_local_file(file_path)
                attached_files_context += f"\n\n--- ATTACHED FILE: {file_path} ---\n{file_content}\n-----------------------------------\n"
                console.print(f"[dim]📎 File [cyan]{file_path}[/cyan] attached to agent context.[/dim]\n")
                continue

            if cmd == "/list":
                files = list_workspace_files()
                console.print(Panel("\n".join([f"• {f}" for f in files]), title="Workspace Files", border_style="bright_black"))
                continue

            if user_input.startswith("/run "):
                shell_cmd = user_input.split(" ", 1)[1].strip()
                output = execute_shell_command(shell_cmd)
                console.print(Panel(output, title=f"Output of: {shell_cmd}", border_style="bright_black"))
                console.print()
                continue

            if cmd == "/save":
                timestamp = int(time.time())
                history_file = os.path.join(HISTORY_DIR, f"session_{timestamp}.json")
                with open(history_file, "w", encoding="utf-8") as f:
                    json.dump(messages, f, indent=4)
                console.print(f"[dim]💾 Session successfully saved to: [cyan]{history_file}[/cyan][/dim]\n")
                continue

            full_prompt = user_input
            if attached_files_context:
                full_prompt = f"{user_input}\n\nAttached files context:{attached_files_context}"
                attached_files_context = ""

            messages.append({'role': 'user', 'content': full_prompt})

            start_time = time.time()
            with console.status("[dim]Generating local response...[/dim]", spinner="dots"):
                response = ollama.chat(model=model, messages=messages)

            elapsed = time.time() - start_time
            answer = response['message']['content']
            
            panel_title = f"TermCoder · {model} · {elapsed:.1f}s"
            console.print(Panel(Markdown(answer), border_style="bright_black", title=panel_title, title_align="left"))
            console.print()
            
            messages.append({'role': 'assistant', 'content': answer})

        except KeyboardInterrupt:
            console.print("\n[dim]Exiting...[/dim]")
            break
        except Exception as e:
            console.print(f"[bold red]Critical Error:[/bold red] {e}")

if __name__ == '__main__':
    main()
