# <img src="assets/origin-updater.svg" width="38" valign="middle" alt="Origin Updater Logo" /> Origin Updater (`origin-updater`)

**Central de Atualizações Nativa para Linux (GTK4 / Libadwaita)** que verifica, descobre, baixa e instala atualizações de aplicativos e pacotes diretamente das suas **fontes originais oficiais**.

---

## ✨ Principais Funcionalidades

1. **Verificação em 3 Camadas de Fontes Originais + Descoberta Automática**:
   - **Varredura de Aplicativos & Descoberta Automática de Fontes**: escaneia a máquina Linux em busca de pacotes `.deb` instalados manualmente (órfãos de repositório APT), entradas `.desktop`, diretórios `/opt` e arquivos `.AppImage`, localizando automaticamente suas fontes oficiais de atualização via `Homepage` do `dpkg`, GitHub Releases API, índices de repositórios oficiais e catálogo expandido.
   - **Fontes Oficiais Diretas (`.deb` avulsos)**: consulta diretamente APIs oficiais, GitHub Releases e repositórios diretos para aplicativos instalados manualmente (ex: **Discord**, **DBeaver Community**, **RustDesk**, **Docker Desktop**, **FortiClient VPN**, **Obsidian**, **LocalSend**, **Insomnia**, etc.).
   - **Repositórios APT Oficiais & de Fabricantes**: identifica a origem exata de cada pacote (`dl.google.com`, `packages.microsoft.com`, `download.docker.com`, `repository.spotify.com`, `deb.anydesk.com`, `security.debian.org`, `deb.debian.org`).
   - **Flatpak / Flathub Oficial**: verifica atualizações de aplicativos e runtimes instalados via Flatpak diretamente no Flathub (`dl.flathub.org`).

2. **Interface Nativa GTK4 + Libadwaita**:
   - **Cards de Filtro Rápido**: alterne entre *Todas as Atualizações*, *Apps & Fontes Diretas*, *Flatpak (Flathub)*, *Sistema (Debian)* e *Já Atualizados*.
   - **Seleção Individual ou em Lote**: escolha exatamente quais aplicativos atualizar ou use *Atualizar Tudo*.
   - **Tela Cheia de Log em Tempo Real**: visualização dedicada em tela cheia exibindo a sincronização de repositórios, velocidade/porcentagem de download dos pacotes `.deb` e a instalação passo a passo no sistema via pseudo-terminal (PTY).

3. **Autenticação Unificada (`pkexec`)**:
   - Solicita permissão de administrador **apenas uma vez** no início da operação, executando `apt-get update`, atualização de pacotes APT, instalação de `.deb` oficiais e Flatpaks em uma única sessão segura.

---

## 🖥️ Compatibilidade de Plataformas

- **Atualmente suportado**: Distribuições Linux baseadas em Debian (Debian, Ubuntu, Linux Mint, Pop!_OS, Zorin OS, etc.) com ambiente gráfico GTK4 / Libadwaita, `apt` e `flatpak`.
- **Roadmap Futuro**:
  - Suporte a outras distribuições Linux (`dnf` para Fedora/RHEL, `pacman` para Arch).
  - Suporte a Windows via `winget` (Windows Package Manager) + GitHub Releases.

---

## 📦 Pré-requisitos (Debian / Ubuntu)

```bash
sudo apt update
sudo apt install -y python3 python3-gi python3-apt gir1.2-gtk-4.0 gir1.2-adw-1 policykit-1 flatpak
```

---

## 🚀 Como Executar e Instalar

```bash
# Clonar o repositório
git clone https://github.com/ChrystiandaHora/origin-updater.git
cd origin-updater

# Executar diretamente
python3 main.py

# Ou instalar o atalho no menu de aplicativos do Linux
./install.sh
```

---

## 🗂️ Estrutura do Projeto

```text
origin-updater/
├── main.py                      # Ponto de entrada GTK4 / Libadwaita
├── install.sh                   # Script de instalação do atalho .desktop, ícone e comando CLI
├── LICENSE                      # Licença MIT
├── README.md                    # Documentação do projeto
├── assets/
│   ├── origin-updater.svg       # Ícone vetorial oficial (GNOME / Libadwaita HIG)
│   └── origin-updater.png       # Ícone rasterizado 256x256
└── src/
    ├── models.py                # Modelos de dados (UpdateItem)
    ├── desktop_resolver.py      # Resolução de ícones e nomes amigáveis (.desktop)
    ├── updater_engine.py        # Orquestrador de verificação, descoberta e execução
    ├── privileged_worker.py     # Worker root (pkexec + PTY) com streaming em tempo real
    ├── discovery/
    │   ├── app_scanner.py       # Varredura de pacotes .deb órfãos, .desktop, /opt e AppImage
    │   └── source_finder.py     # Motor de busca automática de fontes (Homepage, GitHub API, Flathub)
    ├── providers/
    │   ├── apt_provider.py      # Provedor de repositórios APT oficiais e de terceiros
    │   ├── flatpak_provider.py  # Provedor Flatpak / Flathub
    │   └── direct_provider.py   # Provedor de fontes diretas (GitHub Releases / APIs)
    └── ui/
        └── window.py            # Janela principal, Modal de Descoberta e Tela de Log em Tempo Real
```

---

## 📄 Licença

Distribuído sob a licença **MIT**. Veja o arquivo [`LICENSE`](LICENSE) para mais detalhes.
