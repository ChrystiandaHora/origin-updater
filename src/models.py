from dataclasses import dataclass, field
from typing import Optional


@dataclass
class UpdateItem:
    """Representa um aplicativo ou pacote verificável/atualizável."""
    id: str                      # Identificador único (ex: apt:code, flatpak:org.gnome.Platform, direct:discord)
    pkg_name: str                # Nome técnico do pacote ou ID Flatpak
    display_name: str            # Nome amigável para exibição
    summary: str                 # Descrição curta
    installed_version: str       # Versão atualmente instalada
    new_version: str             # Nova versão disponível na fonte original
    source_category: str         # 'app_repo', 'direct_deb', 'flatpak', 'system'
    source_name: str             # Nome amigável da fonte (ex: 'Microsoft VS Code Repo', 'GitHub Oficial', 'Flathub')
    source_host: str             # Domínio/host da fonte original (ex: 'packages.microsoft.com', 'github.com/dbeaver/dbeaver')
    icon_name: str = "package-x-generic"
    icon_path: Optional[str] = None
    download_size: int = 0       # Tamanho em bytes (se conhecido)
    download_size_str: str = ""  # Tamanho formatado (ex: '85.4 MB')
    download_url: Optional[str] = None  # URL direta do .deb para source_category == 'direct_deb'
    homepage_url: Optional[str] = None
    has_update: bool = True
    selected: bool = True
    flatpak_branch: Optional[str] = None
    flatpak_installation: str = "system"

    @property
    def category_badge_label(self) -> str:
        if self.source_category == "direct_deb":
            return f"Fonte Direta • {self.source_name}"
        if self.source_category == "app_repo":
            return f"Repo Oficial • {self.source_name}"
        if self.source_category == "flatpak":
            return f"Flatpak • {self.source_name}"
        return f"Sistema • {self.source_name}"

    @property
    def category_css_class(self) -> str:
        if self.source_category == "direct_deb":
            return "badge-direct"
        if self.source_category == "app_repo":
            return "badge-app-repo"
        if self.source_category == "flatpak":
            return "badge-flatpak"
        return "badge-system"


def format_size(size_bytes: int) -> str:
    if not size_bytes or size_bytes <= 0:
        return ""
    units = ["B", "KB", "MB", "GB"]
    val = float(size_bytes)
    for unit in units:
        if val < 1024.0 or unit == units[-1]:
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return ""
