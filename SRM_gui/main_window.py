from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QTabWidget,
    QMessageBox,
    QDialog,
    QFileDialog,
    QAction,
    QTabBar,
    QLabel,
)
from PyQt5.QtCore import QSettings
from SRM_core.utils import (
    resource_path,
    convert_inventory_to_xml,
    atomic_write_inventory,
    count_channels_with_issues,
)
import os
import sys
from obspy import Inventory
from obspy import read_inventory
from pathlib import Path
from obspy.clients.nrl import NRL
from SRM_core.nrl_index import NRLIndex
from SRM_gui.index_progress_dialog import IndexProgressDialog
from SRM_gui.io_progress import IOProgressDialog, IOSummary
from SRM_gui.manager_tab import ManagerTab
from SRM_gui.explorer_tab import ExplorerTab
from SRM_gui.response_tab import ResponseTab
from SRM_gui.dialogs import StationInventoryWizard, ImportFromMiniSEEDDialog
from SRM_gui.review_dialog import ReviewChangesDialog


def save_outcome(items, failed_paths, summary):
    """What a Save All run actually achieved.

    Returns ``(saved_paths, fully_saved)``: the paths whose job ran without
    error, and whether every file was written. Jobs skipped by a cancel are
    neither saved nor failed — they must keep their unsaved state.
    """
    saved_paths = {
        items[i][0] for i in summary.completed
    } - set(failed_paths)
    fully_saved = (
        len(summary.completed) == len(items) and not failed_paths
    )
    return saved_paths, fully_saved


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Station Response Manager")
        self.resize(1200, 700)

        self.loaded_files = {}
        self.open_tabs = {}

        self.nrl_root = resource_path(os.path.join("resources", "NRL"))
        while True:
            try:
                self.nrl = NRL(root=self.nrl_root)
                break
            except Exception:
                reply = QMessageBox.question(
                    self,
                    "NRL Not Found",
                    "NRL folder not detected at:\n"
                    f"{self.nrl_root}\n\nWould you like to select the NRL"
                    f"folder manually?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    folder = QFileDialog.getExistingDirectory(
                        self, "Select NRL Folder", os.path.expanduser("~")
                    )
                    if folder:
                        self.nrl_root = folder
                        continue
                QMessageBox.critical(
                    self,
                    "NRL Required",
                    "NRL folder is required to run this application."
                    "\nExiting.",
                )
                sys.exit(1)

        self.nrl_index = NRLIndex(self.nrl_root)
        if self.nrl_index.needs_rebuild():
            dialog = IndexProgressDialog(self.nrl_index, self)
            dialog.exec_()
        else:
            self.nrl_index.load_index()

        self.setAcceptDrops(True)
        self.setup_menu()
        self.setup_ui()
        self._status_label = QLabel()
        self.statusBar().addPermanentWidget(self._status_label, 1)
        self.update_status_bar()

    def setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        new_inventory = QAction("New Inventory", self)
        new_inventory.setShortcut("Ctrl+N")
        new_inventory.triggered.connect(self.create_new_inventory)
        file_menu.addAction(new_inventory)
        add_files = QAction("Add File(s)", self)
        add_files.setShortcut("Ctrl+Shift+O")
        add_files.triggered.connect(self.add_files)
        file_menu.addAction(add_files)
        add_data = QAction("Add Data", self)
        add_data.setShortcut("Ctrl+O")
        add_data.triggered.connect(self.add_data)
        file_menu.addAction(add_data)
        review_changes = QAction("Review Changes…", self)
        review_changes.setShortcut("Ctrl+E")
        review_changes.triggered.connect(self.review_changes)
        file_menu.addAction(review_changes)
        save_all = QAction("Save All Files", self)
        save_all.setShortcut("Ctrl+S")
        save_all.triggered.connect(self.save_all_files)
        file_menu.addAction(save_all)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        tools_menu = menubar.addMenu("Tools")
        build_inventory = QAction("Build Inventory", self)
        build_inventory.triggered.connect(self.build_new_inventory)
        tools_menu.addAction(build_inventory)
        convert_to_xml = QAction("Convert to XML", self)
        convert_to_xml.triggered.connect(self.convert_to_xml)
        tools_menu.addAction(convert_to_xml)
        view_menu = menubar.addMenu("View")
        toggle_theme = QAction("Toggle Theme", self)
        toggle_theme.setShortcut("Ctrl+T")
        toggle_theme.triggered.connect(self.toggle_theme)
        view_menu.addAction(toggle_theme)
        view_menu.addSeparator()
        font_increase = QAction("Increase Font Size", self)
        font_increase.setShortcut("Ctrl+=")
        font_increase.triggered.connect(lambda: self._change_font_size(1))
        view_menu.addAction(font_increase)
        font_decrease = QAction("Decrease Font Size", self)
        font_decrease.setShortcut("Ctrl+-")
        font_decrease.triggered.connect(lambda: self._change_font_size(-1))
        view_menu.addAction(font_decrease)
        font_reset = QAction("Reset Font Size", self)
        font_reset.setShortcut("Ctrl+0")
        font_reset.triggered.connect(lambda: self._change_font_size(0))
        view_menu.addAction(font_reset)
        view_menu.addSeparator()
        close_tab_action = QAction("Close Tab", self)
        close_tab_action.setShortcut("Ctrl+W")
        close_tab_action.triggered.connect(
            lambda: self.close_tab(self.tabs.currentIndex())
        )
        view_menu.addAction(close_tab_action)

    def _change_font_size(self, delta):
        app = QApplication.instance()
        font = app.font()
        if delta == 0:
            if not hasattr(self, '_default_font_size'):
                self._default_font_size = font.pointSize()
            font.setPointSize(self._default_font_size)
        else:
            if not hasattr(self, '_default_font_size'):
                self._default_font_size = font.pointSize()
            new_size = max(6, font.pointSize() + delta)
            font.setPointSize(new_size)
        app.setFont(font)
        if hasattr(self, 'manager_tab'):
            self.manager_tab.update_timeline()

    def setup_ui(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.manager_tab = ManagerTab(main_window=self)
        self.tabs.addTab(self.manager_tab, "Manager")
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.tabBar().setTabButton(0, QTabBar.RightSide, None)

    def _run_jobs(self, title, jobs, on_result, on_done=None):
        if not jobs:
            if on_done is not None:
                on_done(IOSummary(completed=set(), canceled=False))
            return
        dialog = IOProgressDialog(
            title, jobs, on_result, on_done, parent=self
        )
        dialog.exec_()

    def review_changes(self):
        if not self.loaded_files:
            QMessageBox.information(
                self, "Review Changes", "No files loaded."
            )
            return
        dialog = ReviewChangesDialog(self.loaded_files, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            self.save_all_files(review=False)

    def save_all_files(self, *, review=True):
        items = list(self.loaded_files.items())
        if not items:
            return

        # Show pending changes before writing anything; the dialog's
        # "Save All" accepts, "Close" aborts the save.
        if review and self.has_unsaved_changes():
            dialog = ReviewChangesDialog(self.loaded_files, parent=self)
            if dialog.exec_() != QDialog.Accepted:
                return

        failed_paths = set()
        jobs = [
            (
                f"Saving {os.path.basename(fp)}...",
                (lambda fp=fp, inv=inv:
                 atomic_write_inventory(inv, fp, fmt="STATIONXML")),
            )
            for fp, inv in items
        ]

        def on_result(idx, _result, error):
            if error is not None:
                fp = items[idx][0]
                failed_paths.add(fp)
                QMessageBox.warning(
                    self, "Error", f"Failed to save {fp}:\n{error}"
                )

        def on_done(summary):
            saved_paths, fully_saved = save_outcome(
                items, failed_paths, summary
            )
            if fully_saved:
                self.manager_tab.undo_stack.clear()
                self.manager_tab.redo_stack.clear()
            for key, widget in self.open_tabs.items():
                if key[0] == "explorer" and isinstance(widget, ExplorerTab):
                    if key[1] not in saved_paths:
                        continue
                    widget.undo_stack.clear()
                    widget.redo_stack.clear()
                    widget._baseline_snapshot = {}
                    widget.populate_tree(widget.current_inventory)
                elif (key[0] == "response"
                      and isinstance(widget, ResponseTab)):
                    tab_path = getattr(
                        widget.explorer_tab, "filepath", None
                    )
                    if tab_path and tab_path in saved_paths:
                        widget.commit_baseline()

            self.manager_tab.refresh()
            if fully_saved:
                QMessageBox.information(
                    self, "Save Complete",
                    "All inventories saved successfully.",
                )
            elif summary.canceled:
                QMessageBox.warning(
                    self, "Save Cancelled",
                    f"Save cancelled — {len(saved_paths)} of {len(items)} "
                    "files saved. The remaining files still have unsaved "
                    "changes.",
                )

        self._run_jobs("Saving files", jobs, on_result, on_done)

    def _load_paths_with_progress(self, paths):
        new_paths = []
        seen = set()
        for p in paths:
            try:
                abs_path = str(Path(p).resolve())
            except Exception:
                continue
            if abs_path in self.loaded_files or abs_path in seen:
                continue
            seen.add(abs_path)
            new_paths.append(abs_path)

        if not new_paths:
            return

        jobs = [
            (
                f"Loading {os.path.basename(p)}...",
                (lambda p=p: read_inventory(p)),
            )
            for p in new_paths
        ]

        def on_result(idx, inv, error):
            path = new_paths[idx]
            if error is not None:
                QMessageBox.warning(
                    self, "Error", f"Failed to load {path}:\n{error}"
                )
                return
            if inv is None:
                return
            self.loaded_files[path] = inv
            self.manager_tab.add_file_to_tree(path, inv)

        def on_done(_summary):
            self.update_status_bar()

        self._run_jobs("Loading files", jobs, on_result, on_done)

    def add_data(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder")
        if not folder:
            return
        exts = (".xml", ".dataless", ".dless")
        paths = [
            str(f.resolve())
            for f in Path(folder).rglob("*")
            if f.suffix.lower() in exts
        ]
        self._load_paths_with_progress(paths)

    def add_files(self):
        filepaths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Station Files",
            "",
            "Station/Response Files (*.xml *.dataless *.dless);;"
            "All Files (*)",
        )
        if not filepaths:
            return
        self._load_paths_with_progress(filepaths)

    def open_explorer_tab(self, filepath, inventory, force_new=False):
        if not force_new:
            for key, widget in self.open_tabs.items():
                if (key[0] == "explorer" and key[1] == filepath
                        and isinstance(widget, ExplorerTab)):
                    index = self.tabs.indexOf(widget)
                    self.tabs.setCurrentIndex(index)
                    return widget

        explorer = ExplorerTab(filepath=filepath, main_window=self)
        explorer.current_inventory = inventory
        explorer.populate_tree(inventory)

        existing = sum(
            1 for k in self.open_tabs
            if k[0] == "explorer" and k[1] == filepath
        )
        base_name = os.path.basename(filepath)
        title = f"Explorer - {base_name}"
        if existing > 0:
            title = f"Explorer - {base_name} ({existing + 1})"

        index = self.tabs.addTab(explorer, title)
        key = ("explorer", filepath, id(explorer))
        self.open_tabs[key] = explorer
        self.tabs.setCurrentIndex(index)
        return explorer

    def open_response_tab(self, response_id, response_data, explorer_tab):
        # Key on the Response object's identity, not its display id, so two
        # channels/epochs that render to the same id still get separate tabs.
        key = ("response", id(response_data))
        if key not in self.open_tabs:
            response_tab = ResponseTab(
                response_data, self, explorer_tab, self.nrl_root
            )
            index = self.tabs.addTab(response_tab, f"Response - {response_id}")
            self.open_tabs[key] = response_tab
            self.tabs.setCurrentIndex(index)
        else:
            index = self.tabs.indexOf(self.open_tabs[key])
            self.tabs.setCurrentIndex(index)

    def close_tab(self, index):
        if index == 0:
            return
        widget = self.tabs.widget(index)

        # Closing a tab reverts its unsaved edits below, so confirm first to
        # avoid silently discarding the user's work.
        if isinstance(widget, ExplorerTab):
            pending = bool(widget.undo_stack) or any(
                isinstance(t, ResponseTab) and t.explorer_tab is widget
                and t.undo_stack
                for t in self.open_tabs.values()
            )
        elif isinstance(widget, ResponseTab):
            pending = bool(widget.undo_stack)
        else:
            pending = False
        if pending:
            reply = QMessageBox.question(
                self, "Discard Changes",
                "This tab has unsaved changes. Discard them?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        inventory_touched = False

        if isinstance(widget, ExplorerTab):
            child_responses = [
                (k, t) for k, t in self.open_tabs.items()
                if (k[0] == "response" and isinstance(t, ResponseTab)
                    and t.explorer_tab is widget)
            ]
            for k, rtab in child_responses:
                if rtab.undo_stack:
                    rtab._revert_all()
                    inventory_touched = True
                ridx = self.tabs.indexOf(rtab)
                if ridx != -1:
                    self.tabs.removeTab(ridx)
                del self.open_tabs[k]

            if widget.undo_stack:
                widget._revert_all()
                inventory_touched = True
        elif isinstance(widget, ResponseTab):
            if widget.undo_stack:
                widget._revert_all()
                inventory_touched = True

        for key, tab in list(self.open_tabs.items()):
            if tab == widget:
                del self.open_tabs[key]
                break
        self.tabs.removeTab(index)

        if inventory_touched:
            self.manager_tab.refresh()
            for k, t in self.open_tabs.items():
                if (k[0] == "explorer" and isinstance(t, ExplorerTab)
                        and t.current_inventory is not None):
                    t._baseline_snapshot = {}
                    t.populate_tree(t.current_inventory)

    def has_unsaved_changes(self):
        if self.manager_tab.undo_stack:
            return True
        for widget in self.open_tabs.values():
            if (isinstance(widget, (ExplorerTab, ResponseTab))
                    and widget.undo_stack):
                return True
        return False

    def closeEvent(self, event):
        if self.has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Save before exiting?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Save:
                # Skip the review dialog here: event.accept() below runs
                # unconditionally, so rejecting a review would otherwise
                # close the app with the changes silently discarded.
                self.save_all_files(review=False)
        event.accept()

    def create_new_inventory(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Create New Inventory",
            "",
            "StationXML Files (*.xml);;All Files (*)",
        )
        if not filepath:
            return

        try:
            inv = Inventory(networks=[], source="Seismic Response Manager")
            self.loaded_files[filepath] = inv
            atomic_write_inventory(inv, filepath, fmt="STATIONXML")
            self.manager_tab.add_file_to_tree(filepath, inv)
            self.open_explorer_tab(filepath, inv)
            self.update_status_bar()
        except Exception as e:
            QMessageBox.warning(
                self, "Error", f"Failed to create inventory:\n{e}"
            )

    def build_new_inventory(self):

        reply = QMessageBox.question(
            self,
            "New Inventory Source",
            "Do you want to provide a MiniSEED file to pre-fill the form?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.No:

            inv_wizard = StationInventoryWizard(self.nrl_root, parent=self)
            inv_wizard.exec_()
            self._maybe_load_built_inventory(inv_wizard)

        elif reply == QMessageBox.Yes:

            import_dialog = ImportFromMiniSEEDDialog(parent=self)

            if import_dialog.exec_() == QDialog.Accepted:
                initial_data = import_dialog.get_initial_data()

                inv_wizard = StationInventoryWizard(
                    self.nrl_root, initial_data=initial_data, parent=self
                )
                inv_wizard.exec_()
                self._maybe_load_built_inventory(inv_wizard)

    def _maybe_load_built_inventory(self, wizard):
        # After the Build Inventory wizard saves a file, offer to load it.
        path = getattr(wizard, "saved_path", None)
        if not path:
            return
        reply = QMessageBox.question(
            self,
            "Load Inventory",
            f"Load the created inventory now?\n{path}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self._load_paths_with_progress([path])

    def convert_to_xml(self):
        input_path, _ = QFileDialog.getOpenFileName(
            None,
            "Select an Input Dataless or RESP File",
            "",
            "Response Files (*.dataless *.resp);;All Files (*)",
        )

        if not input_path:
            return

        default_output_name = (
            os.path.splitext(os.path.basename(input_path))[0] + ".xml"
        )

        output_path, _ = QFileDialog.getSaveFileName(
            None,
            "Save StationXML File As...",
            default_output_name,
            "StationXML Files (*.xml);;All Files (*)",
        )

        if not output_path:
            return

        success, message = convert_inventory_to_xml(input_path, output_path)

        msg_box = QMessageBox()
        if success:
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setText("Conversion Successful!")
        else:
            msg_box.setIcon(QMessageBox.Critical)
            msg_box.setText("Conversion Failed")

        msg_box.setInformativeText(message)
        msg_box.setWindowTitle("Conversion Status")
        msg_box.exec_()

    def toggle_theme(self):
        from app import make_dark_palette
        from SRM_core.utils import is_dark_theme
        app = QApplication.instance()
        settings = QSettings("SRM", "StationResponseManager")
        if is_dark_theme():
            app.setPalette(app.style().standardPalette())
            settings.setValue("theme", "light")
        else:
            app.setPalette(make_dark_palette())
            settings.setValue("theme", "dark")
        if hasattr(self, 'manager_tab'):
            self.manager_tab.refresh_theme()
        for key, widget in self.open_tabs.items():
            if key[0] == "response" and isinstance(widget, ResponseTab):
                widget.apply_theme()
                widget.plot_response(widget.selected_response)
        self.update_status_bar()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile().lower()
                if path.endswith(('.xml', '.dataless', '.dless')):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(('.xml', '.dataless', '.dless')):
                paths.append(p)
        self._load_paths_with_progress(paths)

    def update_status_bar(self):
        n_files = len(self.loaded_files)
        if n_files == 0:
            self._status_label.setText(
                "No data loaded \u2014 use File > Add Data or drag files here"
            )
            return
        n_nets = 0
        n_stas = 0
        n_chans = 0
        n_issues = 0
        for inv in self.loaded_files.values():
            n_issues += count_channels_with_issues(inv)
            for net in inv.networks:
                n_nets += 1
                for sta in net.stations:
                    n_stas += 1
                    n_chans += len(sta.channels)
        text = (
            f"{n_files} file{'s' if n_files != 1 else ''} | "
            f"{n_nets} network{'s' if n_nets != 1 else ''} | "
            f"{n_stas} station{'s' if n_stas != 1 else ''} | "
            f"{n_chans} channel{'s' if n_chans != 1 else ''}"
        )
        if n_issues:
            text += (
                f"  ⚠ {n_issues} channel"
                f"{'s' if n_issues != 1 else ''} with metadata issues"
            )
        self._status_label.setText(text)
