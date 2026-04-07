#!/bin/bash
# PhotoSync - First time setup
# Double-click this file to install PhotoSync

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Setting up PhotoSync..."
chmod +x "$DIR/launch.sh"
chmod +x "$DIR/PhotoSync.app/Contents/MacOS/PhotoSync"

echo "Done. Launching PhotoSync..."
sleep 1
open "$DIR/PhotoSync.app"
