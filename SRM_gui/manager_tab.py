from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTabWidget,
    QMessageBox,
    QSplitter,
    QHBoxLayout,
)
from copy import deepcopy
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtCore import Qt, QTimer
from SRM_gui.timeline import TimelineWidget
import json
import colorsys
from obspy import Inventory
from obspy.core.inventory import Station, Channel
from obspy.core.inventory.response import Response
import os
from pathlib import Path


class ManagerTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

        layout = QHBoxLayout(self)
        self.clipboard_item = None
        splitter = QSplitter(Qt.Horizontal)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
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
        splitter.addWidget(left_widget)
        self.right_tabs = QTabWidget()
        self.map_view = QWebEngineView()
        current_dir = Path(__file__)
        map_template_path = current_dir.parent / "map_template.html"
        with map_template_path.open("r", encoding="utf-8") as f:
            html_template = f.read()
        self.map_view.setHtml(html_template)
        self.right_tabs.addTab(self.map_view, "Map")

        self.timeline_widget = TimelineWidget()
        self.right_tabs.addTab(self.timeline_widget, "Timeline")
        self.right_tabs.currentChanged.connect(
            self.on_right_tab_changed
        )
        splitter.addWidget(self.right_tabs)
        splitter.setSizes([300, 600])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

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
        file_item = QTreeWidgetItem(
            [os.path.basename(abs_filepath)]
        )
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
                    self._add_instrument_detection(chan_item, chan)

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
        self.update_timeline()

    def _add_instrument_detection(self, chan_item, channel):
        if not channel.response:
            return

        nrl_index = self.main_window.nrl_index
        result = nrl_index.detect_instrument(channel.response)

        if result.sensor:
            if result.sensor_ambiguous:
                n_candidates = len(result.sensor_candidates)
                mfr = result.sensor.manufacturer
                model = result.sensor.model
                family = result.sensor.family_name or f"{mfr} {model}"
                sensor_text = f"sensor: {family} (+{n_candidates - 1} similar)"
            else:
                sensor_text = (
                    f"sensor: {result.sensor.manufacturer} "
                    f"{result.sensor.model}"
                )
            sensor_item = QTreeWidgetItem([sensor_text])
            sensor_item.setData(
                0, Qt.UserRole, ("sensor_info", result)
            )
            sensor_item.setForeground(0, QBrush(QColor("#2e7d32")))
            font = sensor_item.font(0)
            font.setItalic(True)
            sensor_item.setFont(0, font)
            sensor_item.setFlags(
                sensor_item.flags() & ~Qt.ItemIsSelectable
            )
            if result.sensor_ambiguous:
                tooltip = "Similar sensors (same response):\n"
                for c in result.sensor_candidates[:10]:
                    tooltip += f"  • {c.manufacturer} {c.model}"
                    if c.variant_params:
                        tooltip += f" ({c.variant_params})"
                    tooltip += "\n"
                if len(result.sensor_candidates) > 10:
                    remaining = len(result.sensor_candidates) - 10
                    tooltip += f"  ... and {remaining} more"
                sensor_item.setToolTip(0, tooltip)
            chan_item.addChild(sensor_item)

        if result.datalogger:
            if result.datalogger_confidence >= 0.9:
                dl_text = (
                    f"digitizer: {result.datalogger.manufacturer} "
                    f"{result.datalogger.model}"
                )
            elif result.datalogger_ambiguous:
                n_candidates = len(result.datalogger_candidates)
                family = (result.datalogger.family_name or
                          f"{result.datalogger.manufacturer}")
                dl_text = f"digitizer: {family} (+{n_candidates - 1} similar)"
            else:
                dl_text = (
                    f"digitizer: {result.datalogger.manufacturer} "
                    f"{result.datalogger.model}"
                )
            dl_item = QTreeWidgetItem([dl_text])
            dl_item.setData(0, Qt.UserRole, ("dl_info", result))
            dl_item.setForeground(0, QBrush(QColor("#1565c0")))
            font = dl_item.font(0)
            font.setItalic(True)
            dl_item.setFont(0, font)
            dl_item.setFlags(dl_item.flags() & ~Qt.ItemIsSelectable)
            is_uncertain = (result.datalogger_ambiguous and
                            result.datalogger_confidence < 0.9)
            if is_uncertain:
                tooltip = f"Confidence: {result.datalogger_confidence:.0%}\n"
                tooltip += "Similar digitizers (same digital chain):\n"
                for c in result.datalogger_candidates[:10]:
                    tooltip += f"  • {c.manufacturer} {c.model}"
                    if c.variant_params:
                        tooltip += f" ({c.variant_params})"
                    tooltip += "\n"
                if len(result.datalogger_candidates) > 10:
                    remaining = len(result.datalogger_candidates) - 10
                    tooltip += f"  ... and {remaining} more"
                dl_item.setToolTip(0, tooltip)
            chan_item.addChild(dl_item)

    def handle_item_double_click(self, item, column):
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
        self._add_instrument_detection(chan_item, chan)

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

            from obspy.core.inventory import Network
            net = Network(code="XX")
            inventory.networks.append(net)
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
            except Exception:
                pass

    def on_right_tab_changed(self, index):
        widget = self.right_tabs.widget(index)
        if widget is self.timeline_widget:
            if self.timeline_widget._needs_initial_fit:
                QTimer.singleShot(
                    50, self.timeline_widget._initial_fit
                )

    def update_timeline(self):
        self.timeline_widget.update_timeline(
            self.main_window.loaded_files
        )

    def refresh(self):
        self.file_tree.clear()
        self.all_stations.clear()
        self.network_colors.clear()
        for filepath, inventory in self.main_window.loaded_files.items():
            self.add_file_to_tree(filepath, inventory)
