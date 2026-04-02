import sys
import os
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QPalette, QColor
from PyQt5.QtCore import QSettings
from SRM_core.utils import resource_path
from SRM_gui.main_window import MainWindow


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


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setDesktopFileName("SRM")
    icon = QIcon(resource_path(os.path.join('resources', 'icon.ico')))
    icon.addFile(resource_path(os.path.join('resources', 'icon.png')))
    app.setWindowIcon(icon)

    settings = QSettings("SRM", "StationResponseManager")
    if settings.value("theme", "light") == "dark":
        app.setPalette(make_dark_palette())

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
