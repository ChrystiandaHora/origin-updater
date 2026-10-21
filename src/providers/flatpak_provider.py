import shutil
import subprocess
from typing import Dict, List, Tuple

from ..desktop_resolver import DesktopResolver
from ..models import UpdateItem


class FlatpakProvider:
    """Verifica aplicativos e runtimes instalados via Flatpak (Flathub e outros remotos)."""

    def __init__(self, resolver: DesktopResolver) -> None:
        self.resolver = resolver

    def scan(self) -> Tuple[List[UpdateItem], List[UpdateItem]]:
        if not shutil.which("flatpak"):
            return [], []

        installed_map: Dict[Tuple[str, str], Dict[str, str]] = {}
        try:
            out_list = subprocess.check_output(
                [
                    "flatpak",
                    "list",
                    "--columns=name,application,version,branch,origin,installation,description",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            for line in out_list.splitlines():
                if not line.strip():
                    continue
                parts = line.split("\t")
                while len(parts) < 7:
                    parts.append("")
                name, app_id, ver, branch, origin, inst, desc = [
                    p.strip() for p in parts[:7]
                ]
                installed_map[(app_id, branch)] = {
                    "name": name or app_id,
                    "version": ver or branch or "instalado",
                    "origin": origin or "flathub",
                    "installation": inst or "system",
                    "description": desc or f"Pacote Flatpak ({branch})",
                }
        except Exception:
            pass

        updates: List[UpdateItem] = []
        updated_keys = set()

        try:
            out_upd = subprocess.check_output(
                [
                    "flatpak",
                    "remote-ls",
                    "--updates",
                    "--columns=name,application,version,branch,origin,download-size",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=25,
            )
            for line in out_upd.splitlines():
                if not line.strip():
                    continue
                parts = line.split("\t")
                while len(parts) < 6:
                    parts.append("")
                name, app_id, new_ver, branch, origin, dl_size = [
                    p.strip() for p in parts[:6]
                ]
                if not app_id:
                    continue

                key = (app_id, branch)
                updated_keys.add(key)
                inst_info = installed_map.get(key, {})
                old_ver = inst_info.get("version") or branch or "atual"
                disp_ver = new_ver or f"{branch} (nova build)"
                if disp_ver == old_ver:
                    disp_ver = f"{new_ver or branch} (nova build no Flathub)"

                display_name, icon_name, icon_path = self.resolver.resolve(
                    app_id, fallback_name=name or inst_info.get("name") or app_id, category="flatpak"
                )
                origin_label = "Flathub Oficial" if origin.lower() == "flathub" else origin

                item = UpdateItem(
                    id=f"flatpak:{app_id}:{branch}",
                    pkg_name=app_id,
                    display_name=display_name,
                    summary=inst_info.get("description") or f"Flatpak ({branch}) via {origin_label}",
                    installed_version=old_ver,
                    new_version=disp_ver,
                    source_category="flatpak",
                    source_name=origin_label,
                    source_host="dl.flathub.org" if origin.lower() == "flathub" else origin,
                    icon_name=icon_name,
                    icon_path=icon_path,
                    download_size=0,
                    download_size_str=dl_size.replace("\xa0", " "),
                    homepage_url=f"https://flathub.org/apps/{app_id}",
                    has_update=True,
                    selected=True,
                    flatpak_branch=branch,
                    flatpak_installation=inst_info.get("installation", "system"),
                )
                updates.append(item)
        except Exception:
            pass

        up_to_date: List[UpdateItem] = []
        for (app_id, branch), info in installed_map.items():
            if (app_id, branch) in updated_keys:
                continue
            display_name, icon_name, icon_path = self.resolver.resolve(
                app_id, fallback_name=info["name"], category="flatpak"
            )
            origin = info["origin"]
            origin_label = "Flathub Oficial" if origin.lower() == "flathub" else origin
            up_to_date.append(
                UpdateItem(
                    id=f"flatpak:{app_id}:{branch}",
                    pkg_name=app_id,
                    display_name=display_name,
                    summary=info["description"],
                    installed_version=info["version"],
                    new_version=info["version"],
                    source_category="flatpak",
                    source_name=origin_label,
                    source_host="dl.flathub.org" if origin.lower() == "flathub" else origin,
                    icon_name=icon_name,
                    icon_path=icon_path,
                    has_update=False,
                    selected=False,
                    flatpak_branch=branch,
                    flatpak_installation=info["installation"],
                )
            )

        updates.sort(key=lambda x: x.display_name.lower())
        up_to_date.sort(key=lambda x: x.display_name.lower())
        return updates, up_to_date
