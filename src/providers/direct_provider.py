from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import urllib.request
import apt
import apt_pkg

from ..desktop_resolver import DesktopResolver
from ..models import UpdateItem, format_size

apt_pkg.init_system()

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AtualizadorApps/1.0"
CUSTOM_SOURCES_PATH = os.path.expanduser(
    "~/.config/atualizador-apps/custom_sources.json"
)

# Catálogo nativo base de fontes oficiais diretas para apps instalados via .deb avulso
BUILTIN_DIRECT_SOURCES: Dict[str, Dict[str, Any]] = {
    "discord": {
        "type": "redirect_deb",
        "source_name": "Discord Oficial",
        "source_host": "discord.com",
        "url": "https://discord.com/api/download?platform=linux&format=deb",
        "version_regex": r"discord-([0-9]+\.[0-9]+\.[0-9]+)\.deb",
        "homepage": "https://discord.com",
    },
    "dbeaver-ce": {
        "type": "github_release",
        "source_name": "GitHub Oficial (dbeaver/dbeaver)",
        "source_host": "github.com/dbeaver/dbeaver",
        "repo": "dbeaver/dbeaver",
        "asset_pattern": r"dbeaver-ce-.*-linux-x86_64\.deb$|dbeaver-ce_.*_amd64\.deb$",
        "fallback_deb_url": "https://dbeaver.io/files/dbeaver-ce_latest_amd64.deb",
        "homepage": "https://dbeaver.io",
    },
    "rustdesk": {
        "type": "github_release",
        "source_name": "GitHub Oficial (rustdesk/rustdesk)",
        "source_host": "github.com/rustdesk/rustdesk",
        "repo": "rustdesk/rustdesk",
        "asset_pattern": r"^rustdesk-[0-9.]+-x86_64\.deb$",
        "homepage": "https://rustdesk.com",
    },
    "docker-desktop": {
        "type": "docker_desktop",
        "source_name": "Docker Oficial (Release Notes)",
        "source_host": "desktop.docker.com",
        "notes_url": "https://docs.docker.com/desktop/release-notes/",
        "deb_url": "https://desktop.docker.com/linux/main/amd64/docker-desktop-amd64.deb",
        "homepage": "https://docs.docker.com/desktop/release-notes/",
    },
}


class DirectProvider:
    """
    Verifica atualizações buscando diretamente nas fontes oficiais na web (GitHub Releases,
    APIs oficiais de download e índices de repositórios diretos) para pacotes .deb instalados manualmente.
    """

    def __init__(self, resolver: DesktopResolver) -> None:
        self.resolver = resolver

    def get_configured_sources(self) -> Dict[str, Dict[str, Any]]:
        sources = dict(BUILTIN_DIRECT_SOURCES)
        if os.path.exists(CUSTOM_SOURCES_PATH):
            try:
                with open(CUSTOM_SOURCES_PATH, "r", encoding="utf-8") as f:
                    custom = json.load(f)
                if isinstance(custom, dict):
                    sources.update(custom)
            except Exception:
                pass
        return sources

    def save_discovered_source(
        self, pkg_name: str, source_config: Dict[str, Any]
    ) -> None:
        """Persiste uma configuração de fonte direta descoberta pelo SourceFinder."""
        os.makedirs(os.path.dirname(CUSTOM_SOURCES_PATH), exist_ok=True)
        custom: Dict[str, Any] = {}
        if os.path.exists(CUSTOM_SOURCES_PATH):
            try:
                with open(CUSTOM_SOURCES_PATH, "r", encoding="utf-8") as f:
                    custom = json.load(f)
            except Exception:
                custom = {}
        custom[pkg_name.strip()] = source_config
        with open(CUSTOM_SOURCES_PATH, "w", encoding="utf-8") as f:
            json.dump(custom, f, indent=2, ensure_ascii=False)

    def save_custom_github_source(
        self,
        pkg_name: str,
        github_repo: str,
        asset_pattern: str = r".*amd64\.deb$|.*x86_64\.deb$|.*_all\.deb$",
    ) -> None:
        clean_repo = github_repo.strip()
        if "github.com/" in clean_repo:
            clean_repo = clean_repo.split("github.com/", 1)[1].strip("/")
            parts = clean_repo.split("/")
            if len(parts) >= 2:
                clean_repo = f"{parts[0]}/{parts[1]}"

        cfg = {
            "type": "github_release",
            "source_name": f"GitHub Oficial ({clean_repo})",
            "source_host": f"github.com/{clean_repo}",
            "repo": clean_repo,
            "asset_pattern": asset_pattern,
            "homepage": f"https://github.com/{clean_repo}/releases",
        }
        self.save_discovered_source(pkg_name, cfg)

    def remove_custom_source(self, pkg_name: str) -> bool:
        if not os.path.exists(CUSTOM_SOURCES_PATH):
            return False
        try:
            with open(CUSTOM_SOURCES_PATH, "r", encoding="utf-8") as f:
                custom = json.load(f)
            if pkg_name in custom:
                del custom[pkg_name]
                with open(CUSTOM_SOURCES_PATH, "w", encoding="utf-8") as f:
                    json.dump(custom, f, indent=2, ensure_ascii=False)
                return True
        except Exception:
            pass
        return False

    def scan(self) -> Tuple[List[UpdateItem], List[UpdateItem]]:
        cache = apt.Cache()
        sources = self.get_configured_sources()

        installed_targets: List[Tuple[str, str, str, Dict[str, Any]]] = []
        for pkg_name, cfg in sources.items():
            if pkg_name in cache and cache[pkg_name].is_installed and cache[pkg_name].installed:
                inst = cache[pkg_name].installed
                installed_targets.append(
                    (pkg_name, inst.version, inst.summary or "", cfg)
                )

        updates: List[UpdateItem] = []
        up_to_date: List[UpdateItem] = []

        if not installed_targets:
            return updates, up_to_date

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(self._check_one, pkg_name, inst_ver, summary, cfg)
                for pkg_name, inst_ver, summary, cfg in installed_targets
            ]
            for fut in futures:
                try:
                    item = fut.result(timeout=12)
                    if item:
                        if item.has_update:
                            updates.append(item)
                        else:
                            up_to_date.append(item)
                except Exception:
                    continue

        updates.sort(key=lambda x: x.display_name.lower())
        up_to_date.sort(key=lambda x: x.display_name.lower())
        return updates, up_to_date

    def _check_one(
        self, pkg_name: str, inst_ver: str, summary: str, cfg: Dict[str, Any]
    ) -> Optional[UpdateItem]:
        stype = cfg.get("type")
        new_ver: Optional[str] = None
        dl_url: Optional[str] = None
        dl_size: int = 0

        if stype == "redirect_deb":
            new_ver, dl_url, dl_size = self._check_redirect(cfg)
        elif stype == "github_release":
            new_ver, dl_url, dl_size = self._check_github(cfg)
        elif stype == "docker_desktop":
            new_ver, dl_url, dl_size = self._check_docker_desktop(cfg)
        elif stype == "apt_repo_deb":
            new_ver, dl_url, dl_size = self._check_apt_repo_deb(cfg)

        if not new_ver:
            return None

        # Para comparação com pacotes como docker-desktop (ex: 4.81.0-232925 vs 4.91.0)
        clean_installed = inst_ver.split("-")[0] if stype == "docker_desktop" else inst_ver
        clean_new = new_ver.lstrip("vV").strip()

        has_upd = apt_pkg.version_compare(clean_new, clean_installed) > 0
        display_name, icon_name, icon_path = self.resolver.resolve(
            pkg_name, fallback_name=pkg_name, category="direct_deb"
        )

        return UpdateItem(
            id=f"direct:{pkg_name}",
            pkg_name=pkg_name,
            display_name=display_name,
            summary=summary or f"Aplicativo monitorado direto na fonte ({cfg.get('source_name')})",
            installed_version=inst_ver,
            new_version=clean_new,
            source_category="direct_deb",
            source_name=cfg.get("source_name", "Fonte Oficial Direta"),
            source_host=cfg.get("source_host", "web"),
            icon_name=icon_name,
            icon_path=icon_path,
            download_size=dl_size,
            download_size_str=format_size(dl_size),
            download_url=dl_url,
            homepage_url=cfg.get("homepage"),
            has_update=has_upd,
            selected=has_upd,
        )

    @staticmethod
    def _check_redirect(cfg: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], int]:
        url = cfg["url"]
        req = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            final_url = resp.url
            clen = int(resp.headers.get("Content-Length", "0") or 0)
            m = re.search(cfg.get("version_regex", r"([0-9]+\.[0-9]+\.[0-9]+)"), final_url)
            if m:
                return m.group(1), final_url, clen
        return None, None, 0

    @staticmethod
    def _check_github(cfg: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], int]:
        repo = cfg["repo"]
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = (data.get("tag_name") or "").lstrip("vV").strip()
        if not tag:
            return None, None, 0

        pattern = re.compile(cfg.get("asset_pattern", r".*\.deb$"))
        for asset in data.get("assets", []):
            aname = asset.get("name", "")
            if pattern.search(aname):
                return (
                    tag,
                    asset.get("browser_download_url"),
                    int(asset.get("size", 0) or 0),
                )

        if cfg.get("fallback_deb_url"):
            return tag, cfg["fallback_deb_url"], 0
        return None, None, 0

    @staticmethod
    def _check_docker_desktop(
        cfg: Dict[str, Any],
    ) -> Tuple[Optional[str], Optional[str], int]:
        req = urllib.request.Request(
            cfg["notes_url"], headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r"Docker Desktop (\d+\.\d+\.\d+)", html)
        if not m:
            return None, None, 0
        ver = m.group(1)
        deb_url = cfg["deb_url"]
        size = 0
        try:
            hreq = urllib.request.Request(
                deb_url, method="HEAD", headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(hreq, timeout=5) as hresp:
                size = int(hresp.headers.get("Content-Length", "0") or 0)
        except Exception:
            pass
        return ver, deb_url, size

    @staticmethod
    def _check_apt_repo_deb(
        cfg: Dict[str, Any],
    ) -> Tuple[Optional[str], Optional[str], int]:
        req = urllib.request.Request(
            cfg["packages_url"], headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            text = resp.read().decode("utf-8", errors="ignore")

        target_pkg = cfg.get("target_pkg", "")
        best_ver: Optional[str] = None
        best_filename: Optional[str] = None
        best_size: int = 0

        for block in text.split("\n\n"):
            if not block.strip():
                continue
            pkg_val = ""
            ver_val = ""
            file_val = ""
            size_val = 0
            for line in block.splitlines():
                if line.startswith("Package:"):
                    pkg_val = line.split(":", 1)[1].strip()
                elif line.startswith("Version:"):
                    ver_val = line.split(":", 1)[1].strip()
                elif line.startswith("Filename:"):
                    file_val = line.split(":", 1)[1].strip()
                elif line.startswith("Size:"):
                    try:
                        size_val = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        size_val = 0
            if pkg_val == target_pkg and ver_val and file_val:
                if best_ver is None or apt_pkg.version_compare(ver_val, best_ver) > 0:
                    best_ver = ver_val
                    best_filename = file_val
                    best_size = size_val

        if best_ver and best_filename:
            dl_url = urllib.parse.urljoin(cfg["base_repo_url"], best_filename)
            return best_ver, dl_url, best_size
        return None, None, 0
