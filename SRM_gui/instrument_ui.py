"""Shared rendering of a channel's instruments in tree views.

The Manager tree and the Response tab show the same entries, built by
SRM_core.instrumentation: what the StationXML states, else what the NRL
index detects from the response. Detected rows are italic and say so;
stated rows are upright. The rows carry no edit role data, so the
editors' inline editing and deletion machinery ignore them.
"""
from PyQt5.QtWidgets import QTreeWidgetItem
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtCore import Qt

from SRM_core.instrumentation import (
    DETECTED,
    NOT_STATED,
    STATED,
    UNNAMED,
    candidates_tooltip,
    equipment_fields,
    resolve_instruments,
)

SENSOR_COLOR = "#2e7d32"
DIGITIZER_COLOR = "#1565c0"
# Placeholder serials and elements that name no model: visibly incomplete.
MUTED_COLOR = "#8a8a8a"

_ROLE_COLOR = {
    "sensor": SENSOR_COLOR,
    "datalogger": DIGITIZER_COLOR,
    "preamplifier": DIGITIZER_COLOR,
}
# Manager rows read "sensor: …" / "digitizer: …", as they always have.
_ROLE_WORD = {
    "sensor": "sensor", "datalogger": "digitizer",
    "preamplifier": "preamp",
}
ROLE_LABEL = {
    "sensor": "Sensor", "datalogger": "Digitizer",
    "preamplifier": "Pre-amplifier",
}
_ELEMENT = {
    "sensor": "<Sensor>", "datalogger": "<DataLogger>",
    "preamplifier": "<PreAmplifier>",
}


def serial_text(entry):
    """The serial number as displayed, with a placeholder marked."""
    if not entry.serial:
        return ""
    if entry.serial_placeholder:
        return f"{entry.serial} (placeholder)"
    return entry.serial


def entry_tooltip(entry):
    element = _ELEMENT[entry.role]
    lines = []
    if entry.source == STATED:
        lines.append(f"Stated in the StationXML {element}:")
        lines += [f"  {label}: {text}"
                  for label, text in equipment_fields(entry.equipment)]
        if entry.nrl_match:
            lines.append("")
            lines.append(f"NRL match for this response: {entry.nrl_match}")
        return "\n".join(lines)

    if entry.source == DETECTED:
        lines.append("Detected from the response (NRL); not stated in the "
                     "file.")
    fields = equipment_fields(entry.equipment)
    if fields:
        lines.append(f"The StationXML {element} names no model, only:")
        lines += [f"  {label}: {text}" for label, text in fields]
    if entry.source == UNNAMED:
        lines.append("No instrument was detected from the response either.")
    if entry.source == DETECTED:
        candidates = candidates_tooltip(entry.role, entry.detection)
        if candidates:
            lines.append("")
            lines.append(candidates.rstrip("\n"))
    return "\n".join(lines)


def _style(item, entry, columns):
    color = MUTED_COLOR if entry.source == UNNAMED else _ROLE_COLOR[
        entry.role]
    for col in columns:
        item.setForeground(col, QBrush(QColor(color)))
        if entry.source == DETECTED:
            font = item.font(col)
            font.setItalic(True)
            item.setFont(col, font)


def instrument_rows(nrl_index, response, channel=None):
    """One-column rows for the Manager tree, one per known instrument.

    A placeholder serial is left out of the row text (it would read as a
    real one at a glance) and shown, marked, in the tooltip."""
    rows = []
    for entry in resolve_instruments(nrl_index, response, channel):
        word = _ROLE_WORD[entry.role]
        if entry.source == DETECTED:
            text = f"{word} (detected): {entry.name}"
        else:
            text = f"{word}: {entry.name or NOT_STATED}"
        if entry.serial and not entry.serial_placeholder:
            text += f" · S/N {entry.serial}"
        item = QTreeWidgetItem([text])
        item.setData(0, Qt.UserRole, ("instrument", entry))
        _style(item, entry, (0,))
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        item.setToolTip(0, entry_tooltip(entry))
        rows.append(item)
    return rows


def instrument_group(nrl_index, response, channel=None):
    """The Response tab's two-column "Instrumentation" group, or None when
    no instrument is known. Add it to the tree, then call
    ``expand_group``: Qt ignores expansion of an item not yet in a view."""
    entries = resolve_instruments(nrl_index, response, channel)
    if not entries:
        return None
    group = QTreeWidgetItem(["Instrumentation", ""])
    group.setForeground(0, QBrush(QColor(SENSOR_COLOR)))
    font = group.font(0)
    font.setBold(True)
    group.setFont(0, font)

    for entry in entries:
        value = entry.name or NOT_STATED
        if entry.source == DETECTED:
            value += " (detected)"
        row = QTreeWidgetItem(group, [ROLE_LABEL[entry.role], value])
        _style(row, entry, (0, 1))
        tooltip = entry_tooltip(entry)
        row.setToolTip(0, tooltip)
        row.setToolTip(1, tooltip)

        if entry.serial:
            sn = QTreeWidgetItem(row, ["Serial number", serial_text(entry)])
            if entry.serial_placeholder:
                for col in (0, 1):
                    sn.setForeground(col, QBrush(QColor(MUTED_COLOR)))
                    sn.setToolTip(col, "A placeholder, not a real serial "
                                       "number (SeisComP writes xxxx/yyyy "
                                       "for unknown ones).")
        if entry.nrl_match:
            match = QTreeWidgetItem(
                row, ["NRL match", f"{entry.nrl_match} (detected)"]
            )
            for col in (0, 1):
                match.setForeground(
                    col, QBrush(QColor(_ROLE_COLOR[entry.role])))
                font = match.font(col)
                font.setItalic(True)
                match.setFont(col, font)
                match.setToolTip(
                    col,
                    candidates_tooltip(entry.role, entry.detection)
                    or "What the response matches in the NRL; shown for "
                       "comparison only.",
                )
    return group


def expand_group(group):
    group.setExpanded(True)
    for i in range(group.childCount()):
        group.child(i).setExpanded(True)
