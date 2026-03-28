from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QCheckBox,
    QScrollArea,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QDateTimeEdit,
    QFileDialog,
)
from PyQt5.QtCore import QDateTime
from SRM_core.utils import wrap_text
import os
from obspy import Inventory, UTCDateTime, read
from obspy.core.inventory.response import Response
from obspy.core.inventory import Station, Network, Channel
from SRM_gui.response_tab import ResponseSelectionDialog


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
        self.filepath = None
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
