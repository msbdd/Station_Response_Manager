import os
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from SRM_core.mseed_scan import (
    build_inventory,
    group_label,
    rate_mismatch,
    response_groups,
    split_by_station,
)
from SRM_core.utils import atomic_write_inventory
from SRM_gui.io_progress import IOProgressDialog
from SRM_gui.response_tab import ResponseSelectionDialog
from SRM_gui.validation_ui import WARNING_COLOR

# The Build Inventory wizard's coordinate ranges. The spin boxes enforce
# them, so out-of-range input cannot be typed in the first place.
_COORD_COLUMNS = (
    ("Latitude", -90.0, 90.0, 6),
    ("Longitude", -180.0, 180.0, 6),
    ("Elevation (m)", -12000.0, 9000.0, 2),
)
_FIXED_STATION_COLUMNS = ["Network", "Station", "Channels", "Data span"]

_NO_RESPONSE = "Not selected (empty placeholder)"


def _preview(names, limit=8):
    shown = ", ".join(names[:limit])
    if len(names) > limit:
        shown += f" and {len(names) - limit} more"
    return shown


def _channel_summary(epochs):
    """``00.HH[ENZ], 00.HN[ENZ]``: one entry per location + band/
    instrument code, with its component letters bracketed."""
    components = {}
    for e in epochs:
        components.setdefault(
            (e.location, e.channel[:-1]), set()
        ).add(e.channel[-1:])
    parts = []
    for (loc, prefix), letters in sorted(components.items()):
        letters = "".join(sorted(letters))
        code = prefix + (letters if len(letters) == 1 else f"[{letters}]")
        parts.append(f"{loc}.{code}" if loc else code)
    return ", ".join(parts)


class _CoordSpinBox(QDoubleSpinBox):
    """Ignores the wheel unless focused: a table full of spin boxes would
    otherwise change whichever value is under the cursor while the user
    scrolls the table."""

    def __init__(self, low, high, decimals):
        super().__init__()
        self.setRange(low, high)
        self.setDecimals(decimals)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class BatchInventoryDialog(QDialog):
    """``stations`` come from ``mseed_scan.aggregate``, ``report`` is the
    scan's ScanReport, and ``loaded_paths`` are the session's loaded files,
    which must never be overwritten. ``saved_paths`` lists every file
    written, for the caller's "load now?" offer."""

    def __init__(self, folder, stations, report, nrl_root,
                 loaded_paths=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Build Inventories from MiniSEED Folder")
        self.resize(1000, 800)
        # Qt gives every QDialog a "What's This?" title-bar button; with no
        # What's This text anywhere it does nothing, so drop it.
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint
        )
        self.folder = folder
        self.stations = stations
        self.report = report
        self.nrl_root = nrl_root
        self.loaded_paths = set(loaded_paths)
        self.saved_paths = []

        self._groups = response_groups(stations)
        self._group_keys = list(self._groups)
        self._responses = dict.fromkeys(self._group_keys)
        self._response_info = {}
        self._coord_boxes = {}

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_summary())
        # The station list grows with the deployment; the group table is
        # sized to its rows, so all spare height goes to the stations.
        layout.addWidget(self._build_station_box(), 1)
        layout.addWidget(self._build_response_box())
        layout.addWidget(self._build_options_box())

        buttons = QDialogButtonBox()
        buttons.addButton("Build and Save…", QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- layout ---------------------------------------------------------

    def _build_summary(self):
        row = QHBoxLayout()
        n_epochs = sum(len(s.epochs) for s in self.stations)
        label = QLabel(
            f"{self.folder}\n{self.report.summary()}. Found "
            f"{len(self.stations)} station(s) with {n_epochs} channel "
            "epoch(s)."
        )
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(label, 1)
        if self.report.not_mseed or self.report.unreadable:
            details = QPushButton("Details…")
            details.clicked.connect(self._show_details)
            row.addWidget(details)
        return row

    def _show_details(self):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Scan Details")
        box.setText(self.report.summary())
        box.setDetailedText(self.report.details())
        box.exec_()

    def _build_station_box(self):
        box = QGroupBox(
            "Stations (MiniSEED carries no coordinates, so enter them here)"
        )
        table = QTableWidget(
            len(self.stations),
            len(_FIXED_STATION_COLUMNS) + len(_COORD_COLUMNS),
        )
        table.setHorizontalHeaderLabels(
            _FIXED_STATION_COLUMNS + [col[0] for col in _COORD_COLUMNS]
        )
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)

        for row, scanned in enumerate(self.stations):
            start = min(e.start for e in scanned.epochs)
            end = max(e.end for e in scanned.epochs)
            cells = [
                scanned.network,
                scanned.station,
                _channel_summary(scanned.epochs),
                f"{start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}",
            ]
            tooltip = "\n".join(
                f"{e.location or '--'}.{e.channel}  {e.sample_rate:g} Hz  "
                f"{e.start.strftime('%Y-%m-%d %H:%M:%S')} → "
                f"{e.end.strftime('%Y-%m-%d %H:%M:%S')}"
                for e in scanned.epochs
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(tooltip)
                table.setItem(row, col, item)

            boxes = []
            for offset, (_name, low, high, decimals) in enumerate(
                    _COORD_COLUMNS):
                spin = _CoordSpinBox(low, high, decimals)
                table.setCellWidget(
                    row, len(_FIXED_STATION_COLUMNS) + offset, spin
                )
                boxes.append(spin)
            self._coord_boxes[(scanned.network, scanned.station)] = boxes

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.station_table = table

        layout = QVBoxLayout(box)
        layout.addWidget(table)
        return box

    def _build_response_box(self):
        box = QGroupBox("Responses by channel group")
        layout = QVBoxLayout(box)
        hint = QLabel(
            "A group is location + band/instrument code + sample rate, i.e. "
            "one sensor/datalogger combination. Groups left unselected get "
            "an empty response to fill in later in the Response tab."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        apply_row = QHBoxLayout()
        apply_all = QPushButton("Apply One Response to All Groups…")
        apply_all.clicked.connect(self._apply_to_all)
        apply_row.addWidget(apply_all)
        apply_row.addStretch()
        layout.addLayout(apply_row)

        table = QTableWidget(len(self._group_keys), 5)
        table.setHorizontalHeaderLabels(
            ["Group", "Channels", "Stations", "Response", ""]
        )
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for row, key in enumerate(self._group_keys):
            n_channels, n_stations = self._groups[key]
            cells = (group_label(key), str(n_channels), str(n_stations),
                     _NO_RESPONSE)
            for col, text in enumerate(cells):
                table.setItem(row, col, QTableWidgetItem(text))

            buttons = QWidget()
            button_layout = QHBoxLayout(buttons)
            button_layout.setContentsMargins(0, 0, 0, 0)
            select_btn = QPushButton("Select…")
            select_btn.clicked.connect(
                lambda _checked=False, k=key: self._select_response(k)
            )
            clear_btn = QPushButton("Clear")
            clear_btn.clicked.connect(
                lambda _checked=False, k=key: self._clear_response(k)
            )
            button_layout.addWidget(select_btn)
            button_layout.addWidget(clear_btn)
            table.setCellWidget(row, 4, buttons)

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        # Fit the rows (a handful is typical), scrolling past six.
        table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        table.setMaximumHeight(
            header.sizeHint().height()
            + min(len(self._group_keys), 6)
            * table.verticalHeader().defaultSectionSize()
            + 2 * table.frameWidth()
        )
        self.group_table = table
        for row in range(len(self._group_keys)):
            self._refresh_group_row(row)

        layout.addWidget(table)
        return box

    def _build_options_box(self):
        box = QGroupBox("Options")
        layout = QVBoxLayout(box)
        self.close_epochs_cb = QCheckBox(
            "End channel epochs at the last sample found "
            "(otherwise the latest epoch stays open)"
        )
        self.close_epochs_cb.setToolTip(
            "Leave unchecked while the deployment is still recording: an "
            "open epoch never excludes data that arrives after the scan."
        )
        layout.addWidget(self.close_epochs_cb)
        self.single_file_rb = QRadioButton(
            "One StationXML file for all stations"
        )
        self.per_station_rb = QRadioButton(
            "One file per station (NET.STA.xml) in a chosen folder"
        )
        self.single_file_rb.setChecked(True)
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Save as:"))
        output_row.addWidget(self.single_file_rb)
        output_row.addWidget(self.per_station_rb)
        output_row.addStretch()
        layout.addLayout(output_row)
        return box

    # --- responses ------------------------------------------------------

    def _pick_response(self):
        dialog = ResponseSelectionDialog(self.nrl_root, self)
        if dialog.exec_() != QDialog.Accepted:
            return None
        response, sensor_info, datalogger_info = dialog.get_response()
        if response is None:
            return None
        info = f"Sensor: {sensor_info} | Datalogger: {datalogger_info}"
        return response, info

    def _select_response(self, key):
        picked = self._pick_response()
        if picked is not None:
            self._set_group_response(key, *picked)

    def _apply_to_all(self):
        # Every group holds the same object; build_inventory deep-copies
        # it per channel, so nothing ends up shared in the output.
        picked = self._pick_response()
        if picked is None:
            return
        for key in self._group_keys:
            self._set_group_response(key, *picked)

    def _clear_response(self, key):
        self._set_group_response(key, None, None)

    def _set_group_response(self, key, response, info):
        self._responses[key] = response
        self._response_info[key] = info
        self._refresh_group_row(self._group_keys.index(key))

    def _mismatches(self):
        """``[(group key, response output rate)]`` for groups whose
        response ends at a different rate than their channels record."""
        found = []
        for key in self._group_keys:
            response = self._responses[key]
            if response is None:
                continue
            out_rate = rate_mismatch(response, key[2])
            if out_rate is not None:
                found.append((key, out_rate))
        return found

    def _refresh_group_row(self, row):
        key = self._group_keys[row]
        item = self.group_table.item(row, 3)
        response = self._responses[key]
        item.setData(Qt.ForegroundRole, None)
        if response is None:
            item.setText(_NO_RESPONSE)
            item.setToolTip(
                "These channels get an empty <Response/> to fill in later "
                "in the Response tab."
            )
            return
        info = self._response_info[key]
        out_rate = rate_mismatch(response, key[2])
        if out_rate is None:
            item.setText(info)
            item.setToolTip(info)
            return
        item.setText(f"⚠ response ends at {out_rate:g} Hz | {info}")
        item.setToolTip(
            f"The response's decimation chain ends at {out_rate:g} Hz, but "
            f"these channels record at {key[2]:g} Hz. NRL datalogger "
            f"responses are specific to one sample rate.\n\n{info}"
        )
        item.setForeground(QBrush(QColor(WARNING_COLOR)))

    # --- build and save -------------------------------------------------

    def _coords(self):
        return {
            key: tuple(box.value() for box in boxes)
            for key, boxes in self._coord_boxes.items()
        }

    def accept(self):
        # Runs as a clicked slot: an exception escaping it would abort the
        # process under PyQt5, and the dialog has to stay open with the
        # user's coordinates and responses intact.
        try:
            coords = self._coords()
            inventory, notes = build_inventory(
                self.stations,
                responses=self._responses,
                coords=coords,
                open_ended=not self.close_epochs_cb.isChecked(),
            )
            if not self._confirm_build(notes, coords):
                return
            targets = self._choose_targets(inventory)
            if targets and self._write(targets):
                super().accept()
        except Exception as e:
            QMessageBox.critical(
                self, "Build Error",
                f"Failed to build or save the inventory:\n{e}"
            )

    def _confirm_build(self, notes, coords):
        """One Yes/No summary of everything placeholder-ish about the
        result, instead of a modal per issue."""
        items = []
        empty = [
            group_label(k) for k in self._group_keys
            if self._responses[k] is None
        ]
        if empty:
            items.append(
                f"No response selected for {_preview(empty)}. Their "
                "channels get an empty response to fill in later in the "
                "Response tab."
            )
        mismatched = [
            f"{group_label(key)} gets a response that ends at {rate:g} Hz"
            for key, rate in self._mismatches()
        ]
        if mismatched:
            items.append(
                f"Sample-rate mismatch: {_preview(mismatched)}. NRL "
                "datalogger responses are specific to one sample rate."
            )
        if notes["no_azimuth"]:
            items.append(
                "The component code does not define an azimuth for "
                f"{_preview(notes['no_azimuth'])}. Azimuth will be left "
                "unset rather than defaulted to 0 (which would claim the "
                "channel points due north). You can fill it in afterwards "
                "in the Explorer tab."
            )
        if notes["overlaps"]:
            items.append(
                "Epochs overlap (the sample rate switched back and forth) "
                f"for {_preview(notes['overlaps'])}."
            )
        unplaced = [
            f"{net}.{sta}" for (net, sta), values in coords.items()
            if not any(values)
        ]
        if unplaced:
            items.append(
                f"Placeholder coordinates 0, 0, 0 for {_preview(unplaced)}."
            )
        if not items:
            return True
        reply = QMessageBox.warning(
            self,
            "Review Before Saving",
            "\n\n".join(f"• {text}" for text in items) + "\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        return reply == QMessageBox.Yes

    def _default_filename(self, inventory):
        codes = [net.code for net in inventory.networks]
        if len(codes) == 1 and codes[0]:
            return f"{codes[0]}.xml"
        name = os.path.basename(os.path.normpath(self.folder))
        return f"{name or 'inventory'}.xml"

    def _choose_targets(self, inventory):
        """``[(path, Inventory)]`` to write, or None if the user backed
        out or a target is unsafe."""
        per_station = self.per_station_rb.isChecked()
        if per_station:
            folder = QFileDialog.getExistingDirectory(
                self, "Select Output Folder"
            )
            if not folder:
                return None
            targets = [
                (os.path.join(folder, name), inv)
                for name, inv in split_by_station(inventory)
            ]
        else:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Inventory File",
                self._default_filename(inventory),
                "StationXML (*.xml)",
            )
            if not path:
                return None
            targets = [(path, inventory)]

        # Overwriting a file open in this session would orphan its
        # in-memory copy, and the next Save All would write that stale
        # copy over the new file.
        loaded = [
            os.path.basename(path) for path, _inv in targets
            if str(Path(path).resolve()) in self.loaded_paths
        ]
        if loaded:
            QMessageBox.warning(
                self, "File Already Loaded",
                f"These files are open in the current session: "
                f"{_preview(loaded)}.\n\nClose them first if you want to "
                "replace them, or save somewhere else."
            )
            return None

        # The single-file save dialog already confirmed any overwrite.
        if per_station:
            existing = [
                os.path.basename(path) for path, _inv in targets
                if os.path.exists(path)
            ]
            if existing:
                reply = QMessageBox.question(
                    self, "Overwrite Files",
                    f"{len(existing)} file(s) already exist in this "
                    f"folder: {_preview(existing)}.\n\nOverwrite them?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return None
        return targets

    def _write(self, targets):
        """Write ``targets`` with progress; True only if all of them were
        written. Successes land in ``saved_paths`` either way."""
        written = []
        failures = []
        outcome = {"canceled": False}

        def on_result(idx, _result, error):
            # Collect only; one summary follows the batch (a modal here
            # would spin a nested event loop under the running batch).
            path = targets[idx][0]
            if error is not None:
                failures.append((path, error))
                return
            written.append(path)
            resolved = str(Path(path).resolve())
            if resolved not in self.saved_paths:
                self.saved_paths.append(resolved)

        def on_done(summary):
            outcome["canceled"] = summary.canceled

        jobs = [
            (
                f"Saving {os.path.basename(path)}...",
                (lambda path=path, inv=inv:
                 atomic_write_inventory(inv, path, fmt="STATIONXML")),
            )
            for path, inv in targets
        ]
        IOProgressDialog(
            "Saving inventories", jobs, on_result, on_done, parent=self
        ).exec_()

        if not failures and not outcome["canceled"]:
            if len(written) == 1:
                text = f"Inventory saved to:\n{written[0]}"
            else:
                text = (
                    f"{len(written)} inventories saved to:\n"
                    f"{os.path.dirname(written[0])}"
                )
            QMessageBox.information(self, "Success", text)
            return True

        lines = [f"{len(written)} of {len(targets)} files saved."]
        if outcome["canceled"]:
            lines.append("Saving was cancelled.")
        if failures:
            lines.append("These files were NOT saved:\n" + "\n".join(
                f"  {os.path.basename(path)}: {error}"
                for path, error in failures
            ))
        lines.append(
            "Your coordinates and responses are kept, so you can try "
            "again or choose another location."
        )
        QMessageBox.warning(self, "Save Incomplete", "\n\n".join(lines))
        return False
