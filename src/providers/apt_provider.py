from typing import Dict, List, Tuple
import apt

from ..desktop_resolver import DesktopResolver
from ..models import UpdateItem, format_size


# Mapeamento de domínios de repositórios para nomes amigáveis da fonte oficial
SITE_LABELS: Dict[str, str] = {
    "dl.google.com": "Google Oficial (Chrome)",
    "packages.microsoft.com": "Microsoft Oficial (VS Code)",
    "download.docker.com": "Docker Oficial",
    "repository.spotify.com": "Spotify Oficial",
    "deb.anydesk.com": "AnyDesk Oficial",
    "security.debian.org": "Debian Security Oficial",
    "deb.debian.org": "Debian Oficial",
}


class AptProvider:
    """Verifica pacotes instalados e atualizáveis nos repositórios APT configurados."""

    def __init__(self, resolver: DesktopResolver) -> None:
        self.resolver = resolver

    def scan(self) -> Tuple[List[UpdateItem], List[UpdateItem]]:
        """
        Retorna (updates, up_to_date_apps):
        - updates: todos os pacotes APT que possuem atualização disponível na fonte
        - up_to_date_apps: aplicativos principais/terceiros que já estão na última versão
        """
        updates: List[UpdateItem] = []
        up_to_date_apps: List[UpdateItem] = []

        cache = apt.Cache()
        for pkg in cache:
            if not pkg.is_installed or not pkg.installed:
                continue

            cand = pkg.candidate
            if not cand:
                continue

            source_name, source_host, is_third_party = self._extract_origin(cand)
            is_gui = self.resolver.is_gui_application(pkg.name)
            category = "app_repo" if (is_third_party or is_gui) else "system"

            display_name, icon_name, icon_path = self.resolver.resolve(
                pkg.name, fallback_name=pkg.name, category=category
            )

            size_bytes = getattr(cand, "size", 0) or 0
            homepage = getattr(cand, "homepage", None) or None

            if pkg.is_upgradable and pkg.installed.version != cand.version:
                item = UpdateItem(
                    id=f"apt:{pkg.name}",
                    pkg_name=pkg.name,
                    display_name=display_name,
                    summary=cand.summary or pkg.installed.summary or "",
                    installed_version=pkg.installed.version,
                    new_version=cand.version,
                    source_category=category,
                    source_name=source_name,
                    source_host=source_host,
                    icon_name=icon_name,
                    icon_path=icon_path,
                    download_size=size_bytes,
                    download_size_str=format_size(size_bytes),
                    homepage_url=homepage,
                    has_update=True,
                    selected=True,
                )
                updates.append(item)
            elif is_third_party and source_host:
                # Aplicativo de repositório oficial de terceiros já atualizado
                item = UpdateItem(
                    id=f"apt:{pkg.name}",
                    pkg_name=pkg.name,
                    display_name=display_name,
                    summary=cand.summary or pkg.installed.summary or "",
                    installed_version=pkg.installed.version,
                    new_version=cand.version,
                    source_category="app_repo",
                    source_name=source_name,
                    source_host=source_host,
                    icon_name=icon_name,
                    icon_path=icon_path,
                    download_size=0,
                    download_size_str="",
                    homepage_url=homepage,
                    has_update=False,
                    selected=False,
                )
                up_to_date_apps.append(item)

        # Ordena colocando apps principais e fontes de terceiros no topo
        updates.sort(
            key=lambda x: (
                0 if x.source_category == "app_repo" else 1,
                x.display_name.lower(),
            )
        )
        up_to_date_apps.sort(key=lambda x: x.display_name.lower())
        return updates, up_to_date_apps

    @staticmethod
    def _extract_origin(cand) -> Tuple[str, str, bool]:
        """Retorna (source_name, source_host, is_third_party)."""
        origins = getattr(cand, "origins", []) or []
        for orig in origins:
            site = (getattr(orig, "site", "") or "").strip()
            if not site:
                continue
            origin_label = (getattr(orig, "origin", "") or "").strip()
            archive = (getattr(orig, "archive", "") or "").strip()

            if site in SITE_LABELS:
                is_tp = site not in ("deb.debian.org", "security.debian.org")
                return SITE_LABELS[site], site, is_tp

            is_tp = "debian.org" not in site
            label = origin_label or archive or site
            return label, site, is_tp

        return ("Repositório Local / APT", "local", False)
