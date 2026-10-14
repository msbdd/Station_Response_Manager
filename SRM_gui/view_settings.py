"""View settings kept between sessions: the theme and the font size.

Stored with QSettings in INI format, so on every platform they are one
small text file in the user's config directory:

    Linux, macOS:  ~/.config/SRM/StationResponseManager.ini
                   ($XDG_CONFIG_HOME is honoured)
    Windows:       %APPDATA%\\SRM\\StationResponseManager.ini

Deleting the file brings back the defaults: the desktop's palette and the
system font size.
"""
from PyQt5.QtCore import QSettings
from PyQt5.QtGui import QColor, QFontDatabase, QPalette
from PyQt5.QtWidgets import QApplication

_ORG = "SRM"
_APP = "StationResponseManager"

THEMES = ("light", "dark")
MIN_FONT_PT = 6
MAX_FONT_PT = 72


def _store():
    store = QSettings(QSettings.IniFormat, QSettings.UserScope, _ORG, _APP)
    if not store.contains("theme"):
        # Older versions kept the theme in the native store (the registry
        # on Windows, a .conf file on Linux). Move it over once, so the
        # pick survives the switch and only one place holds it.
        legacy = QSettings(_ORG, _APP)
        if legacy.contains("theme"):
            store.setValue("theme", legacy.value("theme"))
            store.sync()
            legacy.remove("theme")
            legacy.sync()
    return store


def make_dark_palette():
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#2b2b2b"))
    p.setColor(QPalette.WindowText, QColor("#e0e0e0"))
    p.setColor(QPalette.Base, QColor("#1e1e1e"))
    p.setColor(QPalette.AlternateBase, QColor("#323232"))
    p.setColor(QPalette.ToolTipBase, QColor("#3c3c3c"))
    p.setColor(QPalette.ToolTipText, QColor("#e0e0e0"))
    p.setColor(QPalette.Text, QColor("#e0e0e0"))
    p.setColor(QPalette.Button, QColor("#3c3c3c"))
    p.setColor(QPalette.ButtonText, QColor("#e0e0e0"))
    p.setColor(QPalette.BrightText, QColor("#ff4444"))
    p.setColor(QPalette.Link, QColor("#56a8f5"))
    p.setColor(QPalette.Highlight, QColor("#2979ff"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#777777"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#777777"))
    return p


def apply_theme(name):
    """Apply the "light" or "dark" palette.

    Startup and View > Toggle Theme both come through here. Startup used
    to apply only "dark", so a saved "light" kept whatever palette the
    desktop hands Qt, which is dark on a dark KDE/GNOME setup."""
    app = QApplication.instance()
    if name == "dark":
        app.setPalette(make_dark_palette())
    else:
        app.setPalette(app.style().standardPalette())


def saved_theme():
    """The saved theme, or None when none (or an unknown one) is saved."""
    theme = _store().value("theme")
    return theme if theme in THEMES else None


def save_theme(name):
    store = _store()
    store.setValue("theme", name)
    store.sync()


def saved_font_size():
    """The saved point size, or None when none (or a bad one) is saved."""
    try:
        size = int(_store().value("font_size"))
    except (TypeError, ValueError):
        return None
    return size if MIN_FONT_PT <= size <= MAX_FONT_PT else None


def save_font_size(size):
    """Save ``size``; None forgets it, so the system size applies again."""
    store = _store()
    if size is None:
        store.remove("font_size")
    else:
        store.setValue("font_size", int(size))
    store.sync()


def system_font_size():
    # Unlike QApplication.font(), unaffected by QApplication.setFont.
    return QFontDatabase.systemFont(QFontDatabase.GeneralFont).pointSize()


def set_font_size(size):
    app = QApplication.instance()
    font = app.font()
    font.setPointSize(size)
    app.setFont(font)


def restore():
    """Apply the saved view settings. With no theme saved the desktop's
    palette stays, as it did before the user ever toggled."""
    theme = saved_theme()
    if theme is not None:
        apply_theme(theme)
    size = saved_font_size()
    if size is not None:
        set_font_size(size)
