import sys
import os

if os.environ.get("XDG_SESSION_TYPE") == "wayland" \
        and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

from PyQt5.QtWidgets import QApplication  # noqa: E402
from PyQt5.QtGui import QIcon
from SRM_core.utils import resource_path
from SRM_gui import view_settings
from SRM_gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setDesktopFileName("SRM")
    icon = QIcon(resource_path(os.path.join('resources', 'icon.ico')))
    icon.addFile(resource_path(os.path.join('resources', 'icon.png')))
    app.setWindowIcon(icon)

    # After setStyle, which resets the palette; before the window, so its
    # startup dialogs (NRL prompt, index build) already use the settings.
    view_settings.restore()

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
