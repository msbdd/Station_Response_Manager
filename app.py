import sys
import os
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from SRM_core.utils import resource_path
from SRM_gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setDesktopFileName("SRM")
    icon = QIcon(resource_path(os.path.join('resources', 'icon.ico')))
    icon.addFile(resource_path(os.path.join('resources', 'icon.png')))
    app.setWindowIcon(icon)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
