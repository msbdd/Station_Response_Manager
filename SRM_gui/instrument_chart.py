"""Bar chart of how many stations use each instrument.

Painted directly: thin bars growing from one baseline with a rounded tip,
the count at each tip, a hover tooltip, and click / keyboard selection, a
click toggling its bar. It is one series, so every bar wears the one
series hue. A
selection is emphasis: selected bars keep the hue and the rest go grey,
and a check and bold label mark them too, so it never rests on color
alone. Bars for models nobody stated are grey from the start — missing
metadata, not an instrument.
"""
import html

from PyQt5.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt5.QtWidgets import QSizePolicy, QToolTip, QWidget

from SRM_core.fleet import DETECTED_KIND, OTHER_KIND, UNSTATED_KIND
from SRM_core.utils import is_dark_theme

# Reference-palette tokens as (light, dark), checked against the app's list
# surfaces (#ffffff / #1e1e1e): marks >= 3:1, text >= 4.5:1.
_SERIES = ("#2a78d6", "#3987e5")
_SERIES_HOVER = ("#3987e5", "#5598e7")
_MUTED = ("#898781", "#898781")
_TEXT_SECONDARY = ("#52514e", "#c3c2b7")
_BASELINE = ("#c3c2b7", "#383835")
_HOVER_WASH = ("#f0efec", "#2c2c2a")

_PAD = 8
_GAP = 8
_RADIUS = 4
_MAX_BAR = 20  # mark spec: bars never thicker than 24px


def _bar_path(x0, top, length, height):
    """A bar from the baseline ``x0``: square there, 4px round at the tip."""
    path = QPainterPath()
    r = min(_RADIUS, height / 2, length / 2)
    x1 = x0 + length
    path.moveTo(x0, top)
    path.lineTo(x1 - r, top)
    path.arcTo(QRectF(x1 - 2 * r, top, 2 * r, 2 * r), 90, -90)
    path.lineTo(x1, top + height - r)
    path.arcTo(QRectF(x1 - 2 * r, top + height - 2 * r, 2 * r, 2 * r),
               0, -90)
    path.lineTo(x0, top + height)
    path.closeSubpath()
    return path


def _plural(n, noun):
    return f"{n} {noun}{'' if n == 1 else 's'}"


class InstrumentBarChart(QWidget):
    # A clicked bar's category keys: toggled in or out of the selection.
    bar_toggled = pyqtSignal(object)
    cleared = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars = []
        self._caption = ""
        self._selected = frozenset()
        self._hover = None
        self._focus = 0
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_bars(self, bars, caption, selected_keys=frozenset()):
        self._bars = list(bars)
        self._caption = caption
        self._selected = frozenset(selected_keys)
        self._hover = None
        self._focus = min(self._focus, max(len(self._bars) - 1, 0))
        self._hold_height()
        self.update()

    def _hold_height(self):
        # Never squeezed below its bars: the scroll area around it scrolls
        # instead of clipping them.
        self.setMinimumHeight(self.sizeHint().height())
        self.updateGeometry()

    def bars(self):
        return list(self._bars)

    def is_selected(self, bar):
        return bool(self._selected) and bar.keys <= self._selected

    # --- geometry -------------------------------------------------------

    def _row_height(self):
        return max(24, self.fontMetrics().height() + 8)

    def _top(self):
        return _PAD + self.fontMetrics().height() + _PAD

    def sizeHint(self):
        rows = max(len(self._bars), 1)
        return QSize(420, self._top() + rows * self._row_height() + _PAD)

    def minimumSizeHint(self):
        return QSize(240, self._top() + 2 * self._row_height())

    def changeEvent(self, event):
        # Rows follow the font, which the View menu can resize.
        if event.type() == QEvent.FontChange:
            self._hold_height()
        super().changeEvent(event)

    def row_at(self, y):
        if y < self._top():
            return None
        i = int((y - self._top()) // self._row_height())
        return i if 0 <= i < len(self._bars) else None

    def _row_center(self, i):
        return QPoint(self.width() // 3, int(
            self._top() + (i + 0.5) * self._row_height()))

    # --- painting -------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = 1 if is_dark_theme() else 0
        pal = self.palette()
        p.fillRect(self.rect(), pal.color(pal.Base))
        fm = self.fontMetrics()
        primary = pal.color(pal.Text)
        secondary = QColor(_TEXT_SECONDARY[m])

        p.setPen(secondary)
        p.drawText(QRectF(_PAD, _PAD, self.width() - 2 * _PAD, fm.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, self._caption)
        if not self._bars:
            p.drawText(self.rect(), Qt.AlignCenter, "No channels to chart")
            return

        row_h = self._row_height()
        bar_h = min(_MAX_BAR, row_h - 8)
        bold = QFont(self.font())
        bold.setBold(True)
        # Names are what a reader scans for, so they may take most of a
        # narrow chart; a longer one is elided, whole in the tooltip.
        label_w = min(
            max(QFontMetrics(bold).horizontalAdvance("✓ " + b.label)
                for b in self._bars),
            int(self.width() * 0.55),
        )
        largest = max(b.stations for b in self._bars) or 1
        count_w = fm.horizontalAdvance(str(largest)) + _GAP
        x0 = _PAD + label_w + _GAP
        plot_w = max(self.width() - x0 - count_w - _PAD, 10)
        emphasis = bool(self._selected)

        for i, bar in enumerate(self._bars):
            y = self._top() + i * row_h
            if i == self._hover:
                p.fillRect(QRectF(0, y, self.width(), row_h),
                           QColor(_HOVER_WASH[m]))
            chosen = self.is_selected(bar)

            # Text wears text ink, never the bar's color.
            font = QFont(self.font())
            font.setBold(chosen)
            font.setItalic(bar.kind == DETECTED_KIND)
            p.setFont(font)
            p.setPen(secondary if bar.kind in (
                UNSTATED_KIND, OTHER_KIND, DETECTED_KIND) else primary)
            text = QFontMetrics(font).elidedText(
                ("✓ " if chosen else "") + bar.label, Qt.ElideRight,
                int(label_w))
            p.drawText(QRectF(_PAD, y, label_w, row_h),
                       Qt.AlignLeft | Qt.AlignVCenter, text)

            count = bar.stations
            length = max(plot_w * count / largest, 2.0) if count else 0.0
            if bar.kind == UNSTATED_KIND or (emphasis and not chosen):
                color = _MUTED[m]
            elif i == self._hover:
                color = _SERIES_HOVER[m]
            else:
                color = _SERIES[m]
            if length:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(color))
                p.drawPath(_bar_path(x0, y + (row_h - bar_h) / 2, length,
                                     bar_h))

            p.setFont(self.font())
            p.setPen(secondary)
            p.drawText(QRectF(x0 + length + _GAP / 2, y, count_w, row_h),
                       Qt.AlignLeft | Qt.AlignVCenter, str(count))

            if self.hasFocus() and i == self._focus:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(pal.color(pal.Highlight), 1))
                p.drawRoundedRect(QRectF(1.5, y + 1.5, self.width() - 3,
                                         row_h - 3), 3, 3)

        p.setPen(QPen(QColor(_BASELINE[m]), 1))
        p.drawLine(QPointF(x0, self._top()),
                   QPointF(x0, self._top() + len(self._bars) * row_h))

    # --- interaction ----------------------------------------------------

    def tooltip_for(self, bar):
        """Rich text: the value leads, the label follows."""
        lead = (f"{_plural(bar.stations, 'station')} · "
                f"{_plural(bar.channels, 'channel')}")
        lines = [f"<b>{lead}</b>", html.escape(bar.label)]
        if bar.kind == DETECTED_KIND:
            lines.append("Detected from the response (NRL), not stated.")
        elif bar.kind == UNSTATED_KIND:
            lines.append("No model stated, and none detected.")
        lines.append("Click to add to the Manager's filter, again to "
                     "remove it.")
        return "<br>".join(lines)

    def _set_hover(self, i):
        if i != self._hover:
            self._hover = i
            self.update()

    def mouseMoveEvent(self, event):
        i = self.row_at(event.pos().y())
        self._set_hover(i)
        if i is None:
            QToolTip.hideText()
        else:
            QToolTip.showText(event.globalPos(),
                              self.tooltip_for(self._bars[i]), self)

    def leaveEvent(self, event):
        self._set_hover(None)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        i = self.row_at(event.pos().y())
        if i is None:
            return
        self._focus = i
        self.bar_toggled.emit(self._bars[i].keys)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Up, Qt.Key_Down) and self._bars:
            step = 1 if key == Qt.Key_Down else -1
            self._focus = (self._focus + step) % len(self._bars)
            self.update()
            # Keyboard focus shows what hover shows.
            QToolTip.showText(self.mapToGlobal(self._row_center(self._focus)),
                              self.tooltip_for(self._bars[self._focus]), self)
        elif key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and self._bars:
            self.bar_toggled.emit(self._bars[self._focus].keys)
        elif key == Qt.Key_Escape:
            self.cleared.emit()
        else:
            super().keyPressEvent(event)
