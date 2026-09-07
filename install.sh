#!/usr/bin/env bash
set -e

echo "Initializing TermCoder installation..."

if ! command -v git &> /dev/null; then
    echo "Error: git is required but not installed." >&2
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not installed." >&2
    exit 1
fi

INSTALL_DIR="$HOME/.termcoder"
REPO_URL="https://github.com/DlopedDtorred/termcoder.git"

if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing installation in $INSTALL_DIR..."
    cd "$INSTALL_DIR"
    git pull
else
    echo "Cloning repository..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo "Installing package and dependencies via pip..."
python3 -m pip install --user --upgrade .

echo "Installation completed successfully."
echo "Ensure that your user Python binary directory is included in your system PATH."
