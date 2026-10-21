from datetime import datetime
import os
import threading
import webbrowser
from typing import Dict, List, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from ..discovery import DiscoveredApp, DiscoveredSource
from ..models import UpdateItem, format_size
from ..providers.direct_provider import BUILTIN_DIRECT_SOURCES
from ..updater_engine import UpdaterEngine

ASSETS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "assets")
)
APP_ICON_SVG = os.path.join(ASSETS_DIR, "origin-updater.svg")



APP_CSS = """
.summary-card {
    background-color: alpha(@card_bg_color, 0.95);
    border: 1px solid alpha(@borders, 0.6);
    border-radius: 12px;
    padding: 12px 16px;
    transition: all 150ms ease;
}
.summary-card:hover {
    background-color: alpha(@accent_bg_color, 0.14);
    border-color: alpha(@accent_bg_color, 0.5);
}
.summary-card-active {
    background-color: alpha(@accent_bg_color, 0.20);
    border: 1.5px solid @accent_bg_color;
}
.summary-count {
    font-size: 22px;
    font-weight: 800;
}
.summary-title {
    font-size: 12px;
    opacity: 0.82;
    font-weight: 600;
}
.app-row {
    padding: 10px 14px;
    border-bottom: 1px solid alpha(@borders, 0.35);
}
.app-title {
    font-size: 14px;
    font-weight: 700;
}
.pkg-tech-name {
    font-size: 12px;
    opacity: 0.62;
    font-family: monospace;
}
.app-summary {
    font-size: 12px;
    opacity: 0.78;
}
.badge {
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}
.badge-direct {
    background-color: alpha(#9141ac, 0.22);
    color: #dc8add;
    border: 1px solid alpha(#dc8add, 0.4);
}
.badge-app-repo {
    background-color: alpha(#1c71d8, 0.22);
    color: #78aeed;
    border: 1px solid alpha(#78aeed, 0.4);
}
.badge-flatpak {
    background-color: alpha(#2ec27e, 0.22);
    color: #8ff0a4;
    border: 1px solid alpha(#8ff0a4, 0.4);
}
.badge-system {
    background-color: alpha(#77767b, 0.22);
    color: #deddda;
    border: 1px solid alpha(#deddda, 0.3);
}
.badge-found {
    background-color: alpha(#2ec27e, 0.25);
    color: #8ff0a4;
    border: 1px solid alpha(#8ff0a4, 0.5);
}
.badge-hint {
    background-color: alpha(#e5a50a, 0.25);
    color: #f9f06b;
    border: 1px solid alpha(#f9f06b, 0.45);
}
.version-pill {
    background-color: alpha(@accent_bg_color, 0.16);
    border-radius: 6px;
    padding: 3px 9px;
    font-family: monospace;
    font-size: 12px;
    font-weight: 600;
}
.version-ok-pill {
    background-color: alpha(#2ec27e, 0.16);
    color: #8ff0a4;
    border-radius: 6px;
    padding: 3px 9px;
    font-family: monospace;
    font-size: 12px;
    font-weight: 600;
}
.size-label {
    font-size: 11px;
    opacity: 0.7;
}
.log-header-card {
    background-color: alpha(@card_bg_color, 0.98);
    border: 1px solid alpha(@borders, 0.7);
    border-radius: 12px;
    padding: 14px 18px;
}
.log-status-title {
    font-size: 15px;
    font-weight: 700;
}
.log-pct-badge {
    font-family: monospace;
    font-size: 15px;
    font-weight: 800;
    color: @accent_color;
}
.terminal-frame {
    border-radius: 10px;
    border: 1px solid alpha(@borders, 0.7);
    background-color: #111318;
}
.terminal-view {
    background-color: #111318;
    color: #e5e9f0;
    font-family: monospace;
    font-size: 13px;
    padding: 14px;
}
.bottom-bar {
    background-color: @headerbar_bg_color;
    border-top: 1px solid @borders;
    padding: 10px 18px;
}
"""


class UpdaterWindow(Adw.ApplicationWindow):
    """Janela principal do Atualizador de Apps com Tela Cheia dedicada para Log em Tempo Real."""

    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app)
        self.set_title("Central de Atualizações — Fontes Originais")
        self.set_default_size(1080, 760)

        self.engine = UpdaterEngine()
        self.updates: List[UpdateItem] = []
        self.up_to_date: List[UpdateItem] = []
        self.current_filter: str = "all"
        self.search_query: str = ""
        self.is_busy: bool = False
        self._last_line_is_progress: bool = False

        self._load_css()
        self._build_ui()

        # Inicia verificação rápida das versões assim que abre
        GLib.idle_add(self.start_scan)

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(APP_CSS.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            if os.path.isdir(ASSETS_DIR):
                theme = Gtk.IconTheme.get_for_display(display)
                theme.add_search_path(ASSETS_DIR)
                self.set_icon_name("br.com.chrystian.AtualizadorApps")

    def _build_ui(self) -> None:
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_content(root_box)

        # ─── 1. HeaderBar ────────────────────────────────────────────────────
        header = Adw.HeaderBar()
        title_outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title_outer.set_valign(Gtk.Align.CENTER)
        if os.path.exists(APP_ICON_SVG):
            logo_img = Gtk.Image.new_from_file(APP_ICON_SVG)
            logo_img.set_pixel_size(28)
            title_outer.append(logo_img)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_lbl = Gtk.Label(label="Central de Atualizações")
        title_lbl.add_css_class("title")
        subtitle_lbl = Gtk.Label(
            label="Verificação direta em Repositórios Oficiais, GitHub Releases e Flathub"
        )
        subtitle_lbl.add_css_class("subtitle")
        title_box.append(title_lbl)
        title_box.append(subtitle_lbl)
        title_outer.append(title_box)
        header.set_title_widget(title_outer)

        # Botão Verificar Agora
        self.btn_scan = Gtk.Button()
        scan_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        scan_box.append(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        scan_box.append(Gtk.Label(label="Verificar Agora"))
        self.btn_scan.set_child(scan_box)
        self.btn_scan.set_tooltip_text(
            "Consulta imediatamente versões no APT, Flathub e APIs oficiais"
        )
        self.btn_scan.connect("clicked", lambda *_: self.start_scan())
        header.pack_start(self.btn_scan)

        # Botão Sincronizar Repositórios (apt update)
        self.btn_sync = Gtk.Button()
        sync_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sync_box.append(Gtk.Image.new_from_icon_name("emblem-synchronizing-symbolic"))
        sync_box.append(Gtk.Label(label="Sincronizar Repositórios"))
        self.btn_sync.set_child(sync_box)
        self.btn_sync.set_tooltip_text(
            "Executa 'apt-get update' e atualiza os índices de todos os repositórios oficiais"
        )
        self.btn_sync.connect("clicked", lambda *_: self.start_sync_repositories())
        header.pack_start(self.btn_sync)

        # Botão de Alternância de Tela: Tela de Log em Tempo Real vs Lista de Apps
        self.btn_switch_screen = Gtk.Button()
        self.switch_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.switch_btn_icon = Gtk.Image.new_from_icon_name(
            "utilities-terminal-symbolic"
        )
        self.switch_btn_label = Gtk.Label(label="Tela de Log em Tempo Real")
        self.switch_btn_box.append(self.switch_btn_icon)
        self.switch_btn_box.append(self.switch_btn_label)
        self.btn_switch_screen.set_child(self.switch_btn_box)
        self.btn_switch_screen.set_tooltip_text(
            "Alternar entre a Lista de Aplicativos e a Tela Cheia de Log em Tempo Real"
        )
        self.btn_switch_screen.connect("clicked", self._on_switch_screen_clicked)
        header.pack_end(self.btn_switch_screen)

        # Botão Descobrir Apps & Fontes
        self.btn_add_source = Gtk.Button()
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_box.append(Gtk.Image.new_from_icon_name("system-search-symbolic"))
        add_box.append(Gtk.Label(label="Descobrir Apps & Fontes"))
        self.btn_add_source.set_child(add_box)
        self.btn_add_source.set_tooltip_text(
            "Varrer a máquina em busca de aplicativos instalados (.deb, /opt, AppImage) e encontrar automaticamente suas fontes oficiais de atualização"
        )
        self.btn_add_source.connect("clicked", self._on_discover_sources_clicked)
        header.pack_end(self.btn_add_source)

        root_box.append(header)

        # ─── 2. Stack de Telas (Tela 1: Lista | Tela 2: Log em Tela Cheia) ───
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(200)
        self.stack.set_vexpand(True)
        self.stack.set_hexpand(True)

        self.page_list = self._build_list_page()
        self.page_log = self._build_log_page()

        self.stack.add_named(self.page_list, "list")
        self.stack.add_named(self.page_log, "log")
        self.stack.set_visible_child_name("list")

        root_box.append(self.stack)

    # ─── Construção da Tela 1: Lista de Aplicativos ──────────────────────────

    def _build_list_page(self) -> Gtk.Widget:
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Barra de status rápida no topo da lista
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_row.set_margin_start(18)
        status_row.set_margin_end(18)
        status_row.set_margin_top(10)

        self.list_spinner = Gtk.Spinner()
        status_row.append(self.list_spinner)

        self.lbl_list_status = Gtk.Label(
            label="Iniciando verificação nas fontes originais..."
        )
        self.lbl_list_status.set_halign(Gtk.Align.START)
        self.lbl_list_status.set_hexpand(True)
        status_row.append(self.lbl_list_status)
        page_box.append(status_row)

        # Cards de Resumo / Filtros Rápidos
        cards_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        cards_box.set_homogeneous(True)
        cards_box.set_margin_start(18)
        cards_box.set_margin_end(18)
        cards_box.set_margin_top(8)
        cards_box.set_margin_bottom(8)

        self.card_buttons = {}
        self.card_count_labels = {}

        card_defs = [
            ("all", "Todas as Atualizações", "software-update-available-symbolic"),
            ("apps", "Apps & Fontes Diretas", "starred-symbolic"),
            ("flatpak", "Flatpak (Flathub)", "system-software-install-symbolic"),
            ("system", "Sistema (Debian)", "applications-system-symbolic"),
            ("uptodate", "Já Atualizados", "emblem-ok-symbolic"),
        ]

        for key, title, icon_name in card_defs:
            btn = Gtk.Button()
            btn.add_css_class("summary-card")
            if key == "all":
                btn.add_css_class("summary-card-active")

            cbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            top_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(18)
            count_lbl = Gtk.Label(label="0")
            count_lbl.add_css_class("summary-count")
            top_line.append(img)
            top_line.append(count_lbl)

            title_l = Gtk.Label(label=title)
            title_l.add_css_class("summary-title")
            title_l.set_halign(Gtk.Align.START)

            cbox.append(top_line)
            cbox.append(title_l)
            btn.set_child(cbox)
            btn.connect("clicked", self._on_filter_card_clicked, key)

            self.card_buttons[key] = btn
            self.card_count_labels[key] = count_lbl
            cards_box.append(btn)

        page_box.append(cards_box)

        # Barra de Busca e Seleção em Massa
        toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        toolbar_box.set_margin_start(18)
        toolbar_box.set_margin_end(18)
        toolbar_box.set_margin_bottom(8)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text(
            "Filtrar por aplicativo, pacote ou fonte (ex: chrome, github, discord, microsoft, flathub)..."
        )
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        toolbar_box.append(self.search_entry)

        self.btn_select_all = Gtk.Button(label="Marcar Visíveis")
        self.btn_select_all.connect(
            "clicked", lambda *_: self._set_visible_selected(True)
        )
        toolbar_box.append(self.btn_select_all)

        self.btn_unselect_all = Gtk.Button(label="Desmarcar Visíveis")
        self.btn_unselect_all.connect(
            "clicked", lambda *_: self._set_visible_selected(False)
        )
        toolbar_box.append(self.btn_unselect_all)

        page_box.append(toolbar_box)

        # Lista de Aplicativos em Tela Cheia
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_vexpand(True)
        list_scroll.set_margin_start(18)
        list_scroll.set_margin_end(18)
        list_scroll.set_margin_bottom(10)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")
        list_scroll.set_child(self.list_box)
        page_box.append(list_scroll)

        # Barra Inferior de Ação
        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bottom_bar.add_css_class("bottom-bar")

        self.lbl_selection_summary = Gtk.Label(label="0 atualizações selecionadas")
        self.lbl_selection_summary.set_halign(Gtk.Align.START)
        self.lbl_selection_summary.set_hexpand(True)
        bottom_bar.append(self.lbl_selection_summary)

        self.btn_update_selected = Gtk.Button(label="Atualizar Selecionados (0)")
        self.btn_update_selected.connect(
            "clicked", lambda *_: self.start_apply_updates(only_selected=True)
        )
        bottom_bar.append(self.btn_update_selected)

        self.btn_update_all = Gtk.Button(label="Atualizar Tudo (0)")
        self.btn_update_all.add_css_class("suggested-action")
        self.btn_update_all.connect(
            "clicked", lambda *_: self.start_apply_updates(only_selected=False)
        )
        bottom_bar.append(self.btn_update_all)

        page_box.append(bottom_bar)
        return page_box

    # ─── Construção da Tela 2: Tela Cheia de Log em Tempo Real ───────────────

    def _build_log_page(self) -> Gtk.Widget:
        log_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        log_page.set_margin_start(18)
        log_page.set_margin_end(18)
        log_page.set_margin_top(14)
        log_page.set_margin_bottom(16)

        # Card Superior de Status da Operação e Progresso
        header_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        header_card.add_css_class("log-header-card")

        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        btn_back = Gtk.Button()
        back_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        back_box.append(Gtk.Image.new_from_icon_name("go-previous-symbolic"))
        back_box.append(Gtk.Label(label="Voltar para Lista de Aplicativos"))
        btn_back.set_child(back_box)
        btn_back.connect("clicked", lambda *_: self.show_screen("list"))
        top_bar.append(btn_back)

        self.log_spinner = Gtk.Spinner()
        top_bar.append(self.log_spinner)

        self.lbl_log_status = Gtk.Label(
            label="Pronto para exibir downloads e instalações em tempo real."
        )
        self.lbl_log_status.add_css_class("log-status-title")
        self.lbl_log_status.set_halign(Gtk.Align.START)
        self.lbl_log_status.set_hexpand(True)
        self.lbl_log_status.set_ellipsize(Pango.EllipsizeMode.END)
        top_bar.append(self.lbl_log_status)

        self.lbl_log_pct = Gtk.Label(label="0%")
        self.lbl_log_pct.add_css_class("log-pct-badge")
        top_bar.append(self.lbl_log_pct)

        btn_copy = Gtk.Button(label="Copiar Log")
        btn_copy.connect("clicked", self._on_copy_log_clicked)
        top_bar.append(btn_copy)

        btn_clear = Gtk.Button(label="Limpar Log")
        btn_clear.connect("clicked", self._on_clear_log_clicked)
        top_bar.append(btn_clear)

        header_card.append(top_bar)

        self.log_progress_bar = Gtk.ProgressBar()
        self.log_progress_bar.set_fraction(0.0)
        header_card.append(self.log_progress_bar)

        log_page.append(header_card)

        # Terminal de Log ocupando 100% da tela restante
        term_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        term_frame.add_css_class("terminal-frame")
        term_frame.set_vexpand(True)
        term_frame.set_hexpand(True)

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_vexpand(True)
        log_scroll.set_hexpand(True)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_view.add_css_class("terminal-view")
        self.log_buffer = self.log_view.get_buffer()

        self.log_buffer.set_text(
            "🖥️ TELA DE LOG EM TEMPO REAL\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Aqui você acompanha em tempo real:\n"
            " • Sincronização de repositórios oficiais (apt-get update / Flathub)\n"
            " • Download direto de pacotes .deb (GitHub Releases, Discord, Docker) com velocidade e %\n"
            " • Desempacotamento e instalação de cada pacote na sua máquina\n\n"
        )

        log_scroll.set_child(self.log_view)
        term_frame.append(log_scroll)
        log_page.append(term_frame)

        return log_page

    # ─── Alternância entre Tela de Lista e Tela de Log ───────────────────────

    def show_screen(self, screen_name: str) -> None:
        self.stack.set_visible_child_name(screen_name)
        if screen_name == "log":
            self.switch_btn_icon.set_from_icon_name("view-list-symbolic")
            self.switch_btn_label.set_label("Ver Lista de Aplicativos")
            self.btn_switch_screen.add_css_class("suggested-action")
        else:
            self.switch_btn_icon.set_from_icon_name("utilities-terminal-symbolic")
            self.switch_btn_label.set_label("Tela de Log em Tempo Real")
            self.btn_switch_screen.remove_css_class("suggested-action")

    def _on_switch_screen_clicked(self, _btn: Gtk.Button) -> None:
        current = self.stack.get_visible_child_name()
        self.show_screen("list" if current == "log" else "log")

    def _on_copy_log_clicked(self, _btn: Gtk.Button) -> None:
        start_it = self.log_buffer.get_start_iter()
        end_it = self.log_buffer.get_end_iter()
        text = self.log_buffer.get_text(start_it, end_it, False)
        display = Gdk.Display.get_default()
        if display:
            clipboard = display.get_clipboard()
            clipboard.set(text)
            self.lbl_log_status.set_label("✔ Log copiado para a área de transferência!")

    def _on_clear_log_clicked(self, _btn: Gtk.Button) -> None:
        self.log_buffer.set_text("")
        self._last_line_is_progress = False

    # ─── Eventos de Filtro e Busca ───────────────────────────────────────────

    def _on_filter_card_clicked(self, _btn: Gtk.Button, filter_key: str) -> None:
        self.current_filter = filter_key
        for k, b in self.card_buttons.items():
            if k == filter_key:
                b.add_css_class("summary-card-active")
            else:
                b.remove_css_class("summary-card-active")
        self._populate_list()

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.search_query = entry.get_text().strip().lower()
        self._populate_list()

    def _get_filtered_items(self) -> List[UpdateItem]:
        if self.current_filter == "uptodate":
            base = self.up_to_date
        elif self.current_filter == "apps":
            base = [
                x
                for x in self.updates
                if x.source_category in ("direct_deb", "app_repo")
            ]
        elif self.current_filter == "flatpak":
            base = [x for x in self.updates if x.source_category == "flatpak"]
        elif self.current_filter == "system":
            base = [x for x in self.updates if x.source_category == "system"]
        else:
            base = self.updates

        if not self.search_query:
            return base

        q = self.search_query
        return [
            x
            for x in base
            if q in x.display_name.lower()
            or q in x.pkg_name.lower()
            or q in x.source_name.lower()
            or q in x.source_host.lower()
            or q in x.summary.lower()
        ]

    def _set_visible_selected(self, state: bool) -> None:
        if self.current_filter == "uptodate":
            return
        for item in self._get_filtered_items():
            item.selected = state
        self._populate_list()
        self._update_counters()

    # ─── Renderização da Lista ───────────────────────────────────────────────

    def _populate_list(self) -> None:
        while True:
            row = self.list_box.get_row_at_index(0)
            if row is None:
                break
            self.list_box.remove(row)

        items = self._get_filtered_items()
        if not items:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            empty_box.set_margin_top(48)
            empty_box.set_margin_bottom(48)
            empty_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            empty_icon.set_pixel_size(48)
            empty_box.append(empty_icon)

            msg = (
                "Nenhuma atualização pendente nesta categoria!"
                if not self.search_query
                else f"Nenhum aplicativo encontrado para '{self.search_query}'."
            )
            lbl = Gtk.Label(label=msg)
            lbl.add_css_class("title-3")
            empty_box.append(lbl)
            self.list_box.append(empty_box)
            return

        for item in items:
            self.list_box.append(self._create_item_row(item))

    def _create_item_row(self, item: UpdateItem) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hbox.add_css_class("app-row")

        if item.has_update:
            chk = Gtk.CheckButton()
            chk.set_active(item.selected)
            chk.set_valign(Gtk.Align.CENTER)
            chk.connect("toggled", self._on_item_toggled, item)
            hbox.append(chk)

        img = self._create_item_image(item)
        img.set_pixel_size(36)
        img.set_valign(Gtk.Align.CENTER)
        hbox.append(img)

        info_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_col.set_hexpand(True)
        info_col.set_valign(Gtk.Align.CENTER)

        top_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name_lbl = Gtk.Label(label=item.display_name)
        name_lbl.add_css_class("app-title")
        name_lbl.set_halign(Gtk.Align.START)
        top_line.append(name_lbl)

        if item.pkg_name.lower() != item.display_name.lower():
            pkg_lbl = Gtk.Label(label=f"({item.pkg_name})")
            pkg_lbl.add_css_class("pkg-tech-name")
            top_line.append(pkg_lbl)

        badge_lbl = Gtk.Label(label=item.category_badge_label)
        badge_lbl.add_css_class("badge")
        badge_lbl.add_css_class(item.category_css_class)
        top_line.append(badge_lbl)

        info_col.append(top_line)

        desc_text = item.summary or f"Fonte original: {item.source_host}"
        if item.source_host and item.source_host not in desc_text:
            desc_text = f"{desc_text}  •  Fonte: {item.source_host}"

        desc_lbl = Gtk.Label(label=desc_text)
        desc_lbl.add_css_class("app-summary")
        desc_lbl.set_halign(Gtk.Align.START)
        desc_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        desc_lbl.set_max_width_chars(78)
        info_col.append(desc_lbl)

        hbox.append(info_col)

        right_col = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        right_col.set_valign(Gtk.Align.CENTER)

        ver_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        ver_box.set_valign(Gtk.Align.CENTER)

        if item.has_update:
            ver_lbl = Gtk.Label(
                label=f"{item.installed_version}  ➔  {item.new_version}"
            )
            ver_lbl.add_css_class("version-pill")
        else:
            ver_lbl = Gtk.Label(label=f"✔ {item.installed_version} (Atualizado)")
            ver_lbl.add_css_class("version-ok-pill")
        ver_lbl.set_halign(Gtk.Align.END)
        ver_box.append(ver_lbl)

        if item.download_size_str:
            sz_lbl = Gtk.Label(label=f"Download: {item.download_size_str}")
            sz_lbl.add_css_class("size-label")
            sz_lbl.set_halign(Gtk.Align.END)
            ver_box.append(sz_lbl)

        right_col.append(ver_box)

        if item.homepage_url:
            btn_web = Gtk.Button.new_from_icon_name("globe-symbolic")
            btn_web.set_valign(Gtk.Align.CENTER)
            btn_web.set_tooltip_text(f"Abrir fonte/site oficial: {item.homepage_url}")
            btn_web.connect(
                "clicked", lambda _b, url=item.homepage_url: webbrowser.open(url)
            )
            right_col.append(btn_web)

        if item.has_update:
            btn_single = Gtk.Button(label="Atualizar")
            btn_single.set_valign(Gtk.Align.CENTER)
            btn_single.set_sensitive(not self.is_busy)
            btn_single.set_tooltip_text(f"Atualizar apenas {item.display_name}")
            btn_single.connect(
                "clicked", lambda _b, it=item: self.start_apply_single(it)
            )
            right_col.append(btn_single)

        hbox.append(right_col)
        row.set_child(hbox)
        return row

    @staticmethod
    def _create_item_image(item: UpdateItem) -> Gtk.Image:
        if item.icon_path:
            return Gtk.Image.new_from_file(item.icon_path)
        display = Gdk.Display.get_default()
        if display:
            theme = Gtk.IconTheme.get_for_display(display)
            if theme.has_icon(item.icon_name):
                return Gtk.Image.new_from_icon_name(item.icon_name)
        return Gtk.Image.new_from_icon_name("package-x-generic")

    def _on_item_toggled(self, chk: Gtk.CheckButton, item: UpdateItem) -> None:
        item.selected = chk.get_active()
        self._update_counters()

    def _update_counters(self) -> None:
        total_upd = len(self.updates)
        apps_upd = sum(
            1
            for x in self.updates
            if x.source_category in ("direct_deb", "app_repo")
        )
        fp_upd = sum(1 for x in self.updates if x.source_category == "flatpak")
        sys_upd = sum(1 for x in self.updates if x.source_category == "system")
        ok_count = len(self.up_to_date)

        self.card_count_labels["all"].set_label(str(total_upd))
        self.card_count_labels["apps"].set_label(str(apps_upd))
        self.card_count_labels["flatpak"].set_label(str(fp_upd))
        self.card_count_labels["system"].set_label(str(sys_upd))
        self.card_count_labels["uptodate"].set_label(str(ok_count))

        selected_items = [x for x in self.updates if x.selected]
        sel_count = len(selected_items)
        total_bytes = sum(
            x.download_size for x in selected_items if x.download_size > 0
        )
        size_part = (
            f"  •  Download estimado (APT/.deb): {format_size(total_bytes)}"
            if total_bytes > 0
            else ""
        )

        self.lbl_selection_summary.set_label(
            f"{sel_count} de {total_upd} atualizações selecionadas{size_part}"
        )
        self.btn_update_selected.set_label(f"Atualizar Selecionados ({sel_count})")
        self.btn_update_selected.set_sensitive(not self.is_busy and sel_count > 0)

        self.btn_update_all.set_label(f"Atualizar Tudo ({total_upd})")
        self.btn_update_all.set_sensitive(not self.is_busy and total_upd > 0)

    # ─── Log em Tempo Real e Controle de Operações ───────────────────────────

    def _set_busy(self, busy: bool, status_msg: str = "") -> None:
        self.is_busy = busy
        if busy:
            self.list_spinner.start()
            self.log_spinner.start()
        else:
            self.list_spinner.stop()
            self.log_spinner.stop()

        if status_msg:
            self.lbl_list_status.set_label(status_msg)
            self.lbl_log_status.set_label(status_msg)

        self.btn_scan.set_sensitive(not busy)
        self.btn_sync.set_sensitive(not busy)
        self.btn_select_all.set_sensitive(not busy)
        self.btn_unselect_all.set_sensitive(not busy)
        self._update_counters()

    def _append_log(self, text: str, is_progress_line: bool = False) -> None:
        def _do() -> bool:
            if is_progress_line:
                if self._last_line_is_progress:
                    # Substitui a última linha de progresso no próprio lugar
                    end_it = self.log_buffer.get_end_iter()
                    line_start = end_it.copy()
                    if line_start.backward_line():
                        self.log_buffer.delete(line_start, end_it)
                end_it = self.log_buffer.get_end_iter()
                self.log_buffer.insert(end_it, text + "\n")
                self._last_line_is_progress = True
            else:
                if self._last_line_is_progress:
                    self._last_line_is_progress = False
                end_it = self.log_buffer.get_end_iter()
                self.log_buffer.insert(end_it, text)

            mark = self.log_buffer.create_mark(
                None, self.log_buffer.get_end_iter(), False
            )
            self.log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
            return False

        GLib.idle_add(_do)

    def _update_status(self, message: str, fraction: float) -> None:
        def _do() -> bool:
            clamped = max(0.0, min(1.0, fraction))
            self.lbl_list_status.set_label(message)
            self.lbl_log_status.set_label(message)
            self.log_progress_bar.set_fraction(clamped)
            self.lbl_log_pct.set_label(f"{int(clamped * 100)}%")
            return False

        GLib.idle_add(_do)

    def start_scan(self) -> None:
        if self.is_busy:
            return
        self._set_busy(True, "Consultando versões nas fontes originais...")

        def _worker() -> None:
            try:
                upd, ok = self.engine.scan_all(status_cb=self._update_status)

                def _finish() -> bool:
                    self.updates = upd
                    self.up_to_date = ok
                    direct_c = sum(
                        1 for x in upd if x.source_category == "direct_deb"
                    )
                    app_c = sum(1 for x in upd if x.source_category == "app_repo")
                    fp_c = sum(1 for x in upd if x.source_category == "flatpak")
                    sys_c = sum(1 for x in upd if x.source_category == "system")
                    summary_msg = (
                        f"Encontradas {len(upd)} atualizações disponíveis "
                        f"({direct_c} Fontes Diretas, {app_c} Apps Oficiais, "
                        f"{fp_c} Flatpak, {sys_c} Pacotes do Sistema)."
                    )
                    self._set_busy(False, summary_msg)
                    self._update_counters()
                    self._populate_list()
                    return False

                GLib.idle_add(_finish)
            except Exception as e:
                GLib.idle_add(
                    self._set_busy, False, f"Erro ao verificar atualizações: {e}"
                )

        threading.Thread(target=_worker, daemon=True).start()

    def start_sync_repositories(self) -> None:
        if self.is_busy:
            return
        # Muda imediatamente para a Tela Cheia de Log em Tempo Real
        self.show_screen("log")
        now_str = datetime.now().strftime("%H:%M:%S")
        self._append_log(
            f"\n[{now_str}] 🔄 Iniciando sincronização de repositórios oficiais...\n",
            False,
        )
        self._set_busy(
            True, "Sincronizando listas de pacotes com as fontes originais..."
        )

        def _worker() -> None:
            self.engine.sync_repositories(
                log_cb=self._append_log, status_cb=self._update_status
            )
            upd, ok = self.engine.scan_all(status_cb=self._update_status)

            def _finish() -> bool:
                self.updates = upd
                self.up_to_date = ok
                self._set_busy(
                    False,
                    f"Repositórios sincronizados! {len(upd)} atualizações disponíveis.",
                )
                self._update_counters()
                self._populate_list()
                return False

            GLib.idle_add(_finish)

        threading.Thread(target=_worker, daemon=True).start()

    def start_apply_single(self, item: UpdateItem) -> None:
        if self.is_busy:
            return
        self._run_update_items([item])

    def start_apply_updates(self, only_selected: bool = True) -> None:
        if self.is_busy:
            return
        if not only_selected:
            for x in self.updates:
                x.selected = True
            self._populate_list()
            self._update_counters()

        target_items = [x for x in self.updates if x.selected]
        if not target_items:
            return
        self._run_update_items(target_items)

    def _run_update_items(self, target_items: List[UpdateItem]) -> None:
        # Abre imediatamente a Tela Cheia de Log em Tempo Real!
        self.show_screen("log")
        now_str = datetime.now().strftime("%H:%M:%S")
        names_preview = ", ".join(x.display_name for x in target_items[:6])
        if len(target_items) > 6:
            names_preview += f" e mais {len(target_items) - 6}"

        self._append_log(
            f"\n════════════════════════════════════════════════════════════════════════\n"
            f"[{now_str}] 🚀 INICIANDO ATUALIZAÇÃO DE {len(target_items)} ITEM(NS)\n"
            f"Alvos: {names_preview}\n"
            f"════════════════════════════════════════════════════════════════════════\n",
            False,
        )
        self._set_busy(
            True,
            f"Iniciando atualização de {len(target_items)} aplicativo(s)/pacote(s)...",
        )

        def _worker() -> None:
            ok = self.engine.apply_updates(
                target_items,
                log_cb=self._append_log,
                status_cb=self._update_status,
            )
            upd, up_ok = self.engine.scan_all(status_cb=self._update_status)

            def _finish() -> bool:
                self.updates = upd
                self.up_to_date = up_ok
                msg = (
                    f"✔ Atualização concluída! Restam {len(upd)} atualizações pendentes."
                    if ok
                    else f"⚠️ Atualização finalizada com avisos ({len(upd)} pendentes). Veja os detalhes no log abaixo."
                )
                self._set_busy(False, msg)
                self._update_counters()
                self._populate_list()
                return False

            GLib.idle_add(_finish)

        threading.Thread(target=_worker, daemon=True).start()

    # ─── Janela de Varredura de Aplicativos e Descoberta Automática de Fontes ───

    def _on_discover_sources_clicked(self, _btn: Gtk.Button) -> None:
        win = Gtk.Window(
            title="Varredura de Aplicativos & Descoberta Automática de Fontes",
            transient_for=self,
            modal=True,
            default_width=940,
            default_height=660,
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        win.set_child(root)

        # Topo com instruções e botões de ação
        top_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top_card.add_css_class("log-header-card")
        top_card.set_margin_start(16)
        top_card.set_margin_end(16)
        top_card.set_margin_top(14)
        top_card.set_margin_bottom(10)

        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        spinner = Gtk.Spinner()
        header_row.append(spinner)

        lbl_status = Gtk.Label(
            label="Iniciando varredura dos aplicativos instalados na máquina..."
        )
        lbl_status.add_css_class("log-status-title")
        lbl_status.set_halign(Gtk.Align.START)
        lbl_status.set_hexpand(True)
        lbl_status.set_ellipsize(Pango.EllipsizeMode.END)
        header_row.append(lbl_status)

        btn_manual = Gtk.Button()
        man_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        man_box.append(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        man_box.append(Gtk.Label(label="Fonte GitHub Manual"))
        btn_manual.set_child(man_box)
        btn_manual.connect(
            "clicked",
            lambda *_: self._open_manual_github_dialog(
                parent_win=win, on_saved=lambda: _run_discovery(force=False)
            ),
        )
        header_row.append(btn_manual)

        btn_rescan = Gtk.Button()
        res_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        res_box.append(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        res_box.append(Gtk.Label(label="Re-escanear Fontes na Web"))
        btn_rescan.set_child(res_box)
        header_row.append(btn_rescan)

        top_card.append(header_row)

        prog_bar = Gtk.ProgressBar()
        prog_bar.set_fraction(0.0)
        top_card.append(prog_bar)

        sub_lbl = Gtk.Label(
            label=(
                "O scanner analisa pacotes .deb instalados manualmente (sem repositório APT), diretórios /opt e AppImages,\n"
                "buscando automaticamente a fonte oficial de atualização via Homepage do pacote, GitHub Releases API e Catálogo Oficial."
            )
        )
        sub_lbl.add_css_class("app-summary")
        sub_lbl.set_halign(Gtk.Align.START)
        sub_lbl.set_wrap(True)
        top_card.append(sub_lbl)

        root.append(top_card)

        # Lista de aplicativos descobertos
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_margin_start(16)
        scroll.set_margin_end(16)
        scroll.set_margin_bottom(10)

        disc_list = Gtk.ListBox()
        disc_list.set_selection_mode(Gtk.SelectionMode.NONE)
        disc_list.add_css_class("boxed-list")
        scroll.set_child(disc_list)
        root.append(scroll)

        # Barra inferior do modal
        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bottom_bar.add_css_class("bottom-bar")

        lbl_bottom = Gtk.Label(label="Varrendo sistema...")
        lbl_bottom.set_halign(Gtk.Align.START)
        lbl_bottom.set_hexpand(True)
        bottom_bar.append(lbl_bottom)

        btn_link_all = Gtk.Button(label="Vincular Todas as Fontes Encontradas")
        btn_link_all.add_css_class("suggested-action")
        btn_link_all.set_sensitive(False)
        bottom_bar.append(btn_link_all)

        btn_close = Gtk.Button(label="Concluir e Atualizar Lista")
        btn_close.connect(
            "clicked",
            lambda *_: (win.destroy(), self.start_scan()),
        )
        bottom_bar.append(btn_close)

        root.append(bottom_bar)

        state: Dict[str, object] = {
            "apps": [],
            "sources": {},
            "changes_made": False,
        }

        def _clear_disc_list() -> None:
            while True:
                r = disc_list.get_row_at_index(0)
                if r is None:
                    break
                disc_list.remove(r)

        def _render_results(
            apps: List[DiscoveredApp],
            sources: Dict[str, DiscoveredSource],
        ) -> None:
            _clear_disc_list()
            installable_unlinked: List[DiscoveredSource] = []
            configured_Now = self.engine.direct_provider.get_configured_sources()

            for app in apps:
                src = sources.get(app.pkg_name)
                if (
                    app.current_source_status == "untracked"
                    and src
                    and src.is_installable_direct_source
                ):
                    installable_unlinked.append(src)

                row = Gtk.ListBoxRow()
                hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                hbox.add_css_class("app-row")

                # Ícone
                if app.icon_path:
                    img = Gtk.Image.new_from_file(app.icon_path)
                else:
                    img = Gtk.Image.new_from_icon_name(
                        app.icon_name or "application-x-executable"
                    )
                img.set_pixel_size(34)
                img.set_valign(Gtk.Align.CENTER)
                hbox.append(img)

                # Coluna central de informações
                info_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                info_col.set_hexpand(True)
                info_col.set_valign(Gtk.Align.CENTER)

                line1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                title_lbl = Gtk.Label(label=app.display_name)
                title_lbl.add_css_class("app-title")
                line1.append(title_lbl)

                pkg_lbl = Gtk.Label(
                    label=f"({app.pkg_name} • v{app.installed_version})"
                )
                pkg_lbl.add_css_class("pkg-tech-name")
                line1.append(pkg_lbl)

                kind_badge = Gtk.Label(label=app.install_kind_label)
                kind_badge.add_css_class("badge")
                if app.install_kind == "orphan_deb":
                    kind_badge.add_css_class("badge-direct")
                elif app.install_kind == "apt_repo":
                    kind_badge.add_css_class("badge-app-repo")
                else:
                    kind_badge.add_css_class("badge-system")
                line1.append(kind_badge)
                info_col.append(line1)

                # Linha 2: Status da fonte
                if app.current_source_status == "tracked_direct":
                    cfg_entry = configured_Now.get(app.pkg_name, {})
                    method_note = cfg_entry.get("discovery_method", "")
                    prefix = (
                        "✔ Fonte Direta Auto-Descoberta: "
                        if cfg_entry.get("auto_discovered")
                        else "✔ Fonte Direta Ativa: "
                    )
                    detail_txt = (
                        f"{prefix}{app.current_source_name} ({app.current_source_host})"
                    )
                    if method_note:
                        detail_txt += f"  •  {method_note}"
                elif app.current_source_status == "tracked_apt":
                    detail_txt = f"✔ Monitorado via Repositório APT Oficial: {app.current_source_name} ({app.current_source_host})"
                elif src and src.is_installable_direct_source:
                    ver_part = (
                        f" • Última versão remota: v{src.latest_version}"
                        if src.latest_version
                        else ""
                    )
                    detail_txt = (
                        f"🟢 Fonte Encontrada ({src.confidence_label}): {src.source_name}{ver_part}\n"
                        f"Método: {src.discovery_method}"
                    )
                elif src and src.found:
                    ver_part = (
                        f" (v{src.latest_version})" if src.latest_version else ""
                    )
                    detail_txt = (
                        f"🟡 {src.source_name}{ver_part} — {src.discovery_method}"
                    )
                else:
                    hp_note = (
                        f" • Homepage local: {app.homepage}"
                        if app.homepage
                        else ""
                    )
                    detail_txt = f"⚪ Sem release .deb direta localizada automaticamente{hp_note}"

                desc_lbl = Gtk.Label(label=detail_txt)
                desc_lbl.add_css_class("app-summary")
                desc_lbl.set_halign(Gtk.Align.START)
                desc_lbl.set_wrap(True)
                info_col.append(desc_lbl)

                hbox.append(info_col)

                # Coluna direita de botões de ação
                act_col = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                act_col.set_valign(Gtk.Align.CENTER)

                if (
                    app.current_source_status == "untracked"
                    and src
                    and src.is_installable_direct_source
                ):
                    btn_link = Gtk.Button(label="Vincular Fonte")
                    btn_link.add_css_class("suggested-action")

                    def _on_link_one(
                        _b: Gtk.Button, p_name: str = app.pkg_name, s: DiscoveredSource = src
                    ) -> None:
                        cfg = dict(s.config)
                        cfg["auto_discovered"] = True
                        cfg["discovery_method"] = s.discovery_method
                        self.engine.direct_provider.save_discovered_source(
                            p_name, cfg
                        )
                        state["changes_made"] = True
                        _run_discovery(force=False)

                    btn_link.connect("clicked", _on_link_one)
                    act_col.append(btn_link)

                elif (
                    app.current_source_status == "tracked_direct"
                    and app.pkg_name not in BUILTIN_DIRECT_SOURCES
                ):
                    btn_unlink = Gtk.Button(label="Desvincular")

                    def _on_unlink_one(
                        _b: Gtk.Button, p_name: str = app.pkg_name
                    ) -> None:
                        self.engine.direct_provider.remove_custom_source(p_name)
                        state["changes_made"] = True
                        _run_discovery(force=False)

                    btn_unlink.connect("clicked", _on_unlink_one)
                    act_col.append(btn_unlink)

                if app.install_kind in ("orphan_deb", "appimage", "opt_binary"):
                    btn_cfg = Gtk.Button(label="Configurar GitHub")
                    btn_cfg.set_tooltip_text(
                        f"Informar ou alterar manualmente o repositório GitHub para {app.pkg_name}"
                    )
                    btn_cfg.connect(
                        "clicked",
                        lambda _b, p_name=app.pkg_name: self._open_manual_github_dialog(
                            prefill_pkg=p_name,
                            parent_win=win,
                            on_saved=lambda: _run_discovery(force=False),
                        ),
                    )
                    act_col.append(btn_cfg)

                web_url = (
                    (src.download_url if src and src.download_url else None)
                    or app.homepage
                )
                if web_url and web_url.startswith("http"):
                    btn_web = Gtk.Button.new_from_icon_name("globe-symbolic")
                    btn_web.set_tooltip_text(f"Abrir no navegador: {web_url}")
                    btn_web.connect(
                        "clicked", lambda _b, u=web_url: webbrowser.open(u)
                    )
                    act_col.append(btn_web)

                hbox.append(act_col)
                row.set_child(hbox)
                disc_list.append(row)

            orphan_count = sum(
                1 for a in apps if a.install_kind in ("orphan_deb", "appimage", "opt_binary")
            )
            tracked_direct_count = sum(
                1 for a in apps if a.current_source_status == "tracked_direct"
            )
            lbl_bottom.set_label(
                f"{len(apps)} aplicativos analisados ({orphan_count} pacotes .deb locais/autônomos • "
                f"{tracked_direct_count} com fonte direta vinculada • "
                f"{len(installable_unlinked)} novas fontes prontas para vincular)"
            )
            btn_link_all.set_sensitive(len(installable_unlinked) > 0)
            btn_link_all.set_label(
                f"Vincular Todas as Fontes Encontradas ({len(installable_unlinked)})"
            )

        def _on_link_all(*_) -> None:
            sources: Dict[str, DiscoveredSource] = state.get("sources", {})  # type: ignore
            apps: List[DiscoveredApp] = state.get("apps", [])  # type: ignore
            for app in apps:
                src = sources.get(app.pkg_name)
                if (
                    app.current_source_status == "untracked"
                    and src
                    and src.is_installable_direct_source
                ):
                    cfg = dict(src.config)
                    cfg["auto_discovered"] = True
                    cfg["discovery_method"] = src.discovery_method
                    self.engine.direct_provider.save_discovered_source(
                        app.pkg_name, cfg
                    )
            state["changes_made"] = True
            _run_discovery(force=False)

        btn_link_all.connect("clicked", _on_link_all)

        def _run_discovery(force: bool = False) -> None:
            spinner.start()
            btn_rescan.set_sensitive(False)
            prog_bar.set_fraction(0.05)
            lbl_status.set_label(
                "Varrendo aplicativos instalados e pesquisando fontes oficiais..."
            )

            def _status_cb(msg: str, frac: float) -> None:
                def _ui() -> bool:
                    lbl_status.set_label(msg)
                    prog_bar.set_fraction(max(0.0, min(1.0, frac)))
                    return False

                GLib.idle_add(_ui)

            def _worker() -> None:
                apps, sources = self.engine.discover_apps_and_sources(
                    status_cb=_status_cb,
                    force_refresh=force,
                    auto_link_high_confidence=False,
                )

                def _finish() -> bool:
                    spinner.stop()
                    btn_rescan.set_sensitive(True)
                    prog_bar.set_fraction(1.0)
                    state["apps"] = apps
                    state["sources"] = sources
                    lbl_status.set_label(
                        f"✔ Varredura concluída: {len(apps)} aplicativos encontrados na máquina."
                    )
                    _render_results(apps, sources)
                    return False

                GLib.idle_add(_finish)

            threading.Thread(target=_worker, daemon=True).start()

        btn_rescan.connect("clicked", lambda *_: _run_discovery(force=True))
        win.present()
        _run_discovery(force=False)

    def _open_manual_github_dialog(
        self,
        prefill_pkg: str = "",
        parent_win: Optional[Gtk.Window] = None,
        on_saved: Optional[ object ] = None,
    ) -> None:
        dialog = Gtk.Window(
            title="Configurar Fonte Oficial do GitHub (.deb)",
            transient_for=parent_win or self,
            modal=True,
            default_width=460,
        )
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_margin_top(18)
        vbox.set_margin_bottom(18)
        vbox.set_margin_start(18)
        vbox.set_margin_end(18)

        info = Gtk.Label(
            label=(
                "Informe o nome do pacote instalado e o repositório oficial no GitHub\n"
                "para que o aplicativo verifique e instale novas releases (.deb) automaticamente."
            )
        )
        info.set_wrap(True)
        info.set_halign(Gtk.Align.START)
        vbox.append(info)

        pkg_entry = Gtk.Entry()
        pkg_entry.set_placeholder_text(
            "Nome do pacote instalado (ex: obsidian, localsend)"
        )
        if prefill_pkg:
            pkg_entry.set_text(prefill_pkg)
        vbox.append(pkg_entry)

        repo_entry = Gtk.Entry()
        repo_entry.set_placeholder_text(
            "Repositório no GitHub (ex: obsidianmd/obsidian-releases)"
        )
        vbox.append(repo_entry)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_halign(Gtk.Align.END)

        btn_cancel = Gtk.Button(label="Cancelar")
        btn_cancel.connect("clicked", lambda *_: dialog.destroy())
        btn_row.append(btn_cancel)

        btn_save = Gtk.Button(label="Salvar Fonte")
        btn_save.add_css_class("suggested-action")

        def _on_save(*_) -> None:
            pkg = pkg_entry.get_text().strip()
            repo = repo_entry.get_text().strip()
            if pkg and "/" in repo:
                self.engine.direct_provider.save_custom_github_source(pkg, repo)
                dialog.destroy()
                if callable(on_saved):
                    on_saved()
                else:
                    self.start_scan()

        btn_save.connect("clicked", _on_save)
        btn_row.append(btn_save)

        vbox.append(btn_row)
        dialog.set_child(vbox)
        dialog.present()
