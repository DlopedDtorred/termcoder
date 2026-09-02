#!/usr/bin/env python3
import os
import sys
import json
import time
import ollama
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

console = Console()

CONFIG_DIR = os.path.expanduser("~/.config/termcoder")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "model": "qwen2.5-coder:3b",
    "system_prompt": "Eres TermCoder, un asistente de desarrollo de software senior, conciso y técnico, ejecutándose localmente. Ayudas a escribir código robusto, limpio y eficiente."
}

def load_config():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR, exist_ok=True)
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

ASCII_BANNER = """
 ████████ ███████ ██████  ███    ███  ██████  ██████  ██████  ███████ 
     ██    ██      ██   ██ ████  ████ ██    ██ ██   ██ ██   ██ ██      
    ██    █████   ██████  ██ ████ ██ ██    ██ ██   ██ ██   ██ █████   
    ██    ██      ██   ██ ██ ⠁██  ██ ██    ██ ██   ██ ██   ██ ██      
    ██    ███████ ██   ██ ██      ██ ⠙██████  ██████  ██████  ███████ 
"""

def read_local_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error al leer el archivo {path}: {e}"

def list_workspace_files():
    files = []
    for root, dirs, filenames in os.walk('.'):
        if '.git' in dirs or 'venv' in dirs or '__pycache__' in dirs or '.pytest_cache' in dirs:
            dirs[:] = [d for d in dirs if d not in ['.git', 'venv', '__pycache__', '.pytest_cache']]
        for f in filenames:
            files.append(os.path.join(root, f))
    return files[:40]

def main():
    config = load_config()
    model = config.get("model", "qwen2.5-coder:3b")
    
    console.print(f"[bold bright_black]{ASCII_BANNER}[/bold bright_black]")
    
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("[dim]Workspace[/dim]", f"[cyan]{os.getcwd()}[/cyan]")
    table.add_row("[dim]Modelo Activo[/dim]", f"[bold bright_white]{model}[/bold bright_white]")
    table.add_row("[dim]Comandos[/dim]", "[dim]/model <nombre> | /file <ruta> | /list | salir[/dim]")
    
    console.print(Panel(table, border_style="bright_black", title="TermCoder Workspace", title_align="left"))
    console.print()

    messages = [{'role': 'system', 'content': config.get("system_prompt")}]
    attached_files_context = ""

    while True:
        try:
            user_input = Prompt.ask("[bold bright_cyan]›[/bold bright_cyan]")
            if not user_input.strip():
                continue
            
            cmd = user_input.strip().lower()
            if cmd in ['salir', 'exit', 'quit']:
                console.print("[dim]Cerrando sesión de TermCoder. ¡Hasta pronto![/dim]")
                break
            
            if user_input.startswith("/model "):
                new_model = user_input.split(" ", 1)[1].strip()
                config["model"] = new_model
                save_config(config)
                model = new_model
                console.print(f"[dim]✔ Modelo cambiado correctamente a:[/dim] [bold bright_white]{model}[/bold bright_white]\n")
                continue

            if user_input.startswith("/file "):
                file_path = user_input.split(" ", 1)[1].strip()
                file_content = read_local_file(file_path)
                attached_files_context += f"\n\n--- ARCHIVO CARGADO: {file_path} ---\n{file_content}\n-----------------------------------\n"
                console.print(f"[dim]📎 Archivo [cyan]{file_path}[/cyan] adjuntado al contexto del agente.[/dim]\n")
                continue

            if cmd == "/list":
                files = list_workspace_files()
                console.print(Panel("\n".join([f"• {f}" for f in files]), title="Archivos en Workspace", border_style="bright_black"))
                continue

            full_prompt = user_input
            if attached_files_context:
                full_prompt = f"{user_input}\n\nContexto de archivos adjuntos:{attached_files_context}"
                attached_files_context = ""

            messages.append({'role': 'user', 'content': full_prompt})

            start_time = time.time()
            with console.status("[dim]Generando respuesta local...[/dim]", spinner="dots"):
                response = ollama.chat(model=model, messages=messages)

            elapsed = time.time() - start_time
            answer = response['message']['content']
            
            panel_title = f"TermCoder · {model} · {elapsed:.1f}s"
            console.print(Panel(Markdown(answer), border_style="bright_black", title=panel_title, title_align="left"))
            console.print()
            
            messages.append({'role': 'assistant', 'content': answer})

        except KeyboardInterrupt:
            console.print("\n[dim]Saliendo...[/dim]")
            break
        except Exception as e:
            console.print(f"[bold red]Error crítico:[/bold red] {e}")

if __name__ == '__main__':
    main()
