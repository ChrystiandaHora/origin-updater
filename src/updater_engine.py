from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import tempfile
from typing import Callable, Dict, List, Tuple

from .desktop_resolver import DesktopResolver
from .discovery import AppScanner, DiscoveredApp, DiscoveredSource, SourceFinder
from .models import UpdateItem
from .providers.apt_provider import AptProvider
from .providers.direct_provider import BUILTIN_DIRECT_SOURCES, DirectProvider
from .providers.flatpak_provider import FlatpakProvider


LogCallback = Callable[[str, bool], None]  # (text, is_replace_progress_line)
StatusCallback = Callable[[str, float], None]  # (message, fraction)

WORKER_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "privileged_worker.py"
)


class UpdaterEngine:
    """Motor de verificação, descoberta de fontes, sincronização e instalação de atualizações."""

    def __init__(self) -> None:
        self.resolver = DesktopResolver()
        self.apt_provider = AptProvider(self.resolver)
        self.flatpak_provider = FlatpakProvider(self.resolver)
        self.direct_provider = DirectProvider(self.resolver)
        self.app_scanner = AppScanner(self.resolver)
        self.source_finder = SourceFinder()

    def discover_apps_and_sources(
        self,
        status_cb: StatusCallback = lambda msg, frac: None,
        force_refresh: bool = False,
        auto_link_high_confidence: bool = False,
    ) -> Tuple[List[DiscoveredApp], Dict[str, DiscoveredSource]]:
        """
        Varre a máquina em busca de todos os aplicativos instalados e descobre
        automaticamente as fontes de atualização para aplicativos sem repositório APT.
        """
        status_cb("Varrendo aplicativos instalados na máquina Linux...", 0.10)
        self.resolver = DesktopResolver()
        self.app_scanner.resolver = self.resolver

        configured = self.direct_provider.get_configured_sources()
        apps = self.app_scanner.scan_machine(configured)

        # Seleciona apps que precisam de descoberta (ou todos os órfãos se force_refresh=True)
        targets = [
            a
            for a in apps
            if a.needs_source_discovery
            or (
                force_refresh
                and a.install_kind in ("orphan_deb", "appimage", "opt_binary")
                and a.pkg_name not in BUILTIN_DIRECT_SOURCES
            )
        ]

        discovered_sources: Dict[str, DiscoveredSource] = {}
        if targets:
            total = len(targets)
            done = 0

            def _work(app: DiscoveredApp) -> Tuple[str, DiscoveredSource]:
                return app.pkg_name, self.source_finder.find_source_for_app(
                    app, use_cache=not force_refresh
                )

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(_work, app) for app in targets]
                for fut in futures:
                    try:
                        pkg_name, src = fut.result(timeout=20)
                        discovered_sources[pkg_name] = src
                    except Exception:
                        pass
                    done += 1
                    status_cb(
                        f"Buscando fontes oficiais na web ({done}/{total})...",
                        0.15 + 0.75 * (done / max(1, total)),
                    )
            self.source_finder._save_cache()

        if auto_link_high_confidence:
            linked_any = False
            for pkg_name, src in discovered_sources.items():
                if src.is_installable_direct_source and src.confidence >= 0.85:
                    cfg = dict(src.config)
                    cfg["auto_discovered"] = True
                    cfg["discovery_method"] = src.discovery_method
                    self.direct_provider.save_discovered_source(pkg_name, cfg)
                    linked_any = True
            if linked_any:
                apps = self.app_scanner.scan_machine(
                    self.direct_provider.get_configured_sources()
                )

        status_cb("Varredura de aplicativos e fontes concluída.", 1.0)
        return apps, discovered_sources

    def scan_all(
        self, status_cb: StatusCallback = lambda msg, frac: None
    ) -> Tuple[List[UpdateItem], List[UpdateItem]]:
        status_cb("Varrendo aplicativos locais e descobrindo fontes oficiais...", 0.08)
        self.resolver = DesktopResolver()
        self.apt_provider.resolver = self.resolver
        self.flatpak_provider.resolver = self.resolver
        self.direct_provider.resolver = self.resolver
        self.app_scanner.resolver = self.resolver

        # Auto-descoberta silenciosa com cache para pacotes .deb órfãos recém-instalados
        try:
            configured = self.direct_provider.get_configured_sources()
            apps = self.app_scanner.scan_machine(configured)
            untracked = [a for a in apps if a.needs_source_discovery]
            if untracked:
                found_map = self.source_finder.discover_for_apps(
                    untracked, use_cache=True
                )
                for pkg_name, src in found_map.items():
                    if src.is_installable_direct_source and src.confidence >= 0.85:
                        cfg = dict(src.config)
                        cfg["auto_discovered"] = True
                        cfg["discovery_method"] = src.discovery_method
                        self.direct_provider.save_discovered_source(pkg_name, cfg)
        except Exception:
            pass

        status_cb("Consultando fontes originais (APT, Flathub e APIs oficiais)...", 0.20)

        with ThreadPoolExecutor(max_workers=3) as pool:
            fut_direct = pool.submit(self.direct_provider.scan)
            fut_apt = pool.submit(self.apt_provider.scan)
            fut_flatpak = pool.submit(self.flatpak_provider.scan)

            direct_upd, direct_ok = fut_direct.result()
            status_cb("Fontes diretas verificadas. Lendo repositórios APT...", 0.55)
            apt_upd, apt_ok = fut_apt.result()
            status_cb("Verificando atualizações no Flathub...", 0.82)
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
