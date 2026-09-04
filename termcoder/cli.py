#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import re
import difflib
import platform
import shutil
import subprocess
import signal
import atexit
from html.parser import HTMLParser
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen
from pathlib import Path
import shlex
import ollama
from rich.console import Console
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
    "max_history_messages": 12,
    "max_output_tokens": 512,
    "system_prompt_build": (
        "You are TermCoder BUILD, an autonomous local coding agent. Inspect the supplied "
        "workspace context and implement the user's request directly in the workspace. "
        "Never answer with a tutorial, instructions, step-by-step guide, explanation, or "
        "standalone source-code block. Respond only with a very short status line followed "
        "by one unified diff in a ```diff fenced block. The diff must contain every "
        "file change needed for any requested file type, including source code, configuration, "
        "scripts, documentation, data, and tests, and use paths relative to the workspace root. "
        "Never use a one-line summary such as '+++ b/file @@ ...'; every file header and hunk "
        "header must be on its own line. "
        "To delete a file, return a standard unified diff with 'deleted file mode 100644', "
        "'--- a/path' and '+++ /dev/null'. "
        "You may also include commands that are needed to finish the task in one ```bash fenced "
        "block. Do not only describe code or return raw standalone code blocks. "
        "For installation, uninstallation, updates, or other system operations, do not create "
        "a diff or documentation; output only the real command in a ```bash``` block so it can "
        "be confirmed and executed. For current information or online research, use the web "
        "search results included in the user message when available. "
        "Do not invent files outside the request."
    ),
    "system_prompt_chat": "You are TermCoder, an advanced and fast local technical assistant. Keep track of user instructions, preferences, and maintain accurate conversational continuity."
}

COMMAND_INSTRUCTIONS = (
    "When you need information from the local system, propose a command in one "
    "```bash``` block; TermCoder will ask for confirmation, execute it in the current "
    "workspace with the user's system environment, and show you the output on the next turn. "
    "Use commands such as uname, free, df, lsb_release, /etc/os-release, and python for "
    "system inspection. Before installing or uninstalling packages, detect the available "
    "package manager and inspect installed packages so you do not assume the system. "
    "(for example pacman, apt, dnf, pip, or npm) instead of assuming one. "
    "Package installation commands still require explicit user confirmation. "
    "When the user asks to install, uninstall, or update any program or package, treat it as "
    "a system operation: do not create or modify project files, do not return a diff, and "
    "search the available package manager using the meaningful words in the software name, "
    "resolve the result to its real package name, and then propose the package-manager command "
    "in a ```bash``` block. Do not pass a multi-word product description as one package name. "
    "The same applies to any software name; do not assume a specific application. "
    "When current information, online research, documentation, or the latest version is "
    "needed, use the web search results that TermCoder supplies automatically. "
    "The user can also request web results with /search <query> in either mode."
)

def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        defaults = dict(DEFAULT_CONFIG)
        defaults["system_prompt_build"] += " " + COMMAND_INSTRUCTIONS
        defaults["system_prompt_chat"] += " " + COMMAND_INSTRUCTIONS
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(defaults, f, indent=4)
        return defaults
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if not isinstance(cfg, dict):
                raise ValueError("configuration must be a JSON object")
            changed = False
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
                    changed = True
            try:
                if int(cfg.get("max_history_messages", 12)) > 12:
                    cfg["max_history_messages"] = 12
                    changed = True
            except (TypeError, ValueError):
                cfg["max_history_messages"] = 12
                changed = True
            try:
                output_tokens = int(cfg.get("max_output_tokens", 512))
                if output_tokens < 64 or output_tokens > 4096:
                    cfg["max_output_tokens"] = 512
                    changed = True
            except (TypeError, ValueError):
                cfg["max_output_tokens"] = 512
                changed = True
            if cfg.get("mode") not in {"build", "chat"}:
                cfg["mode"] = DEFAULT_CONFIG["mode"]
                changed = True
            for prompt_key in ("system_prompt_build", "system_prompt_chat"):
                if not isinstance(cfg.get(prompt_key), str):
                    cfg[prompt_key] = DEFAULT_CONFIG[prompt_key]
                    changed = True
            build_file_only_rule = (
                "Never answer with a tutorial, instructions, step-by-step guide, explanation, "
                "or standalone source-code block."
            )
            if build_file_only_rule not in cfg["system_prompt_build"]:
                cfg["system_prompt_build"] = (
                    cfg["system_prompt_build"] + " " + build_file_only_rule
                )
                changed = True
            legacy_claude_rule = (
                "For Claude Code, first check whether `claude` is already installed; if it is "
                "missing, use the official installer or npm package command appropriate for the "
                "detected system. "
            )
            for prompt_key in ("system_prompt_build", "system_prompt_chat"):
                if legacy_claude_rule in cfg[prompt_key]:
                    cfg[prompt_key] = cfg[prompt_key].replace(legacy_claude_rule, "")
                    changed = True
            if "invent files outside the request." in cfg["system_prompt_build"]:
                cfg["system_prompt_build"] = cfg["system_prompt_build"].replace(
                    "invent files outside the request.",
                    "Do not invent files outside the request.",
                )
                changed = True
            if COMMAND_INSTRUCTIONS not in cfg["system_prompt_build"]:
                updated_prompt = cfg["system_prompt_build"].replace(
                    "Do not only describe code and do not invent files outside the request.",
                    "Do not only describe code and do not invent files outside the request. "
                    + COMMAND_INSTRUCTIONS,
                )
                cfg["system_prompt_build"] = (
                    updated_prompt if updated_prompt != cfg["system_prompt_build"]
                    else cfg["system_prompt_build"] + " " + COMMAND_INSTRUCTIONS
                )
                changed = True
            elif "Do not only describe code and do not invent files outside the request." in cfg["system_prompt_build"]:
                cfg["system_prompt_build"] = cfg["system_prompt_build"].replace(
                    "Do not only describe code and do not invent files outside the request.",
                    "Support any requested text-based file type and do not return raw "
                    "standalone code blocks. Do not invent files outside the request.",
                )
                changed = True
            if COMMAND_INSTRUCTIONS not in cfg["system_prompt_chat"]:
                updated_prompt = cfg["system_prompt_chat"].replace(
                    "accurate conversational continuity.",
                    "accurate conversational continuity. " + COMMAND_INSTRUCTIONS,
                )
                cfg["system_prompt_chat"] = (
                    updated_prompt if updated_prompt != cfg["system_prompt_chat"]
                    else cfg["system_prompt_chat"] + " " + COMMAND_INSTRUCTIONS
                )
                changed = True
            if cfg.get("system_prompt_build") == (
                "You are TermCoder, an elite autonomous local AI software engineer. "
                "Write clean, production-grade code, remember user context, and execute tasks efficiently."
            ):
                cfg["system_prompt_build"] = DEFAULT_CONFIG["system_prompt_build"]
                save_config(cfg)
            elif changed:
                save_config(cfg)
            return cfg
    except (OSError, json.JSONDecodeError, ValueError):
        defaults = dict(DEFAULT_CONFIG)
        defaults["system_prompt_build"] += " " + COMMAND_INSTRUCTIONS
        defaults["system_prompt_chat"] += " " + COMMAND_INSTRUCTIONS
        return defaults

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

def load_persistent_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    memory = {}
                    for mode in ("build", "chat"):
                        entries = data.get(mode, [])
                        if not isinstance(entries, list):
                            entries = []
                        memory[mode] = [
                            entry for entry in entries
                            if isinstance(entry, dict)
                            and entry.get("role") in {"system", "user", "assistant"}
                            and isinstance(entry.get("content"), str)
                        ]
                    return memory
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


def get_workspace_summary(max_files=25, max_chars=24000):
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
    total_chars = 0
    for file_path in readable_files[:max_files]:
        try:
            with file_path.open("r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            remaining = max_chars - total_chars
            if remaining <= 0:
                break
            content = content[:remaining]
            context_data += f"\n--- FILE: {file_path} ---\n{content}\n"
            total_chars += len(content)
        except (OSError, UnicodeError):
            continue
    return context_data


def get_system_summary():
    """Return reliable local system facts without asking the model to infer them."""
    managers = detect_package_managers()
    return {
        "OS": platform.system() or "unknown",
        "OS version": platform.platform() or "unknown",
        "Kernel": platform.release() or "unknown",
        "Architecture": platform.machine() or "unknown",
        "Python": platform.python_version(),
        "Shell": os.environ.get("SHELL", "unknown"),
        "Package managers": ", ".join(managers) if managers else "none detected",
    }


PACKAGE_MANAGERS = ("pacman", "apt-get", "dnf", "yum", "zypper", "npm", "pip")


def detect_package_managers():
    """Return package managers available in the current system PATH."""
    return [name for name in PACKAGE_MANAGERS if shutil.which(name)]


def get_installed_packages(search=None):
    """Return installed package names from the highest-priority detected manager."""
    manager = next(iter(detect_package_managers()), None)
    if not manager:
        return [], None

    commands = {
        "pacman": ["pacman", "-Qq"],
        "apt-get": ["dpkg-query", "-W", "-f=${binary:Package}\n"],
        "dnf": ["rpm", "-qa", "--qf", "%{NAME}\n"],
        "yum": ["rpm", "-qa", "--qf", "%{NAME}\n"],
        "zypper": ["rpm", "-qa", "--qf", "%{NAME}\n"],
        "pip": ["python", "-m", "pip", "list", "--format=freeze"],
        "npm": ["npm", "list", "--global", "--depth=0", "--parseable"],
    }
    try:
        result = subprocess.run(
            commands[manager], text=True, capture_output=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"could not query {manager}: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"{manager} query failed: {detail}")

    packages = []
    for line in result.stdout.splitlines():
        name = line.strip()
        if manager == "pip":
            name = re.split(r"[=<>!~]", name, maxsplit=1)[0]
        elif manager == "npm":
            name = _npm_package_name(name)
        if name:
            packages.append(name)
    if search:
        needle = search.casefold()
        packages = [name for name in packages if needle in name.casefold()]
    return sorted(set(packages), key=str.casefold), manager


def _npm_package_name(path):
    """Recover scoped npm names from parseable global installation paths."""
    parts = Path(path).parts
    if len(parts) >= 2 and parts[-2].startswith("@"):
        return "/".join(parts[-2:])
    return Path(path).name


def _query_installed_packages(manager):
    """Return installed package names for one detected package manager."""
    commands = {
        "pacman": ["pacman", "-Qq"],
        "apt-get": ["dpkg-query", "-W", "-f=${binary:Package}\n"],
        "dnf": ["rpm", "-qa", "--qf", "%{NAME}\n"],
        "yum": ["rpm", "-qa", "--qf", "%{NAME}\n"],
        "zypper": ["rpm", "-qa", "--qf", "%{NAME}\n"],
        "pip": ["python", "-m", "pip", "list", "--format=freeze"],
        "npm": ["npm", "list", "--global", "--depth=0", "--parseable"],
    }
    try:
        result = subprocess.run(
            commands[manager], text=True, capture_output=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"could not query {manager}: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"{manager} query failed: {detail}")

    packages = []
    for line in result.stdout.splitlines():
        name = line.strip()
        if manager == "pip":
            name = re.split(r"[=<>!~]", name, maxsplit=1)[0]
        elif manager == "npm":
            name = _npm_package_name(name)
        if name:
            packages.append(name)
    return sorted(set(packages), key=str.casefold)


def _package_name_key(name):
    """Normalize package names for matching user wording to manager names."""
    return re.sub(r"[-_\s]+", "-", name.strip().casefold())


def _package_aliases(package):
    normalized = _package_name_key(package)
    aliases = {normalized}
    if normalized.startswith("@") and "/" in normalized:
        aliases.add(normalized.split("/", 1)[1])
    return aliases


def find_installed_package(package):
    """Find a requested package across every available package manager."""
    requested = _package_aliases(package)
    matches = []
    errors = []
    for manager in detect_package_managers():
        try:
            installed = _query_installed_packages(manager)
        except RuntimeError as error:
            errors.append(str(error))
            continue
        for name in installed:
            installed_aliases = _package_aliases(name)
            if requested.intersection(installed_aliases):
                matches.append((manager, name))
    if errors and not matches:
        raise RuntimeError("; ".join(errors))
    return matches


def _search_package_candidates(manager, query):
    """Search available package names using the detected package manager."""
    tokens = [token for token in re.split(r"[-_\s]+", query.casefold()) if len(token) > 1]
    if not tokens:
        return []
    commands = {
        "pacman": lambda token: ["pacman", "-Ssq", token],
        "apt-get": lambda token: ["apt-cache", "search", token],
        "dnf": lambda token: ["dnf", "repoquery", "--qf", "%{name}", token],
        "yum": lambda token: ["yum", "list", "available", token],
        "zypper": lambda token: ["zypper", "--non-interactive", "search", "--match-substrings", token],
        "npm": lambda token: ["npm", "search", "--parseable", token],
        "pip": lambda token: ["python", "-m", "pip", "index", "versions", token],
    }
    if manager not in commands:
        return []

    candidates = set()
    for token in dict.fromkeys(tokens):
        try:
            result = subprocess.run(
                commands[manager](token), text=True, capture_output=True, check=False, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"could not search {manager}: {error}") from error
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if manager == "apt-get":
                name = line.split(" - ", 1)[0].split()[0]
            elif manager in {"dnf", "yum", "zypper"}:
                name = line.split()[0].split("/", 1)[-1]
                if name in {"Available", "Name", "S"} or name.startswith("-"):
                    continue
            elif manager == "npm":
                name = line.split("\t", 1)[0]
            elif manager == "pip":
                name = line.split(" ", 1)[0].removeprefix("ERROR:")
            else:
                name = line.split("/", 1)[-1]
            if name and re.match(r"^[A-Za-z0-9@._+/-]+$", name):
                candidates.add(name)
    return sorted(candidates, key=str.casefold)


def resolve_install_package(package, manager):
    """Resolve human software wording to the best available package name."""
    candidates = _search_package_candidates(manager, package)
    if not candidates:
        return None
    requested = _package_name_key(package)
    requested_tokens = set(token for token in requested.split("-") if token)

    def score(candidate):
        normalized = _package_name_key(candidate)
        matched_tokens = sum(token in normalized for token in requested_tokens)
        exact = normalized == requested or normalized.replace("-", "") == requested.replace("-", "")
        return (exact, matched_tokens, -len(normalized))

    return max(candidates, key=score)


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
        "[bold]/mode <build|chat>[/bold] Switch between build and chat\n"
        "[bold]/model <model>[/bold]     Change the active model\n"
        "[bold]/host <url>[/bold]        Change the Ollama server\n"
        "[bold]/system <prompt>[/bold]  Update the active system prompt\n"
        "[bold]/run <command>[/bold]    Run a local command after confirmation\n"
        "[bold]/install <package>[/bold] Install a package with confirmation\n"
        "[bold]/uninstall <package>[/bold] Remove a package with confirmation\n"
        "[bold]/packages [search][/bold] List installed packages\n"
        "[bold]/search <query>[/bold]   Search the web and show results\n"
        "[bold]/voice [on|off][/bold]   Enable or disable spoken responses\n"
        "[bold]/git[/bold]              Show git workspace status\n"
        "[bold]/config[/bold]           Show current configuration\n"
        "[bold]/clear-mem[/bold]        Clear memory for the current mode\n"
        "[bold]/save[/bold]             Export session memory\n"
        "[bold]/clear[/bold]            Clear the terminal and redraw the header\n"
        "[bold]exit / quit[/bold]        Close TermCoder",
        title="TermCoder · Commands", border_style="cyan"
    ))




def _ollama_process_ids():
    """Find Ollama server and model-runner processes without using shell commands."""
    process_ids = []
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return process_ids
    process_names = {"ollama", "ollama_llama_server"}
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            name = (entry / "comm").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        if name in process_names:
            process_ids.append(int(entry.name))
    return process_ids


_ollama_cleanup_done = False


def close_ollama_instances():
    """Stop Ollama processes so the next session starts with a clean backend."""
    global _ollama_cleanup_done
    if _ollama_cleanup_done:
        return
    _ollama_cleanup_done = True
    process_ids = _ollama_process_ids()
    current_pid = os.getpid()
    process_ids = [pid for pid in process_ids if pid != current_pid]
    for pid in process_ids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError:
            continue

    deadline = time.monotonic() + 1.5
    remaining = set(process_ids)
    while remaining and time.monotonic() < deadline:
        remaining = {pid for pid in remaining if Path(f"/proc/{pid}").exists()}
        if remaining:
            time.sleep(0.05)
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            continue


def _safe_model_path(raw_path):
    """Return a workspace-relative model path, or None for unsafe paths."""
    path = raw_path.strip().strip("`")
    if path.startswith(("a/", "b/")):
        path = path[2:]
    candidate = Path(path)
    if not path or candidate.is_absolute() or ".." in candidate.parts:
        return None
    return candidate.as_posix()


def _diff_from_file_blocks(response, repository_root=None):
    """Convert the file-marker format commonly emitted by small local models."""
    marker = re.compile(r"^[ \t]*---[ \t]+FILE:[ \t]*(.+?)[ \t]+---[ \t]*$", re.MULTILINE)
    matches = list(marker.finditer(response))
    if not matches:
        return ""

    root = Path(repository_root or os.getcwd())
    sections = []
    for index, match in enumerate(matches):
        path = _safe_model_path(match.group(1))
        if not path:
            return ""
        content_start = match.end()
        remainder = response[content_start:]
        plus_marker = re.match(
            r"[ \t]*\r?\n[ \t]*\+\+\+[ \t]+FILE:[ \t]*(.+?)[ \t]+---[ \t]*(?:\r?\n|$)",
            remainder,
        )
        if plus_marker:
            if _safe_model_path(plus_marker.group(1)) != path:
                return ""
            content_start += plus_marker.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(response)
        content = response[content_start:content_end]
        content = content.lstrip("\r\n").rstrip()
        if content.startswith("```") and content.endswith("```"):
            content = content[content.find("\n") + 1:-3].rstrip()
        new_lines = content.splitlines()
        target = root / path
        if target.exists() and not target.is_file():
            return ""
        try:
            old_lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
        except (OSError, UnicodeError):
            return ""
        if old_lines == new_lines:
            continue

        if target.exists():
            patch = difflib.unified_diff(
                old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""
            )
            sections.append(f"diff --git a/{path} b/{path}\n" + "\n".join(patch))
        else:
            sections.append(
                f"diff --git a/{path} b/{path}\n"
                "new file mode 100644\n"
                "--- /dev/null\n"
                f"+++ b/{path}\n"
                f"@@ -0,0 +1,{len(new_lines)} @@\n"
                + "\n".join(f"+{line}" for line in new_lines)
            )
    return "\n".join(sections) + ("\n" if sections else "")


def extract_unified_diff(response, repository_root=None):
    """Extract a model diff, including the file-marker format from small models."""
    fenced = re.search(r"```[ \t]*diff[ \t]*\r?\n(.*?)```", response, re.IGNORECASE | re.DOTALL)
    if fenced:
        diff = repair_nested_diff(fenced.group(1).strip())
        if is_valid_diff_candidate(diff):
            return diff

    # Some models omit the language marker while still returning a valid diff.
    raw = re.search(
        r"(?m)^(diff --git .+?)(?=\n```|\Z)",
        response,
        re.DOTALL,
    )
    diff = repair_nested_diff(raw.group(1).strip()) if raw else ""
    if is_valid_diff_candidate(diff):
        return diff
    return _diff_from_file_blocks(response, repository_root)


def is_valid_diff_candidate(diff):
    """Reject workspace listings and other text mistaken for unified diffs."""
    lines = diff.splitlines()
    if any("```" in line or re.match(r"^\+\+\+ .+ @@ ", line) for line in lines):
        return False
    has_hunk = any(line.startswith("@@ ") for line in lines)
    has_git_header = any(line.startswith("diff --git ") for line in lines)
    has_file_headers = (
        any(line.startswith("--- a/") for line in lines)
        and any(line.startswith(("+++ b/", "+++ /dev/null")) for line in lines)
    ) or (
        any(line.startswith("--- /dev/null") for line in lines)
        and any(line.startswith("+++ b/") for line in lines)
    )
    return has_hunk and (has_git_header or has_file_headers)


def repair_nested_diff(diff):
    """Unwrap one or more diffs pasted as added lines inside another diff."""
    lines = diff.splitlines()
    nested_indexes = [
        index for index, line in enumerate(lines)
        if re.match(r"^\+\+\+\+[ \t]+(?:a|b)/", line)
    ]
    if not nested_indexes:
        return diff

    sections = []
    for section_number, nested_index in enumerate(nested_indexes):
        nested_path = lines[nested_index][5:].strip()
        section_end = (
            nested_indexes[section_number + 1]
            if section_number + 1 < len(nested_indexes)
            else len(lines)
        )
        nested_lines = []
        for line in lines[nested_index + 1:section_end]:
            if not line.startswith("+"):
                return diff
            nested_lines.append(line[1:])

        if not any(line.startswith("@@ ") for line in nested_lines):
            return diff
        if nested_path.startswith("b/"):
            relative_path = nested_path[2:]
        else:
            relative_path = nested_path
        if not relative_path or relative_path.startswith("/"):
            return diff
        sections.append(
            f"diff --git a/{relative_path} b/{relative_path}\n"
            f"--- a/{relative_path}\n"
            f"+++ b/{relative_path}\n"
            + "\n".join(nested_lines)
        )
    return "\n".join(sections)


def extract_shell_commands(response):
    """Extract safe, explicitly fenced shell commands proposed by the model."""
    blocks = re.findall(
        r"```(?:bash|sh|shell)\s*\r?\n(.*?)```",
        response,
        re.IGNORECASE | re.DOTALL,
    )
    commands = []
    diff_markers = (
        "diff --git ", "index ", "--- ", "+++ ", "@@ ", "new file mode ",
        "deleted file mode ",
    )
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or any(
            line.startswith(diff_markers) or line[:1] in {"+", "-"}
            for line in lines
        ):
            # Small models sometimes label a unified diff as bash. Never execute
            # its added/removed lines as shell commands.
            continue
        commands.extend(
            line[2:].strip() if line.startswith("$ ") else line
            for line in lines
            if not line.startswith("#")
        )
    return commands


def build_diff_repair_messages(messages, config, reason=""):
    """Ask the model for a diff based on the workspace's current contents."""
    workspace = get_workspace_summary(get_context_limit(config))
    detail = f"\nThe previous diff was rejected with this error: {reason}" if reason else ""
    return messages + [{
        "role": "user",
        "content": (
            "The previous BUILD response did not produce an applicable diff."
            f"{detail}\n"
            "Use the current workspace contents below as the source of truth. Do not write a "
            "tutorial or explain how to do the task. Return only a one-line status and one "
            "complete unified diff inside ```diff```. Never use a one-line summary such as "
            "'+++ b/file @@ ...'; every file header and hunk header must be on its own line. Existing "
            "file hunks must match their current contents exactly. For new files, use "
            "--- /dev/null and +++ b/path. For deleted files, use "
            "'deleted file mode 100644', --- a/path, and +++ /dev/null. The lines marked "
            "[Workspace file contents] and "
            "--- FILE: ... --- are context only; never copy those markers into the diff. "
            "Do not include tutorials, standalone files, or raw code blocks.\n\n"
            f"{workspace}"
        ),
    }]


class _DuckDuckGoResultsParser(HTMLParser):
    """Extract the title, URL, and snippet from DuckDuckGo's HTML results."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._current = None
        self._capture = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if tag == "a" and "result__a" in classes:
            self._current = {"title": "", "url": urljoin("https://html.duckduckgo.com", attrs.get("href", "")),
                             "snippet": ""}
            self._capture = "title"
        elif self._current and tag in ("a", "div") and "result__snippet" in classes:
            self._capture = "snippet"

    def handle_data(self, data):
        if self._current and self._capture:
            self._current[self._capture] += data

    def handle_endtag(self, tag):
        if self._current and tag == "a" and self._capture == "title":
            self._capture = None
        elif self._current and tag == "div" and self._capture == "snippet":
            self.results.append(self._current)
            self._current = None
            self._capture = None


class _BingResultsParser(HTMLParser):
    """Extract standard result cards from Bing's HTML response."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._current = None
        self._capture = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if tag == "li" and "b_algo" in classes:
            self._current = {"title": "", "url": "", "snippet": ""}
        elif self._current and tag == "a" and not self._current["url"]:
            href = attrs.get("href", "")
            if href.startswith(("http://", "https://")):
                self._current["url"] = href
                self._capture = "title"
        elif self._current and tag in ("p", "div") and (
                "b_caption" in classes or "b_snippet" in classes):
            self._capture = "snippet"

    def handle_data(self, data):
        if self._current and self._capture:
            self._current[self._capture] += data

    def handle_endtag(self, tag):
        if self._current and tag == "a" and self._capture == "title":
            self._capture = None
        elif self._current and tag == "p" and self._capture == "snippet":
            self._capture = None
        elif self._current and tag == "li":
            if self._current["url"] and self._current["title"]:
                self.results.append(self._current)
            self._current = None
            self._capture = None


def search_web(query, max_results=5):
    """Search the public web without requiring an API key."""
    if not query.strip():
        raise ValueError("La consulta de búsqueda no puede estar vacía.")
    headers = {"User-Agent": "TermCoder/2.0 (+https://github.com/DlopedDtorred/termcode)"}
    endpoints = (
        ("https://html.duckduckgo.com/html/?q=", _DuckDuckGoResultsParser),
        ("https://www.bing.com/search?q=", _BingResultsParser),
    )
    errors = []
    for endpoint, parser_type in endpoints:
        try:
            request = Request(endpoint + quote(query), headers=headers)
            with urlopen(request, timeout=15) as response:
                html = response.read().decode("utf-8", errors="replace")
            parser = parser_type()
            parser.feed(html)
            if parser.results:
                return parser.results[:max_results]
        except OSError as error:
            errors.append(str(error))
    if errors:
        raise OSError("No se pudo consultar un buscador público: " + errors[-1])
    return []


def format_search_results(query, results):
    if not results:
        return f"No se encontraron resultados para: {query}"
    lines = [f"Resultados web para: {query}"]
    for index, result in enumerate(results, 1):
        snippet = " ".join(result["snippet"].split())
        lines.append(f"{index}. {result['title'].strip()}\n   {result['url']}\n   {snippet}")
    return "\n".join(lines)


def should_search_web(user_input):
    """Detect requests where fresh online information is useful without a command."""
    terms = (
        "internet", "web", "online", "buscar", "busca", "investiga", "investigar",
        "documentación", "documentacion", "docs", "última versión", "ultima version",
        "actual", "actualizado", "latest", "newest", "release", "version",
        "precio", "noticias", "cómo se instala", "como se instala",
    )
    text = user_input.casefold()
    return any(term in text for term in terms)


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


def repair_existing_file_diff(diff, repository_root):
    """Convert mistaken new-file diffs into replacements for existing files."""
    sections = [section for section in re.split(
        r"(?=^diff --git )", diff, flags=re.MULTILINE
    ) if section]
    if not sections or any(not section.startswith("diff --git ") for section in sections):
        return ""

    repaired = []
    for section in sections:
        match = re.search(r"^diff --git a/(.+?) b/(.+?)$", section, re.MULTILINE)
        if not match or match.group(1) != match.group(2):
            return ""
        if "new file mode" not in section or "--- /dev/null" not in section:
            return ""

        relative_path = Path(match.group(2))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            return ""
        path = Path(repository_root) / relative_path
        if not path.is_file():
            return ""

        added_lines = []
        in_hunk = False
        for line in section.splitlines():
            if line.startswith("@@ "):
                in_hunk = True
                continue
            if not in_hunk or line.startswith(("diff --git ", "index ", "--- ", "+++ ")):
                continue
            if line.startswith("+"):
                added_lines.append(line[1:])
            elif line.startswith((" ", "-")):
                continue
            elif line.startswith("\\"):
                continue
            else:
                return ""
        if not added_lines:
            return ""

        try:
            old_lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return ""

        path_string = relative_path.as_posix()
        replacement = difflib.unified_diff(
            old_lines,
            added_lines,
            fromfile=f"a/{path_string}",
            tofile=f"b/{path_string}",
            lineterm="",
        )
        hunk = "\n".join(replacement)
        if not hunk:
            return ""
        repaired.append(f"diff --git a/{path_string} b/{path_string}\n{hunk}\n")
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


def request_model_response(client, config, messages, on_chunk=None):
    """Collect a streamed Ollama response and optionally display each chunk."""
    try:
        temperature = float(config.get("temperature", 0.2))
    except (TypeError, ValueError):
        temperature = 0.2
    try:
        max_output_tokens = int(config.get("max_output_tokens", 512))
    except (TypeError, ValueError):
        max_output_tokens = 512
    result = client.chat(
        model=config.get("model"),
        messages=messages,
        options={"temperature": temperature, "num_predict": max_output_tokens},
        stream=True,
    )
    response_parts = []
    for chunk in result:
        content = _message_content(chunk)
        if not content:
            continue
        response_parts.append(content)
        if on_chunk:
            on_chunk(content)
    return "".join(response_parts)


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
    workspace = os.getcwd()
    check = subprocess.run(check_command, input=candidate, text=True,
                           capture_output=True, check=False, cwd=workspace)
    if check.returncode != 0:
        candidate = repair_new_file_diff(candidate, repository_root)
        if candidate:
            check = subprocess.run(check_command, input=candidate, text=True,
                                   capture_output=True, check=False, cwd=workspace)
        if check.returncode != 0:
            candidate = repair_existing_file_diff(normalize_unified_diff(diff), repository_root)
            if candidate:
                check = subprocess.run(check_command, input=candidate, text=True,
                                       capture_output=True, check=False, cwd=workspace)
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
        check=False, cwd=workspace,
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
            res = subprocess.run(
                command, shell=True, text=True, capture_output=True,
                timeout=120, cwd=os.getcwd(),
            )
            output = "\n".join(part for part in (res.stdout, res.stderr) if part).strip()
            if res.returncode != 0:
                return f"Command failed with exit code {res.returncode}:\n{output}"
            return output or "Command executed successfully with no output text."
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"Execution error: {e}"
    return "Command execution cancelled by user."


def get_package_command(request, action, manager=None, installed_name=None):
    """Build a confirmed package-manager command for an install or removal request."""
    text = request.strip()
    verbs = {
        "install": r"(?:install|instala(?:r|me)?|inst[aá]lame|instalar)",
        "uninstall": r"(?:uninstall|remove|uninstallar|desinstala(?:r|me)?|desinstalar|elimina(?:r|me)?)",
    }
    match = re.match(
        rf"^(?:please\s+)?{verbs[action]}\s+(.+?)\s*$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    package = match.group(1).strip().strip("`'\"")
    if not package or any(char in package for char in "\n\r;&|<>$"):
        return None

    normalized = re.sub(r"\s+", " ", package).lower()
    if action == "install" and normalized in {"claude code", "claude-code"}:
        if shutil.which("npm"):
            return "npm install --global @anthropic-ai/claude-code"
        if shutil.which("curl"):
            return "curl -fsSL https://claude.ai/install.sh | bash"
        return None

    if action == "uninstall" and manager is None:
        matches = find_installed_package(package)
        if matches:
            manager, installed_name = matches[0]
    if action == "uninstall" and normalized in {"claude code", "claude-code"}:
        installed_name = installed_name or "@anthropic-ai/claude-code"

    manager = manager or next(iter(detect_package_managers()), None)
    if not manager:
        return None
    package_name = shlex.quote(installed_name or package)
    if manager == "pacman":
        return f"sudo pacman -{'S --needed' if action == 'install' else 'Rns'} {package_name}"
    if manager == "apt-get":
        verb = "install -y" if action == "install" else "remove -y"
        return f"sudo apt-get {verb} {package_name}"
    if manager == "dnf":
        verb = "install -y" if action == "install" else "remove -y"
        return f"sudo dnf {verb} {package_name}"
    if manager == "yum":
        verb = "install -y" if action == "install" else "remove -y"
        return f"sudo yum {verb} {package_name}"
    if manager == "zypper":
        verb = "install" if action == "install" else "remove"
        return f"sudo zypper --non-interactive {verb} {package_name}"
    if manager == "npm":
        verb = "install" if action == "install" else "uninstall"
        return f"npm {verb} --global {package_name}"
    if manager == "pip":
        verb = "install" if action == "install" else "uninstall"
        return f"python -m pip {verb} {package_name}"
    return None


def get_install_command(request):
    return get_package_command(request, "install")


def get_uninstall_command(request):
    return get_package_command(request, "uninstall")

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
    table.add_row("[dim]Commands[/dim]", "[dim]Use /help to see all available commands[/dim]")
    
    console.print(Panel(table, border_style="bright_black", title="TermCoder · Persistent Agent", title_align="left"))
    console.print()

def main():
    config = load_config()
    atexit.register(close_ollama_instances)

    def handle_exit_signal(signum, _frame):
        close_ollama_instances()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, handle_exit_signal)
    signal.signal(signal.SIGHUP, handle_exit_signal)
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

            if cmd == "/packages" or cmd.startswith("/packages "):
                package_search = user_input.split(" ", 1)[1].strip() if " " in user_input else None
                try:
                    packages, manager = get_installed_packages(package_search)
                    if not manager:
                        console.print("[yellow]No supported package manager was detected.[/yellow]")
                    elif packages:
                        title = f"Installed packages via {manager}"
                        if package_search:
                            title += f" matching '{package_search}'"
                        console.print(Panel("\n".join(packages), title=title, border_style="cyan"))
                        console.print(f"[dim]{len(packages)} package(s) shown.[/dim]")
                    else:
                        console.print("[yellow]No installed packages matched that search.[/yellow]")
                except RuntimeError as error:
                    console.print(f"[bold red]Could not query installed packages:[/bold red] {error}")
                continue

            if cmd == '/doctor':
                console.print("[bold]TermCoder diagnostics[/bold]")
                console.print(f"Workspace: [green]{os.getcwd()}[/green]")
                console.print(f"Files detected: [green]{len(get_workspace_files())}[/green]")
                system_table = Table("System", "Value", show_header=True)
                for key, value in get_system_summary().items():
                    system_table.add_row(key, str(value))
                console.print(system_table)
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

            if user_input == "/search":
                console.print("[bold red]Usage:[/bold red] /search <consulta>")
                continue

            if user_input.startswith("/search "):
                query = user_input.split(" ", 1)[1].strip()
                try:
                    search_output = format_search_results(query, search_web(query))
                    console.print(Panel(search_output, title="Web Search", border_style="cyan"))
                    messages.append({
                        "role": "user",
                        "content": f"[Web search requested]\n{search_output}",
                    })
                    persistent_memory[current_mode] = messages
                    save_persistent_memory(persistent_memory)
                except (OSError, ValueError) as e:
                    console.print(f"[bold red]Web search failed:[/bold red] {e}")
                continue

            if user_input.startswith("/run "):
                shell_cmd = user_input.split(" ", 1)[1].strip()
                output = execute_shell_command(shell_cmd)
                console.print(f"\n[bold]System Shell Output:[/bold]\n{output}\n")
                continue

            if user_input in {"/install", "/uninstall", "/remove"}:
                console.print("[bold red]Usage:[/bold red] /install <paquete> or /uninstall <paquete>")
                continue

            package_request = (
                user_input.split(" ", 1)[1].strip()
                if user_input.lower().startswith(("/install ", "/uninstall ", "/remove "))
                else user_input
            )
            is_explicit_package_command = user_input.lower().startswith(
                ("/install ", "/uninstall ", "/remove ")
            )
            command_action = "uninstall" if user_input.lower().startswith(
                ("/uninstall ", "/remove ")
            ) else "install"
            is_package_intent = is_explicit_package_command or bool(re.match(
                r"^(?:please\s+)?(?:install|instala(?:r|me)?|inst[aá]lame|instalar|"
                r"uninstall|remove|uninstallar|desinstala(?:r|me)?|desinstalar|"
                r"elimina(?:r|me)?)\s+.+$",
                package_request,
                re.IGNORECASE,
            ))
            request_for_command = (
                f"{command_action} {package_request}"
                if is_explicit_package_command else package_request
            )
            installed_matches = []
            inspection_error = None
            if is_package_intent:
                package_for_inspection = package_request
                if not is_explicit_package_command:
                    package_match = re.match(
                        r"^(?:please\s+)?(?:install|instala(?:r|me)?|inst[aá]lame|instalar|"
                        r"uninstall|remove|uninstallar|desinstala(?:r|me)?|desinstalar|"
                        r"elimina(?:r|me)?)\s+(.+)$",
                        package_request,
                        re.IGNORECASE,
                    )
                    package_for_inspection = (
                        package_match.group(1).strip() if package_match else package_request
                    )
                try:
                    installed_matches = find_installed_package(package_for_inspection)
                except RuntimeError as error:
                    inspection_error = error
            selected_manager = installed_matches[0][0] if installed_matches else None
            selected_name = installed_matches[0][1] if installed_matches else None
            package_search_error = None
            if is_package_intent and command_action == "install":
                selected_manager = selected_manager or next(iter(detect_package_managers()), None)
                normalized_request = re.sub(
                    r"^(?:please\s+)?(?:install|instala(?:r|me)?|inst[aá]lame|instalar)\s+",
                    "",
                    request_for_command,
                    flags=re.IGNORECASE,
                ).strip()
                if selected_manager and normalized_request.lower() not in {
                    "claude code", "claude-code",
                }:
                    try:
                        selected_name = resolve_install_package(
                            normalized_request, selected_manager,
                        )
                    except RuntimeError as error:
                        package_search_error = error
                    if not selected_name:
                        package_search_error = package_search_error or (
                            f"no package matching '{normalized_request}' was found"
                        )
            package_command = get_package_command(
                request_for_command,
                command_action,
                manager=selected_manager,
                installed_name=selected_name,
            )
            if command_action == "install" and package_search_error:
                package_command = None
            if (
                is_package_intent
                and not is_explicit_package_command
                and not package_command
                and not package_search_error
            ):
                command_action = "uninstall"
                package_command = get_package_command(
                    package_request,
                    command_action,
                    manager=selected_manager,
                    installed_name=selected_name,
                )
            if is_explicit_package_command or package_command or (
                is_package_intent and package_search_error
            ):
                if package_command:
                    if installed_matches:
                        detected = ", ".join(
                            f"{name} ({manager})" for manager, name in installed_matches
                        )
                        console.print(
                            f"[cyan]Detected installed package(s): {detected}[/cyan]"
                        )
                    elif inspection_error:
                        console.print(
                            f"[yellow]Could not inspect installed packages: "
                            f"{inspection_error}[/yellow]"
                        )
                    elif package_search_error:
                        console.print(
                            f"[yellow]Could not resolve the package name: "
                            f"{package_search_error}[/yellow]"
                        )
                    elif command_action == "uninstall":
                        console.print(
                            f"[dim]'{package_request}' was not found in any detected "
                            "package manager.[/dim]"
                        )
                    output = execute_shell_command(package_command)
                    label = "Install" if command_action == "install" else "Uninstall"
                    console.print(f"\n[bold]{label} command output:[/bold]\n{output}\n")
                    continue
                console.print(
                    f"[yellow]Could not resolve the package name: {package_search_error}[/yellow]"
                    if package_search_error
                    else "[yellow]No compatible package manager was detected, or the package "
                    "name is invalid. Use /run with the official installer command.[/yellow]"
                )
                continue

            if cmd == "/save":
                path = os.path.join(HISTORY_DIR, f"session_{int(time.time())}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(persistent_memory, f, indent=4)
                console.print(f"[dim]💾 Full multi-mode memory successfully exported to: {path}[/dim]")
                continue

            if cmd == "/clear-mem":
                current_key = current_mode if current_mode in persistent_memory else "default"
                persistent_memory[current_key] = []
                save_persistent_memory(persistent_memory)
                console.print(f"[dim]✔ Memory cleared for mode '{current_mode}'.[/dim]")
                continue

            if current_mode == "build":
                max_files = get_context_limit(config)
                payload = f"{user_input}\n\n[Automatic Workspace Files Context]:\n{get_workspace_summary(max_files)}"
            else:
                payload = user_input

            if should_search_web(user_input):
                try:
                    web_results = search_web(user_input)
                    payload += (
                        "\n\n[Automatic Web Search Results]\n"
                        + format_search_results(user_input, web_results)
                        + "\nUse these results when answering; do not claim to have browsed "
                        "anything beyond the supplied results."
                    )
                    console.print("[dim]Searching the web for current information...[/dim]")
                except (OSError, ValueError) as error:
                    console.print(f"[yellow]Automatic web search unavailable:[/yellow] {error}")

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

            def stream_to_terminal(content):
                console.print(content, end="", markup=False, highlight=False)

            response_output = stream_to_terminal if current_mode == "chat" else None
            full_response = request_model_response(
                client, config, messages, on_chunk=response_output
            )
            console.print()

            has_commands = bool(extract_shell_commands(full_response))
            if (
                current_mode == "build"
                and not has_commands
                and not extract_unified_diff(full_response, os.getcwd())
            ):
                console.print("[dim]The model returned no diff; requesting a corrected response...[/dim]")
                full_response = request_model_response(
                    client,
                    config,
                    build_diff_repair_messages(messages, config),
                    on_chunk=response_output,
                )
                console.print()

            elapsed = time.time() - start

            if current_mode == "build":
                model_diff = extract_unified_diff(full_response, os.getcwd())
                if model_diff:
                    applied = apply_model_diff(model_diff)
                    if not applied:
                        console.print(
                            "[dim]The diff did not match the current workspace; "
                            "requesting a corrected diff...[/dim]"
                        )
                        corrected_response = request_model_response(
                            client,
                            config,
                            build_diff_repair_messages(messages, config, "the patch did not match"),
                            on_chunk=response_output,
                        )
                        corrected_diff = extract_unified_diff(corrected_response, os.getcwd())
                        if corrected_diff:
                            full_response = corrected_response
                            console.print()
                            apply_model_diff(corrected_diff)
                        else:
                            console.print(
                                "[yellow]The correction still did not contain an applicable diff.[/yellow]"
                            )
                else:
                    console.print(
                        "[yellow]BUILD did not produce an applicable diff. "
                        "Ask the model to implement the change, not just describe it.[/yellow]"
                    )
            command_outputs = []
            for command in extract_shell_commands(full_response):
                output = execute_shell_command(command)
                console.print(f"\n[bold]{current_mode.upper()} command output:[/bold]\n{output}\n")
                command_outputs.append(f"$ {command}\n{output}")
            messages.append({'role': 'assistant', 'content': full_response})
            if command_outputs:
                messages.append({
                    'role': 'user',
                    'content': "[Confirmed local command output]\n" + "\n\n".join(command_outputs),
                })

            persistent_memory[current_mode] = messages
            save_persistent_memory(persistent_memory)

        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Session interrupted. Exiting...[/dim]")
            break
        except Exception as e:
            console.print(f"[bold red]Connection / Execution Error:[/bold red] {e}")

if __name__ == '__main__':
    main()
