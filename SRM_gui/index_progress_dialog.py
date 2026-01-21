from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar,
    QPushButton, QApplication
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal


class IndexBuildWorker(QThread):

    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int, int)
    error = pyqtSignal(str)

    def __init__(self, nrl_index):
        super().__init__()
        self.nrl_index = nrl_index

    def run(self):
        try:
            print(f"[DEBUG] Starting index build for: "
                  f"{self.nrl_index.nrl_root}")
            print(f"[DEBUG] Index path: {self.nrl_index.index_path}")

            def progress_callback(current, total, message):
                print(f"[DEBUG] Progress: {current}/{total} - {message}")
                self.progress.emit(current, total, message)

            sensors, dataloggers = self.nrl_index.build_index(
                progress_callback
                )
            print(f"[DEBUG] Build complete: {sensors} sensors, "
                  f"{dataloggers} dataloggers")
            self.finished.emit(sensors, dataloggers)

        except Exception as e:
            import traceback
            error_msg = f"{e}\n{traceback.format_exc()}"
            print(f"[DEBUG] Error: {error_msg}")
            self.error.emit(str(e))


class IndexProgressDialog(QDialog):
    def __init__(self, nrl_index, parent=None):
        super().__init__(parent)
        self.nrl_index = nrl_index
        self.setWindowTitle("Building NRL Index")
        self.setMinimumWidth(500)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)

        self._init_ui()
        self._start_indexing()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self.info_label = QLabel(
            "Building instrument response index...\n"
            "This is a one-time operation that enables automatic\n"
            "detection of NRL instruments in loaded responses."
        )
        layout.addWidget(self.info_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Initializing...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.result_label = QLabel("")
        self.result_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.result_label)

        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn)

    def _start_indexing(self):
        self.worker = IndexBuildWorker(self.nrl_index)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, current, total, message):
        if total > 0:
            percent = int((current / total) * 100)
            self.progress_bar.setValue(percent)

        # Truncate long messages
        if len(message) > 60:
            message = message[:57] + "..."
        self.status_label.setText(message)
        QApplication.processEvents()

    def _on_finished(self, sensors_count, dataloggers_count):
        self.progress_bar.setValue(100)
        self.status_label.setText("Indexing complete!")
        self.result_label.setText(
            f"Indexed {sensors_count} sensors and "
            f"{dataloggers_count} dataloggers."
        )
        self.close_btn.setEnabled(True)
        self.setWindowFlags(self.windowFlags() | Qt.WindowCloseButtonHint)

    def _on_error(self, error_msg):
        self.status_label.setText(f"Error: {error_msg}")
        self.result_label.setText("Indexing failed. "
                                  "You can try rebuilding later.")
        self.result_label.setStyleSheet("font-weight: bold; color: red;")
        self.close_btn.setEnabled(True)
        self.setWindowFlags(self.windowFlags() | Qt.WindowCloseButtonHint)
