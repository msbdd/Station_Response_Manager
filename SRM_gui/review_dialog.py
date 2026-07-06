import os

from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
)
from PyQt5.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PyQt5.QtCore import Qt

from SRM_core.utils import diff_inventory_vs_file, is_dark_theme


class _DiffHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        dark = is_dark_theme()
        self._added = QTextCharFormat()
        self._added.setForeground(
            QColor("#81c784" if dark else "#1b5e20")
        )
        self._removed = QTextCharFormat()
        self._removed.setForeground(
            QColor("#e57373" if dark else "#b71c1c")
        )
        self._header = QTextCharFormat()
        self._header.setForeground(
            QColor("#9e9e9e" if dark else "#616161")
        )
        self._header.setFontWeight(QFont.Bold)

    def highlightBlock(self, text):
        if text.startswith(("+++", "---", "@@", "!")):
            self.setFormat(0, len(text), self._header)
        elif text.startswith("+"):
            self.setFormat(0, len(text), self._added)
        elif text.startswith("-"):
            self.setFormat(0, len(text), self._removed)


class ReviewChangesDialog(QDialog):
    """Show pending in-memory changes per loaded file as a unified diff
    against the on-disk baseline. Accepting the dialog means "save all"."""

    def __init__(self, loaded_files, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Changes")
        self.resize(950, 600)
        self._loaded_files = loaded_files
        self._diff_cache = {}

        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        self.file_list = QListWidget()
        for path in loaded_files:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.file_list.addItem(item)
        self.file_list.currentItemChanged.connect(self._on_file_selected)
        splitter.addWidget(self.file_list)

        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFont("Monospace")
        font.setStyleHint(QFont.TypeWriter)
        self.diff_view.setFont(font)
        self._highlighter = _DiffHighlighter(self.diff_view.document())
        splitter.addWidget(self.diff_view)
        splitter.setSizes([250, 700])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)

        buttons = QDialogButtonBox()
        buttons.addButton("Save All", QDialogButtonBox.AcceptRole)
        buttons.addButton("Close", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self.file_list.count():
            self.file_list.setCurrentRow(0)

    def _compute_diff(self, path):
        # Re-reading and serializing a large file blocks the GUI thread;
        # cache per path and show a wait cursor meanwhile.
        if path not in self._diff_cache:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._diff_cache[path] = diff_inventory_vs_file(
                    path, self._loaded_files[path]
                )
            finally:
                QApplication.restoreOverrideCursor()
        return self._diff_cache[path]

    def _on_file_selected(self, current, previous):
        if current is None:
            self.diff_view.setPlainText("")
            return
        path = current.data(Qt.UserRole)
        diff = self._compute_diff(path)
        if not diff:
            marker = "(unchanged)"
        elif diff.startswith("!"):
            marker = "(baseline unavailable)"
        else:
            marker = "(modified)"
        current.setText(f"{os.path.basename(path)}  {marker}")
        self.diff_view.setPlainText(
            diff or "No changes compared to the file on disk."
        )
