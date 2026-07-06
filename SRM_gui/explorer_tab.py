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
    QShortcut,
)
from PyQt5.QtGui import QColor, QBrush, QKeySequence
from PyQt5.QtCore import Qt
from obspy import UTCDateTime
from obspy.core.inventory import Station, Channel
from obspy.core.inventory.response import Response
from SRM_gui.validation_ui import build_issue_items, tint_warning


_BASELINE_ROLE = Qt.UserRole + 1
_FIELDS_CACHE = {}


def _editable_attrs(obj):
    cls = type(obj)
    cached = _FIELDS_CACHE.get(cls)
    if cached is not None:
        return cached
    names = []
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            val = getattr(obj, name)
        except Exception:
            continue
        if callable(val):
            continue
        names.append(name)
    names.sort()
    _FIELDS_CACHE[cls] = names
    return names


class ExplorerTab(QWidget):
    def __init__(self, filepath, main_window):
        super().__init__()
        self.filepath = filepath
        self.main_window = main_window
        self.current_inventory = None
        self.undo_stack = []
        self.redo_stack = []
        self._suppress_edits = False
        self._item_index = {}
        self._baseline_snapshot = {}

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

        self.undo_shortcut = QShortcut(QKeySequence.Undo, self)
        self.undo_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.undo_shortcut.activated.connect(self.undo)
        self.redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.redo_shortcut.activated.connect(self.redo)
        self.redo_shortcut_alt = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self.redo_shortcut_alt.setContext(Qt.WidgetWithChildrenShortcut)
        self.redo_shortcut_alt.activated.connect(self.redo)

    def navigate_to(
        self, net_code, sta_code, chan_code,
        loc_code="", start_ts=0.0,
    ):
        # Find and select/expand a specific network/station/channel.
        from SRM_core.utils import utc_to_ts

        for ni in range(self.tree.topLevelItemCount()):
            net_item = self.tree.topLevelItem(ni)
            if net_item.text(0) != f"Network: {net_code}":
                continue
            net_item.setExpanded(True)
            if not sta_code:
                self.tree.setCurrentItem(net_item)
                self.tree.scrollToItem(net_item)
                return

            # A station code may appear multiple times under the same
            # network when StationXML has separate <Station> blocks for
            # different operational periods. Search across all of them.
            sta_items = [
                net_item.child(si)
                for si in range(net_item.childCount())
                if net_item.child(si).text(0) == f"Station: {sta_code}"
            ]
            if not sta_items:
                return

            for s in sta_items:
                s.setExpanded(True)

            if not chan_code:
                self.tree.setCurrentItem(sta_items[0])
                self.tree.scrollToItem(sta_items[0])
                return

            best_item = None
            best_diff = None
            for sta_item in sta_items:
                for ci in range(sta_item.childCount()):
                    chan_item = sta_item.child(ci)
                    ref = chan_item.data(0, Qt.UserRole)
                    if not (
                        ref and isinstance(ref, tuple)
                        and ref[0] == "channel"
                    ):
                        continue
                    ch = ref[1]
                    if ch.code != chan_code:
                        continue
                    # Match timeline.py's "--" sentinel for empty loc.
                    cur_loc = ch.location_code or "--"
                    if loc_code and cur_loc != loc_code:
                        continue
                    if start_ts and ch.start_date:
                        ts = utc_to_ts(ch.start_date) or 0
                        diff = abs(ts - start_ts)
                        if best_diff is None or diff < best_diff:
                            best_diff = diff
                            best_item = chan_item
                    elif best_item is None:
                        best_item = chan_item

            if best_item:
                best_item.setExpanded(True)
                self.tree.setCurrentItem(best_item)
                self.tree.scrollToItem(best_item)
                return

            # Channel not found in any matching station — fall back.
            self.tree.setCurrentItem(sta_items[0])
            self.tree.scrollToItem(sta_items[0])
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
    # Integer-typed fields whose ObsPy setter validates the value, so a raw
    # string would raise. Float fields (water_level, clock_drift, ...) are
    # coerced by ObsPy automatically and need no special handling.
    _INT_FIELDS = {"total_number_of_stations"}

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
            # Resolve via the stored object ref so an inline code edit (which
            # leaves the header label stale) doesn't break resolution.
            ref = header_item.data(0, Qt.UserRole)
            if ref and isinstance(ref, tuple) and ref[0] == "network":
                return ref[1]
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

        new_ref = None
        if choice == "New Station":
            sta = Station(
                code="STA", latitude=0.0, longitude=0.0, elevation=0.0
            )
            obj.stations.append(sta)
            self._push_undo(("add_station", obj, sta))
            new_ref = ("station", sta)
        elif choice == "New Channel":
            chan = Channel(
                code="BHZ", location_code="",
                latitude=obj.latitude, longitude=obj.longitude,
                depth=0.0, elevation=obj.elevation,
                azimuth=0.0, dip=-90.0, sample_rate=100.0,
            )
            chan.response = Response()
            obj.channels.append(chan)
            self._push_undo(("add_channel", obj, chan))
            new_ref = ("channel", chan)
        else:
            prev_value = getattr(obj, choice, None)
            self._set_field(obj, choice)
            self._push_undo(("add_field", obj, choice, prev_value))
        self.populate_tree(self.current_inventory)
        if new_ref is not None:
            self._focus_tree_item(
                self._find_tree_item_by_data(new_ref)
            )
        else:
            self._focus_tree_item(
                self._item_index.get((id(obj), choice))
            )

    def add_object_fields(self, parent_item, obj):
        for field in _editable_attrs(obj):
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
            else:
                continue
            key = (id(obj), field)
            if key not in self._baseline_snapshot:
                self._baseline_snapshot[key] = value
            baseline_value = self._baseline_snapshot[key]
            item.setData(0, _BASELINE_ROLE, baseline_value)
            if self._values_differ(value, baseline_value):
                self._apply_modified_style(item, True)
            self._item_index[key] = item

    @staticmethod
    def _values_differ(current, baseline):
        if isinstance(current, UTCDateTime) or isinstance(
            baseline, UTCDateTime
        ):
            return str(current) != str(baseline)
        return current != baseline

    def _apply_modified_style(self, item, modified):
        font = item.font(1)
        font.setBold(modified)
        item.setFont(1, font)
        if modified:
            item.setForeground(1, QBrush(QColor("royalblue")))
            item.setData(1, Qt.UserRole, "modified")
        else:
            item.setForeground(1, QBrush())
            item.setData(1, Qt.UserRole, None)

    @staticmethod
    def _find_match(items, target, keys):
        for it in items:
            if all(
                getattr(it, k, None) == getattr(target, k, None) for k in keys
            ):
                return it
        return None

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

    def _find_tree_item_by_data(self, ref):
        def walk(item):
            if item.data(0, Qt.UserRole) == ref:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None

        for i in range(self.tree.topLevelItemCount()):
            found = walk(self.tree.topLevelItem(i))
            if found is not None:
                return found
        return None

    def _focus_tree_item(self, item):
        if item is None:
            return
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    def populate_tree(self, inv):
        expanded, selected_path = self._save_tree_state()
        self._suppress_edits = True
        self.tree.setUpdatesEnabled(False)
        self.tree.blockSignals(True)
        self.tree.clear()
        self._item_index = {}
        self.current_inventory = inv
        try:
            for net in inv.networks:
                net_item = QTreeWidgetItem([f"Network: {net.code}", ""])
                net_item.setData(0, Qt.UserRole, ("network", net))
                self.tree.addTopLevelItem(net_item)
                self.add_object_fields(net_item, net)
                net_has_issues = False

                for sta in net.stations:
                    sta_item = QTreeWidgetItem([f"Station: {sta.code}", ""])
                    sta_item.setData(0, Qt.UserRole, ("station", sta))
                    net_item.addChild(sta_item)
                    self.add_object_fields(sta_item, sta)
                    sta_has_issues = False

                    for chan in sta.channels:
                        chan_item = QTreeWidgetItem(
                            [f"Channel: {chan.code}", ""]
                        )
                        chan_item.setData(
                            0, Qt.UserRole, ("channel", chan)
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

                        warn_item = build_issue_items(chan, two_columns=True)
                        if warn_item is not None:
                            chan_item.insertChild(0, warn_item)
                            tint_warning(chan_item)
                            sta_has_issues = True

                    if sta_has_issues:
                        tint_warning(sta_item)
                        net_has_issues = True

                if net_has_issues:
                    tint_warning(net_item)
        except Exception as e:
            QTreeWidgetItem(self.tree, ["Error", str(e)])
        if expanded or selected_path:
            self._restore_tree_state(expanded, selected_path)
        if (self.station_filter.text().strip()
                or self.search_bar.text().strip()):
            self.filter_tree()
        self.tree.blockSignals(False)
        self.tree.setUpdatesEnabled(True)
        self._suppress_edits = False

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
                    idx = net.stations.index(sta)
                    net.stations.remove(sta)
                    self._push_undo(
                        ("delete_station", net, sta, idx)
                    )
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
            idx = sta.channels.index(chan)
            sta.channels.remove(chan)
            self._push_undo(("delete_channel", sta, chan, idx))
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
            old_value = getattr(obj, field, None)
            setattr(obj, field, None)
            self._push_undo(("delete_field", obj, field, old_value))
            self.populate_tree(self.current_inventory)

    def handle_tree_edit(self, item, column):
        if column != 1 or self._suppress_edits:
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
            elif old_value is None and attr in self._INT_FIELDS:
                new_value = int(new_value) if new_value.strip() else None
            elif isinstance(old_value, float):
                new_value = float(new_value)
            elif isinstance(old_value, int):
                new_value = int(new_value)

            setattr(ref_object, attr, new_value)
            self._push_undo(("edit", ref_object, attr, old_value))

            baseline_value = item.data(0, _BASELINE_ROLE)
            self._suppress_edits = True
            try:
                self._apply_modified_style(
                    item, self._values_differ(new_value, baseline_value)
                )
            finally:
                self._suppress_edits = False

        except Exception as e:
            QMessageBox.warning(
                self, "Edit Error", f"Failed to update {attr}: {e}"
            )
            self._suppress_edits = True
            item.setText(1, str(old_value))
            self._suppress_edits = False

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

            # Include the location code so channels that share a code but
            # differ by location (e.g. 00.BHZ / 10.BHZ) get distinct ids.
            chan_ref = chan_item.data(0, Qt.UserRole)
            loc_code = ""
            if (chan_ref and isinstance(chan_ref, tuple)
                    and chan_ref[0] == "channel"):
                loc_code = chan_ref[1].location_code or ""
            unique_id = f"{net_code}.{sta_code}.{loc_code}.{chan_code}"

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

    _UNDO_LIMIT = 100

    def _push_undo(self, op):
        # A new user edit invalidates anything that was undone.
        self.redo_stack.clear()
        self.undo_stack.append(op)
        if len(self.undo_stack) > self._UNDO_LIMIT:
            self.undo_stack = self.undo_stack[-self._UNDO_LIMIT:]

    def _apply_reverse(self, op):
        tag = op[0]
        if tag == "edit":
            _, ref_object, attr, old_value = op
            setattr(ref_object, attr, old_value)
            return ("field", ref_object, attr, old_value)
        if tag == "add_station":
            _, network, station = op
            if station in network.stations:
                network.stations.remove(station)
            return ("structural",)
        if tag == "add_channel":
            _, station, channel = op
            if channel in station.channels:
                station.channels.remove(channel)
            return ("structural",)
        if tag == "add_field":
            _, obj, attr, prev_value = op
            setattr(obj, attr, prev_value)
            return ("structural",)
        if tag == "delete_station":
            _, network, station, index = op
            network.stations.insert(index, station)
            return ("structural",)
        if tag == "delete_channel":
            _, station, channel, index = op
            station.channels.insert(index, channel)
            return ("structural",)
        if tag == "delete_field":
            _, obj, attr, old_value = op
            setattr(obj, attr, old_value)
            return ("field", obj, attr, old_value)
        return ("structural",)

    def _capture_forward(self, op):
        # Save what _apply_reverse is about to destroy so redo can restore
        # it. Structural ops already carry the object and index.
        if op[0] in ("edit", "add_field", "delete_field"):
            return getattr(op[1], op[2], None)
        return None

    def _apply_forward(self, op, captured):
        tag = op[0]
        if tag == "edit":
            _, ref_object, attr, _old = op
            setattr(ref_object, attr, captured)
            return ("field", ref_object, attr, captured)
        if tag == "add_station":
            _, network, station = op
            if station not in network.stations:
                network.stations.append(station)
            return ("structural",)
        if tag == "add_channel":
            _, station, channel = op
            if channel not in station.channels:
                station.channels.append(channel)
            return ("structural",)
        if tag == "add_field":
            # Structural: the field row has to (re)appear in the tree.
            _, obj, attr, _prev = op
            setattr(obj, attr, captured)
            return ("structural",)
        if tag == "delete_station":
            _, network, station, _index = op
            if station in network.stations:
                network.stations.remove(station)
            return ("structural",)
        if tag == "delete_channel":
            _, station, channel, _index = op
            if channel in station.channels:
                station.channels.remove(channel)
            return ("structural",)
        if tag == "delete_field":
            _, obj, attr, _old = op
            setattr(obj, attr, None)
            return ("structural",)
        return ("structural",)

    def undo(self):
        if not self.undo_stack:
            return
        op = self.undo_stack.pop()
        fast = False
        try:
            captured = self._capture_forward(op)
            result = self._apply_reverse(op)
            self.redo_stack.append((op, captured))
            if result[0] == "field":
                _, ref_object, attr, value = result
                fast = self._fast_update_item(ref_object, attr, value)
        except Exception as e:
            QMessageBox.warning(
                self, "Undo Error", f"Failed to undo: {e}"
            )
        if not fast:
            self.populate_tree(self.current_inventory)

    def redo(self):
        if not self.redo_stack:
            return
        op, captured = self.redo_stack.pop()
        fast = False
        try:
            result = self._apply_forward(op, captured)
            # Append directly: _push_undo would clear the redo stack.
            self.undo_stack.append(op)
            if result[0] == "field":
                _, ref_object, attr, value = result
                fast = self._fast_update_item(ref_object, attr, value)
        except Exception as e:
            QMessageBox.warning(
                self, "Redo Error", f"Failed to redo: {e}"
            )
        if not fast:
            self.populate_tree(self.current_inventory)

    def _revert_all(self):
        while self.undo_stack:
            op = self.undo_stack.pop()
            try:
                self._apply_reverse(op)
            except Exception:
                pass
        self.redo_stack.clear()

    def _fast_update_item(self, ref_object, attr, value):
        item = self._item_index.get((id(ref_object), attr))
        if item is None:
            return False
        self._suppress_edits = True
        try:
            item.setText(1, str(value) if value is not None else "")
            baseline_value = item.data(0, _BASELINE_ROLE)
            self._apply_modified_style(
                item, self._values_differ(value, baseline_value)
            )
        finally:
            self._suppress_edits = False
        return True
