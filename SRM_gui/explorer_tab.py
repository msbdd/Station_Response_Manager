from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QMessageBox,
    QLineEdit,
    QInputDialog,
    QHBoxLayout,
)
from PyQt5.QtGui import QColor, QFont, QBrush
from PyQt5.QtCore import Qt
from obspy import UTCDateTime
from obspy.core.inventory import Station, Channel
from obspy.core.inventory.response import Response


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
        self.delete_button = QPushButton("Delete")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete_selected)
        top_layout.addStretch()
        top_layout.addWidget(self.new_button)
        top_layout.addWidget(self.delete_button)
        layout.addLayout(top_layout)
        # Filters
        search_layout = QHBoxLayout()
        self.station_filter = QLineEdit()
        self.station_filter.setPlaceholderText(
            "Filter by network or station..."
        )
        self.station_filter.setClearButtonEnabled(True)
        self.station_filter.textChanged.connect(self.filter_tree)
        search_layout.addWidget(self.station_filter, 1)
        search_layout.addSpacing(4)
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Property filter...")
        self.search_bar.setClearButtonEnabled(True)
        self.search_bar.textChanged.connect(self.filter_tree)
        search_layout.addWidget(self.search_bar, 1)
        layout.addLayout(search_layout)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Field", "Value"])
        self.tree.itemChanged.connect(self.handle_tree_edit)
        self.tree.itemDoubleClicked.connect(self.handle_tree_double_click)
        layout.addWidget(self.tree)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 150)
        self.tree.itemSelectionChanged.connect(self.on_tree_selection_changed)
        self.info_label = QLabel(f"Loaded file: {filepath}")
        layout.addWidget(self.info_label)

    def navigate_to(self, net_code, sta_code, chan_code):
        # Find and select/expand a specific network/station/channel."""
        for ni in range(self.tree.topLevelItemCount()):
            net_item = self.tree.topLevelItem(ni)
            if net_item.text(0) != f"Network: {net_code}":
                continue
            net_item.setExpanded(True)
            if not sta_code:
                self.tree.setCurrentItem(net_item)
                self.tree.scrollToItem(net_item)
                return
            for si in range(net_item.childCount()):
                sta_item = net_item.child(si)
                if sta_item.text(0) != f"Station: {sta_code}":
                    continue
                sta_item.setExpanded(True)
                if not chan_code:
                    self.tree.setCurrentItem(sta_item)
                    self.tree.scrollToItem(sta_item)
                    return
                for ci in range(sta_item.childCount()):
                    chan_item = sta_item.child(ci)
                    if chan_item.text(0) == f"Channel: {chan_code}":
                        chan_item.setExpanded(True)
                        self.tree.setCurrentItem(chan_item)
                        self.tree.scrollToItem(chan_item)
                        return
                # Channel not found, select station
                self.tree.setCurrentItem(sta_item)
                self.tree.scrollToItem(sta_item)
                return

    # Editable fields per type — from ObsPy's actual attributes
    # This needs to be changed if moved to a different ObsPy version...
    _NETWORK_FIELDS = [
        "alternate_code", "description", "end_date", "historical_code",
        "restricted_status", "source_id", "start_date",
        "total_number_of_stations",
    ]
    _STATION_FIELDS = [
        "alternate_code", "creation_date", "description", "end_date",
        "geology", "historical_code", "restricted_status", "source_id",
        "start_date", "termination_date", "vault", "water_level",
    ]
    _CHANNEL_FIELDS = [
        "alternate_code", "calibration_units",
        "calibration_units_description",
        "clock_drift_in_seconds_per_sample", "description", "end_date",
        "historical_code", "restricted_status", "source_id", "start_date",
        "water_level",
    ]

    def _find_header_item(self, item):
        # Walk up to the nearest Network/Station/Channel header
        while item:
            label = item.text(0)
            for prefix in ("Network: ", "Station: ", "Channel: "):
                if label.startswith(prefix):
                    return item
            item = item.parent()
        return None

    def _get_obj_for_header(self, header_item):
        # Get the ObsPy object for a Network/Station/Channel header
        label = header_item.text(0)
        inv = self.current_inventory
        if label.startswith("Network: "):
            code = label.replace("Network: ", "").strip()
            return next(
                (n for n in inv.networks if n.code == code), None
            )
        elif label.startswith("Station: "):
            ref = header_item.data(0, Qt.UserRole)
            if ref and isinstance(ref, tuple) and ref[0] == "station":
                return ref[1]
        elif label.startswith("Channel: "):
            sta_header = header_item.parent()
            if sta_header:
                sta_ref = sta_header.data(0, Qt.UserRole)
                if sta_ref and sta_ref[0] == "station":
                    chan_code = label.replace("Channel: ", "").strip()
                    for ch in sta_ref[1].channels:
                        if ch.code == chan_code:
                            return ch
        return None

    def _missing_fields(self, obj, whitelist):
        # Return whitelist fields that are currently None or empty
        return [
            a for a in whitelist
            if getattr(obj, a, None) in (None, "")
        ]

    @staticmethod
    def _set_field(obj, field):
        """Set a missing field, using a non-empty placeholder for fields
        that ObsPy silently converts empty strings to None."""
        # Try empty string first
        setattr(obj, field, "")
        if getattr(obj, field, None) is not None:
            return
        # ObsPy swallowed it — use a typed placeholder
        setattr(obj, field, "—")

    def create_new_field(self):
        item = self.tree.currentItem()
        if not item:
            QMessageBox.warning(self, "No Selection", "Please select an item.")
            return

        header = self._find_header_item(item)
        if not header:
            QMessageBox.warning(
                self, "Invalid Selection",
                "Select a Network, Station, Channel, or one of their fields."
            )
            return

        label = header.text(0)
        obj = self._get_obj_for_header(header)
        if not obj:
            QMessageBox.warning(self, "Error", "Could not resolve object.")
            return

        if label.startswith("Network: "):
            field_choices = self._missing_fields(obj, self._NETWORK_FIELDS)
            new_item_label = "New Station"
        elif label.startswith("Station: "):
            field_choices = self._missing_fields(obj, self._STATION_FIELDS)
            new_item_label = "New Channel"
        elif label.startswith("Channel: "):
            field_choices = self._missing_fields(obj, self._CHANNEL_FIELDS)
            new_item_label = None
        else:
            return

        choices = []
        if new_item_label:
            choices.append(new_item_label)
        choices.extend(field_choices)

        if not choices:
            QMessageBox.information(
                self, "Info", "No missing editable fields."
            )
            return

        choice, ok = QInputDialog.getItem(
            self, "New", "Select what to add:", choices, editable=False,
        )
        if not ok:
            return

        if choice == "New Station":
            sta = Station(
                code="STA", latitude=0.0, longitude=0.0, elevation=0.0
            )
            obj.stations.append(sta)
        elif choice == "New Channel":
            chan = Channel(
                code="BHZ", location_code="",
                latitude=obj.latitude, longitude=obj.longitude,
                depth=0.0, elevation=obj.elevation,
                azimuth=0.0, dip=-90.0, sample_rate=100.0,
            )
            chan.response = Response()
            obj.channels.append(chan)
        else:
            self._set_field(obj, choice)
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

    def add_object_fields(self, parent_item, obj):
        for field in sorted(dir(obj)):
            if field.startswith("_") or callable(getattr(obj, field)):
                continue
            value = getattr(obj, field)
            if isinstance(value, UTCDateTime):
                item = QTreeWidgetItem(
                    parent_item, [field, str(value)]
                )
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setData(0, Qt.UserRole, (obj, field))
            elif isinstance(value, (str, float, int)):
                item = QTreeWidgetItem(
                    parent_item, [field, str(value)]
                )
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setData(0, Qt.UserRole, (obj, field))

    def _save_tree_state(self):
        # Save expanded paths and selected item path.
        # Fixes new item creation
        expanded = set()
        selected_path = None
        sel = self.tree.currentItem()

        def walk(item, path=""):
            p = f"{path}/{item.text(0)}" if path else item.text(0)
            if item.isExpanded():
                expanded.add(p)
            if item is sel:
                nonlocal selected_path
                selected_path = p
            for i in range(item.childCount()):
                walk(item.child(i), p)

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return expanded, selected_path

    def _restore_tree_state(self, expanded, selected_path):
        """Restore expanded paths and selection."""
        def walk(item, path=""):
            p = f"{path}/{item.text(0)}" if path else item.text(0)
            if p in expanded:
                item.setExpanded(True)
            if p == selected_path:
                self.tree.setCurrentItem(item)
            for i in range(item.childCount()):
                walk(item.child(i), p)

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def populate_tree(self, inv):
        expanded, selected_path = self._save_tree_state()
        self.tree.clear()
        self.current_inventory = inv
        try:
            for net in inv.networks:
                net_item = QTreeWidgetItem([f"Network: {net.code}", ""])
                self.tree.addTopLevelItem(net_item)
                self.add_object_fields(net_item, net)

                for sta in net.stations:
                    sta_item = QTreeWidgetItem([f"Station: {sta.code}", ""])
                    sta_item.setData(0, Qt.UserRole, ("station", sta))
                    net_item.addChild(sta_item)
                    self.add_object_fields(sta_item, sta)

                    for chan in sta.channels:
                        chan_item = QTreeWidgetItem(
                            [f"Channel: {chan.code}", ""]
                        )
                        sta_item.addChild(chan_item)
                        self.add_object_fields(chan_item, chan)
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
        self._restore_tree_state(expanded, selected_path)
        self.filter_tree()

    def on_tree_selection_changed(self):
        item = self.tree.currentItem()
        if not item:
            self.new_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        label = item.text(0)
        in_response = label.startswith("Response") or label.startswith("Stage")

        if in_response:
            self.new_button.setEnabled(False)
            self.delete_button.setEnabled(False)
        else:
            self.new_button.setEnabled(
                self._find_header_item(item) is not None
            )
            # Deletable: Station, Channel, or an optional property field
            can_delete = (
                label.startswith("Station: ")
                or label.startswith("Channel: ")
                or self._is_optional_field(item)
            )
            self.delete_button.setEnabled(can_delete)

    def _is_optional_field(self, item):
        """Check if item is a deletable (optional) property field."""
        ref = item.data(0, Qt.UserRole)
        if not ref or not isinstance(ref, tuple) or len(ref) != 2:
            return False
        _obj, field = ref
        if not isinstance(field, str):
            return False
        # Don't allow deleting core required fields
        required = {
            "code", "latitude", "longitude", "elevation",
            "depth", "azimuth", "dip", "sample_rate", "location_code",
        }
        return field not in required

    def delete_selected(self):
        item = self.tree.currentItem()
        if not item:
            return
        label = item.text(0)

        # Delete a Station
        if label.startswith("Station: "):
            ref = item.data(0, Qt.UserRole)
            if not ref or ref[0] != "station":
                return
            sta = ref[1]
            net_item = item.parent()
            if not net_item:
                return
            net_label = net_item.text(0)
            reply = QMessageBox.question(
                self, "Delete Station",
                f"Delete {label} from {net_label}?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            net_code = net_label.replace("Network: ", "").strip()
            for net in self.current_inventory.networks:
                if net.code == net_code and sta in net.stations:
                    net.stations.remove(sta)
                    break
            self.populate_tree(self.current_inventory)
            return

        # Delete a Channel
        if label.startswith("Channel: "):
            sta_item = item.parent()
            if not sta_item:
                return
            sta_ref = sta_item.data(0, Qt.UserRole)
            if not sta_ref or sta_ref[0] != "station":
                return
            sta = sta_ref[1]
            chan_code = label.replace("Channel: ", "").strip()
            chan = next(
                (c for c in sta.channels if c.code == chan_code), None
            )
            if not chan:
                return
            reply = QMessageBox.question(
                self, "Delete Channel",
                f"Delete {label} from Station: {sta.code}?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            sta.channels.remove(chan)
            self.populate_tree(self.current_inventory)
            return

        # Delete an optional property field
        if self._is_optional_field(item):
            obj, field = item.data(0, Qt.UserRole)
            reply = QMessageBox.question(
                self, "Delete Field",
                f"Remove field \"{field}\"?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            setattr(obj, field, None)
            self.populate_tree(self.current_inventory)

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
            if isinstance(old_value, UTCDateTime):
                new_value = UTCDateTime(new_value)
            elif old_value is None and attr in (
                "start_date", "end_date", "creation_date",
                "termination_date",
            ):
                if new_value.strip():
                    new_value = UTCDateTime(new_value)
                else:
                    new_value = None
            elif isinstance(old_value, float):
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
        sta_text = self.station_filter.text().strip().upper()
        prop_text = self.search_bar.text().lower()

        for ni in range(self.tree.topLevelItemCount()):
            net_item = self.tree.topLevelItem(ni)
            net_code = net_item.text(0).replace("Network: ", "").strip()
            net_matches = not sta_text or sta_text in net_code.upper()

            any_sta_visible = False
            for si in range(net_item.childCount()):
                sta_item = net_item.child(si)
                label = sta_item.text(0)
                if not label.startswith("Station: "):
                    # property field under network — handle with prop filter
                    self._filter_prop(sta_item, prop_text)
                    continue
                sta_code = label.replace("Station: ", "").strip()
                sta_visible = net_matches or sta_text in sta_code.upper()

                if sta_visible:
                    # Station matched — apply property filter inside
                    self._filter_prop(sta_item, prop_text)
                    any_sta_visible = True
                else:
                    sta_item.setHidden(True)

            net_item.setHidden(not (net_matches or any_sta_visible))
            if (net_matches or any_sta_visible) and sta_text:
                net_item.setExpanded(True)

    def _filter_prop(self, item, prop_text):
        # Apply property text filter recursively. Show all if empty."""
        if not prop_text:
            item.setHidden(False)
            for i in range(item.childCount()):
                self._filter_prop(item.child(i), prop_text)
            return True

        child_match = False
        for i in range(item.childCount()):
            if self._filter_prop(item.child(i), prop_text):
                child_match = True

        item_text = (item.text(0) + item.text(1)).lower()
        visible = prop_text in item_text or child_match
        item.setHidden(not visible)
        if visible and prop_text:
            item.setExpanded(True)
        return visible
