from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.parse
import urllib.request

from .app_scanner import DiscoveredApp

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) OriginUpdater/2.0"
DISCOVERY_CACHE_PATH = os.path.expanduser(
    "~/.config/atualizador-apps/discovery_cache.json"
)
CACHE_TTL_SECONDS = 86400 * 3  # 3 dias para entradas negativas

# Links genéricos do GitHub que não são repositórios de software
IGNORED_GITHUB_OWNERS = {
    "features",
    "orgs",
    "topics",
    "collections",
    "sponsors",
    "about",
    "pricing",
    "security",
    "login",
    "join",
    "settings",
    "marketplace",
    "apps",
    " enterprise",
}

# Catálogo expandido de fontes oficiais diretas para aplicativos populares no Linux
KNOWN_DIRECT_CATALOG: Dict[str, Dict[str, Any]] = {
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
    "forticlient": {
        "type": "apt_repo_deb",
        "source_name": "Repositório Oficial Fortinet (FortiClient 7.4)",
        "source_host": "repo.fortinet.com",
        "packages_url": "https://repo.fortinet.com/repo/forticlient/7.4/ubuntu22/dists/stable/non-free/binary-amd64/Packages",
        "base_repo_url": "https://repo.fortinet.com/repo/forticlient/7.4/ubuntu22/",
        "target_pkg": "forticlient",
        "homepage": "https://www.forticlient.com",
    },
    "obsidian": {
        "type": "github_release",
        "source_name": "GitHub Oficial (obsidianmd/obsidian-releases)",
        "source_host": "github.com/obsidianmd/obsidian-releases",
        "repo": "obsidianmd/obsidian-releases",
        "asset_pattern": r"obsidian_[0-9.]+_amd64\.deb$",
        "homepage": "https://obsidian.md",
    },
    "localsend": {
        "type": "github_release",
        "source_name": "GitHub Oficial (localsend/localsend)",
        "source_host": "github.com/localsend/localsend",
        "repo": "localsend/localsend",
        "asset_pattern": r"LocalSend-.*-linux-x86-64\.deb$",
        "homepage": "https://localsend.org",
    },
    "insomnia": {
        "type": "github_release",
        "source_name": "GitHub Oficial (Kong/insomnia)",
        "source_host": "github.com/Kong/insomnia",
        "repo": "Kong/insomnia",
        "asset_pattern": r"Insomnia\.Core-.*\.deb$",
        "homepage": "https://insomnia.rest",
    },
    "bitwarden": {
        "type": "github_release",
        "source_name": "GitHub Oficial (bitwarden/clients)",
        "source_host": "github.com/bitwarden/clients",
        "repo": "bitwarden/clients",
        "asset_pattern": r"Bitwarden-.*-amd64\.deb$",
        "homepage": "https://bitwarden.com",
    },
    "balena-etcher": {
        "type": "github_release",
        "source_name": "GitHub Oficial (balena-io/etcher)",
        "source_host": "github.com/balena-io/etcher",
        "repo": "balena-io/etcher",
        "asset_pattern": r"balena-etcher_.*_amd64\.deb$",
        "homepage": "https://etcher.balena.io",
    },
    "heroic": {
        "type": "github_release",
        "source_name": "GitHub Oficial (Heroic-Games-Launcher)",
        "source_host": "github.com/Heroic-Games-Launcher/HeroicGamesLauncher",
        "repo": "Heroic-Games-Launcher/HeroicGamesLauncher",
        "asset_pattern": r"heroic_.*_amd64\.deb$|Heroic-.*-linux-amd64\.deb$",
        "homepage": "https://heroicgameslauncher.com",
    },
    "vesktop": {
        "type": "github_release",
        "source_name": "GitHub Oficial (Vencord/Vesktop)",
        "source_host": "github.com/Vencord/Vesktop",
        "repo": "Vencord/Vesktop",
        "asset_pattern": r"vesktop_.*_amd64\.deb$",
        "homepage": "https://github.com/Vencord/Vesktop",
    },
    "ferdium": {
        "type": "github_release",
        "source_name": "GitHub Oficial (ferdium/ferdium-app)",
        "source_host": "github.com/ferdium/ferdium-app",
        "repo": "ferdium/ferdium-app",
        "asset_pattern": r"Ferdium-linux-.*-amd64\.deb$",
        "homepage": "https://ferdium.org",
    },
    "vscodium": {
        "type": "github_release",
        "source_name": "GitHub Oficial (VSCodium/vscodium)",
        "source_host": "github.com/VSCodium/vscodium",
        "repo": "VSCodium/vscodium",
        "asset_pattern": r"codium_.*_amd64\.deb$",
        "homepage": "https://vscodium.com",
    },
    "tabby-terminal": {
        "type": "github_release",
        "source_name": "GitHub Oficial (Eugeny/tabby)",
        "source_host": "github.com/Eugeny/tabby",
        "repo": "Eugeny/tabby",
        "asset_pattern": r"tabby-.*-linux-x64\.deb$",
        "homepage": "https://tabby.sh",
    },
    "beekeeper-studio": {
        "type": "github_release",
        "source_name": "GitHub Oficial (beekeeper-studio)",
        "source_host": "github.com/beekeeper-studio/beekeeper-studio",
        "repo": "beekeeper-studio/beekeeper-studio",
        "asset_pattern": r"beekeeper-studio_.*_amd64\.deb$",
        "homepage": "https://www.beekeeperstudio.io",
    },
    "ulauncher": {
        "type": "github_release",
        "source_name": "GitHub Oficial (Ulauncher/Ulauncher)",
        "source_host": "github.com/Ulauncher/Ulauncher",
        "repo": "Ulauncher/Ulauncher",
        "asset_pattern": r"ulauncher_.*_all\.deb$",
        "homepage": "https://ulauncher.io",
    },
    "logseq": {
        "type": "github_release",
        "source_name": "GitHub Oficial (logseq/logseq)",
        "source_host": "github.com/logseq/logseq",
        "repo": "logseq/logseq",
        "asset_pattern": r"Logseq-linux-x64-.*\.deb$",
        "homepage": "https://logseq.com",
    },
    "pulsar": {
        "type": "github_release",
        "source_name": "GitHub Oficial (pulsar-edit/pulsar)",
        "source_host": "github.com/pulsar-edit/pulsar",
        "repo": "pulsar-edit/pulsar",
        "asset_pattern": r"Linux\.pulsar_.*_amd64\.deb$",
        "homepage": "https://pulsar-edit.dev",
    },
    "zoom": {
        "type": "redirect_deb",
        "source_name": "Zoom Oficial",
        "source_host": "zoom.us",
        "url": "https://zoom.us/client/latest/zoom_amd64.deb",
        "version_regex": r"/prod/([0-9.]+)/zoom_amd64\.deb",
        "homepage": "https://zoom.us",
    },
    "code": {
        "type": "redirect_deb",
        "source_name": "Microsoft VS Code Oficial",
        "source_host": "code.visualstudio.com",
        "url": "https://code.visualstudio.com/sha/download?build=stable&os=linux-deb-x64",
        "version_regex": r"code_([0-9]+\.[0-9]+\.[0-9]+)-.*_amd64\.deb",
        "homepage": "https://code.visualstudio.com",
    },
}


@dataclass
class DiscoveredSource:
    """Resultado da busca automática de fonte de atualização para um aplicativo."""
    pkg_name: str
    found: bool
    confidence: float                # 0.0 a 1.0
    source_type: str                 # 'github_release', 'redirect_deb', 'docker_desktop', 'apt_repo_deb', 'flathub_hint', 'none'
    source_name: str
    source_host: str
    config: Dict[str, Any]
    latest_version: Optional[str] = None
    download_url: Optional[str] = None
    discovery_method: str = ""       # Descrição de como a fonte foi localizada

    @property
    def is_installable_direct_source(self) -> bool:
        return self.found and self.source_type in (
            "github_release",
            "redirect_deb",
            "docker_desktop",
            "apt_repo_deb",
            "web_regex_deb",
        )

    @property
    def confidence_label(self) -> str:
        if self.confidence >= 0.85:
            return f"Alta ({int(self.confidence * 100)}%)"
        if self.confidence >= 0.55:
            return f"Média ({int(self.confidence * 100)}%)"
        if self.confidence > 0:
            return f"Sugestão ({int(self.confidence * 100)}%)"
        return "Não localizada"


class SourceFinder:
    """
    Motor de busca automática de fontes de atualização para aplicativos instalados:
    1. Catálogo Heurístico de Fontes Oficiais Conhecidas
    2. Inspeção e Scraping Leve da Homepage registrada no dpkg / .desktop
    3. Busca Inteligente na API do GitHub (validando assets .deb / releases)
    4. Fallback consultando Flathub API v2
    """

    def __init__(self) -> None:
        self._cache = self._load_cache()

    def discover_for_apps(
        self,
        apps: List[DiscoveredApp],
        progress_cb: Callable[[str, float], None] = lambda msg, frac: None,
        use_cache: bool = True,
    ) -> Dict[str, DiscoveredSource]:
        results: Dict[str, DiscoveredSource] = {}
        targets = [a for a in apps if a.needs_source_discovery]
        if not targets:
            return results

        total = len(targets)
        completed = 0

        def _work(app: DiscoveredApp) -> Tuple[str, DiscoveredSource]:
            res = self.find_source_for_app(app, use_cache=use_cache)
            return app.pkg_name, res

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_work, app) for app in targets]
            for fut in futures:
                try:
                    pkg_name, src = fut.result(timeout=20)
                    results[pkg_name] = src
                except Exception:
                    pass
                completed += 1
                progress_cb(
                    f"Buscando fontes oficiais de atualização ({completed}/{total})...",
                    completed / max(1, total),
                )

        self._save_cache()
        return results

    def find_source_for_app(
        self, app: DiscoveredApp, use_cache: bool = True
    ) -> DiscoveredSource:
        pkg = app.pkg_name.lower()

        # 1. Verifica no catálogo heurístico expandido
        if pkg in KNOWN_DIRECT_CATALOG:
            cfg = dict(KNOWN_DIRECT_CATALOG[pkg])
            ver, dl_url = self._probe_config_version(cfg)
            return DiscoveredSource(
                pkg_name=app.pkg_name,
                found=True,
                confidence=0.98,
                source_type=cfg["type"],
                source_name=cfg["source_name"],
                source_host=cfg["source_host"],
                config=cfg,
                latest_version=ver,
                download_url=dl_url,
                discovery_method="Catálogo Oficial Verificado",
            )

        # Verifica cache de descoberta anterior
        if use_cache and pkg in self._cache:
            entry = self._cache[pkg]
            ts = entry.get("timestamp", 0)
            if time.time() - ts < CACHE_TTL_SECONDS:
                cached_src = entry.get("source")
                if cached_src and cached_src.get("found"):
                    return DiscoveredSource(**cached_src)

        # 2. Inspeção da Homepage do pacote (dpkg)
        if app.homepage:
            from_homepage = self._discover_from_homepage(app)
            if from_homepage and from_homepage.found:
                self._store_cache(pkg, from_homepage)
                return from_homepage

        # 3. Busca na API do GitHub por nome do pacote / nome de exibição
        from_gh_search = self._discover_via_github_search(app)
        if from_gh_search and from_gh_search.found:
            self._store_cache(pkg, from_gh_search)
            return from_gh_search

        # 4. Fallback: verifica se existe no Flathub Oficial
        from_flathub = self._discover_flathub_alternative(app)
        if from_flathub and from_flathub.found:
            self._store_cache(pkg, from_flathub)
            return from_flathub

        not_found = DiscoveredSource(
            pkg_name=app.pkg_name,
            found=False,
            confidence=0.0,
            source_type="none",
            source_name="Fonte automática não localizada",
            source_host="",
            config={},
            discovery_method="Nenhuma release .deb pública encontrada automaticamente",
        )
        self._store_cache(pkg, not_found)
        return not_found

    def _discover_from_homepage(
        self, app: DiscoveredApp
    ) -> Optional[DiscoveredSource]:
        hp = app.homepage.strip()
        if not hp:
            return None

        # 2a. A própria Homepage já é um link do GitHub
        gh_match = re.search(
            r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", hp
        )
        if gh_match:
            owner, repo = gh_match.group(1), gh_match.group(2).rstrip("/")
            if owner.lower() not in IGNORED_GITHUB_OWNERS:
                src = self._validate_github_repo(
                    app,
                    f"{owner}/{repo}",
                    base_confidence=0.95,
                    method="Extraído diretamente da Homepage do pacote (.deb)",
                )
                if src:
                    return src

        # 2b. Scraping leve da Homepage oficial procurando link do GitHub ou .deb direto
        try:
            req = urllib.request.Request(hp, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=6) as resp:
                raw_html = resp.read(250_000).decode("utf-8", errors="ignore")

            # Procura links para repositórios no GitHub dentro do site oficial
            gh_links = re.findall(
                r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
                raw_html,
            )
            seen_repos = set()
            for owner, repo in gh_links:
                clean_repo = repo.split("#")[0].split("?")[0].rstrip("/.")
                if (
                    owner.lower() in IGNORED_GITHUB_OWNERS
                    or clean_repo.lower() in ("releases", "issues", "wiki", "pulls")
                ):
                    continue
                full_repo = f"{owner}/{clean_repo}"
                if full_repo.lower() in seen_repos:
                    continue
                seen_repos.add(full_repo.lower())

                src = self._validate_github_repo(
                    app,
                    full_repo,
                    base_confidence=0.92,
                    method=f"Repositório GitHub localizado no site oficial ({ self._extract_domain(hp) })",
                )
                if src and src.is_installable_direct_source:
                    return src
        except Exception:
            pass

        return None

    def _discover_via_github_search(
        self, app: DiscoveredApp
    ) -> Optional[DiscoveredSource]:
        queries = self._build_search_queries(app)
        hp_domain = self._extract_domain(app.homepage)

        best_non_deb_candidate: Optional[DiscoveredSource] = None

        for q in queries[:2]:
            encoded_q = urllib.parse.quote(q)
            url = f"https://api.github.com/search/repositories?q={encoded_q}&per_page=5"
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/vnd.github+json",
                    },
                )
                with urllib.request.urlopen(req, timeout=7) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception:
                continue

            items = data.get("items", []) or []
            for repo_info in items[:4]:
                full_name = repo_info.get("full_name", "")
                if not full_name:
                    continue
                repo_name = (repo_info.get("name") or "").lower()
                repo_hp = self._extract_domain(repo_info.get("homepage") or "")

                # Calcula confiança base pela similaridade de nome e homepage
                conf = 0.55
                if hp_domain and repo_hp and (
                    hp_domain == repo_hp
                    or hp_domain.endswith("." + repo_hp)
                    or repo_hp.endswith("." + hp_domain)
                ):
                    conf += 0.30
                if repo_name == app.pkg_name.lower() or repo_name in app.pkg_name.lower():
                    conf += 0.10

                src = self._validate_github_repo(
                    app,
                    full_name,
                    base_confidence=min(0.96, conf),
                    method=f"Encontrado via busca na API do GitHub ({full_name})",
                )
                if src:
                    if src.is_installable_direct_source:
                        return src
                    if best_non_deb_candidate is None and src.found:
                        best_non_deb_candidate = src

        return best_non_deb_candidate

    def _validate_github_repo(
        self,
        app: DiscoveredApp,
        full_repo: str,
        base_confidence: float,
        method: str,
    ) -> Optional[DiscoveredSource]:
        """
        Verifica se o repositório GitHub possui Releases e se distribui pacotes .deb
        compatíveis com amd64 / x86_64 / all.
        """
        api_url = f"https://api.github.com/repos/{full_repo}/releases?per_page=3"
        try:
            req = urllib.request.Request(
                api_url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=7) as resp:
                releases = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

        if not isinstance(releases, list) or not releases:
            repo_short = full_repo.split("/")[-1].lower()
            if len(repo_short) >= 5 and (
                repo_short in app.pkg_name.lower() or app.pkg_name.lower() in repo_short
            ):
                latest_tag = self._fetch_latest_github_tag(full_repo)
                extra_note = (
                    "pacote local convertido via alien (repositório usa tags sem releases .deb)"
                    if app.section == "alien"
                    else "repositório sem releases .deb públicas"
                )
                return DiscoveredSource(
                    pkg_name=app.pkg_name,
                    found=True,
                    confidence=0.65,
                    source_type="github_upstream_only",
                    source_name=f"GitHub Upstream ({full_repo})",
                    source_host=f"github.com/{full_repo}",
                    config={
                        "homepage": f"https://github.com/{full_repo}",
                        "repo": full_repo,
                    },
                    latest_version=latest_tag,
                    download_url=f"https://github.com/{full_repo}/tags",
                    discovery_method=f"Repositório oficial localizado ({full_repo}) — {extra_note}",
                )
            return None

        deb_regex = re.compile(
            r"(amd64|x86_64|x64|linux.*deb|_all\.deb|\.deb$)", re.IGNORECASE
        )
        wrong_arch_regex = re.compile(
            r"(arm64|aarch64|armv7|armhf|i386|i686|riscv)", re.IGNORECASE
        )

        for rel in releases:
            tag = (rel.get("tag_name") or "").lstrip("vV").strip()
            assets = rel.get("assets", []) or []
            for asset in assets:
                aname = asset.get("name", "")
                if not aname.lower().endswith(".deb"):
                    continue
                if wrong_arch_regex.search(aname):
                    continue
                if deb_regex.search(aname):
                    dl_url = asset.get("browser_download_url")
                    asset_pattern = self._build_asset_pattern(aname)
                    cfg = {
                        "type": "github_release",
                        "source_name": f"GitHub Oficial ({full_repo})",
                        "source_host": f"github.com/{full_repo}",
                        "repo": full_repo,
                        "asset_pattern": asset_pattern,
                        "homepage": f"https://github.com/{full_repo}/releases",
                    }
                    final_conf = min(0.98, base_confidence + 0.08)
                    return DiscoveredSource(
                        pkg_name=app.pkg_name,
                        found=True,
                        confidence=final_conf,
                        source_type="github_release",
                        source_name=f"GitHub Oficial ({full_repo})",
                        source_host=f"github.com/{full_repo}",
                        config=cfg,
                        latest_version=tag or None,
                        download_url=dl_url,
                        discovery_method=f"{method} • Asset: {aname}",
                    )

        # Caso o repositório seja exatamente do pacote (ex: pacote convertido via alien de RPM)
        latest_tag = (releases[0].get("tag_name") or "").lstrip("vV").strip()
        repo_short = full_repo.split("/")[-1].lower()
        if latest_tag and len(repo_short) >= 4 and (
            repo_short in app.pkg_name.lower() or app.pkg_name.lower() in repo_short
        ):
            has_rpm = any(
                (a.get("name") or "").lower().endswith(".rpm")
                for a in (releases[0].get("assets") or [])
            )
            extra_note = (
                "possui pacote .rpm (pacote local foi convertido via alien)"
                if has_rpm or app.section == "alien"
                else "sem pacote .deb nativo nas releases"
            )
            return DiscoveredSource(
                pkg_name=app.pkg_name,
                found=True,
                confidence=0.68 if has_rpm else 0.60,
                source_type="github_upstream_only",
                source_name=f"GitHub Upstream ({full_repo})",
                source_host=f"github.com/{full_repo}",
                config={
                    "homepage": f"https://github.com/{full_repo}/releases",
                    "repo": full_repo,
                },
                latest_version=latest_tag,
                download_url=f"https://github.com/{full_repo}/releases",
                discovery_method=f"Repositório oficial localizado ({full_repo}), porém {extra_note}",
            )

        return None

    @staticmethod
    def _fetch_latest_github_tag(full_repo: str) -> Optional[str]:
        api_url = f"https://api.github.com/repos/{full_repo}/tags?per_page=1"
        try:
            req = urllib.request.Request(
                api_url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                tags = json.loads(resp.read().decode("utf-8"))
            if isinstance(tags, list) and tags:
                return (tags[0].get("name") or "").lstrip("vV").strip() or None
        except Exception:
            pass
        return None

    def _discover_flathub_alternative(
        self, app: DiscoveredApp
    ) -> Optional[DiscoveredSource]:
        query = app.display_name or app.pkg_name
        url = "https://flathub.org/api/v2/search"
        payload = json.dumps({"query": query}).encode("utf-8")
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={
                    "User-Agent": USER_AGENT,
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            hits = data.get("hits", []) or []
            for hit in hits[:2]:
                name = (hit.get("name") or "").strip()
                app_id = (hit.get("app_id") or "").strip()
                if not app_id:
                    continue
                if (
                    name.lower() == app.display_name.lower()
                    or app.pkg_name.lower() in app_id.lower()
                ):
                    return DiscoveredSource(
                        pkg_name=app.pkg_name,
                        found=True,
                        confidence=0.55,
                        source_type="flathub_hint",
                        source_name=f"Disponível no Flathub ({app_id})",
                        source_host="flathub.org",
                        config={
                            "flathub_app_id": app_id,
                            "homepage": f"https://flathub.org/apps/{app_id}",
                        },
                        latest_version=None,
                        download_url=f"https://flathub.org/apps/{app_id}",
                        discovery_method=f"Sem .deb público no GitHub, mas disponível oficialmente no Flathub ({app_id})",
                    )
        except Exception:
            pass
        return None

    @staticmethod
    def _probe_config_version(
        cfg: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Faz uma consulta rápida na fonte configurada para obter a versão remota atual."""
        stype = cfg.get("type")
        try:
            if stype == "github_release":
                repo = cfg["repo"]
                api_url = f"https://api.github.com/repos/{repo}/releases/latest"
                req = urllib.request.Request(
                    api_url, headers={"User-Agent": USER_AGENT}
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                tag = (data.get("tag_name") or "").lstrip("vV").strip()
                pat = re.compile(cfg.get("asset_pattern", r".*\.deb$"))
                for asset in data.get("assets", []):
                    if pat.search(asset.get("name", "")):
                        return tag, asset.get("browser_download_url")
                return tag, cfg.get("fallback_deb_url")
            elif stype == "redirect_deb":
                req = urllib.request.Request(
                    cfg["url"], method="HEAD", headers={"User-Agent": USER_AGENT}
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    final_url = resp.url
                    m = re.search(
                        cfg.get("version_regex", r"([0-9]+\.[0-9]+\.[0-9]+)"),
                        final_url,
                    )
                    if m:
                        return m.group(1), final_url
            elif stype == "apt_repo_deb":
                req = urllib.request.Request(
                    cfg["packages_url"], headers={"User-Agent": USER_AGENT}
                )
                with urllib.request.urlopen(req, timeout=7) as resp:
                    text = resp.read().decode("utf-8", errors="ignore")
                best_ver, best_file = SourceFinder.parse_apt_packages_index(
                    text, cfg.get("target_pkg", "")
                )
                if best_ver and best_file:
                    dl = urllib.parse.urljoin(cfg["base_repo_url"], best_file)
                    return best_ver, dl
        except Exception:
            pass
        return None, None

    @staticmethod
    def parse_apt_packages_index(
        packages_text: str, target_pkg: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Extrai a versão mais recente e o Filename (.deb) de um arquivo Packages
        de repositório APT (como repo.fortinet.com).
        """
        import apt_pkg
        apt_pkg.init_system()

        best_ver: Optional[str] = None
        best_filename: Optional[str] = None
        best_size: int = 0

        for block in packages_text.split("\n\n"):
            if not block.strip():
                continue
            pkg_val = ""
            ver_val = ""
            file_val = ""
            for line in block.splitlines():
                if line.startswith("Package:"):
                    pkg_val = line.split(":", 1)[1].strip()
                elif line.startswith("Version:"):
                    ver_val = line.split(":", 1)[1].strip()
                elif line.startswith("Filename:"):
                    file_val = line.split(":", 1)[1].strip()
            if pkg_val == target_pkg and ver_val and file_val:
                if best_ver is None or apt_pkg.version_compare(ver_val, best_ver) > 0:
                    best_ver = ver_val
                    best_filename = file_val
        return best_ver, best_filename

    @staticmethod
    def _build_search_queries(app: DiscoveredApp) -> List[str]:
        queries: List[str] = []
        raw = app.pkg_name.lower()
        queries.append(raw)

        # Remove sufixos comuns de empacotamento Debian
        cleaned = re.sub(
            r"(-ce|-desktop|-client|-driver|-bin|-app|-linux|-amd64)$", "", raw
        )
        if cleaned and cleaned != raw:
            queries.append(cleaned)

        if app.display_name and app.display_name.lower() not in queries:
            queries.append(app.display_name.lower())
        return queries

    @staticmethod
    def _build_asset_pattern(sample_asset_name: str) -> str:
        """
        Gera uma expressão regular genérica a partir do nome de um asset .deb real
        (substituindo números de versão por curingas).
        """
        if "amd64.deb" in sample_asset_name:
            return r".*amd64\.deb$"
        if "x86_64.deb" in sample_asset_name:
            return r".*x86_64\.deb$"
        if "x86-64.deb" in sample_asset_name:
            return r".*x86-64\.deb$"
        if "x64.deb" in sample_asset_name:
            return r".*x64\.deb$"
        if "_all.deb" in sample_asset_name:
            return r".*_all\.deb$"
        return r".*\.deb$"

    @staticmethod
    def _extract_domain(url: str) -> str:
        if not url:
            return ""
        try:
            parsed = urllib.parse.urlparse(
                url if "://" in url else f"https://{url}"
            )
            host = (parsed.netloc or "").lower()
            if host.startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return ""

    def _load_cache(self) -> Dict[str, Any]:
        if os.path.exists(DISCOVERY_CACHE_PATH):
            try:
                with open(DISCOVERY_CACHE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def _store_cache(self, pkg: str, src: DiscoveredSource) -> None:
        self._cache[pkg] = {
            "timestamp": time.time(),
            "source": {
                "pkg_name": src.pkg_name,
                "found": src.found,
                "confidence": src.confidence,
                "source_type": src.source_type,
                "source_name": src.source_name,
                "source_host": src.source_host,
                "config": src.config,
                "latest_version": src.latest_version,
                "download_url": src.download_url,
                "discovery_method": src.discovery_method,
            },
        }

    def _save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(DISCOVERY_CACHE_PATH), exist_ok=True)
            with open(DISCOVERY_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
