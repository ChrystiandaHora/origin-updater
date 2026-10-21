#!/usr/bin/env python3
"""
Worker privilegiado executado via pkexec em uma única sessão autenticada.
Realiza sincronização de repositórios (apt-get update), atualização de pacotes APT,
download + instalação de pacotes .deb das fontes oficiais e atualização de Flatpaks,
transmitindo logs e progresso em tempo real sem bufferização.
"""

import json
import os
import pty
import select
import subprocess
import sys
import time
import urllib.request
from typing import Any, Dict, List

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AtualizadorApps/2.0"
CACHE_DIR = "/var/cache/atualizador-apps/debs"


def emit(text: str) -> None:
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def emit_status(fraction: float, message: str) -> None:
    clean_msg = message.replace("\n", " ").strip()
    sys.stdout.write(f"@@STATUS|{fraction:.4f}|{clean_msg}\n")
    sys.stdout.flush()


def emit_progress_line(text: str) -> None:
    clean_text = text.replace("\n", " ").replace("\r", "").strip()
    sys.stdout.write(f"@@PROGRESS_LINE|{clean_text}\n")
    sys.stdout.flush()


def format_size(size_bytes: float) -> str:
    if size_bytes <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0 or unit == "GB":
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{int(size_bytes)} B"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} GB"


def run_pty_command(cmd: List[str], env_extra: Dict[str, str] | None = None) -> int:
    """
    Executa um comando dentro de um pseudo-terminal (PTY) para que apt-get, dpkg e flatpak
    enviem cada linha e porcentagem de download em tempo real sem bufferizar.
    """
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    env["TERM"] = "dumb"
    env["LC_ALL"] = "C.UTF-8"
    if env_extra:
        env.update(env_extra)

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        close_fds=True,
    )
    os.close(slave_fd)

    buf = ""
    try:
        while True:
            rlist, _, _ = select.select([master_fd], [], [], 0.2)
            if master_fd in rlist:
                try:
                    data = os.read(master_fd, 1024)
                except OSError:
                    break
                if not data:
                    break
                chunk = data.decode("utf-8", errors="replace")
                for ch in chunk:
                    if ch == "\r":
                        line = buf.strip()
                        if line:
                            emit_progress_line(f"  ⟳ {line}")
                        buf = ""
                    elif ch == "\n":
                        line = buf.rstrip()
                        if line.strip():
                            sys.stdout.write(f"  {line}\n")
                            sys.stdout.flush()
                        buf = ""
                    else:
                        buf += ch
            elif proc.poll() is not None:
                break
        if buf.strip():
            sys.stdout.write(f"  {buf.strip()}\n")
            sys.stdout.flush()
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass

    return proc.wait()


def download_deb_with_progress(
    url: str, dest_path: str, display_name: str, base_frac: float, span_frac: float
) -> bool:
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    os.chmod(os.path.dirname(dest_path), 0o755)

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    start_time = time.time()
    last_emit = 0.0

    with urllib.request.urlopen(req, timeout=45) as resp:
        total = int(resp.headers.get("Content-Length", "0") or 0)
        # Se já existe no cache com o mesmo tamanho exato, reaproveita
        if total > 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) == total:
            os.chmod(dest_path, 0o644)
            emit(f"  ✔ Arquivo já em cache local ({format_size(total)}): {os.path.basename(dest_path)}")
            return True

        downloaded = 0
        chunk_size = 128 * 1024
        part_path = dest_path + ".part"

        with open(part_path, "wb") as out:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_emit >= 0.20 or (total > 0 and downloaded == total):
                    last_emit = now
                    elapsed = max(0.001, now - start_time)
                    speed = downloaded / elapsed
                    if total > 0:
                        pct = (downloaded / total) * 100.0
                        filled = int(pct // 5)
                        bar = "█" * filled + "░" * (20 - filled)
                        msg = (
                            f"⬇ Baixando {display_name}: [{bar}] {pct:5.1f}% "
                            f"({format_size(downloaded)} / {format_size(total)}) • {format_size(speed)}/s"
                        )
                        emit_progress_line(msg)
                        emit_status(
                            base_frac + span_frac * (pct / 100.0),
                            f"Baixando {display_name}: {pct:.0f}% ({format_size(downloaded)} / {format_size(total)}) — {format_size(speed)}/s",
                        )
                    else:
                        msg = f"⬇ Baixando {display_name}: {format_size(downloaded)} ({format_size(speed)}/s)"
                        emit_progress_line(msg)

        os.replace(part_path, dest_path)
        os.chmod(dest_path, 0o644)
        emit(
            f"  ✔ Download concluído: {os.path.basename(dest_path)} ({format_size(downloaded)})"
        )
        return True


def handle_sync() -> int:
    emit("┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
    emit("┃ 1/2 • SINCRONIZANDO REPOSITÓRIOS APT OFICIAIS (apt-get update)     ┃")
    emit("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
    emit_status(0.15, "Sincronizando listas de pacotes APT com os servidores oficiais...")
    rc_apt = run_pty_command(["apt-get", "update"])
    if rc_apt == 0:
        emit("✔ Índices APT sincronizados com sucesso.\n")
    else:
        emit(f"⚠️ Aviso: 'apt-get update' retornou código {rc_apt} (algum repositório pode ter aviso).\n")

    if os.path.exists("/usr/bin/flatpak"):
        emit("┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
        emit("┃ 2/2 • ATUALIZANDO METADADOS DO FLATHUB (flatpak update --appstream)┃")
        emit("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
        emit_status(0.70, "Sincronizando metadados do Flathub...")
        run_pty_command(["flatpak", "update", "--appstream", "-y"])
        emit("✔ Metadados do Flathub sincronizados.\n")

    emit_status(1.0, "Sincronização concluída com sucesso!")
    return 0


def handle_update(manifest: Dict[str, Any]) -> int:
    apt_packages: List[str] = manifest.get("apt_packages", [])
    direct_items: List[Dict[str, Any]] = manifest.get("direct_items", [])
    flatpak_items: List[Dict[str, Any]] = manifest.get("flatpak_items", [])

    apt_opts = [
        "-y",
        "--fix-missing",
        "-o",
        "Dpkg::Options::=--force-confdef",
        "-o",
        "Dpkg::Options::=--force-confold",
    ]

    succeeded: List[str] = []
    failed: List[str] = []

    # 1. Sempre sincronizar o APT antes de atualizar pacotes APT ou instalar .debs
    if apt_packages or direct_items:
        emit("┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
        emit("┃ ETAPA 1 • SINCRONIZANDO ÍNDICES APT OFICIAIS (apt-get update)      ┃")
        emit("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
        emit_status(0.08, "Etapa 1: Sincronizando listas de pacotes dos repositórios oficiais...")
        rc_upd = run_pty_command(["apt-get", "update"])
        if rc_upd == 0:
            emit("✔ Índices dos repositórios oficiais atualizados.\n")
        else:
            emit(
                f"⚠️ 'apt-get update' concluiu com aviso (código {rc_upd}). Prosseguindo com os pacotes disponíveis...\n"
            )

    # 2. Atualizar pacotes APT selecionados
    if apt_packages:
        emit("┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
        emit(f"┃ ETAPA 2 • ATUALIZANDO {len(apt_packages)} PACOTE(S) VIA REPOSITÓRIOS APT OFICIAIS  ┃")
        emit("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
        emit(
            "Pacotes selecionados: "
            + ", ".join(apt_packages[:20])
            + (f" e mais {len(apt_packages) - 20}..." if len(apt_packages) > 20 else "")
        )
        emit_status(
            0.25,
            f"Etapa 2: Baixando e instalando {len(apt_packages)} pacote(s) dos repositórios APT...",
        )

        cmd = ["apt-get", "install"] + apt_opts + ["--only-upgrade"] + apt_packages
        rc = run_pty_command(cmd)
        if rc == 0:
            emit(f"✔ {len(apt_packages)} pacote(s) APT atualizados com sucesso!\n")
            succeeded.append(f"{len(apt_packages)} pacote(s) APT")
        else:
            emit(
                f"\n⚠️ O lote APT retornou código {rc}. Tentando atualizar individualmente/com fallback para não bloquear os demais...\n"
            )
            # Fallback: se muitos pacotes foram selecionados, roda apt-get upgrade -y --fix-missing
            if len(apt_packages) > 10:
                rc_fallback = run_pty_command(["apt-get", "upgrade"] + apt_opts)
                if rc_fallback == 0:
                    emit("✔ Atualização geral APT (upgrade) concluída com sucesso!\n")
                    succeeded.append("Pacotes do sistema APT")
                else:
                    failed.append("Alguns pacotes APT")
            else:
                for idx, pkg in enumerate(apt_packages, start=1):
                    emit_status(
                        0.25 + 0.25 * (idx / len(apt_packages)),
                        f"Instalando pacote APT ({idx}/{len(apt_packages)}): {pkg}...",
                    )
                    rc_one = run_pty_command(
                        ["apt-get", "install"] + apt_opts + ["--only-upgrade", pkg]
                    )
                    if rc_one == 0:
                        succeeded.append(pkg)
                    else:
                        failed.append(pkg)

    # 3. Baixar e instalar pacotes .deb das Fontes Diretas (GitHub / Discord / Docker)
    if direct_items:
        emit("┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
        emit(f"┃ ETAPA 3 • FONTES OFICIAIS DIRETAS ({len(direct_items)} APLICATIVO(S) .DEB)         ┃")
        emit("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
        for idx, item in enumerate(direct_items, start=1):
            pkg_name = item["pkg_name"]
            disp = item["display_name"]
            new_ver = item["new_version"]
            dl_url = item.get("download_url")
            base_f = 0.55 + 0.25 * ((idx - 1) / len(direct_items))
            span_f = 0.25 / len(direct_items)

            emit(f"\n▶ [{idx}/{len(direct_items)}] {disp} ({pkg_name}) ➔ v{new_ver}")
            emit(f"  Fonte Oficial: {dl_url}")
            if not dl_url:
                emit(f"  ❌ URL de download não encontrada para {disp}.")
                failed.append(disp)
                continue

            dest_deb = os.path.join(CACHE_DIR, f"{pkg_name}_{new_ver}_amd64.deb")
            try:
                download_deb_with_progress(
                    dl_url, dest_deb, disp, base_f, span_f * 0.65
                )
            except Exception as e:
                emit(f"  ❌ Erro ao baixar {disp}: {e}")
                failed.append(disp)
                continue

            emit(f"  ⚙ Instalando pacote {os.path.basename(dest_deb)} no sistema...")
            emit_status(
                base_f + span_f * 0.70,
                f"Instalando {disp} v{new_ver} na máquina...",
            )
            rc_deb = run_pty_command(
                ["apt-get", "install"] + apt_opts + ["--allow-downgrades", dest_deb]
            )
            if rc_deb == 0:
                emit(f"  ✔ {disp} atualizado com sucesso para a versão {new_ver}!")
                succeeded.append(f"{disp} ({new_ver})")
            else:
                emit(f"  ❌ Falha na instalação de {disp} (código {rc_deb}).")
                failed.append(disp)

    # 4. Atualizar aplicativos e runtimes Flatpak (Flathub)
    if flatpak_items:
        emit("\n┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
        emit(f"┃ ETAPA 4 • ATUALIZANDO {len(flatpak_items)} PACOTE(S) FLATPAK (FLATHUB OFICIAL)     ┃")
        emit("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
        for idx, fp in enumerate(flatpak_items, start=1):
            app_id = fp["pkg_name"]
            disp = fp["display_name"]
            branch = fp.get("branch")
            frac = 0.82 + 0.16 * ((idx - 1) / len(flatpak_items))

            emit(f"\n▶ [{idx}/{len(flatpak_items)}] Flatpak: {disp} ({app_id})")
            emit_status(frac, f"Atualizando Flatpak ({idx}/{len(flatpak_items)}): {disp}...")

            cmd = ["flatpak", "update", "-y", "--noninteractive", app_id]
            if branch:
                cmd.append(branch)
            rc_fp = run_pty_command(cmd)
            if rc_fp == 0:
                emit(f"  ✔ {disp} atualizado com sucesso via Flathub!")
                succeeded.append(f"{disp} (Flatpak)")
            else:
                emit(f"  ⚠️ Aviso ao atualizar {disp} (código {rc_fp}).")
                failed.append(f"{disp} (Flatpak)")

    # Resumo final
    emit("\n┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
    emit("┃ RESUMO FINAL DA EXECUÇÃO                                           ┃")
    emit("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
    if succeeded:
        emit(f"✔ Concluídos com sucesso: {', '.join(succeeded)}")
    if failed:
        emit(f"⚠️ Com falhas ou avisos: {', '.join(failed)}")
        emit_status(1.0, f"Finalizado com alguns avisos ({len(failed)} falha(s)).")
        return 1

    emit("🎉 Todos os aplicativos e pacotes selecionados foram atualizados!")
    emit_status(1.0, "Todas as atualizações foram instaladas com sucesso!")
    return 0


def main() -> int:
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]):
        emit("❌ Erro: Manifesto de execução não encontrado.")
        return 2

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        manifest = json.load(f)

    mode = manifest.get("mode", "update")
    if mode == "sync":
        return handle_sync()
    return handle_update(manifest)


if __name__ == "__main__":
    sys.exit(main())
