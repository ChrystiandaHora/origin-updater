import configparser
import glob
import os
from typing import Dict, Optional, Tuple


# Mapeamento explícito para pacotes populares cujo nome do .desktop difere ou merece nome amigável
KNOWN_PACKAGES: Dict[str, Tuple[str, str]] = {
    "google-chrome-stable": ("Google Chrome", "google-chrome"),
    "google-chrome": ("Google Chrome", "google-chrome"),
    "code": ("Visual Studio Code", "vscode"),
    "firefox-esr": ("Firefox ESR", "firefox-esr"),
    "firefox": ("Mozilla Firefox", "firefox"),
    "spotify-client": ("Spotify", "spotify-client"),
    "anydesk": ("AnyDesk", "anydesk"),
    "discord": ("Discord", "discord"),
    "dbeaver-ce": ("DBeaver Community", "/usr/share/dbeaver-ce/dbeaver.png"),
    "rustdesk": ("RustDesk", "rustdesk"),
    "docker-desktop": ("Docker Desktop", "/opt/docker-desktop/share/icon.original.png"),
    "docker-ce": ("Docker Engine (CE)", "docker"),
    "docker-ce-cli": ("Docker CLI", "utilities-terminal"),
    "docker-buildx-plugin": ("Docker Buildx Plugin", "docker"),
    "docker-compose-plugin": ("Docker Compose Plugin", "docker"),
    "forticlient": ("FortiClient VPN", "network-vpn"),
    "obs-studio": ("OBS Studio", "com.obsproject.Studio"),
}


class DesktopResolver:
    """Resolve pacotes APT e IDs Flatpak para nomes amigáveis e ícones reais do sistema."""

    def __init__(self) -> None:
        self._by_key: Dict[str, Tuple[str, str]] = {}
        self._desktop_packages: set[str] = set()
        self._load_desktop_entries()

    def _load_desktop_entries(self) -> None:
        search_dirs = [
            "/usr/share/applications",
            "/usr/local/share/applications",
            "/var/lib/flatpak/exports/share/applications",
            os.path.expanduser("~/.local/share/applications"),
            os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
        ]
        for folder in search_dirs:
            if not os.path.isdir(folder):
                continue
            for path in glob.glob(os.path.join(folder, "*.desktop")):
                cp = configparser.ConfigParser(interpolation=None)
                try:
                    cp.read(path, encoding="utf-8")
                    if "Desktop Entry" not in cp:
                        continue
                    de = cp["Desktop Entry"]
                    if de.get("NoDisplay", "false").lower() == "true":
                        continue
                    name = (
                        de.get("Name[pt_BR]")
                        or de.get("Name[pt]")
                        or de.get("Name")
                        or ""
                    ).strip()
                    icon = (de.get("Icon") or "").strip()
                    exec_cmd = (de.get("Exec") or "").strip()
                    base = os.path.splitext(os.path.basename(path))[0]

                    if name:
                        self._by_key[base.lower()] = (name, icon)
                        self._desktop_packages.add(base.lower())
                        if exec_cmd:
                            first_tok = os.path.basename(exec_cmd.split()[0]).lower()
                            if first_tok not in self._by_key:
                                self._by_key[first_tok] = (name, icon)
                            self._desktop_packages.add(first_tok)
                except Exception:
                    continue

    def is_gui_application(self, pkg_name: str) -> bool:
        key = pkg_name.lower()
        if key in KNOWN_PACKAGES or key in self._desktop_packages:
            return True
        if key.endswith("-stable") and key[:-7] in self._desktop_packages:
            return True
        return False

    def resolve(
        self, pkg_name: str, fallback_name: Optional[str] = None, category: str = "system"
    ) -> Tuple[str, str, Optional[str]]:
        """Retorna (display_name, icon_name, icon_path)."""
        key = pkg_name.lower()

        if key in KNOWN_PACKAGES:
            dname, icon = KNOWN_PACKAGES[key]
            return self._split_icon(dname, icon)

        if key in self._by_key:
            dname, icon = self._by_key[key]
            if dname.lower() == key and fallback_name:
                dname = fallback_name
            return self._split_icon(dname, icon)

        if key.endswith("-stable") and key[:-7] in self._by_key:
            dname, icon = self._by_key[key[:-7]]
            return self._split_icon(dname, icon)

        default_icon = "package-x-generic"
        if category == "flatpak":
            default_icon = "system-software-install"
        elif category in ("app_repo", "direct_deb"):
            default_icon = "application-x-executable"

        return (fallback_name or pkg_name, default_icon, None)

    @staticmethod
    def _split_icon(
        display_name: str, icon_val: str
    ) -> Tuple[str, str, Optional[str]]:
        if not icon_val:
            return (display_name, "package-x-generic", None)
        if icon_val.startswith("/") and os.path.exists(icon_val):
            return (display_name, "application-x-executable", icon_val)
        return (display_name, icon_val, None)
