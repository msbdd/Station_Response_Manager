from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal


class _IOWorker(QThread):
    progress = pyqtSignal(int, int, str)
    item_done = pyqtSignal(int, object, object)
    finished_all = pyqtSignal()

    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs
        self._canceled = False

    def cancel(self):
        self._canceled = True

    def run(self):
        total = len(self.jobs)
        for i, (label, fn) in enumerate(self.jobs):
            if self._canceled:
                break
            self.progress.emit(i, total, label)
            try:
                result = fn()
                self.item_done.emit(i, result, None)
            except Exception as e:
                self.item_done.emit(i, None, e)
        self.finished_all.emit()


class IOProgressDialog(QDialog):
    def __init__(self, title, jobs, on_result, on_done=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self.setModal(True)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowCloseButtonHint
        )

        self._on_result = on_result
        self._on_done = on_done
        self._total = len(jobs)

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Starting...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Indeterminate "activity" bar — animates while any job runs so the
        # user can see the app is alive even for a single opaque obspy call.
        self.activity_bar = QProgressBar()
        self.activity_bar.setRange(0, 0)
        self.activity_bar.setTextVisible(False)
        layout.addWidget(self.activity_bar)

        # Determinate N/M bar — only shown for multi-job batches.
        self.overall_bar = None
        if self._total > 1:
            self.overall_bar = QProgressBar()
            self.overall_bar.setRange(0, self._total)
            self.overall_bar.setValue(0)
            layout.addWidget(self.overall_bar)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        layout.addWidget(self.cancel_btn)

        self.worker = _IOWorker(jobs)
        self.worker.progress.connect(self._on_progress)
        self.worker.item_done.connect(self._on_item_done)
        self.worker.finished_all.connect(self._on_finished_all)
        self.worker.start()

    def _on_cancel_clicked(self):
        self.worker.cancel()
        self.cancel_btn.setEnabled(False)
        self.status_label.setText("Cancelling...")

    def _on_progress(self, idx, total, label):
        truncated = label if len(label) <= 80 else label[:77] + "..."
        if total > 1:
            self.status_label.setText(f"[{idx + 1}/{total}] {truncated}")
        else:
            self.status_label.setText(truncated)

    def _on_item_done(self, idx, result, error):
        try:
            self._on_result(idx, result, error)
        except Exception:
            pass
        if self.overall_bar is not None:
            self.overall_bar.setValue(idx + 1)

    def _on_finished_all(self):
        # Freeze the marquee at "full" briefly so it doesn't look mid-stride.
        self.activity_bar.setRange(0, 1)
        self.activity_bar.setValue(1)
        self.cancel_btn.setEnabled(False)
        if self._on_done is not None:
            try:
                self._on_done()
            except Exception:
                pass
        self.accept()
