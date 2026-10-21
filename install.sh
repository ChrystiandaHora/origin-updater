#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"

mkdir -p "$BIN_DIR" "$APPS_DIR"
chmod +x "$APP_DIR/main.py" "$APP_DIR/src/privileged_worker.py"

ln -sf "$APP_DIR/main.py" "$BIN_DIR/origin-updater"
ln -sf "$APP_DIR/main.py" "$BIN_DIR/atualizador-apps"

cat > "$APPS_DIR/atualizador-apps.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Origin Updater (Central de Atualizações)
Comment=Verifica e atualiza aplicativos diretamente dos Repositórios Oficiais, GitHub Releases e Flathub
Exec=/usr/bin/python3 $APP_DIR/main.py
Icon=system-software-update
Terminal=false
Categories=System;PackageManager;GTK;
StartupNotify=true
StartupWMClass=br.com.chrystian.AtualizadorApps
EOF

chmod +x "$APPS_DIR/atualizador-apps.desktop"
echo "✔ Origin Updater instalado com sucesso!"
