#!/bin/bash
# Double-click on macOS (or run ./start.command) to start OpenPictalis in your browser.
cd "$(dirname "$0")" || exit 1
exec python3 -m openpictalis --open
