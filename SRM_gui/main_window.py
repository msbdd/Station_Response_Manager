from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QFileDialog,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QTabWidget,
    QMessageBox,
    QSplitter,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QComboBox,
    QInputDialog,
    QGroupBox,
    QRadioButton,
    QCheckBox,
    QScrollArea,
    QHBoxLayout,
    QFormLayout,
    QAction,
    QDateTimeEdit,
    QTabBar,
)
from copy import deepcopy
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtGui import QColor, QFont, QBrush
from PyQt5.QtCore import Qt, QTimer, QDateTime
from SRM_core.utils import (
    combine_resp,
    resource_path,
    wrap_text,
    convert_inventory_to_xml,
    natural_sort_key
)
import os
import sys
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
)
from matplotlib.figure import Figure
from obspy import Inventory, UTCDateTime, read
from obspy.core.inventory.response import Response
from obspy.core.inventory.response import (
    ResponseStage,
    PolesZerosResponseStage,
    CoefficientsTypeResponseStage,
    ResponseListResponseStage,
    FIRResponseStage,
    PolynomialResponseStage,
    ResponseListElement,
)
import numpy as np
from obspy import read_inventory
from obspy.core.inventory import Station, Network, Channel
import configparser
import copy
import json
from obspy.clients.nrl import NRL
from pathlib import Path
import colorsys


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.ax_amp = self.fig.add_subplot(211)
        self.ax_phase = self.fig.add_subplot(212, sharex=self.ax_amp)
        self.fig.tight_layout()
        super().__init__(self.fig)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Seismic Inventory Manager")
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

        self.setup_menu()
        self.setup_ui()

    def setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        new_inventory = QAction("New Inventory", self)
        new_inventory.triggered.connect(self.create_new_inventory)
        file_menu.addAction(new_inventory)
        add_data = QAction("Add Data", self)
        add_data.triggered.connect(self.add_data)
        file_menu.addAction(add_data)
        save_all = QAction("Save All Files", self)
        save_all.triggered.connect(self.save_all_files)
        file_menu.addAction(save_all)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        tools_menu = menubar.addMenu("Tools")
        build_inventory = QAction("Build Inventory", self)
        build_inventory.triggered.connect(self.build_new_inventory)
        tools_menu.addAction(build_inventory)
        convert_to_xml = QAction("Convert to XML", self)
        convert_to_xml.triggered.connect(self.convert_to_xml)
        tools_menu.addAction(convert_to_xml)

    def setup_ui(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.manager_tab = ManagerTab(main_window=self)
        self.tabs.addTab(self.manager_tab, "Manager")
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.tabBar().setTabButton(0, QTabBar.RightSide, None)

    def save_all_files(self):

        for filepath, inv in self.loaded_files.items():
            try:
                inv.write(filepath, format="STATIONXML")
                for (tab_type, tab_id), widget in self.open_tabs.items():
                    if tab_type == "explorer" and isinstance(
                        widget, ExplorerTab
                    ):
                        inv = self.loaded_files.get(tab_id)
                        if inv:
                            widget.populate_tree(inv)
                self.manager_tab.refresh()
            except Exception as e:
                QMessageBox.warning(
                    self, "Error", f"Failed to save {filepath}:\n{e}"
                )
        QMessageBox.information(
            self, "Save Complete", "All inventories saved successfully."
        )

    def add_data(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder")
        if not folder:
            return

        exts = (".xml", ".dataless", ".dless")
        for file in Path(folder).rglob("*"):
            if file.suffix.lower() in exts:
                try:
                    abs_path = str(file.resolve())
                    inv = read_inventory(abs_path)
                    self.loaded_files[abs_path] = inv
                    self.manager_tab.add_file_to_tree(abs_path, inv)
                except Exception as e:
                    QMessageBox.warning(
                        self, "Error", f"Failed to load {file}:\n{e}"
                    )

    def open_explorer_tab(self, filepath, inventory):
        key = ("explorer", filepath)
        if key not in self.open_tabs:
            explorer = ExplorerTab(filepath=filepath, main_window=self)
            explorer.populate_tree(inventory)
            index = self.tabs.addTab(
                explorer, f"Explorer - {os.path.basename(filepath)}"
            )
            self.open_tabs[key] = explorer
            self.tabs.setCurrentIndex(index)
        else:
            index = self.tabs.indexOf(self.open_tabs[key])
            self.tabs.setCurrentIndex(index)

    def open_response_tab(self, response_id, response_data, explorer_tab):
        key = ("response", response_id)
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
        for key, tab in list(self.open_tabs.items()):
            if tab == widget:
                del self.open_tabs[key]
                break
        self.tabs.removeTab(index)

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
            inv.write(filepath, format="STATIONXML")
            self.manager_tab.add_file_to_tree(filepath, inv)
            self.open_explorer_tab(filepath, inv)
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
            if inv_wizard.exec_() == QDialog.Accepted:
                print("Inventory creation successful!")

        elif reply == QMessageBox.Yes:

            import_dialog = ImportFromMiniSEEDDialog(parent=self)

            if import_dialog.exec_() == QDialog.Accepted:
                initial_data = import_dialog.get_initial_data()

                inv_wizard = StationInventoryWizard(
                    self.nrl_root, initial_data=initial_data, parent=self
                )
                if inv_wizard.exec_() == QDialog.Accepted:
                    print("Inventory creation from MiniSEED successful!")

    def convert_to_xml(self):
        input_path, _ = QFileDialog.getOpenFileName(
            None,
            "Select an Input Dataless or RESP File",
            "",
            "Response Files (*.dataless *.resp);;All Files (*)",
        )

        if not input_path:
            print("Operation cancelled by user (no input file selected).")
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
            print("Operation cancelled by user (no output file selected).")
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


class ManagerTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

        layout = QHBoxLayout(self)
        self.clipboard_item = None
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        self.all_stations = []
        self.network_colors = {}
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["Loaded Inventories"])
        self.file_tree.itemDoubleClicked.connect(self.handle_item_double_click)
        left_layout.addWidget(self.file_tree)
        self.file_tree.itemSelectionChanged.connect(
            self.handle_selection_changed
        )
        btn_layout = QHBoxLayout()
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self.new_item)
        btn_layout.addWidget(new_btn)

        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self.copy_selected_item)
        btn_layout.addWidget(copy_btn)

        paste_btn = QPushButton("Paste")
        paste_btn.clicked.connect(self.paste_to_selected_item)
        btn_layout.addWidget(paste_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self.delete_selected_item)
        btn_layout.addWidget(delete_btn)

        left_layout.addLayout(btn_layout)
        layout.addWidget(left_widget)

        self.map_view = QWebEngineView()
        layout.addWidget(self.map_view)
        current_dir = Path(__file__)
        map_template_path = current_dir.parent / "map_template.html"
        with map_template_path.open("r", encoding="utf-8") as f:
            html_template = f.read()

        self.map_view.setHtml(html_template)

        layout.setStretch(0, 1)
        layout.setStretch(1, 2)

    def get_color_for_network(self, network_name):
        if network_name not in self.network_colors:
            existing = len(self.network_colors)
            hue = (existing * 0.618033988749895) % 1
            r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.95)
            hex_color = "#{:02x}{:02x}{:02x}".format(
                int(r * 255), int(g * 255), int(b * 255)
            )
            self.network_colors[network_name] = hex_color
        return self.network_colors[network_name]

    def add_file_to_tree(self, abs_filepath, inventory):
        file_item = QTreeWidgetItem([os.path.basename(abs_filepath)])
        file_item.setData(0, Qt.UserRole, ("file", abs_filepath))
        file_item.setExpanded(True)
        file_item.setFlags(
            file_item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled
        )
        self.file_tree.addTopLevelItem(file_item)

        for net in inventory.networks:
            net_item = QTreeWidgetItem([f"Network: {net.code}"])
            net_item.setData(0, Qt.UserRole, ("network", net))
            file_item.addChild(net_item)

            for sta in net.stations:
                sta_item = QTreeWidgetItem([f"Station: {sta.code}"])
                sta_item.setData(0, Qt.UserRole, ("station", sta))
                net_item.addChild(sta_item)

                for chan in sta.channels:
                    chan_item = QTreeWidgetItem([f"Channel: {chan.code}"])
                    chan_item.setData(0, Qt.UserRole, ("channel", chan))
                    sta_item.addChild(chan_item)

                file_item.setExpanded(True)

        for net in inventory.networks:
            color = self.get_color_for_network(net.code)
            for sta in net.stations:
                self.all_stations.append(
                    {
                        "name": f"{net.code}.{sta.code}",
                        "lat": sta.latitude,
                        "lon": sta.longitude,
                        "network": net.code,
                        "color": color,
                    }
                )
        js_code = f"addStations({json.dumps(self.all_stations)});"
        self.map_view.page().runJavaScript(js_code)

    def handle_item_double_click(self, item, column):
        print("Double-click on item:", item.text(0))
        data = item.data(0, Qt.UserRole)
        if data and data[0] == "file":
            filepath = data[1]
            inventory = self.main_window.loaded_files.get(filepath)
            if inventory:
                self.main_window.open_explorer_tab(
                    filepath=filepath, inventory=inventory
                )

    def copy_selected_item(self):
        item = self.file_tree.currentItem()
        if item:
            self.clipboard_item = item.data(0, Qt.UserRole)
            QMessageBox.information(self, "Copied", f"Copied: {item.text(0)}")
        else:
            QMessageBox.warning(
                self, "No Selection", "Please select an item to copy."
            )

    def paste_to_selected_item(self):
        if not self.clipboard_item:
            QMessageBox.warning(self, "Clipboard Empty", "Copy an item first.")
            return

        target_item = self.file_tree.currentItem()
        if not target_item:
            QMessageBox.warning(
                self, "No Selection", "Select a parent item to paste into."
            )
            return

        target_data = target_item.data(0, Qt.UserRole)
        if not target_data:
            QMessageBox.warning(self, "Invalid Target", "Cannot paste here.")
            return

        type_, obj = self.clipboard_item
        pasted_item = None

        if type_ == "station" and target_data[0] == "network":
            station_copy = deepcopy(obj)
            target_data[1].stations.append(station_copy)
            pasted_item = self._add_station_to_tree(target_item, station_copy)

        elif type_ == "channel" and target_data[0] == "station":
            chan_copy = deepcopy(obj)
            target_data[1].channels.append(chan_copy)
            pasted_item = self._add_channel_to_tree(target_item, chan_copy)

        elif type_ == "network" and target_data[0] == "file":
            net_copy = deepcopy(obj)
            inv = self.main_window.loaded_files.get(target_data[1])
            if inv:
                inv.networks.append(net_copy)
                pasted_item = self._add_network_to_tree(target_item, net_copy)

        else:
            QMessageBox.warning(
                self, "Invalid Paste", "Cannot paste this item here."
            )

        if pasted_item:
            target_item.setExpanded(True)

    def delete_selected_item(self):
        item = self.file_tree.currentItem()
        if not item:
            QMessageBox.warning(
                self, "No Selection", "Select an item to delete."
            )
            return

        parent = item.parent()
        data = item.data(0, Qt.UserRole)
        if not data:
            QMessageBox.warning(
                self, "Invalid Selection", "Cannot delete this item."
            )
            return

        type_, obj = data

        if type_ == "station" and parent:
            net_data = parent.data(0, Qt.UserRole)
            if net_data and net_data[0] == "network":
                net_data[1].stations.remove(obj)
                parent.removeChild(item)
        elif type_ == "channel" and parent:
            sta_data = parent.data(0, Qt.UserRole)
            if sta_data and sta_data[0] == "station":
                sta_data[1].channels.remove(obj)
                parent.removeChild(item)
        else:
            QMessageBox.warning(
                self, "Invalid Delete", "Cannot delete this type of item."
            )

    def _add_network_to_tree(self, file_item, net):
        net_item = QTreeWidgetItem([f"Network: {net.code}"])
        net_item.setData(0, Qt.UserRole, ("network", net))
        file_item.addChild(net_item)

        for sta in net.stations:
            self._add_station_to_tree(net_item, sta)

        return net_item

    def _add_station_to_tree(self, net_item, sta):
        sta_item = QTreeWidgetItem([f"Station: {sta.code}"])
        sta_item.setData(0, Qt.UserRole, ("station", sta))
        net_item.addChild(sta_item)

        for chan in sta.channels:
            self._add_channel_to_tree(sta_item, chan)

        return sta_item

    def _add_channel_to_tree(self, sta_item, chan):
        chan_item = QTreeWidgetItem([f"Channel: {chan.code}"])
        chan_item.setData(0, Qt.UserRole, ("channel", chan))
        sta_item.addChild(chan_item)

        return chan_item

    def new_item(self):
        selected_item = self.file_tree.currentItem()

        if not selected_item:
            QMessageBox.warning(
                self, "No Selection", "Select a parent to add a new item."
            )
            return

        data = selected_item.data(0, Qt.UserRole)
        if not data:
            return

        type_, obj = data
        if type_ == "file":
            filepath = obj
            inventory = self.main_window.loaded_files.get(filepath)
            if not inventory:
                inventory = Inventory()
                self.main_window.loaded_files[filepath] = inventory

            net = Network(code="XX")
            inventory.networks.append(net)
            print(f"Added new network 'XX' to {filepath}")
            self._add_network_to_tree(selected_item, net)
            selected_item.setExpanded(True)

        elif type_ == "network":
            net = obj
            sta = Station(
                code="STA", latitude=0.0, longitude=0.0, elevation=0.0
            )
            net.stations.append(sta)
            self._add_station_to_tree(selected_item, sta)
            selected_item.setExpanded(True)

        elif type_ == "station":
            sta = obj
            chan = Channel(
                code="BHZ",
                location_code="",
                latitude=sta.latitude,
                longitude=sta.longitude,
                depth=0.0,
                elevation=sta.elevation,
                azimuth=0.0,
                dip=-90.0,
                sample_rate=100.0,
            )

            chan.response = Response()

            sta.channels.append(chan)
            self._add_channel_to_tree(selected_item, chan)
            selected_item.setExpanded(True)

        else:
            QMessageBox.warning(
                self,
                "Invalid Target",
                "You can only add new items under File, "
                "Network, or Station.",
            )

    def handle_selection_changed(self):
        selected_items = self.file_tree.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        data = item.data(0, Qt.UserRole)
        if data and data[0] == "station":
            sta = data[1]
            try:
                lat = sta.latitude
                lon = sta.longitude
                js = f"focusOnStation({lat}, {lon}, 10);"
                self.map_view.page().runJavaScript(js)
            except Exception as e:
                print(f"Error focusing on station: {e}")

    def refresh(self):
        self.file_tree.clear()
        for filepath, inventory in self.main_window.loaded_files.items():
            self.add_file_to_tree(filepath, inventory)


class ExplorerTab(QWidget):
    def __init__(self, filepath, main_window):
        super().__init__()
        self.filepath = filepath
        self.main_window = main_window
        self.current_inventory = None

        layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()
        self.object_label = QLabel("No item selected")
        self.new_button = QPushButton("New")
        self.new_button.setEnabled(True)
        self.new_button.clicked.connect(self.create_new_field)
        top_layout.addWidget(self.object_label)
        top_layout.addStretch()
        top_layout.addWidget(self.new_button)
        layout.addLayout(top_layout)
        # Search
        search_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Filter properties...")
        self.clear_search_btn = QPushButton("Clear")
        search_layout.addWidget(self.search_bar)
        search_layout.addWidget(self.clear_search_btn)
        layout.addLayout(search_layout)
        self.search_bar.textChanged.connect(self.filter_tree)
        self.clear_search_btn.clicked.connect(self.search_bar.clear)
        # Search_End
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Field", "Value"])
        self.tree.itemChanged.connect(self.handle_tree_edit)
        self.tree.itemDoubleClicked.connect(self.handle_tree_double_click)
        layout.addWidget(self.tree)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 150)
        self.info_label = QLabel(f"Loaded file: {filepath}")
        layout.addWidget(self.info_label)

    def create_new_field(self):
        item = self.tree.currentItem()
        if not item:
            QMessageBox.warning(self, "No Selection", "Please select an item.")
            return

        label_text = item.text(0)
        parent_inventory = self.current_inventory

        if label_text.startswith("Network:"):
            net_code = label_text.replace("Network:", "").strip()
            net = next(
                (n for n in parent_inventory.networks if n.code == net_code),
                None,
            )
            if not net:
                QMessageBox.warning(
                    self, "Error", "Could not find target Network."
                )
                return

            sta = Station(
                code="STA", latitude=0.0, longitude=0.0, elevation=0.0
            )
            net.stations.append(sta)
            self.populate_tree(parent_inventory)
            return

        elif label_text.startswith("Station:"):
            ref_data = item.data(0, Qt.UserRole)
            if (
                not ref_data
                or not isinstance(ref_data, tuple)
                or ref_data[0] != "station"
            ):
                QMessageBox.warning(
                    self, "Error", "Station reference not found."
                )
                return

            sta = ref_data[1]

            # Get parent network
            parent = item.parent()
            net_code = None
            while parent:
                label = parent.text(0)
                if label.startswith("Network:"):
                    net_code = label.replace("Network:", "").strip()
                    break
                parent = parent.parent()

            if not net_code:
                QMessageBox.warning(
                    self,
                    "Error",
                    "Could not find parent Network for Station.",
                )
                return

            net = next(
                (n for n in parent_inventory.networks if n.code == net_code),
                None,
            )
            if not net:
                QMessageBox.warning(
                    self, "Error", "Could not find Network in inventory."
                )
                return

            chan = Channel(
                code="BHZ",
                location_code="",
                latitude=sta.latitude,
                longitude=sta.longitude,
                depth=0.0,
                elevation=sta.elevation,
                azimuth=0.0,
                dip=-90.0,
                sample_rate=100.0,
            )
            chan.response = Response()
            sta.channels.append(chan)
            self.populate_tree(parent_inventory)
            return

        elif label_text.startswith("Channel:"):
            QMessageBox.information(
                self, "Info", "Channels cannot contain sub-items."
            )
            return

        elif label_text == "Response" or label_text.startswith("Stage"):
            QMessageBox.information(
                self, "Info", "Cannot add fields inside a response."
            )
            return

        obj = self.current_obj
        if not obj:
            QMessageBox.warning(self, "Error", "No valid object selected.")
            return

        all_attrs = sorted(
            [
                attr
                for attr in dir(obj)
                if not attr.startswith("_")
                and not callable(getattr(obj, attr))
                and isinstance(
                    getattr(obj, attr, None), (str, int, float, type(None))
                )
            ]
        )

        missing_attrs = [
            a for a in all_attrs if getattr(obj, a, None) in (None, "")
        ]

        if not missing_attrs:
            QMessageBox.information(
                self, "Info", "No missing editable fields found."
            )
            return

        attr, ok = QInputDialog.getItem(
            self,
            "Add Field",
            "Select a field to add:",
            missing_attrs,
            editable=False,
        )

        if ok and attr:
            setattr(obj, attr, "")
            self.populate_tree(self.current_inventory)

    def apply_modified_response(self, response):
        updated = False
        for net in self.current_inventory.networks:
            for sta in net.stations:
                for chan in sta.channels:
                    if chan.response is response:
                        chan.response = response
                        updated = True

        if updated:
            QMessageBox.information(
                self, "Saved", "Response updated successfully."
            )
            self.populate_tree(self.current_inventory)
        else:
            QMessageBox.warning(
                self, "Error", "Response not found in inventory."
            )

    def populate_tree(self, inv):
        self.tree.clear()
        self.current_inventory = inv
        try:
            for net in inv.networks:
                net_item = QTreeWidgetItem([f"Network: {net.code}", ""])
                self.tree.addTopLevelItem(net_item)

                for field in dir(net):
                    if not field.startswith("_") and not callable(
                        getattr(net, field)
                    ):
                        value = getattr(net, field)
                        if isinstance(value, (str, float, int)):
                            item = QTreeWidgetItem(
                                net_item, [field, str(value)]
                            )
                            item.setFlags(item.flags() | Qt.ItemIsEditable)
                            item.setData(0, Qt.UserRole, (net, field))

                for sta in net.stations:
                    sta_item = QTreeWidgetItem([f"Station: {sta.code}", ""])
                    sta_item.setData(0, Qt.UserRole, ("station", sta))
                    net_item.addChild(sta_item)

                    for field in dir(sta):
                        if not field.startswith("_") and not callable(
                            getattr(sta, field)
                        ):
                            value = getattr(sta, field)
                            if isinstance(value, (str, float, int)):
                                item = QTreeWidgetItem(
                                    sta_item, [field, str(value)]
                                )
                                item.setFlags(item.flags() | Qt.ItemIsEditable)
                                item.setData(0, Qt.UserRole, (sta, field))

                    for chan in sta.channels:
                        chan_item = QTreeWidgetItem(
                            [f"Channel: {chan.code}", ""]
                        )
                        sta_item.addChild(chan_item)
                        leaf_item = QTreeWidgetItem(
                            sta_item, [field, str(value)]
                        )
                        leaf_item.setFlags(
                            leaf_item.flags() | Qt.ItemIsEditable
                        )
                        leaf_item.setData(0, Qt.UserRole, (chan, field))
                        for field in dir(chan):
                            if not field.startswith("_") and not callable(
                                getattr(chan, field)
                            ):
                                value = getattr(chan, field)
                                if isinstance(value, (str, float, int)):
                                    item = QTreeWidgetItem(
                                        chan_item, [field, str(value)]
                                    )
                                    item.setFlags(
                                        item.flags() | Qt.ItemIsEditable
                                    )
                                    item.setData(0, Qt.UserRole, (chan, field))
                        resp = chan.response
                        if resp:
                            resp_item = QTreeWidgetItem(["Response", ""])
                            chan_item.addChild(resp_item)
                            resp_item.setData(
                                0, Qt.UserRole, ("response", chan.response)
                            )
                            resp_item.setFlags(
                                resp_item.flags()
                                | Qt.ItemIsSelectable
                                | Qt.ItemIsEnabled
                            )
                            if resp.instrument_sensitivity:
                                QTreeWidgetItem(
                                    resp_item,
                                    [
                                        "Sensitivity Value",
                                        str(resp.instrument_sensitivity.value),
                                    ],
                                )
                                QTreeWidgetItem(
                                    resp_item,
                                    [
                                        "Sensitivity Frequency",
                                        str(
                                            resp.instrument_sensitivity.
                                            frequency
                                        ),
                                    ],
                                )

                            for i, stage in enumerate(resp.response_stages):
                                stage_item = QTreeWidgetItem(
                                    [f"Stage {i+1}", type(stage).__name__]
                                )
                                resp_item.addChild(stage_item)

                                if hasattr(stage, "stage_gain"):
                                    QTreeWidgetItem(
                                        stage_item,
                                        ["Stage Gain", str(stage.stage_gain)],
                                    )

                                if hasattr(stage, "normalization_frequency"):
                                    QTreeWidgetItem(
                                        stage_item,
                                        [
                                            "Norm. Frequency",
                                            str(stage.normalization_frequency),
                                        ],
                                    )

                                if hasattr(stage, "poles"):
                                    poles_item = QTreeWidgetItem(
                                        stage_item, ["Poles", ""]
                                    )
                                    for j, p in enumerate(stage.poles):
                                        QTreeWidgetItem(
                                            poles_item,
                                            [
                                                f"Pole {j}",
                                                f"{p.real} + {p.imag}j",
                                            ],
                                        )

                                if hasattr(stage, "zeros"):
                                    zeros_item = QTreeWidgetItem(
                                        stage_item, ["Zeros", ""]
                                    )
                                    for j, z in enumerate(stage.zeros):
                                        QTreeWidgetItem(
                                            zeros_item,
                                            [
                                                f"Zero {j}",
                                                f"{z.real} + {z.imag}j",
                                            ],
                                        )
        except Exception as e:
            QTreeWidgetItem(self.tree, ["Error", str(e)])
        self.tree.itemSelectionChanged.connect(self.on_tree_selection_changed)
        self.current_obj = None
        self.tree.expandAll()

    def on_tree_selection_changed(self):
        item = self.tree.currentItem()
        if not item:
            self.current_obj = None
            self.new_button.setEnabled(False)
            return

        label = item.text(0)
        valid = True

        if label.startswith("Response") or label.startswith("Stage"):
            valid = False

        self.new_button.setEnabled(valid)

        ref = item.data(0, Qt.UserRole)
        if ref and isinstance(ref, tuple):
            self.current_obj = ref[0]
        else:
            self.current_obj = None

    def handle_tree_edit(self, item, column):
        if column != 1:
            return

        ref = item.data(0, Qt.UserRole)
        if ref is None:
            return

        ref_object, attr = ref
        new_value = item.text(1)

        old_value = getattr(ref_object, attr, None)
        try:
            if isinstance(old_value, float):
                new_value = float(new_value)
            elif isinstance(old_value, int):
                new_value = int(new_value)
            setattr(ref_object, attr, new_value)

            font = QFont()
            font.setBold(True)
            item.setFont(1, font)
            item.setForeground(1, QBrush(QColor("royalblue")))

            item.setData(1, Qt.UserRole, "modified")

        except Exception as e:
            QMessageBox.warning(
                self, "Edit Error", f"Failed to update {attr}: {e}"
            )
            item.setText(1, str(old_value))

    def handle_tree_double_click(self, item, column):
        data = item.data(0, Qt.UserRole)
        if data and isinstance(data, tuple) and data[0] == "response":
            response = data[1]

            chan_item = item.parent() if item.parent() else None
            sta_item = (
                chan_item.parent()
                if chan_item and chan_item.parent()
                else None
            )
            net_item = (
                sta_item.parent() if sta_item and sta_item.parent() else None
            )

            if not (chan_item and sta_item and net_item):
                QMessageBox.warning(
                    self, "Error", "Could not identify response hierarchy."
                )
                return

            chan_code = chan_item.text(0).replace("Channel: ", "").strip()
            sta_code = sta_item.text(0).replace("Station: ", "").strip()
            net_code = net_item.text(0).replace("Network: ", "").strip()

            unique_id = f"{net_code}.{sta_code}..{chan_code}"

            self.main_window.open_response_tab(
                response_id=unique_id,
                response_data=response,
                explorer_tab=self,
            )

    def filter_tree(self):
        search_text = self.search_bar.text().lower()
        # Iterate over all top-level items in the tree
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            match_found = self._recursive_filter(item, search_text)
            item.setHidden(not match_found)

    def _recursive_filter(self, item, search_text):
        child_match_found = False
        for i in range(item.childCount()):
            child_item = item.child(i)
            if self._recursive_filter(child_item, search_text):
                child_match_found = True

        item_text = (item.text(0) + item.text(1)).lower()
        self_match = search_text in item_text

        should_be_visible = self_match or child_match_found
        item.setHidden(not should_be_visible)

        if should_be_visible and search_text:
            item.setExpanded(True)

        return should_be_visible


class ResponseTab(QWidget):
    def __init__(self, response_data, main_window, explorer_tab, nrl_root):
        super().__init__()
        self.response = response_data
        self.original_response = deepcopy(response_data)
        self.main_window = main_window
        self.explorer_tab = explorer_tab
        self.nrl_root = nrl_root
        self.response_layout = QVBoxLayout(self)
        self.load_response_editor(self.response)

    def load_response_editor(self, response):
        self.selected_response = response

        for i in reversed(range(self.response_layout.count())):
            item = self.response_layout.itemAt(i)
            if item.widget():
                item.widget().setParent(None)

        splitter = QSplitter(Qt.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        if response.instrument_sensitivity:
            sens = response.instrument_sensitivity
            left_layout.addWidget(
                QLabel(
                    f"<b>Sensitivity:</b> {sens.value} @ {sens.frequency} Hz"
                )
            )

        self.stage_tree = QTreeWidget()
        self.stage_tree.setHeaderLabels(["Field", "Value"])
        self.stage_tree.setColumnWidth(0, 200)
        self.stage_tree.itemChanged.connect(self.handle_response_edit)
        self.stage_tree.itemDoubleClicked.connect(self.edit_complex_value)

        self.populate_stage_tree(response)
        left_layout.addWidget(self.stage_tree)
        btn_layout = QHBoxLayout()
        add_stage = QPushButton("New")
        add_stage.clicked.connect(self.new)
        btn_layout.addWidget(add_stage)

        delete_stage = QPushButton("Delete")
        delete_stage.clicked.connect(self.delete)
        btn_layout.addWidget(delete_stage)

        replace_button = QPushButton("Replace Response")
        replace_button.clicked.connect(self.replace_response)
        btn_layout.addWidget(replace_button)

        save_btn = QPushButton("Revert Response")
        save_btn.clicked.connect(self.revert_response)
        btn_layout.addWidget(save_btn)
        left_layout.addLayout(btn_layout)
        splitter.addWidget(left_widget)

        self.canvas = MplCanvas(self)
        splitter.addWidget(self.canvas)

        self.response_layout.addWidget(splitter)
        self.plot_response(response)

    def plot_response(self, response):
        self.canvas.ax_amp.clear()
        self.canvas.ax_phase.clear()
        try:
            freq = np.logspace(-2, 2, 1000)
            h = response.get_evalresp_response_for_frequencies(
                freq, output="DEF"
            )

            amp = np.abs(h)
            phase = np.angle(h, deg=True)

            self.canvas.ax_amp.plot(
                freq, amp, color="royalblue", label="Amplitude"
            )
            self.canvas.ax_amp.set_title("Amplitude Response")
            self.canvas.ax_amp.set_ylabel("Amplitude")
            self.canvas.ax_amp.set_xscale("log")
            self.canvas.ax_amp.set_yscale("log")
            self.canvas.ax_amp.legend()

            self.canvas.ax_phase.plot(
                freq, phase, color="seagreen", label="Phase"
            )
            self.canvas.ax_phase.set_title("Phase Response")
            self.canvas.ax_phase.set_xlabel("Frequency [Hz]")
            self.canvas.ax_phase.set_ylabel("Phase [°]")
            self.canvas.ax_phase.set_xscale("log")
            self.canvas.ax_phase.legend()

        except Exception as e:
            self.canvas.ax_amp.text(
                0.5, 0.5, f"Error plotting: {e}", ha="center"
            )
            self.canvas.ax_phase.text(
                0.5, 0.5, f"Error plotting: {e}", ha="center"
            )
        self.canvas.draw()

    def revert_response(self):
        self.response = deepcopy(self.original_response)
        self.load_response_editor(self.response)
        QMessageBox.information(
            self, "Reverted",
            "All changes in this tab have been reverted."
            )

    def populate_stage_tree(self, response):
        self.stage_tree.clear()
        if response.instrument_sensitivity:
            sens = response.instrument_sensitivity
            sens_item = QTreeWidgetItem(
                self.stage_tree, ["Instrument Sensitivity", ""]
            )

            val_item = QTreeWidgetItem(sens_item, ["Value", str(sens.value)])
            val_item.setFlags(val_item.flags() | Qt.ItemIsEditable)
            val_item.setData(0, Qt.UserRole, (sens, "value"))

            freq_item = QTreeWidgetItem(
                sens_item, ["Frequency", str(sens.frequency)]
            )
            freq_item.setFlags(freq_item.flags() | Qt.ItemIsEditable)
            freq_item.setData(0, Qt.UserRole, (sens, "frequency"))

        for i, stage in enumerate(response.response_stages):
            stage_item = QTreeWidgetItem(
                self.stage_tree, [f"Stage {i+1}: {type(stage).__name__}", ""]
            )
            if hasattr(stage, "stage_gain"):
                item = QTreeWidgetItem(
                    stage_item, ["Stage Gain", str(stage.stage_gain)]
                )
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setData(0, Qt.UserRole, (stage, "stage_gain"))
            if hasattr(stage, "normalization_frequency"):
                item = QTreeWidgetItem(
                    stage_item,
                    [
                        "Normalization Freq",
                        str(stage.normalization_frequency),
                    ],
                )
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setData(
                    0, Qt.UserRole, (stage, "normalization_frequency")
                )

            if hasattr(stage, "poles"):
                poles_item = QTreeWidgetItem(stage_item, ["Poles", ""])
                for j, pole in enumerate(stage.poles):
                    pole_item = QTreeWidgetItem(
                        poles_item,
                        [f"Pole {j}", f"{pole.real} + {pole.imag}j"],
                    )

                    pole_item.setData(0, Qt.UserRole, ("pole", stage, j))

            if hasattr(stage, "zeros"):
                zeros_item = QTreeWidgetItem(stage_item, ["Zeros", ""])
                for j, zero in enumerate(stage.zeros):
                    zero_item = QTreeWidgetItem(
                        zeros_item,
                        [f"Zero {j}", f"{zero.real} + {zero.imag}j"],
                    )
                    zero_item.setData(0, Qt.UserRole, ("zero", stage, j))

    def handle_response_edit(self, item, column):
        if column != 1:
            return

        ref = item.data(0, Qt.UserRole)
        if not ref or not isinstance(ref, tuple):
            return

        if len(ref) != 2:
            return

        ref_object, attr = ref
        new_text = item.text(1)
        old_value = getattr(ref_object, attr)

        try:
            if isinstance(old_value, float):
                new_value = float(new_text)
            elif isinstance(old_value, int):
                new_value = int(new_text)
            else:
                new_value = new_text

            setattr(ref_object, attr, new_value)

            item.setForeground(1, QBrush(QColor("blue")))
            font = item.font(1)
            font.setBold(True)
            item.setFont(1, font)

        except Exception as e:
            QMessageBox.warning(
                self, "Edit Error", f"Failed to update {attr}: {e}"
            )
            item.setText(1, str(old_value))

    def edit_complex_value(self, item, column):
        if column != 1:
            return

        ref = item.data(0, Qt.UserRole)
        if not ref or not isinstance(ref, tuple):
            return

        if len(ref) != 3:
            return

        ref_type, stage, index = ref
        if ref_type not in ("pole", "zero"):
            return

        value = (
            stage.poles[index] if ref_type == "pole" else stage.zeros[index]
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit {ref_type.title()} {index}")
        layout = QVBoxLayout(dialog)

        real_edit = QLineEdit(str(value.real))
        imag_edit = QLineEdit(str(value.imag))

        layout.addWidget(QLabel("Real:"))
        layout.addWidget(real_edit)
        layout.addWidget(QLabel("Imag:"))
        layout.addWidget(imag_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        layout.addWidget(buttons)

        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec_() == QDialog.Accepted:
            try:
                real = float(real_edit.text())
                imag = float(imag_edit.text())
                new_val = complex(real, imag)
                if ref_type == "pole":
                    stage.poles[index] = new_val
                else:
                    stage.zeros[index] = new_val

                item.setText(1, f"{new_val.real} + {new_val.imag}j")
                item.setForeground(1, QBrush(QColor("blue")))
                font = item.font(1)
                font.setBold(True)
                item.setFont(1, font)

                self.plot_response(self.selected_response)

            except ValueError:
                QMessageBox.warning(
                    self, "Invalid Input", "Please enter valid float numbers."
                )

    def select_response_from_inventory(self, inventory):
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Response to Import")
        layout = QVBoxLayout(dialog)

        combo = QComboBox()
        channel_map = {}

        for net in inventory.networks:
            for sta in net.stations:
                for chan in sta.channels:
                    label = (
                        f"{net.code}.{sta.code}."
                        f"{chan.location_code}.{chan.code}"
                    )
                    combo.addItem(label)
                    channel_map[label] = chan

        layout.addWidget(QLabel("Select Channel Response:"))
        layout.addWidget(combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        layout.addWidget(buttons)

        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec_() == QDialog.Accepted:
            selected = combo.currentText()
            chan_to_copy = channel_map[selected]

            if hasattr(self, "selected_response") and self.selected_response:
                new_response = chan_to_copy.response
                if new_response:
                    self.selected_response.response_stages = copy.deepcopy(
                        new_response.response_stages
                    )
                    self.selected_response.instrument_sensitivity = (
                        copy.deepcopy(new_response.instrument_sensitivity)
                    )

                    QMessageBox.information(
                        self, "Success", "Response replaced successfully."
                    )
                    self.load_response_editor(self.selected_response)
                    self.plot_response(self.selected_response)
                else:
                    QMessageBox.warning(
                        self,
                        "No Response",
                        "Selected channel has no response.",
                    )

    def replace_response(self):
        dlg = ResponseSelectionDialog(self.nrl_root, self)
        dlg.exec_()
        new_resp, _, _ = dlg.get_response()
        if (
            new_resp
            and hasattr(self, "selected_response")
            and self.selected_response
        ):
            self.selected_response.response_stages = copy.deepcopy(
                new_resp.response_stages
            )
            self.selected_response.instrument_sensitivity = copy.deepcopy(
                new_resp.instrument_sensitivity
            )

            self.load_response_editor(self.selected_response)
            self.plot_response(self.selected_response)
            QMessageBox.information(
                self, "Success", "Response updated."
            )

    def new(self):
        item = self.stage_tree.currentItem()
        if not item:
            QMessageBox.warning(
                self,
                "No Selection",
                "Select an item to add a new field under.",
            )
            return

        ref = item.data(0, Qt.UserRole)

        if isinstance(ref, tuple):
            ref_type = ref[0]

            if ref_type == "zero":
                stage = ref[1]
                stage.zeros.append(complex(0.0, 0.0))
                self.load_response_editor(self.selected_response)
                return

            elif ref_type == "pole":
                stage = ref[1]
                stage.poles.append(complex(0.0, 0.0))
                self.load_response_editor(self.selected_response)
                return

        #  New Stage
        is_stage_node = (
            item.text(0).startswith("Stage")
            or item == self.stage_tree.invisibleRootItem()
        )

        if is_stage_node:

            possible_stages = (
                "Response Stage",
                "Poles Zeros Response Stage",
                "Coefficients Type Response Stage",
                "Response List Response Stage",
                "FIR Response Stage",
                "Polynomial Response Stage",
            )
            stage_type, ok = QInputDialog.getItem(
                self,
                "Select Stage Type",
                "Stage type:",
                possible_stages,
                0,
                False,
            )
            if not ok:
                return

            stage_builders = {
                "Response Stage":
                    self._build_response_stage,
                "Poles Zeros Response Stage":
                    self._build_poles_zeros_stage,
                "Coefficients Type Response Stage":
                    self._build_coefficients_type_stage,
                "Response List Response Stage":
                    self._build_response_list_stage,
                "FIR Response Stage":
                    self._build_fir_stage,
                "Polynomial Response Stage":
                    self._build_polynomial_stage,
            }

            builder_func = stage_builders.get(stage_type)
            if not builder_func:
                return

            new_stage = builder_func()

            if new_stage:
                self.selected_response.response_stages.append(new_stage)
                self.load_response_editor(self.selected_response)
                return

        QMessageBox.warning(
            self,
            "Unsupported Selection",
            "You can't create a new item under this element.",
        )

    def _get_common_stage_parameters(self):
        stage_gain, ok1 = QInputDialog.getDouble(
            self, "Stage Gain", "Enter stage gain:", value=1.0
        )
        if not ok1:
            return None

        stage_gain_freq, ok2 = QInputDialog.getDouble(
            self,
            "Stage Gain Frequency",
            "Enter gain frequency (Hz):",
            value=1.0,
        )
        if not ok2:
            return None

        input_units, ok3 = QInputDialog.getText(
            self, "Input Units", "Enter input units:", text="M/S"
        )
        if not ok3:
            return None

        output_units, ok4 = QInputDialog.getText(
            self, "Output Units", "Enter output units:", text="V"
        )
        if not ok4:
            return None

        return {
            "stage_gain": stage_gain,
            "stage_gain_frequency": stage_gain_freq,
            "input_units": input_units,
            "output_units": output_units,
        }

    def _build_response_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        return ResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            **common_params,
        )

    def _build_poles_zeros_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        possible_tf_types = (
            "LAPLACE (RADIANS/SECOND)",
            "LAPLACE (HERTZ)",
            "DIGITAL (Z-TRANSFORM)",
        )
        pz_type, ok1 = QInputDialog.getItem(
            self,
            "Transfer Function Type",
            "Select type:",
            possible_tf_types,
            0,
            False,
        )
        if not ok1:
            return None

        norm_freq, ok2 = QInputDialog.getDouble(
            self,
            "Normalization Frequency",
            "Enter normalization frequency (Hz):",
            value=1.0,
        )
        if not ok2:
            return None

        return PolesZerosResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            normalization_frequency=norm_freq,
            pz_transfer_function_type=pz_type,
            zeros=[0.0 + 0.0j],
            poles=[0.0 + 0.0j],
            **common_params,
        )

    def _build_coefficients_type_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        possible_tf_types = ("DIGITAL", "ANALOG")
        cf_type, ok = QInputDialog.getItem(
            self,
            "Transfer Function Type",
            "Select type:",
            possible_tf_types,
            0,
            False,
        )
        if not ok:
            return None

        return CoefficientsTypeResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            cf_transfer_function_type=cf_type,
            numerator=[1.0],
            denominator=[],
            **common_params,
        )

    def _build_response_list_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        default_element = ResponseListElement(
            frequency=1.0, amplitude=1.0, phase=0.0
        )

        return ResponseListResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            response_list_elements=[default_element],
            **common_params,
        )

    def _build_fir_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        symmetry_options = ("NONE", "ODD", "EVEN")
        symmetry, ok = QInputDialog.getItem(
            self,
            "Symmetry",
            "Select FIR symmetry:",
            symmetry_options,
            0,
            False,
        )
        if not ok:
            return None

        return FIRResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            symmetry=symmetry,
            coefficients=[1.0],  # Add default coefficient
            **common_params,
        )

    def _build_polynomial_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        approx_types = ("MACLAURIN", "CHEBYSHEV")
        approx_type, ok1 = QInputDialog.getItem(
            self, "Approximation Type", "Select type:", approx_types, 0, False
        )
        if not ok1:
            return None

        freq_lower, ok2 = QInputDialog.getDouble(
            self,
            "Frequency Lower Bound",
            "Enter frequency lower bound (Hz):",
            value=0.0,
        )
        if not ok2:
            return None

        freq_upper, ok3 = QInputDialog.getDouble(
            self,
            "Frequency Upper Bound",
            "Enter frequency upper bound (Hz):",
            value=100.0,
        )
        if not ok3:
            return None

        approx_lower, ok4 = QInputDialog.getDouble(
            self,
            "Approximation Lower Bound",
            "Enter approximation lower bound:",
            value=0.0,
        )
        if not ok4:
            return None

        approx_upper, ok5 = QInputDialog.getDouble(
            self,
            "Approximation Upper Bound",
            "Enter approximation upper bound:",
            value=1.0,
        )
        if not ok5:
            return None

        max_error, ok6 = QInputDialog.getDouble(
            self, "Maximum Error", "Enter maximum error:", value=0.0
        )
        if not ok6:
            return None

        return PolynomialResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            approximation_type=approx_type,
            frequency_lower_bound=freq_lower,
            frequency_upper_bound=freq_upper,
            approximation_lower_bound=approx_lower,
            approximation_upper_bound=approx_upper,
            maximum_error=max_error,
            coefficients=[1.0],
            **common_params,
        )

    def delete(self):
        item = self.stage_tree.currentItem()
        if not item:
            QMessageBox.warning(
                self, "No Selection", "Select a field to delete."
            )
            return

        ref = item.data(0, Qt.UserRole)
        if not ref:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            "Are you sure you want to delete this field?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        if isinstance(ref, tuple):
            if len(ref) == 3:
                ref_type, stage, index = ref
                if ref_type == "pole":
                    del stage.poles[index]
                    self.load_response_editor(self.selected_response)
                    return
                elif ref_type == "zero":
                    del stage.zeros[index]
                    self.load_response_editor(self.selected_response)
                    return

            elif len(ref) == 2:
                ref_object, attr = ref
                try:
                    setattr(ref_object, attr, None)
                    self.load_response_editor(self.selected_response)
                    return
                except Exception as e:
                    QMessageBox.warning(
                        self, "Error", f"Could not delete attribute: {e}"
                    )
                    return

        parent = item.parent()
        if parent is None:
            idx = self.stage_tree.indexOfTopLevelItem(item)
            if idx >= 0 and idx < len(self.selected_response.response_stages):
                del self.selected_response.response_stages[idx]
                self.load_response_editor(self.selected_response)
                return


class ResponseSelectionDialog(QDialog):

    def __init__(self, nrl_root, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Instrument Response")
        self.setMinimumWidth(600)

        self.nrl = NRL(root=nrl_root)
        self.nrl_root = nrl_root

        self.sensor_response = None
        self.digitizer_response = None
        self.sensor_info = "Not selected"
        self.digitizer_info = "Not selected"
        self.final_resp = None

        self._init_ui()
        self._update_ui()

    def _init_ui(self):

        main_layout = QVBoxLayout(self)

        sensor_group = QGroupBox("Sensor Response")
        sensor_layout = QFormLayout()
        self.sensor_status_label = QLabel(self.sensor_info)
        sensor_buttons_layout = QHBoxLayout()
        sensor_file_btn = QPushButton("Load from File...")
        sensor_nrl_btn = QPushButton("Select from NRL...")
        sensor_buttons_layout.addWidget(sensor_file_btn)
        sensor_buttons_layout.addWidget(sensor_nrl_btn)
        sensor_layout.addRow(self.sensor_status_label)
        sensor_layout.addRow(sensor_buttons_layout)
        sensor_group.setLayout(sensor_layout)

        datalogger_group = QGroupBox("Datalogger (Digitizer) Response")
        datalogger_layout = QFormLayout()
        self.datalogger_status_label = QLabel(self.digitizer_info)
        datalogger_buttons_layout = QHBoxLayout()
        datalogger_file_btn = QPushButton("Load from File...")
        datalogger_nrl_btn = QPushButton("Select from NRL...")
        datalogger_buttons_layout.addWidget(datalogger_file_btn)
        datalogger_buttons_layout.addWidget(datalogger_nrl_btn)
        datalogger_layout.addRow(self.datalogger_status_label)
        datalogger_layout.addRow(datalogger_buttons_layout)
        datalogger_group.setLayout(datalogger_layout)

        main_layout.addWidget(sensor_group)
        main_layout.addWidget(datalogger_group)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        main_layout.addWidget(self.button_box)

        sensor_file_btn.clicked.connect(self.select_sensor_from_file)
        sensor_nrl_btn.clicked.connect(self.launch_sensor_wizard)
        datalogger_file_btn.clicked.connect(self.select_digitizer_from_file)
        datalogger_nrl_btn.clicked.connect(self.launch_digitizer_wizard)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def launch_sensor_wizard(self):
        wizard = NRLWizard(self.nrl_root, "sensor", self)
        if wizard.exec_() == QDialog.Accepted:
            keys, desc = wizard.get_result()
            if keys:
                try:
                    self.sensor_response = self.nrl.get_sensor_response(keys)
                    self.sensor_info = f"From NRL: {desc}"
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "NRL Error",
                        f"Failed to get sensor response:\n{e}",
                    )
                    self.sensor_response = None
            self._update_ui()

    def launch_digitizer_wizard(self):
        wizard = NRLWizard(self.nrl_root, "datalogger", self)
        if wizard.exec_() == QDialog.Accepted:
            keys, desc = wizard.get_result()
            if keys:
                try:
                    self.digitizer_response = self.nrl.get_datalogger_response(
                        keys
                    )
                    self.digitizer_info = f"From NRL: {desc}"
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "NRL Error",
                        f"Failed to get datalogger response:\n{e}",
                    )
                    self.digitizer_response = None
            self._update_ui()

    def select_sensor_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Sensor Response File",
            "",
            "StationXML (*.xml);;RESP (*.resp);;All Files (*)",
        )
        if path:
            try:
                inv = read_inventory(path)
                self.sensor_response = inv[0][0][0].response
                self.sensor_info = f"From file: {os.path.basename(path)}"
            except Exception as e:
                QMessageBox.warning(
                    self, "Error", f"Failed to read file:\n{e}"
                )
                self.sensor_response = None
            self._update_ui()

    def select_digitizer_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Digitizer Response File",
            "",
            "StationXML (*.xml);;RESP (*.resp);;All Files (*)",
        )
        if path:
            try:
                inv = read_inventory(path)
                self.digitizer_response = inv[0][0][0].response
                self.digitizer_info = f"From file: {os.path.basename(path)}"
            except Exception as e:
                QMessageBox.warning(
                    self, "Error", f"Failed to read file:\n{e}"
                )
                self.digitizer_response = None
            self._update_ui()

    def _update_ui(self):
        self.sensor_status_label.setText(wrap_text(self.sensor_info))
        self.datalogger_status_label.setText(wrap_text(self.digitizer_info))

        ok_button = self.button_box.button(QDialogButtonBox.Ok)
        ok_button.setEnabled(
            self.sensor_response is not None
            and self.digitizer_response is not None
        )

    def accept(self):
        try:
            print("Sensor:", self.sensor_response)
            print("Digitizer:", self.digitizer_response)
            final_response = combine_resp(
                deepcopy(self.sensor_response),
                deepcopy(self.digitizer_response),
            )
            self.final_resp = final_response
            print("Final inventory built:", self.final_resp)
            super().accept()
        except Exception as e:
            print("Combine error:", e)
            QMessageBox.critical(
                self,
                "Response Combination Error",
                f"Could not combine responses:\n{e}",
            )
            self.final_resp = None

    def get_response(self):
        return self.final_resp, self.sensor_info, self.digitizer_info


class NRLWizard(QDialog):

    def __init__(self, nrl_root, stage, parent=None):

        super().__init__(parent)
        self.setWindowTitle(f"NRL {stage.capitalize()} Wizard")
        self.setMinimumWidth(500)
        self.setModal(True)

        self.nrl_root = nrl_root
        self.stage = stage

        initial_dir = os.path.normpath(os.path.join(self.nrl_root, self.stage))
        self.path_stack = [(initial_dir, None)]

        self.selected_keys = []
        self.selected_option = None
        self._final_xml_config = None
        self.final_description = ""

        self.auto_step_timer = QTimer(self)
        self.auto_step_timer.setSingleShot(True)
        self.auto_step_timer.timeout.connect(self.next_step)

        self.back_bool_flag = False
        self._init_ui()
        self.load_step()

    def _init_ui(self):
        self.layout = QVBoxLayout(self)
        self.question_label = QLabel("Loading...")
        self.layout.addWidget(self.question_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.back_btn = QPushButton("Back")
        self.next_btn = QPushButton("Next")
        self.cancel_btn = QPushButton("Cancel")
        button_layout.addWidget(self.back_btn)
        button_layout.addWidget(self.next_btn)
        button_layout.addWidget(self.cancel_btn)
        self.layout.addLayout(button_layout)

        self.back_btn.clicked.connect(self.go_back)
        self.next_btn.clicked.connect(self.next_step)
        self.cancel_btn.clicked.connect(self.reject)

        self.option_buttons = {}

    def load_step(self):

        if self.auto_step_timer.isActive():
            self.auto_step_timer.stop()

        self.clear_layout(self.scroll_layout)
        self.selected_option = None
        self._final_xml_config = None
        self.next_btn.setText("Next")

        current_dir, txt_file = self.path_stack[-1]
        config_filename = txt_file if txt_file else "index.txt"
        config_path = os.path.join(current_dir, config_filename)

        if not os.path.isfile(config_path):
            QMessageBox.warning(
                self, "Error", f"Missing configuration file:\n{config_path}"
            )
            self.go_back()
            return

        config = self._read_config(config_path)
        if not config:
            QMessageBox.critical(
                self,
                "Read Error",
                f"Could not read or parse the config file:\n{config_path}",
            )
            self.go_back()
            return

        self.question_label.setText(
            config.get("Main", "question", fallback="Make a selection")
        )

        self.option_buttons = {}
        base_dir = current_dir

        sections = sorted(
            [s for s in config.sections() if s != "Main"], key=natural_sort_key
        )
        for section in sections:
            raw_path = (
                config.get(section, "path", fallback="").strip().strip('"')
            )
            btn = QRadioButton(wrap_text(section))
            btn.toggled.connect(
                lambda checked, s=section: self.set_selection(s)
            )
            self.scroll_layout.addWidget(btn)

            resolved_path = os.path.normpath(os.path.join(base_dir, raw_path))
            self.option_buttons[section] = (btn, resolved_path)
        if not self.back_bool_flag:
            if len(self.option_buttons) == 1:
                only_section = next(iter(self.option_buttons))
                self.option_buttons[only_section][0].setChecked(True)
                self.auto_step_timer.start(100)

        self.back_btn.setEnabled(len(self.path_stack) > 1)

    def load_final_xml_choices(self, config):

        self._final_xml_config = config
        self.selected_option = None
        self.clear_layout(self.scroll_layout)
        self.next_btn.setText("Finish")

        question = config.get(
            "Main", "question", fallback="Select configuration"
        )
        self.question_label.setText(question)

        self.option_buttons = {}
        for section in sorted(
            [s for s in config.sections() if s != "Main"], key=natural_sort_key
                ):
            desc = (
                config.get(section, "description", fallback="")
                .strip()
                .strip('"')
            )
            xml = config.get(section, "xml", fallback="").strip().strip('"')

            label = f"{section}: {desc}"
            btn = QRadioButton(wrap_text(label))
            btn.toggled.connect(
                lambda checked, s=section: self.set_selection(s)
            )
            self.scroll_layout.addWidget(btn)
            self.option_buttons[section] = (btn, xml)

    def next_step(self):

        self.back_bool_flag = False
        if not self.selected_option:
            QMessageBox.warning(
                self, "Selection Required", "Please select an option."
            )
            return

        if self._final_xml_config:
            self.selected_keys.append(self.selected_option)
            self.final_description = self.option_buttons[self.selected_option][
                0
            ].text()
            self.accept()
            return

        _, next_path = self.option_buttons[self.selected_option]

        if os.path.isdir(next_path):
            self.selected_keys.append(self.selected_option)
            self.path_stack.append((next_path, None))
            self.load_step()
        elif os.path.isfile(next_path) and next_path.endswith(".txt"):
            config = self._read_config(next_path)
            if "Main" in config:
                sections = [s for s in config.sections() if s != "Main"]

                is_final = all(config.has_option(s, "xml") for s in sections)
                is_intermediate = all(
                    config.has_option(s, "path") for s in sections
                )

                self.selected_keys.append(self.selected_option)
                self.path_stack.append(
                    (os.path.dirname(next_path), os.path.basename(next_path))
                )

                if is_final:
                    self.load_final_xml_choices(config)
                elif is_intermediate:
                    self.load_step()
                else:
                    QMessageBox.warning(
                        self,
                        "NRL Error",
                        f"Invalid config file format:\n{next_path}",
                    )
                    self.go_back()
            else:
                QMessageBox.warning(
                    self,
                    "NRL Error",
                    f"Invalid config file format:\n{next_path}",
                )
                self.go_back()
        else:
            QMessageBox.warning(
                self,
                "NRL Error",
                f"Unrecognized or invalid path:\n{next_path}",
            )

    def go_back(self):
        self.back_bool_flag = True
        if len(self.path_stack) > 1:
            self.path_stack.pop()
            if self.selected_keys:
                self.selected_keys.pop()
            self.load_step()

    def set_selection(self, section):

        if (
            section in self.option_buttons
            and self.option_buttons[section][0].isChecked()
        ):
            self.selected_option = section

    def get_result(self):

        if self.result() == QDialog.Accepted:
            return self.selected_keys, self.final_description
        return None, None

    def _read_config(self, path):

        config = configparser.ConfigParser()
        config.optionxform = str
        try:
            config.read(path, encoding="utf-8-sig")
            return config
        except Exception as e:
            print(f"Error reading config file {path}: {e}")
            return None

    def clear_layout(self, layout):

        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()


class StationInventoryWizard(QDialog):
    def __init__(self, nrl_root, initial_data=None, parent=None):
        super().__init__(parent)
        self.nrl_root = nrl_root
        self.setWindowTitle("Station Inventory Creation Wizard")
        self.resize(800, 600)
        self.inventory = None
        self.groups = {}
        self._init_ui()
        if initial_data:
            self._populate_from_initial_data(initial_data)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        station_group = QGroupBox("Station Parameters")
        station_layout = QFormLayout()
        self.net_edit = QLineEdit("XX")
        self.sta_edit = QLineEdit("STA")
        self.lat_edit = QLineEdit("0.0")
        self.lon_edit = QLineEdit("0.0")
        self.ele_edit = QLineEdit("0.0")
        station_layout.addRow("Network Code:", self.net_edit)
        station_layout.addRow("Station Code:", self.sta_edit)
        station_layout.addRow("Latitude:", self.lat_edit)
        station_layout.addRow("Longitude:", self.lon_edit)
        station_layout.addRow("Elevation (m):", self.ele_edit)
        station_group.setLayout(station_layout)
        main_layout.addWidget(station_group)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.groups_layout = QHBoxLayout(self.scroll_content)
        self.scroll.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll)
        group1_box = QGroupBox("Channel Group 1 (Primary)")
        self.groups[1] = self._create_channel_group_widgets()
        group1_layout = self._create_layout_from_widgets(self.groups[1])
        self.groups[1]["resp_btn"].clicked.connect(
            lambda: self._select_response(1)
        )
        group1_box.setLayout(group1_layout)
        self.groups_layout.addWidget(group1_box)
        self.group2_box = QGroupBox("Channel Group 2 (Secondary)")
        self.groups[2] = self._create_channel_group_widgets()
        group2_layout = self._create_layout_from_widgets(self.groups[2])
        self.groups[2]["resp_btn"].clicked.connect(
            lambda: self._select_response(2)
        )
        self.group2_box.setLayout(group2_layout)
        self.groups_layout.addWidget(self.group2_box)
        self.group2_box.setVisible(False)
        self.toggle_group2_cb = QCheckBox("Enable Secondary Channel Group")
        self.toggle_group2_cb.toggled.connect(self.group2_box.setVisible)
        self.toggle_group2_cb.toggled.connect(self._on_toggle_group2)
        main_layout.insertWidget(2, self.toggle_group2_cb)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

    def _create_channel_group_widgets(self):
        loc_edit = QLineEdit("00")
        loc_edit.setToolTip(
            "One code for all, or a comma-separated list per component."
        )
        comp_edit = QLineEdit("Z,N,E")
        comp_edit.setToolTip(
            "Comma-separated channel endings (e.g., Z,N,E or 1,2,Z)"
        )

        return {
            "loc": loc_edit,
            "base": QLineEdit("HH"),
            "comp": comp_edit,
            "depth": QLineEdit("0.0"),
            "date": QDateTimeEdit(QDateTime.currentDateTimeUtc()),
            "resp_label": QLabel("Not Selected"),
            "resp_btn": QPushButton("Select Response..."),
            "response_obj": None,
            "response_info": "Not Selected",
        }

    def _create_layout_from_widgets(self, widgets):
        layout = QFormLayout()
        widgets["date"].setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        layout.addRow("Location Code(s):", widgets["loc"])
        layout.addRow("Channel Base Code:", widgets["base"])
        layout.addRow("Channel Components:", widgets["comp"])
        layout.addRow("Start Date:", widgets["date"])
        layout.addRow("Sensor Depth (m):", widgets["depth"])
        layout.addRow("Instrument Response:", widgets["resp_label"])
        layout.addRow(widgets["resp_btn"])
        return layout

    def _populate_from_initial_data(self, data):
        self.net_edit.setText(data.get("net", ""))
        self.sta_edit.setText(data.get("sta", ""))
        self.lat_edit.setText(data.get("lat", "0.0"))
        self.lon_edit.setText(data.get("lon", "0.0"))
        self.ele_edit.setText(data.get("ele", "0.0"))

        if "group1" in data:
            g1_data = data["group1"]
            self.groups[1]["loc"].setText(g1_data.get("locs", ""))
            self.groups[1]["base"].setText(g1_data.get("base", ""))
            self.groups[1]["comp"].setText(g1_data.get("comps", ""))
        if "group2" in data:
            self.toggle_group2_cb.setChecked(True)
            g2_data = data["group2"]
            self.groups[2]["loc"].setText(g2_data.get("locs", ""))
            self.groups[2]["base"].setText(g2_data.get("base", ""))
            self.groups[2]["comp"].setText(g2_data.get("comps", ""))

    def _select_response(self, group_num):
        dialog = ResponseSelectionDialog(self.nrl_root, self)
        if dialog.exec_() == QDialog.Accepted:
            response_obj, s_info, d_info = dialog.get_response()
            group_widgets = self.groups[group_num]
            group_widgets["response_obj"] = response_obj
            group_widgets["response_info"] = (
                f"Sensor: {s_info} | Datalogger: {d_info}"
            )
            group_widgets["resp_label"].setText(
                wrap_text(group_widgets["response_info"])
            )

        self.scroll_content.adjustSize()
        self.groups_layout.update()
        content_size = self.scroll_content.sizeHint()
        extra_width = 40
        extra_height = 80
        new_width = max(self.width(), content_size.width() + extra_width)
        new_height = max(self.height(), content_size.height() + extra_height)
        self.resize(new_width, new_height)

    def _on_toggle_group2(self, checked):
        self.group2_box.setVisible(checked)
        self.scroll_content.adjustSize()
        self.groups_layout.update()
        self.scroll.updateGeometry()
        content_size = self.scroll_content.sizeHint()
        extra_width = 40
        extra_height = 80
        new_width = max(self.width(), content_size.width() + extra_width)
        new_height = max(self.height(), content_size.height() + extra_height)
        self.resize(new_width, new_height)

    def accept(self):
        if not self._validate_inputs():
            return
        try:
            self._build_inventory()
            default_filename = (
                f"{self.inventory[0].code}.{self.inventory[0][0].code}.xml"
            )
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Inventory File",
                default_filename,
                "StationXML (*.xml)",
            )
            if save_path:
                self.inventory.write(save_path, format="STATIONXML")
                QMessageBox.information(
                    self, "Success", f"Inventory saved to:\n{save_path}"
                )
                super().accept()
        except Exception as e:
            QMessageBox.critical(
                self, "Build Error", f"Failed to build or save inventory:\n{e}"
            )

    def _validate_inputs(self):
        if not all(
            [
                self.net_edit.text(),
                self.sta_edit.text(),
                self.lat_edit.text(),
                self.lon_edit.text(),
                self.ele_edit.text(),
            ]
        ):
            QMessageBox.warning(
                self,
                "Input Error",
                "All Station Parameter fields"
                " (Codes, Lat, Lon, Ele) are required.",
            )
            return False
        try:
            float(self.lat_edit.text())
            float(self.lon_edit.text())
            float(self.ele_edit.text())
        except ValueError:
            QMessageBox.warning(
                self,
                "Input Error",
                "Latitude, Longitude, and Elevation must be valid numbers.",
            )
            return False

        try:
            self._parse_channel_group(self.groups[1], "Group 1")
            if self.toggle_group2_cb.isChecked():
                self._parse_channel_group(self.groups[2], "Group 2")
        except ValueError as e:
            QMessageBox.warning(self, "Input Error", str(e))
            return False
        return True

    def _parse_channel_group(self, widgets, group_name):
        if not all(
            [
                widgets["loc"].text(),
                widgets["base"].text(),
                widgets["comp"].text(),
            ]
        ):
            raise ValueError(
                f"{group_name}: All channel code fields are required."
            )
        if not widgets["response_obj"]:
            raise ValueError(
                f"{group_name}: An instrument response must be"
                f" selected for {group_name}."
            )
        try:
            float(widgets["depth"].text())
        except ValueError:
            raise ValueError(
                f"{group_name}: Sensor Depth must be a valid number."
            )

        locs = [
            loc.strip().upper()
            for loc in widgets["loc"].text().split(",")
            if loc.strip()
        ]
        comps = [
            c.strip().upper()
            for c in widgets["comp"].text().split(",")
            if c.strip()
        ]

        if len(locs) != 1 and len(locs) != len(comps):
            raise ValueError(
                f"{group_name}: The number of Location Codes must"
                f" be 1 or match the number of Channel Components."
            )
        if len(locs) == 1 and len(comps) > 1:
            locs = locs * len(comps)
        return locs, comps

    def _build_inventory(self):
        all_channels = []
        all_channels.extend(
            self._build_channels_for_group(self.groups[1], "Group 1")
        )
        if self.toggle_group2_cb.isChecked():
            all_channels.extend(
                self._build_channels_for_group(self.groups[2], "Group 2")
            )

        creation_dt = self.groups[1]["date"].dateTime().toPyDateTime()

        station = Station(
            code=self.sta_edit.text().upper(),
            latitude=float(self.lat_edit.text()),
            longitude=float(self.lon_edit.text()),
            elevation=float(self.ele_edit.text()),
            creation_date=UTCDateTime(creation_dt),
            channels=all_channels,
        )
        network = Network(
            code=self.net_edit.text().upper(), stations=[station]
        )
        self.inventory = Inventory(
            networks=[network], source="StationInventoryWizard"
        )

    def _build_channels_for_group(self, widgets, group_name):
        channels = []
        locs, comps = self._parse_channel_group(widgets, group_name)
        base = widgets["base"].text().upper()

        station_lat = float(self.lat_edit.text())
        station_lon = float(self.lon_edit.text())
        station_ele = float(self.ele_edit.text())

        sensor_depth = float(widgets["depth"].text())
        start_date = UTCDateTime(widgets["date"].dateTime().toPyDateTime())
        response = widgets["response_obj"]

        for i, comp in enumerate(comps):
            code = base + comp
            az, dip = 0, 0
            if comp.endswith("E"):
                az, dip = 90, 0
            elif comp.endswith("N"):
                az, dip = 0, 0
            elif comp.endswith("Z"):
                az, dip = 0, -90

            rate = (
                response.instrument_sensitivity.frequency
                if isinstance(response, Response)
                and response.instrument_sensitivity
                else 1.0
            )

            channels.append(
                Channel(
                    code=code,
                    location_code=locs[i],
                    latitude=station_lat,
                    longitude=station_lon,
                    elevation=station_ele,
                    depth=sensor_depth,
                    azimuth=az,
                    dip=dip,
                    sample_rate=rate,
                    start_date=start_date,
                    response=response,
                )
            )
        return channels


class ImportFromMiniSEEDDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import from MiniSEED")
        self.setMinimumWidth(400)
        self.initial_data = {}
        layout = QFormLayout(self)
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_file)
        layout.addRow("MiniSEED File:", self.path_edit)
        layout.addRow("", browse_btn)
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select MiniSEED File",
            "",
            "MiniSEED files (*.mseed *.msd *.miniseed)",
        )
        if path:
            self.filepath = path
            self.path_edit.setText(path)

    def accept(self):
        if not self.filepath:
            QMessageBox.warning(
                self, "No File", "Please select a MiniSEED file."
            )
            return
        try:
            stream = read(self.filepath, headonly=False)
            if not stream:
                QMessageBox.warning(
                    self,
                    "Empty File",
                    "The selected file contains no data traces.",
                )
                return
            stream = [tr for tr in stream if len(tr.data) > 0]
            grouped_channels = {}
            for tr in stream:
                band_code = tr.stats.channel[0]
                if band_code not in grouped_channels:
                    grouped_channels[band_code] = []
                grouped_channels[band_code].append(tr)

            first_trace = stream[0]
            self.initial_data = {
                "net": first_trace.stats.network,
                "sta": first_trace.stats.station,
            }

            group_keys = sorted(grouped_channels.keys())
            if len(group_keys) > 0:
                self.initial_data["group1"] = self._process_channel_group(
                    grouped_channels[group_keys[0]]
                )
            if len(group_keys) > 1:
                self.initial_data["group2"] = self._process_channel_group(
                    grouped_channels[group_keys[1]]
                )

            super().accept()
        except Exception as e:
            QMessageBox.critical(
                self, "Read Error", f"Could not read or parse the file:\n{e}"
            )

    def _process_channel_group(self, traces):
        chan_info = sorted(
            list(set((tr.stats.location, tr.stats.channel) for tr in traces)),
            key=lambda x: x[1],
        )

        locs = [info[0] for info in chan_info]
        chan_codes = [info[1] for info in chan_info]

        base = (
            os.path.commonprefix(chan_codes)
            if len(chan_codes) > 1
            else chan_codes[0][:2]
        )
        comps = [ch.replace(base, "", 1) for ch in chan_codes]

        return {
            "locs": ",".join(locs),
            "base": base,
            "comps": ",".join(comps),
        }

    def get_initial_data(self):
        return self.initial_data
