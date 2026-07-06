"""Shared rendering of response metadata validation issues in tree views.

Both the Manager and Explorer trees show the same information: a summary
node per channel ("⚠ N metadata issues") with one display-only child row
per issue, colored by severity. Issue rows carry no edit role data, so the
Explorer's inline editing and deletion machinery ignores them.
"""
from PyQt5.QtWidgets import QTreeWidgetItem
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtCore import Qt

from SRM_core.utils import validate_response

# Amber for warnings, red for errors — distinct from the green sensor /
# blue digitizer detection annotations used in the manager view.
WARNING_COLOR = "#c77700"
ERROR_COLOR = "#b93a3a"

_SEVERITY_MARK = {"error": "✖", "warning": "⚠"}


def issue_color(severity):
    return ERROR_COLOR if severity == "error" else WARNING_COLOR


def tint_warning(item, color=WARNING_COLOR, column=0):
    item.setForeground(column, QBrush(QColor(color)))


def build_issue_items(channel, two_columns=False):
    """Build the validation summary node for ``channel``'s response.

    Returns a ``QTreeWidgetItem`` ("⚠ N metadata issues (M errors)") with
    one child row per issue, or ``None`` when the channel has no response
    or no issues. With ``two_columns`` the severity goes in column 0 and
    the message in column 1 (Explorer field/value layout); otherwise both
    are combined in column 0 (Manager layout).
    """
    if not channel.response:
        return None
    issues = validate_response(channel.response)
    if not issues:
        return None

    n = len(issues)
    n_err = sum(1 for sev, _ in issues if sev == "error")
    label = f"⚠ {n} metadata issue{'s' if n != 1 else ''}"
    if n_err:
        label += f" ({n_err} error{'s' if n_err != 1 else ''})"

    ncols = 2 if two_columns else 1
    summary = QTreeWidgetItem([label] + [""] * (ncols - 1))
    summary.setData(0, Qt.UserRole, ("validation", channel))
    tint_warning(summary, ERROR_COLOR if n_err else WARNING_COLOR)
    font = summary.font(0)
    font.setItalic(True)
    summary.setFont(0, font)
    summary.setFlags(Qt.ItemIsEnabled)
    summary.setToolTip(0, "Metadata validation:\n" + "\n".join(
        f"  • [{sev}] {msg}" for sev, msg in issues
    ))

    for sev, msg in issues:
        mark = _SEVERITY_MARK.get(sev, "•")
        if two_columns:
            item = QTreeWidgetItem([f"{mark} {sev}", msg])
        else:
            item = QTreeWidgetItem([f"{mark} [{sev}] {msg}"])
        item.setFlags(Qt.ItemIsEnabled)
        for col in range(ncols):
            tint_warning(item, issue_color(sev), col)
            item.setToolTip(col, msg)
        summary.addChild(item)

    return summary
