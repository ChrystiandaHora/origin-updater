from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import tempfile
from typing import Callable, List, Tuple

from .desktop_resolver import DesktopResolver
from .models import UpdateItem
from .providers.apt_provider import AptProvider
from .providers.direct_provider import DirectProvider
from .providers.flatpak_provider import FlatpakProvider


LogCallback = Callable[[str, bool], None]  # (text, is_replace_progress_line)
StatusCallback = Callable[[str, float], None]  # (message, fraction)

WORKER_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "privileged_worker.py"
)


class UpdaterEngine:
    """Motor de verificação, sincronização de fontes originais e instalação de atualizações."""

    def __init__(self) -> None:
        self.resolver = DesktopResolver()
        self.apt_provider = AptProvider(self.resolver)
        self.flatpak_provider = FlatpakProvider(self.resolver)
        self.direct_provider = DirectProvider(self.resolver)

    def scan_all(
        self, status_cb: StatusCallback = lambda msg, frac: None
    ) -> Tuple[List[UpdateItem], List[UpdateItem]]:
        status_cb("Consultando fontes originais (APT, Flathub e APIs oficiais)...", 0.15)
        self.resolver = DesktopResolver()
        self.apt_provider.resolver = self.resolver
        self.flatpak_provider.resolver = self.resolver
        self.direct_provider.resolver = self.resolver

        with ThreadPoolExecutor(max_workers=3) as pool:
            fut_direct = pool.submit(self.direct_provider.scan)
            fut_apt = pool.submit(self.apt_provider.scan)
            fut_flatpak = pool.submit(self.flatpak_provider.scan)

            direct_upd, direct_ok = fut_direct.result()
            status_cb("Fontes diretas verificadas. Lendo repositórios APT...", 0.50)
            apt_upd, apt_ok = fut_apt.result()
            status_cb("Verificando atualizações no Flathub...", 0.80)
            fp_upd, fp_ok = fut_flatpak.result()

        app_repo_upd = [x for x in apt_upd if x.source_category == "app_repo"]
        sys_upd = [x for x in apt_upd if x.source_category == "system"]

        all_updates = direct_upd + app_repo_upd + fp_upd + sys_upd
        all_up_to_date = direct_ok + apt_ok + fp_ok

        status_cb("Verificação concluída.", 1.0)
        return all_updates, all_up_to_date

    def sync_repositories(
        self, log_cb: LogCallback, status_cb: StatusCallback
    ) -> bool:
        manifest = {"mode": "sync"}
        return self._execute_worker_manifest(manifest, log_cb, status_cb)

    def apply_updates(
        self,
        selected_items: List[UpdateItem],
        log_cb: LogCallback,
        status_cb: StatusCallback,
    ) -> bool:
        if not selected_items:
            return True

        apt_packages = [
            x.pkg_name
            for x in selected_items
            if x.source_category in ("app_repo", "system")
        ]
        direct_items = [
            {
                "pkg_name": x.pkg_name,
                "display_name": x.display_name,
                "new_version": x.new_version,
                "download_url": x.download_url,
                "source_host": x.source_host,
            }
            for x in selected_items
            if x.source_category == "direct_deb"
        ]
        flatpak_items = [
            {
                "pkg_name": x.pkg_name,
                "display_name": x.display_name,
                "branch": x.flatpak_branch,
                "installation": x.flatpak_installation,
            }
            for x in selected_items
            if x.source_category == "flatpak"
        ]

        manifest = {
            "mode": "update",
            "apt_packages": apt_packages,
            "direct_items": direct_items,
            "flatpak_items": flatpak_items,
        }
        return self._execute_worker_manifest(manifest, log_cb, status_cb)

    def _execute_worker_manifest(
        self,
        manifest: dict,
        log_cb: LogCallback,
        status_cb: StatusCallback,
    ) -> bool:
        fd, manifest_path = tempfile.mkstemp(
            prefix="atualizador-manifest-", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            os.chmod(manifest_path, 0o644)

            status_cb(
                "Solicitando permissão de administrador (pkexec) para iniciar...",
                0.03,
            )
            log_cb(
                "🔐 Aguardando autorização de administrador (janela de senha do sistema)...\n\n",
                False,
            )

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            proc = subprocess.Popen(
                ["pkexec", "/usr/bin/python3", "-u", WORKER_PATH, manifest_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\r\n")
                if line.startswith("@@STATUS|"):
                    parts = line.split("|", 2)
                    if len(parts) == 3:
                        try:
                            frac = float(parts[1])
                        except ValueError:
                            frac = 0.5
                        status_cb(parts[2], frac)
                elif line.startswith("@@PROGRESS_LINE|"):
                    text = line.split("|", 1)[1]
                    log_cb(text, True)
                else:
                    log_cb(line + "\n", False)

            rc = proc.wait()
            if rc == 126 or rc == 127:
                log_cb(
                    "\n❌ Autorização cancelada ou recusada pelo usuário.\n",
                    False,
                )
                status_cb("Operação cancelada (autorização não concedida).", 0.0)
                return False
            return rc == 0
        finally:
            try:
                os.remove(manifest_path)
            except OSError:
                pass
