import configparser
from dataclasses import dataclass
import glob
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Set, Tuple

import apt

from ..desktop_resolver import DesktopResolver
from ..providers.apt_provider import SITE_LABELS


# Prefixos de pacotes de sistema/kernel que são locais mas não são aplicativos de usuário
IGNORED_ORPHAN_PREFIXES = (
    "linux-headers-",
    "linux-kbuild-",
    "linux-image-",
    "linux-libc-",
    "linux-modules-",
    "linux-tools-",
)


@dataclass
class DiscoveredApp:
    """Representa um aplicativo instalado encontrado na varredura da máquina."""
    pkg_name: str
    display_name: str
    installed_version: str
    summary: str
    homepage: str
    maintainer: str
    section: str
    icon_name: str
    icon_path: Optional[str]
    install_kind: str            # 'orphan_deb', 'appimage', 'opt_binary', 'apt_repo', 'flatpak'
    current_source_status: str   # 'untracked', 'tracked_direct', 'tracked_apt', 'tracked_flatpak'
    current_source_name: str = ""
    current_source_host: str = ""
    desktop_file: Optional[str] = None
    exec_path: Optional[str] = None

    @property
    def needs_source_discovery(self) -> bool:
        return self.current_source_status == "untracked"

    @property
    def install_kind_label(self) -> str:
        if self.install_kind == "orphan_deb":
            return "Pacote .deb Local (Sem Repositório APT)"
        if self.install_kind == "appimage":
            return "AppImage Autônomo"
        if self.install_kind == "opt_binary":
            return "Binário em /opt (Sem Pacote)"
        if self.install_kind == "apt_repo":
            return "Repositório APT Oficial"
        if self.install_kind == "flatpak":
            return "Flatpak (Flathub)"
        return "Aplicativo Local"


class AppScanner:
    """
    Varre a máquina Linux em busca de todos os aplicativos instalados:
    1. Pacotes .deb instalados manualmente (órfãos de repositório APT no dpkg)
    2. Entradas .desktop e diretórios /opt
    3. Arquivos .AppImage em pastas do usuário
    4. Aplicativos já monitorados por Fontes Diretas, Repositórios APT de terceiros e Flatpak
    """

    def __init__(self, resolver: Optional[DesktopResolver] = None) -> None:
        self.resolver = resolver or DesktopResolver()

    def scan_machine(
        self, configured_direct_sources: Dict[str, Dict[str, Any]]
    ) -> List[DiscoveredApp]:
        discovered: Dict[str, DiscoveredApp] = {}
        desktop_by_pkg, standalone_desktops = self._scan_desktop_entries()

        # 1. Varredura do cache APT / dpkg
        cache = apt.Cache()
        for pkg in cache:
            if not pkg.is_installed or not pkg.installed:
                continue

            name = pkg.name
            if name.startswith(IGNORED_ORPHAN_PREFIXES):
                continue

            inst = pkg.installed
            cand = pkg.candidate
            origins = getattr(cand, "origins", []) if cand else []
            sites = [
                (getattr(o, "site", "") or "").strip()
                for o in origins
                if (getattr(o, "site", "") or "").strip()
            ]

            homepage = (getattr(inst, "homepage", "") or "").strip()
            summary = (getattr(inst, "summary", "") or "").strip()
            section = (getattr(inst, "section", "") or "").strip()
            record = getattr(inst, "record", {}) or {}
            maintainer = str(record.get("Maintainer", "")).strip()

            desktop_info = desktop_by_pkg.get(name)
            desktop_path = desktop_info[0] if desktop_info else None
            exec_path = desktop_info[1] if desktop_info else None

            if not sites:
                # Pacote instalado localmente via .deb sem repositório APT remoto
                # Ignora bibliotecas puras de sistema (lib*) que não possuem .desktop nem /opt
                if (
                    name.startswith("lib")
                    and not desktop_path
                    and not self.resolver.is_gui_application(name)
                ):
                    continue

                is_tracked = name in configured_direct_sources
                src_cfg = configured_direct_sources.get(name, {})

                display_name, icon_name, icon_path = self.resolver.resolve(
                    name, fallback_name=name, category="direct_deb"
                )
                discovered[name] = DiscoveredApp(
                    pkg_name=name,
                    display_name=display_name,
                    installed_version=inst.version,
                    summary=summary or "Pacote .deb instalado manualmente no sistema",
                    homepage=homepage or src_cfg.get("homepage", ""),
                    maintainer=maintainer,
                    section=section,
                    icon_name=icon_name,
                    icon_path=icon_path,
                    install_kind="orphan_deb",
                    current_source_status="tracked_direct" if is_tracked else "untracked",
                    current_source_name=src_cfg.get("source_name", "Sem fonte vinculada"),
                    current_source_host=src_cfg.get("source_host", ""),
                    desktop_file=desktop_path,
                    exec_path=exec_path,
                )
            else:
                # Possui repositório APT configurado; verifica se já está em DirectSources ou se é repo oficial de terceiros
                site = sites[0]
                is_tp = "debian.org" not in site and "ubuntu.com" not in site
                if name in configured_direct_sources:
                    src_cfg = configured_direct_sources[name]
                    display_name, icon_name, icon_path = self.resolver.resolve(
                        name, fallback_name=name, category="direct_deb"
                    )
                    discovered[name] = DiscoveredApp(
                        pkg_name=name,
                        display_name=display_name,
                        installed_version=inst.version,
                        summary=summary,
                        homepage=homepage or src_cfg.get("homepage", ""),
                        maintainer=maintainer,
                        section=section,
                        icon_name=icon_name,
                        icon_path=icon_path,
                        install_kind="orphan_deb",
                        current_source_status="tracked_direct",
                        current_source_name=src_cfg.get("source_name", "Fonte Direta"),
                        current_source_host=src_cfg.get("source_host", ""),
                        desktop_file=desktop_path,
                        exec_path=exec_path,
                    )
                elif is_tp and (
                    self.resolver.is_gui_application(name) or desktop_path is not None
                ):
                    display_name, icon_name, icon_path = self.resolver.resolve(
                        name, fallback_name=name, category="app_repo"
                    )
                    src_label = SITE_LABELS.get(site, site)
                    discovered[name] = DiscoveredApp(
                        pkg_name=name,
                        display_name=display_name,
                        installed_version=inst.version,
                        summary=summary,
                        homepage=homepage,
                        maintainer=maintainer,
                        section=section,
                        icon_name=icon_name,
                        icon_path=icon_path,
                        install_kind="apt_repo",
                        current_source_status="tracked_apt",
                        current_source_name=src_label,
                        current_source_host=site,
                        desktop_file=desktop_path,
                        exec_path=exec_path,
                    )

        # 2. Entradas .desktop autônomas (AppImages ou binários em /opt sem pacote dpkg)
        for slug, info in standalone_desktops.items():
            if slug in discovered:
                continue
            is_appimage = "appimage" in (info["exec_path"] or "").lower()
            kind = "appimage" if is_appimage else "opt_binary"
            is_tracked = slug in configured_direct_sources
            src_cfg = configured_direct_sources.get(slug, {})
            discovered[slug] = DiscoveredApp(
                pkg_name=slug,
                display_name=info["name"],
                installed_version=info["version"] or "instalado",
                summary=info["comment"] or f"Aplicativo instalado em {info['exec_path']}",
                homepage=src_cfg.get("homepage", ""),
                maintainer="",
                section="standalone",
                icon_name=info["icon_name"],
                icon_path=info["icon_path"],
                install_kind=kind,
                current_source_status="tracked_direct" if is_tracked else "untracked",
                current_source_name=src_cfg.get("source_name", "Sem fonte vinculada"),
                current_source_host=src_cfg.get("source_host", ""),
                desktop_file=info["desktop_file"],
                exec_path=info["exec_path"],
            )

        # 3. Varredura de arquivos .AppImage em pastas comuns do usuário
        for appimage_app in self._scan_user_appimages(configured_direct_sources):
            if appimage_app.pkg_name not in discovered:
                discovered[appimage_app.pkg_name] = appimage_app

        # Ordenar: primeiro os não rastreados ('untracked'), depois 'tracked_direct', depois 'tracked_apt'
        status_order = {
            "untracked": 0,
            "tracked_direct": 1,
            "tracked_apt": 2,
            "tracked_flatpak": 3,
        }
        result = list(discovered.values())
        result.sort(
            key=lambda x: (
                status_order.get(x.current_source_status, 9),
                x.display_name.lower(),
            )
        )
        return result

    def _scan_desktop_entries(
        self,
    ) -> Tuple[Dict[str, Tuple[str, str]], Dict[str, Dict[str, Optional[str]]]]:
        """
        Retorna:
        - desktop_by_pkg: mapeia pkg_name -> (desktop_file_path, exec_bin_path)
        - standalone_desktops: entradas .desktop em /opt ou ~/.local que não pertencem a pacotes dpkg
        """
        search_dirs = [
            "/usr/share/applications",
            "/usr/local/share/applications",
            os.path.expanduser("~/.local/share/applications"),
        ]
        entries: List[Dict[str, str]] = []
        paths_to_query: Set[str] = set()

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
                    comment = (
                        de.get("Comment[pt_BR]")
                        or de.get("Comment[pt]")
                        or de.get("Comment")
                        or ""
                    ).strip()
                    icon = (de.get("Icon") or "").strip()
                    exec_raw = (de.get("Exec") or "").strip()
                    version = (de.get("X-AppImage-Version") or "").strip()

                    exec_bin = self._extract_exec_binary(exec_raw)
                    paths_to_query.add(path)
                    if exec_bin and exec_bin.startswith("/"):
                        paths_to_query.add(exec_bin)

                    entries.append(
                        {
                            "desktop_file": path,
                            "name": name,
                            "comment": comment,
                            "icon": icon,
                            "exec_bin": exec_bin,
                            "version": version,
                        }
                    )
                except Exception:
                    continue

        owner_map = self._batch_dpkg_owners(list(paths_to_query))
        desktop_by_pkg: Dict[str, Tuple[str, str]] = {}
        standalone_desktops: Dict[str, Dict[str, Optional[str]]] = {}

        for e in entries:
            dpath = e["desktop_file"]
            ebin = e["exec_bin"]
            pkg = owner_map.get(dpath) or (owner_map.get(ebin) if ebin else None)
            if pkg:
                desktop_by_pkg[pkg] = (dpath, ebin)
            else:
                # Verifica se é um AppImage ou executável em /opt instalado fora do dpkg
                if ebin and (
                    ebin.startswith("/opt/")
                    or ".appimage" in ebin.lower()
                    or ebin.startswith(os.path.expanduser("~"))
                ) and os.path.exists(ebin):
                    slug = os.path.splitext(os.path.basename(dpath))[0].lower()
                    icon_val = e["icon"]
                    icon_name = "application-x-executable"
                    icon_path = None
                    if icon_val.startswith("/") and os.path.exists(icon_val):
                        icon_path = icon_val
                    elif icon_val:
                        icon_name = icon_val
                    standalone_desktops[slug] = {
                        "desktop_file": dpath,
                        "name": e["name"] or slug,
                        "comment": e["comment"],
                        "icon_name": icon_name,
                        "icon_path": icon_path,
                        "exec_path": ebin,
                        "version": e["version"],
                    }

        return desktop_by_pkg, standalone_desktops

    @staticmethod
    def _extract_exec_binary(exec_cmd: str) -> str:
        if not exec_cmd:
            return ""
        tokens = exec_cmd.split()
        for tok in tokens:
            cleaned = tok.strip("\"'")
            if cleaned == "env" or "=" in cleaned or cleaned.startswith("-"):
                continue
            return cleaned
        return ""

    @staticmethod
    def _batch_dpkg_owners(paths: List[str]) -> Dict[str, str]:
        if not paths:
            return {}
        owners: Dict[str, str] = {}
        try:
            proc = subprocess.run(
                ["dpkg-query", "-S"] + paths,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=6,
            )
            for line in proc.stdout.splitlines():
                if ": " in line:
                    pkg_part, path_part = line.split(": ", 1)
                    pkg_name = pkg_part.split(":")[0].strip()
                    owners[path_part.strip()] = pkg_name
        except Exception:
            pass
        return owners

    @staticmethod
    def _scan_user_appimages(
        configured_direct_sources: Dict[str, Dict[str, Any]]
    ) -> List[DiscoveredApp]:
        folders = [
            os.path.expanduser("~/Applications"),
            os.path.expanduser("~/.local/bin"),
        ]
        found: List[DiscoveredApp] = []
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            for fname in os.listdir(folder):
                if not fname.lower().endswith(".appimage"):
                    continue
                full_path = os.path.join(folder, fname)
                if not os.path.isfile(full_path):
                    continue
                stem = os.path.splitext(fname)[0]
                m = re.match(r"^([A-Za-z0-9._-]+?)[-_]v?(\d+\.\d+(?:\.\d+)?)", stem)
                if m:
                    raw_name, ver = m.group(1), m.group(2)
                else:
                    raw_name, ver = stem, "instalado"
                slug = raw_name.lower()
                is_tracked = slug in configured_direct_sources
                src_cfg = configured_direct_sources.get(slug, {})
                found.append(
                    DiscoveredApp(
                        pkg_name=slug,
                        display_name=raw_name.replace("-", " ").replace("_", " ").title(),
                        installed_version=ver,
                        summary=f"AppImage em {full_path}",
                        homepage=src_cfg.get("homepage", ""),
                        maintainer="",
                        section="appimage",
                        icon_name="application-x-executable",
                        icon_path=None,
                        install_kind="appimage",
                        current_source_status="tracked_direct" if is_tracked else "untracked",
                        current_source_name=src_cfg.get("source_name", "Sem fonte vinculada"),
                        current_source_host=src_cfg.get("source_host", ""),
                        desktop_file=None,
                        exec_path=full_path,
                    )
                )
        return found

