"""The Manager's Instruments tab: what is deployed.

Two linked bar charts count stations per sensor and per digitizer model.
Clicking bars filters the Manager's tree, map and timeline — each click
adds or removes one, Clear filter resets — and rescopes the other chart:
pick the STS-2, and the digitizer chart shows what records them. The
Manager tree is the station list and the Timeline shows when instruments
changed, so the tab holds nothing else.
"""
from collections import Counter

from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import pyqtSignal

from SRM_core import fleet
from SRM_gui.instrument_chart import InstrumentBarChart

_ROLE_CHOICES = (
    ("sensor", "Sensors"),
    ("datalogger", "Digitizers"),
    ("preamplifier", "Pre-amplifiers"),
)
_ROLE_NAME = {
    "sensor": "Sensor", "datalogger": "Digitizer",
    "preamplifier": "Pre-amplifier",
}


class InstrumentsWidget(QWidget):
    # {role: frozenset(category keys)}, current deployments only, and a
    # short description of the selection for the Manager's header.
    filter_changed = pyqtSignal(object, bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loaded_files = {}
        self._nrl_index = None
        self._issue_stations = None
        self._dirty = False
        self._selection = {}
        # role -> {category key: label}, and the keys of its Other bar.
        self._labels = {}
        self._other = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 0)

        # One row of filters, above everything they scope.
        ctrl = QHBoxLayout()
        self.current_cb = QCheckBox("Current deployments only")
        self.current_cb.setChecked(True)
        self.current_cb.setToolTip(
            "Count each channel's open epoch, else its latest one: today's "
            "fleet. Untick to count every epoch in the files."
        )
        ctrl.addWidget(self.current_cb)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # The active selection: one chip per role, each removable.
        self.chip_bar = QWidget()
        self._chips = QHBoxLayout(self.chip_bar)
        self._chips.setContentsMargins(0, 0, 0, 0)
        self.clear_btn = QPushButton("Clear filter")
        self.clear_btn.clicked.connect(self.clear_filter)
        self.chip_bar.setVisible(False)
        layout.addWidget(self.chip_bar)

        # The charts, side by side; pre-amplifiers only when stated.
        row = QHBoxLayout()
        self.charts, self._areas = {}, {}
        for role, _label in _ROLE_CHOICES:
            chart = InstrumentBarChart()
            chart.bar_toggled.connect(
                lambda keys, r=role: self._on_bar_toggled(r, keys))
            chart.cleared.connect(
                lambda r=role: self._set_role_selection(r, frozenset()))
            area = QScrollArea()
            area.setWidget(chart)
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.NoFrame)
            row.addWidget(area, 1)
            self.charts[role], self._areas[role] = chart, area
        self._areas["preamplifier"].setVisible(False)
        layout.addLayout(row, 1)

        self.current_cb.toggled.connect(self._on_current_toggled)

    # --- data -----------------------------------------------------------

    def set_data(self, loaded_files, nrl_index, issue_stations=None):
        """Show ``loaded_files``; ``issue_stations`` (Station ids) limits it
        to the stations the issues-only filter keeps.

        Rebuilt now if on screen, otherwise when next shown: the Manager
        calls this on every load, edit and refresh."""
        self._loaded_files = loaded_files
        self._nrl_index = nrl_index
        self._issue_stations = issue_stations
        self._dirty = True
        if self.isVisible():
            self._rebuild()

    def showEvent(self, event):
        super().showEvent(event)
        if self._dirty:
            self._rebuild()

    def refresh_theme(self):
        for chart in self.charts.values():
            chart.update()

    def current_only(self):
        return self.current_cb.isChecked()

    def selection(self):
        return dict(self._selection)

    def _deployments(self):
        deps = fleet.deployments(self._loaded_files, self._nrl_index,
                                 current_only=self.current_only())
        if self._issue_stations is not None:
            deps = [d for d in deps
                    if any(id(b) in self._issue_stations for b in d.blocks)]
        return deps

    def _rebuild(self):
        self._dirty = False
        deps = self._deployments()
        self._remember_labels(deps)
        self._areas["preamplifier"].setVisible(
            any("preamplifier" in d.entries for d in deps))
        for role, chart in self.charts.items():
            if not self._areas[role].isVisibleTo(self):
                continue
            # A chart is scoped by the other roles' selections, never its
            # own, so every one of its categories stays there to pick.
            bars = fleet.tally(fleet.selected(deps, self._selection, role),
                               role)
            self._other[role] = next(
                (b.keys for b in bars if b.key == fleet.OTHER_KEY),
                frozenset())
            chart.set_bars(bars, self._caption(role),
                           self._selection.get(role, frozenset()))
        self._update_chips()

    def _caption(self, role):
        when = "now" if self.current_only() else "all epochs"
        return f"Stations per {_ROLE_NAME[role].lower()} model · {when}"

    def _remember_labels(self, deps):
        counts = {}
        for dep in deps:
            for role, _label in _ROLE_CHOICES:
                key, label, _kind = fleet.category(dep.entries.get(role))
                counts.setdefault(role, {}).setdefault(
                    key, Counter())[label] += 1
        for role, per_key in counts.items():
            self._labels.setdefault(role, {}).update({
                key: c.most_common(1)[0][0] for key, c in per_key.items()})

    # --- selection ------------------------------------------------------

    def _on_bar_toggled(self, role, keys):
        # A click adds its bar to the role's selection, or removes it if
        # already in; Clear filter resets everything.
        current = self._selection.get(role, frozenset())
        new = current - keys if keys <= current else current | keys
        self._set_role_selection(role, new)

    def _set_role_selection(self, role, keys):
        if keys:
            self._selection[role] = frozenset(keys)
        else:
            self._selection.pop(role, None)
        self._rebuild()
        self._emit_filter()

    def clear_filter(self):
        self._selection = {}
        self._rebuild()
        self._emit_filter()

    def _on_current_toggled(self, _checked):
        self._rebuild()
        if self._selection:
            # The filter means "deployed now" or "ever": the Manager has
            # to recount.
            self._emit_filter()

    def _emit_filter(self):
        self.filter_changed.emit(dict(self._selection), self.current_only(),
                                 self.describe())

    def _describe_role(self, role):
        keys = self._selection.get(role, frozenset())
        if not keys:
            return ""
        if len(keys) > 1 and keys == self._other.get(role):
            return f"Other ({len(keys)} models)"
        labels = self._labels.get(role, {})
        names = sorted(labels.get(k, k.split(":", 1)[-1]) for k in keys)
        if len(names) == 1:
            return names[0]
        return f"{names[0]} +{len(names) - 1} more"

    def describe(self):
        """The selection as text, e.g. "Sensor: Streckeisen STS-2"."""
        return " · ".join(
            f"{_ROLE_NAME[role]}: {self._describe_role(role)}"
            for role, _label in _ROLE_CHOICES if self._selection.get(role))

    def _update_chips(self):
        while self._chips.count():
            widget = self._chips.takeAt(0).widget()
            if widget is not None and widget is not self.clear_btn:
                widget.deleteLater()
        for role, _label in _ROLE_CHOICES:
            if not self._selection.get(role):
                continue
            chip = QToolButton()
            chip.setText(f"{_ROLE_NAME[role]}: {self._describe_role(role)}"
                         "  ✕")
            chip.setToolTip("Remove this filter")
            chip.clicked.connect(
                lambda _checked=False, r=role:
                self._set_role_selection(r, frozenset()))
            self._chips.addWidget(chip)
        self._chips.addWidget(self.clear_btn)
        self._chips.addStretch()
        self.chip_bar.setVisible(bool(self._selection))
