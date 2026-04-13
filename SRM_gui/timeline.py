from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QHBoxLayout,
    QLineEdit,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGraphicsLineItem,
    QToolTip,
)
from PyQt5.QtGui import QColor, QFont, QBrush, QPen, QTransform
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from SRM_core.utils import (
    utc_to_ts,
    ts_to_label,
    shift_color,
    BASE_COLORS,
    is_dark_theme,
)
from fnmatch import fnmatch
from datetime import datetime, timezone as _tz


def _match(pattern, full_id, has_wildcards):
    # Match a filter pattern against a SEED-style id (NET.STA.LOC.CHA)

    if has_wildcards:
        # Wrap in * if user didn't — so "HH?" matches anywhere in the id
        glob_pat = pattern if '*' in pattern else f"*{pattern}*"
        return fnmatch(full_id, glob_pat)
    return pattern in full_id


class _BarItem(QGraphicsRectItem):
    # A single bar in the timeline with tooltip

    def __init__(self, x, y, w, h, color, tooltip, parent=None):
        super().__init__(x, y, w, h, parent)
        qc = QColor(color)
        qc.setAlpha(220)
        self.setBrush(QBrush(qc))
        border = QColor("#333333") if is_dark_theme() else QColor("white")
        pen = QPen(border, 0.5)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setAcceptHoverEvents(True)
        self._tip = tooltip

    def hoverEnterEvent(self, event):
        QToolTip.showText(
            event.screenPos(), self._tip
        )

    def hoverLeaveEvent(self, event):
        QToolTip.hideText()


class TimelineView(QGraphicsView):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(self.NoFrame)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.AnchorUnderMouse
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._x_scale = 1.0
        self._y_scale = 1.0
        self._timeline_widget = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._timeline_widget:
            scene_pt = self.mapToScene(event.pos())
            row_idx = int(scene_pt.y() / self._timeline_widget.ROW_H)
            self._timeline_widget.activate_row(row_idx, scene_pt.x())
        else:
            super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        mods = event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)

        if ctrl and shift:
            # Ctrl+Shift+wheel → zoom X (time)
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else 1 / 1.15
            self._x_scale *= factor
            self._apply_transform(event.pos())
            self._notify_sync()
        elif ctrl:
            # Ctrl+wheel → change visible rows
            delta = event.angleDelta().y()
            if self._timeline_widget:
                step = max(1, abs(delta) // 120)
                if delta > 0:
                    step = -step  # scroll up → fewer rows
                self._timeline_widget.adjust_visible_rows(step)
        else:
            # Normal scroll
            super().wheelEvent(event)

    def _apply_transform(self, anchor=None):
        # Rebuild the transform from tracked x/y scales
        if anchor is not None:
            old_scene_pt = self.mapToScene(anchor)

        t = QTransform()
        t.scale(self._x_scale, self._y_scale)
        self.setTransform(t)

        if anchor is not None:
            new_vp_pt = self.mapFromScene(old_scene_pt)
            delta = new_vp_pt - anchor
            hs = self.horizontalScrollBar()
            vs = self.verticalScrollBar()
            hs.setValue(hs.value() + delta.x())
            vs.setValue(vs.value() + delta.y())

    def zoom_in(self):
        self._x_scale *= 1.25
        self._apply_transform()
        self._notify_sync()

    def zoom_out(self):
        self._x_scale /= 1.25
        self._apply_transform()
        self._notify_sync()

    def zoom_fit(self):
        if self._timeline_widget:
            self._timeline_widget.reset_view()

    def _notify_sync(self):
        if self._timeline_widget:
            self._timeline_widget.sync_axis()
            self._timeline_widget.sync_labels()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._notify_sync()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if (self._timeline_widget
                and self._timeline_widget._needs_initial_fit):
            self._timeline_widget._initial_fit()
        self._notify_sync()


class TimelineWidget(QWidget):

    ROW_H = 22
    LABEL_W = 140
    # Emitted on double-click: (filepath, net, sta, chan, loc, start_ts)
    item_activated = pyqtSignal(str, str, str, str, str, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(4, 2, 4, 0)
        self.btn_zin = QPushButton("T+")
        self.btn_zin.setToolTip("Zoom in on Time axis")
        self.btn_zout = QPushButton("T\u2013")
        self.btn_zout.setToolTip("Zoom out on Time axis")
        self.btn_rin = QPushButton("R+")
        self.btn_rin.setToolTip("Show more rows")
        self.btn_rout = QPushButton("R\u2013")
        self.btn_rout.setToolTip("Show fewer rows")
        self.btn_all = QPushButton("All")
        self.btn_all.setToolTip("Fit all rows and full time range")
        self.btn_rst = QPushButton("Rst")
        self.btn_rst.setToolTip("Reset to 10 rows, top-left, fit time")
        for b in (self.btn_zin, self.btn_zout,
                  self.btn_rin, self.btn_rout,
                  self.btn_all, self.btn_rst):
            b.setFixedWidth(36)
            b.setFixedHeight(22)
            ctrl.addWidget(b)
        ctrl.addSpacing(8)
        self.filter_bar = QLineEdit()
        self.filter_bar.setPlaceholderText(
            "Filter: station, channel, NET.STA.LOC.CHA, HH?, *BHZ..."
        )
        self.filter_bar.setClearButtonEnabled(True)
        self.filter_bar.textChanged.connect(self._apply_filter)
        ctrl.addWidget(self.filter_bar, 1)
        ctrl.addSpacing(4)
        layout.addLayout(ctrl)

        # --- middle row: frozen label view | main timeline view ---
        mid_layout = QHBoxLayout()
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(0)

        # Frozen label panel (left side)
        self.label_scene = QGraphicsScene(self)
        self.label_view = QGraphicsView(self)
        self.label_view.setScene(self.label_scene)
        self.label_view.setFixedWidth(self.LABEL_W)
        self.label_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.label_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.label_view.setInteractive(False)
        self.label_view.setFrameShape(self.label_view.NoFrame)
        self.label_view.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.label_view.setBackgroundBrush(
            QBrush(self.palette().color(self.palette().Base))
        )
        mid_layout.addWidget(self.label_view)

        # Main graphics view (bars / timeline)
        self.scene = QGraphicsScene(self)
        self.view = TimelineView(self)
        self.view.setScene(self.scene)
        self.view.setBackgroundBrush(
            QBrush(self.palette().color(self.palette().Base))
        )
        mid_layout.addWidget(self.view)
        layout.addLayout(mid_layout)

        # --- bottom row: spacer | fixed time-axis view ---
        bot_layout = QHBoxLayout()
        bot_layout.setContentsMargins(0, 0, 0, 0)
        bot_layout.setSpacing(0)

        self._axis_spacer = QWidget()
        self._axis_spacer.setFixedWidth(self.LABEL_W)
        self._axis_spacer.setFixedHeight(28)
        bot_layout.addWidget(self._axis_spacer)

        self.axis_scene = QGraphicsScene(self)
        self.axis_view = QGraphicsView(self)
        self.axis_view.setScene(self.axis_scene)
        self.axis_view.setFixedHeight(28)
        self.axis_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.axis_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.axis_view.setInteractive(False)
        self.axis_view.setFrameShape(self.axis_view.NoFrame)
        self.axis_view.setBackgroundBrush(
            QBrush(self.palette().color(self.palette().Base))
        )
        bot_layout.addWidget(self.axis_view)
        layout.addLayout(bot_layout)

        self.view._timeline_widget = self
        self._visible_rows = 10
        self._total_rows = 0
        self._needs_initial_fit = False
        self._grid_items = []

        self.btn_zin.clicked.connect(self.view.zoom_in)
        self.btn_zout.clicked.connect(self.view.zoom_out)
        self.btn_rin.clicked.connect(
            lambda: self.adjust_visible_rows(1)
        )
        self.btn_rout.clicked.connect(
            lambda: self.adjust_visible_rows(-1)
        )
        self.btn_all.clicked.connect(self.fit_all)
        self.btn_rst.clicked.connect(self.reset_view)

    def refresh_theme(self):
        base = self.palette().color(self.palette().Base)
        brush = QBrush(base)
        self.label_view.setBackgroundBrush(brush)
        self.view.setBackgroundBrush(brush)
        self.axis_view.setBackgroundBrush(brush)

    def sync_labels(self):
        if not self.view.scene() or not hasattr(self, '_rows'):
            return

        self.label_scene.clear()
        vp = self.view.viewport().rect()
        visible = self.view.mapToScene(vp).boundingRect()
        lw = self.LABEL_W
        rh = self.ROW_H
        label_vp_h = self.label_view.viewport().rect().height()

        self.label_scene.setSceneRect(0, 0, lw, label_vp_h)
        self.label_view.resetTransform()

        dark = is_dark_theme()
        pal = QApplication.instance().palette()
        text_color = pal.color(pal.Text)
        sep_color = QColor("#555555") if dark else QColor("#cccccc")

        app_pt = QApplication.instance().font().pointSize()
        label_font = QFont("Monospace", max(6, app_pt - 1))
        label_font_bold = QFont("Monospace", max(6, app_pt - 1), QFont.Bold)

        prev_group = None
        for yi, row in enumerate(self._rows):
            y_top = yi * rh
            y_bot = y_top + rh

            # Skip rows outside the visible vertical range
            if y_bot < visible.y() or y_top > visible.bottom():
                prev_group = row['group']
                continue

            # Map scene-y to viewport pixel-y
            pt_top = self.view.mapFromScene(0, y_top)
            py = pt_top.y()
            pt_bot = self.view.mapFromScene(0, y_bot)
            row_px_h = pt_bot.y() - py

            # Group separator
            if (
                prev_group is not None
                and row['group'] != prev_group
            ):
                sep = QGraphicsLineItem(0, py, lw, py)
                sep.setPen(QPen(sep_color, 0.5, Qt.DashLine))
                self.label_scene.addItem(sep)
            prev_group = row['group']

            # Label
            txt = QGraphicsSimpleTextItem(row['label'])
            txt.setBrush(QBrush(text_color))
            if row['kind'] == 'station':
                txt.setFont(label_font_bold)
            else:
                txt.setFont(label_font)
            txt.setPos(
                        2,
                        py + max(
                            1,
                            (row_px_h - txt.boundingRect().height()) / 2
                        )
                    )

            self.label_scene.addItem(txt)

    def sync_axis(self):
        if not hasattr(self, '_t_min') or not self.view.scene():
            return

        vp = self.view.viewport().rect()
        visible = self.view.mapToScene(vp).boundingRect()

        pps = self._pps
        t_min = self._t_min

        # Convert visible scene-x range to time range
        vis_t_start = t_min + max(0, visible.x()) / pps
        vis_t_end = t_min + max(0, visible.right()) / pps

        # Effective pixels-per-second in the viewport
        eff_pps = pps * self.view._x_scale
        # Minimum pixel gap between major ticks
        MIN_PX = 80

        # Candidate intervals (ascending), with minor sub,
        # label format
        candidates = [
            (60,              15,             "%H:%M:%S"),
            (300,             60,             "%H:%M"),
            (900,             300,            "%H:%M"),
            (3600,            900,            "%H:%M"),
            (6 * 3600,        3600,           "%Y-%m-%d %H:%M"),
            (86400,           6 * 3600,       "%Y-%m-%d"),
            (7 * 86400,       86400,          "%Y-%m-%d"),
            (30 * 86400,      7 * 86400,      "%Y-%m-%d"),
            (91 * 86400,      30 * 86400,     "%Y-%m"),
            (365 * 86400,     91 * 86400,     "%Y-%m"),
            (730 * 86400,     182 * 86400,    "%Y"),
            (1825 * 86400,    365 * 86400,    "%Y"),
            (3650 * 86400,    730 * 86400,    "%Y"),
        ]

        # Pick smallest interval whose pixel width >= MIN_PX
        interval, minor_iv, fmt = candidates[-1]
        for iv, miv, f in candidates:
            if iv * eff_pps >= MIN_PX:
                interval, minor_iv, fmt = iv, miv, f
                break

        # Ensure minor ticks also respect a min gap
        MIN_MINOR_PX = 15
        if minor_iv * eff_pps < MIN_MINOR_PX:
            minor_iv = interval  # disable minor ticks

        vp_w = vp.width()
        AXIS_H = 28

        self.axis_scene.clear()
        self.axis_scene.setSceneRect(0, 0, vp_w, AXIS_H)
        self.axis_view.resetTransform()

        dark = is_dark_theme()
        _gc = QColor("#444444") if dark else QColor("#e0e0e0")
        _tc = QColor("#aaaaaa") if dark else QColor("#666666")

        app_pt = QApplication.instance().font().pointSize()
        tick_font = QFont("Monospace", max(5, app_pt - 2))

        # Separator at top
        sep = QGraphicsLineItem(0, 0, vp_w, 0)
        sep.setPen(QPen(_gc, 1))
        self.axis_scene.addItem(sep)

        # --- Dynamic grid lines in main scene ---
        for item in self._grid_items:
            self.scene.removeItem(item)
        self._grid_items.clear()

        total_h = self.scene.sceneRect().height()
        pen_major_grid = QPen(_gc, 0.5, Qt.DotLine)
        pen_major_grid.setCosmetic(True)

        # Extend by one interval each side for scroll coverage
        g_start = vis_t_start - interval
        g_end = vis_t_end + interval

        # -- Minor ticks in axis panel only (no grid lines) --
        if minor_iv < interval:
            t = (int(g_start / minor_iv)) * minor_iv
            while t <= g_end:
                # Skip positions that coincide with major
                rem = t % interval
                if abs(rem) < 1 or abs(rem - interval) < 1:
                    t += minor_iv
                    continue
                sx = (t - t_min) * pps
                pt = self.view.mapFromScene(sx, 0)
                px = pt.x()
                if 0 <= px <= vp_w:
                    tk = QGraphicsLineItem(px, 0, px, 3)
                    tk.setPen(QPen(_tc, 0.5))
                    self.axis_scene.addItem(tk)
                t += minor_iv

        # -- Major ticks + labels (axis) + major grid (scene) --
        t = (int(g_start / interval)) * interval
        while t <= g_end:
            sx = (t - t_min) * pps
            # Major grid line in main scene
            gl = QGraphicsLineItem(sx, 0, sx, total_h)
            gl.setPen(pen_major_grid)
            gl.setZValue(2)
            self.scene.addItem(gl)
            self._grid_items.append(gl)
            # Major tick + label in axis panel
            pt = self.view.mapFromScene(sx, 0)
            px = pt.x()
            if 0 <= px <= vp_w:
                tick = QGraphicsLineItem(px, 0, px, 6)
                tick.setPen(QPen(_tc, 1))
                self.axis_scene.addItem(tick)

                label_str = datetime.fromtimestamp(
                    t, tz=_tz.utc
                ).strftime(fmt)
                lbl = QGraphicsSimpleTextItem(label_str)
                lbl.setFont(tick_font)
                lbl.setBrush(QBrush(_tc))
                lbl.setPos(px - 25, 6)
                self.axis_scene.addItem(lbl)
            t += interval

    def adjust_visible_rows(self, delta):
        # Change the number of visible rows by delta
        if self._total_rows == 0:
            return
        new_val = max(
            1, min(self._total_rows, self._visible_rows + delta)
        )
        if new_val == self._visible_rows:
            return
        self._visible_rows = new_val
        self._apply_y_from_visible_rows()

    def _apply_y_from_visible_rows(self):
        # Recompute Y scale from _visible_rows and apply
        vp_h = self.view.viewport().rect().height()
        if vp_h <= 0:
            return
        target_scene_h = self._visible_rows * self.ROW_H
        self.view._y_scale = vp_h / target_scene_h
        self.view._apply_transform()
        self.sync_labels()
        self.sync_axis()

    def _initial_fit(self):
        # Set initial view: X fits visible rows, Y shows N rows
        vp = self.view.viewport().rect()
        if vp.width() < 50 or vp.height() < 50:
            # Viewport not fully laid out; retry later
            if self._needs_initial_fit:
                QTimer.singleShot(100, self._initial_fit)
            return
        sr = self.view.scene().sceneRect()
        if sr.width() <= 0:
            return
        self._needs_initial_fit = False

        # Compute X range from the first _visible_rows rows
        vis_rows = self._rows[:self._visible_rows]
        vis_ts = []
        for r in vis_rows:
            for seg in r['segments']:
                vis_ts.extend([seg['start'], seg['end']])
        if vis_ts:
            vis_t_min = min(vis_ts)
            vis_t_max = max(vis_ts)
            vis_span = max(vis_t_max - vis_t_min, 86400)
            x_start = (vis_t_min - self._t_min) * self._pps
            x_width = vis_span * self._pps
            if x_width > 0:
                self.view._x_scale = vp.width() / x_width
            else:
                self.view._x_scale = vp.width() / sr.width()
        else:
            x_start = 0
            self.view._x_scale = vp.width() / sr.width()

        # Y: show _visible_rows
        target_scene_h = self._visible_rows * self.ROW_H
        self.view._y_scale = vp.height() / target_scene_h
        self.view._apply_transform()

        # Scroll: X to vis_t_min, Y to top
        hs = self.view.horizontalScrollBar()
        hs.setValue(int(x_start * self.view._x_scale))
        self.view.verticalScrollBar().setValue(
            self.view.verticalScrollBar().minimum()
        )

        # Defer sync so Qt processes the transform first
        QTimer.singleShot(0, self.sync_labels)
        QTimer.singleShot(0, self.sync_axis)

    def fit_all(self):
        # Fit all rows and full time range
        if self._total_rows == 0:
            return
        self._visible_rows = self._total_rows
        self._fit_visible()

    def _fit_visible(self):
        # Fit X to full scene, Y to _visible_rows
        vp = self.view.viewport().rect()
        if vp.width() < 50 or vp.height() < 50:
            return
        sr = self.view.scene().sceneRect()
        if sr.width() <= 0:
            return
        self.view._x_scale = vp.width() / sr.width()
        target_scene_h = self._visible_rows * self.ROW_H
        self.view._y_scale = vp.height() / target_scene_h
        self.view._apply_transform()
        self.view.horizontalScrollBar().setValue(
            self.view.horizontalScrollBar().minimum()
        )
        self.view.verticalScrollBar().setValue(
            self.view.verticalScrollBar().minimum()
        )
        QTimer.singleShot(0, self.sync_labels)
        QTimer.singleShot(0, self.sync_axis)

    def reset_view(self):
        # Reset to 10 visible rows, top-left, X fit to visible rows
        if self._total_rows == 0:
            return
        self._visible_rows = min(10, self._total_rows)
        self._needs_initial_fit = True
        self._initial_fit()

    def update_timeline(self, loaded_files):
        self.scene.clear()
        self._grid_items.clear()
        self.label_scene.clear()
        self.axis_scene.clear()
        groups = self.group_stations(loaded_files)
        if not groups:
            self._all_rows = []
            return

        rows = self.build_rows(groups)
        if not rows:
            self._all_rows = []
            return

        self._all_rows = rows
        self._show_rows(self._filter_rows(rows))

    def _show_rows(self, rows):
        self.scene.clear()
        self._grid_items.clear()
        self.label_scene.clear()
        self.axis_scene.clear()

        if not rows:
            self._rows = []
            self._total_rows = 0
            return

        all_ts = []
        for r in rows:
            for seg in r['segments']:
                all_ts.extend([seg['start'], seg['end']])
        t_min = min(all_ts)
        t_max = max(all_ts)
        span = max(t_max - t_min, 86400)  # at least 1 day

        self._t_min = t_min
        self._span = span
        self._rows = rows

        self.draw(rows, t_min, span)

        self._total_rows = len(rows)
        self._visible_rows = min(10, self._total_rows)
        self._needs_initial_fit = True
        QTimer.singleShot(50, self._initial_fit)

    def activate_row(self, row_idx, scene_x=0):
        if not hasattr(self, '_rows') or row_idx < 0:
            return
        if row_idx >= len(self._rows):
            return
        row = self._rows[row_idx]
        # full_id is "NET.STA" for stations, "NET.STA.LOC.CHA" for channels
        parts = row['full_id'].split('.')
        net_code = parts[0] if len(parts) >= 1 else ""
        sta_code = parts[1] if len(parts) >= 2 else ""
        loc_code = parts[2] if len(parts) >= 3 else ""
        chan_code = parts[3] if len(parts) >= 4 else ""

        # Determine which segment (epoch) was clicked via x position
        start_ts = 0.0
        pps = getattr(self, '_pps', 0)
        t_min = getattr(self, '_t_min', 0)
        if pps > 0 and row.get('segments'):
            click_t = t_min + scene_x / pps
            for seg in row['segments']:
                if seg['start'] <= click_t <= seg['end']:
                    start_ts = seg['start']
                    break
            else:
                # No exact hit — pick the nearest segment
                start_ts = min(
                    row['segments'],
                    key=lambda s: min(
                        abs(s['start'] - click_t),
                        abs(s['end'] - click_t),
                    ),
                )['start']

        self.item_activated.emit(
            row['filepath'], net_code, sta_code, chan_code,
            loc_code, start_ts,
        )

    def _apply_filter(self):
        if not hasattr(self, '_all_rows') or not self._all_rows:
            return
        self._show_rows(self._filter_rows(self._all_rows))

    def _filter_rows(self, rows):
        pattern = self.filter_bar.text().strip()
        if not pattern:
            return rows

        pat = pattern.upper()
        has_wildcards = any(c in pat for c in ('*', '?', '['))

        visible_groups = set()
        for row in rows:
            fid = row['full_id'].upper()
            if _match(pat, fid, has_wildcards):
                visible_groups.add(row['group'])

        return [r for r in rows if r['group'] in visible_groups]

    def group_stations(self, loaded_files):
        groups = {}
        for fp, inv in loaded_files.items():
            for net in inv.networks:
                for sta in net.stations:
                    key = f"{net.code}.{sta.code}"
                    groups.setdefault(key, []).append(
                        (sta, net.code, fp)
                    )
        return groups

    def build_rows(self, groups):
        rows = []
        color_idx = 0
        now_ts = datetime.now(tz=_tz.utc).timestamp()

        for sta_key in sorted(groups.keys()):
            entries = groups[sta_key]
            base = BASE_COLORS[
                color_idx % len(BASE_COLORS)
            ]
            color_idx += 1

            sta_segs = []
            prev_params = None
            seg_idx = 0
            # Use first entry's filepath for this group
            sta_filepath = entries[0][2]
            for sta, net_code, _fp in sorted(
                entries,
                key=lambda e: utc_to_ts(
                    e[0].creation_date
                ) or 0,
            ):
                s = utc_to_ts(sta.creation_date)
                e = utc_to_ts(sta.termination_date)
                if s is None:
                    starts = [
                        utc_to_ts(c.start_date)
                        for c in sta.channels
                        if utc_to_ts(c.start_date)
                    ]
                    s = min(starts) if starts else 946684800
                if e is None:
                    e = now_ts

                cur_params = (
                    round(sta.latitude, 5),
                    round(sta.longitude, 5),
                    round(sta.elevation, 2),
                    len(sta.channels),
                )
                if (
                    prev_params
                    and cur_params != prev_params
                ):
                    seg_idx += 1
                prev_params = cur_params

                color = shift_color(base, seg_idx)
                tip = (
                    f"Station: {sta_key}\n"
                    f"Lat: {sta.latitude}  "
                    f"Lon: {sta.longitude}\n"
                    f"Elev: {sta.elevation} m\n"
                    f"Channels: {len(sta.channels)}\n"
                    f"{ts_to_label(s)} \u2192 "
                    f"{ts_to_label(e)}"
                )
                sta_segs.append({
                    'start': s, 'end': e,
                    'color': color, 'tooltip': tip,
                })

            rows.append({
                'label': sta_key,
                'segments': sta_segs,
                'kind': 'station',
                'group': sta_key,
                'full_id': sta_key,
                'filepath': sta_filepath,
            })

            # --- channel-level rows ---
            chan_map = {}
            for sta, _nc, _fp in entries:
                for ch in sta.channels:
                    loc = ch.location_code or "--"
                    k = (loc, ch.code)
                    chan_map.setdefault(k, []).append(
                        (ch, sta)
                    )

            for (loc, code), epoch_list in sorted(
                chan_map.items()
            ):
                segs = []
                epoch_list.sort(
                    key=lambda x: utc_to_ts(
                        x[0].start_date
                    ) or 0
                )
                for ci, (ch, sta) in enumerate(
                    epoch_list
                ):
                    s = utc_to_ts(ch.start_date)
                    e = utc_to_ts(ch.end_date)
                    if s is None:
                        s = utc_to_ts(
                            sta.creation_date
                        ) or 946684800
                    if e is None:
                        e = now_ts
                    seg_c = shift_color(base, ci)
                    tip = (
                        f"{sta_key}.{loc}.{code}\n"
                        f"Lat: {ch.latitude}  "
                        f"Lon: {ch.longitude}\n"
                        f"Depth: {ch.depth} m  "
                        f"SR: {ch.sample_rate} Hz\n"
                        f"Az: {ch.azimuth}\u00b0  "
                        f"Dip: {ch.dip}\u00b0\n"
                        f"{ts_to_label(s)} \u2192 "
                        f"{ts_to_label(e)}"
                    )
                    if (
                        ch.response
                        and ch.response.instrument_sensitivity
                    ):
                        sens = (
                            ch.response.instrument_sensitivity
                        )
                        tip += (
                            f"\nSensitivity: {sens.value}"
                            f" {sens.input_units}"
                        )
                    segs.append({
                        'start': s, 'end': e,
                        'color': seg_c, 'tooltip': tip,
                    })
                rows.append({
                    'label': f"  {loc}.{code}",
                    'segments': segs,
                    'kind': 'channel',
                    'group': sta_key,
                    'full_id': f"{sta_key}.{loc}.{code}",
                    'filepath': sta_filepath,
                })
        return rows

    def draw(self, rows, t_min, span):
        rh = self.ROW_H
        px_per_sec = 800.0 / span
        self._pps = px_per_sec

        total_h = len(rows) * rh
        total_w = span * px_per_sec + 20

        self.scene.setSceneRect(
            0, 0, total_w, total_h
        )

        dark = is_dark_theme()
        sep_color = QColor("#555555") if dark else QColor("#cccccc")

        prev_group = None

        for yi, row in enumerate(rows):
            y_top = yi * rh

            if (
                prev_group is not None
                and row['group'] != prev_group
            ):
                # separator in main scene
                line = QGraphicsLineItem(
                    0, y_top, total_w, y_top
                )
                sep_pen = QPen(sep_color, 0.5, Qt.DashLine)
                sep_pen.setCosmetic(True)
                line.setPen(sep_pen)
                line.setZValue(2)
                self.scene.addItem(line)
            prev_group = row['group']

            # bars (in main scene, starting at x=0)
            for seg in row['segments']:
                x = (seg['start'] - t_min) * px_per_sec
                w = (seg['end'] - seg['start']) * px_per_sec
                w = max(w, 2)  # minimum visible px
                h = rh - 4 if row['kind'] == 'channel' \
                    else rh - 2
                y_bar = y_top + (rh - h) / 2

                bar = _BarItem(
                    x, y_bar, w, h,
                    seg['color'], seg['tooltip'],
                )
                self.scene.addItem(bar)
