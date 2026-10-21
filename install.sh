#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
ICON_SCALABLE_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
ICON_256_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

mkdir -p "$BIN_DIR" "$APPS_DIR" "$ICON_SCALABLE_DIR" "$ICON_256_DIR"
chmod +x "$APP_DIR/main.py" "$APP_DIR/src/privileged_worker.py"

ln -sf "$APP_DIR/main.py" "$BIN_DIR/origin-updater"
ln -sf "$APP_DIR/main.py" "$BIN_DIR/atualizador-apps"

if [ -f "$APP_DIR/assets/origin-updater.svg" ]; then
    cp -f "$APP_DIR/assets/origin-updater.svg" "$ICON_SCALABLE_DIR/origin-updater.svg"
    cp -f "$APP_DIR/assets/origin-updater.svg" "$ICON_SCALABLE_DIR/br.com.chrystian.AtualizadorApps.svg"
fi

if [ -f "$APP_DIR/assets/origin-updater.png" ]; then
    cp -f "$APP_DIR/assets/origin-updater.png" "$ICON_256_DIR/origin-updater.png"
    cp -f "$APP_DIR/assets/origin-updater.png" "$ICON_256_DIR/br.com.chrystian.AtualizadorApps.png"
fi

# Remove arquivo antigo se existir para evitar duplicata no menu
rm -f "$APPS_DIR/atualizador-apps.desktop"

# Nome do arquivo .desktop igual ao application_id para o GNOME / Wayland exibir o ícone na Dock
cat > "$APPS_DIR/br.com.chrystian.AtualizadorApps.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Origin Updater (Central de Atualizações)
Comment=Verifica e atualiza aplicativos diretamente dos Repositórios Oficiais, GitHub Releases e Flathub
Exec=/usr/bin/python3 $APP_DIR/main.py
Icon=$APP_DIR/assets/origin-updater.svg
Terminal=false
Categories=System;PackageManager;GTK;
StartupNotify=true
StartupWMClass=br.com.chrystian.AtualizadorApps
EOF

chmod +x "$APPS_DIR/br.com.chrystian.AtualizadorApps.desktop"

# Atualiza caches de ícones e atalhos do ambiente gráfico (se disponíveis)
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
update-desktop-database "$APPS_DIR" 2>/dev/null || true

echo "✔ Origin Updater e novo ícone instalados com sucesso no sistema!"
