#!/usr/bin/env python3
import sys
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio

from src.ui.window import UpdaterWindow


class UpdaterApplication(Adw.Application):
    """Aplicação Desktop Nativa GTK4 / Libadwaita para atualização de apps."""

    def __init__(self) -> None:
        super().__init__(
            application_id="br.com.chrystian.AtualizadorApps",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        # Preferência por esquema de cores escuro/adaptativo moderno
        style_mgr = Adw.StyleManager.get_default()
        style_mgr.set_color_scheme(Adw.ColorScheme.PREFER_DARK)

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            win = UpdaterWindow(self)
        win.present()


def main() -> int:
    app = UpdaterApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
