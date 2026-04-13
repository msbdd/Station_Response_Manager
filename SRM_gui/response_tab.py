from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QMessageBox,
    QSplitter,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QComboBox,
    QInputDialog,
    QGroupBox,
    QRadioButton,
    QScrollArea,
    QHBoxLayout,
    QFormLayout,
    QFileDialog,
)
from copy import deepcopy
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtCore import Qt, QTimer
from SRM_core.utils import (
    combine_resp,
    wrap_text,
    natural_sort_key,
    validate_response,
)
import os
import copy
import configparser
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
)
from matplotlib.figure import Figure
import numpy as np
from obspy import read_inventory
from obspy.core.inventory.response import (
    ResponseStage,
    PolesZerosResponseStage,
    CoefficientsTypeResponseStage,
    ResponseListResponseStage,
    FIRResponseStage,
    PolynomialResponseStage,
    ResponseListElement,
)
from obspy.clients.nrl import NRL


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.ax_amp = self.fig.add_subplot(211)
        self.ax_phase = self.fig.add_subplot(212, sharex=self.ax_amp)
        self.fig.tight_layout()
        super().__init__(self.fig)
        self.apply_theme()

    def apply_theme(self):
        from SRM_core.utils import is_dark_theme
        dark = is_dark_theme()
        bg = "#1e1e1e" if dark else "#ffffff"
        fg = "#e0e0e0" if dark else "#000000"
        grid_c = "#444444" if dark else "#cccccc"
        self.fig.set_facecolor(bg)
        for ax in (self.ax_amp, self.ax_phase):
            ax.set_facecolor(bg)
            ax.tick_params(colors=fg, which="both")
            ax.xaxis.label.set_color(fg)
            ax.yaxis.label.set_color(fg)
            ax.title.set_color(fg)
            for spine in ax.spines.values():
                spine.set_edgecolor(fg)
            ax.grid(True, color=grid_c, alpha=0.5, linewidth=0.5)


class ResponseTab(QWidget):
    def __init__(self, response_data, main_window, explorer_tab, nrl_root):
        super().__init__()
        self.response = response_data
        self.original_response = deepcopy(response_data)
        self.main_window = main_window
        self.explorer_tab = explorer_tab
        self.nrl_root = nrl_root
        self.response_layout = QVBoxLayout(self)
        self.load_response_editor(self.response)

    def load_response_editor(self, response):
        self.selected_response = response

        for i in reversed(range(self.response_layout.count())):
            item = self.response_layout.itemAt(i)
            if item.widget():
                item.widget().setParent(None)

        splitter = QSplitter(Qt.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        if response.instrument_sensitivity:
            sens = response.instrument_sensitivity
            left_layout.addWidget(
                QLabel(
                    f"<b>Sensitivity:</b> {sens.value} @ {sens.frequency} Hz"
                )
            )

        self.stage_tree = QTreeWidget()
        self.stage_tree.setHeaderLabels(["Field", "Value"])
        self.stage_tree.setColumnWidth(0, 200)
        self.stage_tree.itemChanged.connect(self.handle_response_edit)
        self.stage_tree.itemDoubleClicked.connect(self.edit_complex_value)

        self.populate_stage_tree(response)
        left_layout.addWidget(self.stage_tree)
        btn_layout = QHBoxLayout()
        add_stage = QPushButton("New")
        add_stage.clicked.connect(self.new)
        btn_layout.addWidget(add_stage)

        delete_stage = QPushButton("Delete")
        delete_stage.clicked.connect(self.delete)
        btn_layout.addWidget(delete_stage)

        replace_button = QPushButton("Replace Response")
        replace_button.clicked.connect(self.replace_response)
        btn_layout.addWidget(replace_button)

        save_btn = QPushButton("Revert Response")
        save_btn.clicked.connect(self.revert_response)
        btn_layout.addWidget(save_btn)
        left_layout.addLayout(btn_layout)
        splitter.addWidget(left_widget)

        self.canvas = MplCanvas(self)
        splitter.addWidget(self.canvas)

        self.response_layout.addWidget(splitter)
        self.plot_response(response)

    def apply_theme(self):
        self.canvas.apply_theme()

    def plot_response(self, response):
        self.canvas.ax_amp.clear()
        self.canvas.ax_phase.clear()
        self.canvas.apply_theme()
        from SRM_core.utils import is_dark_theme
        dark = is_dark_theme()
        fg = "#e0e0e0" if dark else "#000000"
        try:
            freq = np.logspace(-2, 2, 1000)
            h = response.get_evalresp_response_for_frequencies(
                freq, output="DEF"
            )

            amp = np.abs(h)
            phase = np.angle(h, deg=True)

            self.canvas.ax_amp.plot(
                freq, amp, color="royalblue", label="Amplitude"
            )
            self.canvas.ax_amp.set_title("Amplitude Response")
            self.canvas.ax_amp.set_ylabel("Amplitude")
            self.canvas.ax_amp.set_xscale("log")
            self.canvas.ax_amp.set_yscale("log")
            self.canvas.ax_amp.legend(
                facecolor="none", edgecolor="none", labelcolor=fg
            )

            self.canvas.ax_phase.plot(
                freq, phase, color="seagreen", label="Phase"
            )
            self.canvas.ax_phase.set_title("Phase Response")
            self.canvas.ax_phase.set_xlabel("Frequency [Hz]")
            self.canvas.ax_phase.set_ylabel("Phase [°]")
            self.canvas.ax_phase.set_xscale("log")
            self.canvas.ax_phase.legend(
                facecolor="none", edgecolor="none", labelcolor=fg
            )

        except Exception as e:
            self.canvas.ax_amp.text(
                0.5, 0.5, f"Error plotting: {e}", ha="center", color=fg
            )
            self.canvas.ax_phase.text(
                0.5, 0.5, f"Error plotting: {e}", ha="center", color=fg
            )
        self.canvas.draw()

    def revert_response(self):
        self.response = deepcopy(self.original_response)
        self.load_response_editor(self.response)
        QMessageBox.information(
            self, "Reverted",
            "All changes in this tab have been reverted."
            )

    def populate_stage_tree(self, response):
        self.stage_tree.clear()
        nrl_index = self.main_window.nrl_index
        detection = nrl_index.detect_instrument(response)
        if detection.found_any:
            detect_item = QTreeWidgetItem(
                self.stage_tree, ["Detected Instrumentation", ""]
            )
            detect_item.setForeground(0, QBrush(QColor("#2e7d32")))
            font = detect_item.font(0)
            font.setBold(True)
            detect_item.setFont(0, font)
            detect_item.setExpanded(True)

            if detection.sensor:
                if detection.sensor_ambiguous:
                    n_cand = len(detection.sensor_candidates)
                    mfr = detection.sensor.manufacturer
                    model = detection.sensor.model
                    family = detection.sensor.family_name or f"{mfr} {model}"
                    sensor_text = f"{family} (+{n_cand - 1} similar)"
                else:
                    sensor_text = (
                        f"{detection.sensor.manufacturer} "
                        f"{detection.sensor.model}"
                    )
                sensor_item = QTreeWidgetItem(
                    detect_item, ["Sensor", sensor_text]
                )
                sensor_item.setForeground(0, QBrush(QColor("#2e7d32")))
                sensor_item.setForeground(1, QBrush(QColor("#2e7d32")))
                if detection.sensor_ambiguous:
                    tooltip = "Similar sensors (same response):\n"
                    for c in detection.sensor_candidates[:10]:
                        tooltip += f"  • {c.manufacturer} {c.model}"
                        if c.variant_params:
                            tooltip += f" ({c.variant_params})"
                        tooltip += "\n"
                    if len(detection.sensor_candidates) > 10:
                        remaining = len(detection.sensor_candidates) - 10
                        tooltip += f"  ... and {remaining} more"
                    sensor_item.setToolTip(0, tooltip)
                    sensor_item.setToolTip(1, tooltip)

            if detection.datalogger:
                if detection.datalogger_confidence >= 0.9:
                    dl_text = (
                        f"{detection.datalogger.manufacturer} "
                        f"{detection.datalogger.model}"
                    )
                elif detection.datalogger_ambiguous:
                    n_cand = len(detection.datalogger_candidates)
                    mfr = detection.datalogger.manufacturer
                    family = detection.datalogger.family_name or mfr
                    dl_text = f"{family} (+{n_cand - 1} similar)"
                else:
                    dl_text = (
                        f"{detection.datalogger.manufacturer} "
                        f"{detection.datalogger.model}"
                    )
                dl_item = QTreeWidgetItem(
                    detect_item, ["Digitizer", dl_text]
                )
                dl_item.setForeground(0, QBrush(QColor("#1565c0")))
                dl_item.setForeground(1, QBrush(QColor("#1565c0")))
                is_uncertain = (detection.datalogger_ambiguous and
                                detection.datalogger_confidence < 0.9)
                if is_uncertain:
                    conf = detection.datalogger_confidence
                    tooltip = f"Confidence: {conf:.0%}\n"
                    tooltip += "Similar digitizers (same digital chain):\n"
                    for c in detection.datalogger_candidates[:10]:
                        tooltip += f"  • {c.manufacturer} {c.model}"
                        if c.variant_params:
                            tooltip += f" ({c.variant_params})"
                        tooltip += "\n"
                    if len(detection.datalogger_candidates) > 10:
                        remaining = len(detection.datalogger_candidates) - 10
                        tooltip += f"  ... and {remaining} more"
                    dl_item.setToolTip(0, tooltip)
                    dl_item.setToolTip(1, tooltip)

        if response.instrument_sensitivity:
            sens = response.instrument_sensitivity
            sens_item = QTreeWidgetItem(
                self.stage_tree, ["Instrument Sensitivity", ""]
            )

            val_item = QTreeWidgetItem(sens_item, ["Value", str(sens.value)])
            val_item.setFlags(val_item.flags() | Qt.ItemIsEditable)
            val_item.setData(0, Qt.UserRole, (sens, "value"))

            freq_item = QTreeWidgetItem(
                sens_item, ["Frequency", str(sens.frequency)]
            )
            freq_item.setFlags(freq_item.flags() | Qt.ItemIsEditable)
            freq_item.setData(0, Qt.UserRole, (sens, "frequency"))

        for i, stage in enumerate(response.response_stages):
            stage_item = QTreeWidgetItem(
                self.stage_tree, [f"Stage {i+1}: {type(stage).__name__}", ""]
            )
            stage_item.setData(0, Qt.UserRole, ("stage", i))
            if hasattr(stage, "stage_gain"):
                item = QTreeWidgetItem(
                    stage_item, ["Stage Gain", str(stage.stage_gain)]
                )
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setData(0, Qt.UserRole, (stage, "stage_gain"))
            if hasattr(stage, "normalization_frequency"):
                item = QTreeWidgetItem(
                    stage_item,
                    [
                        "Normalization Freq",
                        str(stage.normalization_frequency),
                    ],
                )
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setData(
                    0, Qt.UserRole, (stage, "normalization_frequency")
                )

            if hasattr(stage, "poles"):
                poles_item = QTreeWidgetItem(stage_item, ["Poles", ""])
                for j, pole in enumerate(stage.poles):
                    pole_item = QTreeWidgetItem(
                        poles_item,
                        [f"Pole {j}", f"{pole.real} + {pole.imag}j"],
                    )

                    pole_item.setData(0, Qt.UserRole, ("pole", stage, j))

            if hasattr(stage, "zeros"):
                zeros_item = QTreeWidgetItem(stage_item, ["Zeros", ""])
                for j, zero in enumerate(stage.zeros):
                    zero_item = QTreeWidgetItem(
                        zeros_item,
                        [f"Zero {j}", f"{zero.real} + {zero.imag}j"],
                    )
                    zero_item.setData(0, Qt.UserRole, ("zero", stage, j))

        issues = validate_response(response)
        if issues:
            issues_item = QTreeWidgetItem(
                self.stage_tree, ["Validation Warnings", ""]
            )
            issues_item.setForeground(0, QBrush(QColor("#e65100")))
            font = issues_item.font(0)
            font.setBold(True)
            issues_item.setFont(0, font)
            issues_item.setExpanded(True)
            for severity, msg in issues:
                issue_child = QTreeWidgetItem(
                    issues_item,
                    [severity.upper(), msg],
                )
                color = "#c62828" if severity == "error" else "#e65100"
                issue_child.setForeground(0, QBrush(QColor(color)))
                issue_child.setForeground(1, QBrush(QColor(color)))

    def handle_response_edit(self, item, column):
        if column != 1:
            return

        ref = item.data(0, Qt.UserRole)
        if not ref or not isinstance(ref, tuple):
            return

        if len(ref) != 2:
            return

        ref_object, attr = ref
        new_text = item.text(1)
        old_value = getattr(ref_object, attr)

        try:
            if isinstance(old_value, float):
                new_value = float(new_text)
            elif isinstance(old_value, int):
                new_value = int(new_text)
            else:
                new_value = new_text

            setattr(ref_object, attr, new_value)

            item.setForeground(1, QBrush(QColor("blue")))
            font = item.font(1)
            font.setBold(True)
            item.setFont(1, font)

            self.plot_response(self.selected_response)

        except Exception as e:
            QMessageBox.warning(
                self, "Edit Error", f"Failed to update {attr}: {e}"
            )
            item.setText(1, str(old_value))

    def edit_complex_value(self, item, column):
        if column != 1:
            return

        ref = item.data(0, Qt.UserRole)
        if not ref or not isinstance(ref, tuple):
            return

        if len(ref) != 3:
            return

        ref_type, stage, index = ref
        if ref_type not in ("pole", "zero"):
            return

        value = (
            stage.poles[index] if ref_type == "pole" else stage.zeros[index]
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit {ref_type.title()} {index}")
        layout = QVBoxLayout(dialog)

        real_edit = QLineEdit(str(value.real))
        imag_edit = QLineEdit(str(value.imag))

        layout.addWidget(QLabel("Real:"))
        layout.addWidget(real_edit)
        layout.addWidget(QLabel("Imag:"))
        layout.addWidget(imag_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        layout.addWidget(buttons)

        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec_() == QDialog.Accepted:
            try:
                real = float(real_edit.text())
                imag = float(imag_edit.text())
                new_val = complex(real, imag)
                if ref_type == "pole":
                    stage.poles[index] = new_val
                else:
                    stage.zeros[index] = new_val

                item.setText(1, f"{new_val.real} + {new_val.imag}j")
                item.setForeground(1, QBrush(QColor("blue")))
                font = item.font(1)
                font.setBold(True)
                item.setFont(1, font)

                self.plot_response(self.selected_response)

            except ValueError:
                QMessageBox.warning(
                    self, "Invalid Input", "Please enter valid float numbers."
                )

    def select_response_from_inventory(self, inventory):
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Response to Import")
        layout = QVBoxLayout(dialog)

        combo = QComboBox()
        channel_map = {}

        for net in inventory.networks:
            for sta in net.stations:
                for chan in sta.channels:
                    label = (
                        f"{net.code}.{sta.code}."
                        f"{chan.location_code}.{chan.code}"
                    )
                    combo.addItem(label)
                    channel_map[label] = chan

        layout.addWidget(QLabel("Select Channel Response:"))
        layout.addWidget(combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        layout.addWidget(buttons)

        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec_() == QDialog.Accepted:
            selected = combo.currentText()
            chan_to_copy = channel_map[selected]

            if hasattr(self, "selected_response") and self.selected_response:
                new_response = chan_to_copy.response
                if new_response:
                    self.selected_response.response_stages = copy.deepcopy(
                        new_response.response_stages
                    )
                    self.selected_response.instrument_sensitivity = (
                        copy.deepcopy(new_response.instrument_sensitivity)
                    )

                    QMessageBox.information(
                        self, "Success", "Response replaced successfully."
                    )
                    self.load_response_editor(self.selected_response)
                    self.plot_response(self.selected_response)
                else:
                    QMessageBox.warning(
                        self,
                        "No Response",
                        "Selected channel has no response.",
                    )

    def replace_response(self):
        dlg = ResponseSelectionDialog(self.nrl_root, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        new_resp, _, _ = dlg.get_response()
        if (
            new_resp
            and hasattr(self, "selected_response")
            and self.selected_response
        ):
            self.selected_response.response_stages = copy.deepcopy(
                new_resp.response_stages
            )
            self.selected_response.instrument_sensitivity = copy.deepcopy(
                new_resp.instrument_sensitivity
            )

            self.load_response_editor(self.selected_response)
            self.plot_response(self.selected_response)
            QMessageBox.information(
                self, "Success", "Response updated."
            )

    def new(self):
        item = self.stage_tree.currentItem()
        if not item:
            QMessageBox.warning(
                self,
                "No Selection",
                "Select an item to add a new field under.",
            )
            return

        ref = item.data(0, Qt.UserRole)

        if isinstance(ref, tuple):
            ref_type = ref[0]

            if ref_type == "zero":
                stage = ref[1]
                stage.zeros.append(complex(0.0, 0.0))
                self.load_response_editor(self.selected_response)
                return

            elif ref_type == "pole":
                stage = ref[1]
                stage.poles.append(complex(0.0, 0.0))
                self.load_response_editor(self.selected_response)
                return

        #  New Stage
        is_stage_node = (
            item.text(0).startswith("Stage")
            or item == self.stage_tree.invisibleRootItem()
        )

        if is_stage_node:

            possible_stages = (
                "Response Stage",
                "Poles Zeros Response Stage",
                "Coefficients Type Response Stage",
                "Response List Response Stage",
                "FIR Response Stage",
                "Polynomial Response Stage",
            )
            stage_type, ok = QInputDialog.getItem(
                self,
                "Select Stage Type",
                "Stage type:",
                possible_stages,
                0,
                False,
            )
            if not ok:
                return

            stage_builders = {
                "Response Stage":
                    self._build_response_stage,
                "Poles Zeros Response Stage":
                    self._build_poles_zeros_stage,
                "Coefficients Type Response Stage":
                    self._build_coefficients_type_stage,
                "Response List Response Stage":
                    self._build_response_list_stage,
                "FIR Response Stage":
                    self._build_fir_stage,
                "Polynomial Response Stage":
                    self._build_polynomial_stage,
            }

            builder_func = stage_builders.get(stage_type)
            if not builder_func:
                return

            new_stage = builder_func()

            if new_stage:
                self.selected_response.response_stages.append(new_stage)
                self.load_response_editor(self.selected_response)
                return

        QMessageBox.warning(
            self,
            "Unsupported Selection",
            "You can't create a new item under this element.",
        )

    def _get_common_stage_parameters(self):
        stage_gain, ok1 = QInputDialog.getDouble(
            self, "Stage Gain", "Enter stage gain:", value=1.0
        )
        if not ok1:
            return None

        stage_gain_freq, ok2 = QInputDialog.getDouble(
            self,
            "Stage Gain Frequency",
            "Enter gain frequency (Hz):",
            value=1.0,
        )
        if not ok2:
            return None

        input_units, ok3 = QInputDialog.getText(
            self, "Input Units", "Enter input units:", text="M/S"
        )
        if not ok3:
            return None

        output_units, ok4 = QInputDialog.getText(
            self, "Output Units", "Enter output units:", text="V"
        )
        if not ok4:
            return None

        return {
            "stage_gain": stage_gain,
            "stage_gain_frequency": stage_gain_freq,
            "input_units": input_units,
            "output_units": output_units,
        }

    def _build_response_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        return ResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            **common_params,
        )

    def _build_poles_zeros_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        possible_tf_types = (
            "LAPLACE (RADIANS/SECOND)",
            "LAPLACE (HERTZ)",
            "DIGITAL (Z-TRANSFORM)",
        )
        pz_type, ok1 = QInputDialog.getItem(
            self,
            "Transfer Function Type",
            "Select type:",
            possible_tf_types,
            0,
            False,
        )
        if not ok1:
            return None

        norm_freq, ok2 = QInputDialog.getDouble(
            self,
            "Normalization Frequency",
            "Enter normalization frequency (Hz):",
            value=1.0,
        )
        if not ok2:
            return None

        return PolesZerosResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            normalization_frequency=norm_freq,
            pz_transfer_function_type=pz_type,
            zeros=[0.0 + 0.0j],
            poles=[0.0 + 0.0j],
            **common_params,
        )

    def _build_coefficients_type_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        possible_tf_types = ("DIGITAL", "ANALOG")
        cf_type, ok = QInputDialog.getItem(
            self,
            "Transfer Function Type",
            "Select type:",
            possible_tf_types,
            0,
            False,
        )
        if not ok:
            return None

        return CoefficientsTypeResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            cf_transfer_function_type=cf_type,
            numerator=[1.0],
            denominator=[],
            **common_params,
        )

    def _build_response_list_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        default_element = ResponseListElement(
            frequency=1.0, amplitude=1.0, phase=0.0
        )

        return ResponseListResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            response_list_elements=[default_element],
            **common_params,
        )

    def _build_fir_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        symmetry_options = ("NONE", "ODD", "EVEN")
        symmetry, ok = QInputDialog.getItem(
            self,
            "Symmetry",
            "Select FIR symmetry:",
            symmetry_options,
            0,
            False,
        )
        if not ok:
            return None

        return FIRResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            symmetry=symmetry,
            coefficients=[1.0],
            **common_params,
        )

    def _build_polynomial_stage(self):
        common_params = self._get_common_stage_parameters()
        if not common_params:
            return None

        approx_types = ("MACLAURIN", "CHEBYSHEV")
        approx_type, ok1 = QInputDialog.getItem(
            self, "Approximation Type", "Select type:", approx_types, 0, False
        )
        if not ok1:
            return None

        freq_lower, ok2 = QInputDialog.getDouble(
            self,
            "Frequency Lower Bound",
            "Enter frequency lower bound (Hz):",
            value=0.0,
        )
        if not ok2:
            return None

        freq_upper, ok3 = QInputDialog.getDouble(
            self,
            "Frequency Upper Bound",
            "Enter frequency upper bound (Hz):",
            value=100.0,
        )
        if not ok3:
            return None

        approx_lower, ok4 = QInputDialog.getDouble(
            self,
            "Approximation Lower Bound",
            "Enter approximation lower bound:",
            value=0.0,
        )
        if not ok4:
            return None

        approx_upper, ok5 = QInputDialog.getDouble(
            self,
            "Approximation Upper Bound",
            "Enter approximation upper bound:",
            value=1.0,
        )
        if not ok5:
            return None

        max_error, ok6 = QInputDialog.getDouble(
            self, "Maximum Error", "Enter maximum error:", value=0.0
        )
        if not ok6:
            return None

        return PolynomialResponseStage(
            stage_sequence_number=len(self.selected_response.response_stages)
            + 1,
            approximation_type=approx_type,
            frequency_lower_bound=freq_lower,
            frequency_upper_bound=freq_upper,
            approximation_lower_bound=approx_lower,
            approximation_upper_bound=approx_upper,
            maximum_error=max_error,
            coefficients=[1.0],
            **common_params,
        )

    def _renumber_stages(self):
        for i, stage in enumerate(
            self.selected_response.response_stages
        ):
            stage.stage_sequence_number = i + 1

    def delete(self):
        item = self.stage_tree.currentItem()
        if not item:
            QMessageBox.warning(
                self, "No Selection", "Select a field to delete."
            )
            return

        ref = item.data(0, Qt.UserRole)
        if not ref:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            "Are you sure you want to delete this field?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        if isinstance(ref, tuple):
            if len(ref) == 2 and ref[0] == "stage":
                stage_idx = ref[1]
                if 0 <= stage_idx < len(
                    self.selected_response.response_stages
                ):
                    del self.selected_response.response_stages[stage_idx]
                    self._renumber_stages()
                    self.load_response_editor(self.selected_response)
                    return

            elif len(ref) == 3:
                ref_type, stage, index = ref
                if ref_type == "pole":
                    del stage.poles[index]
                    self.load_response_editor(self.selected_response)
                    return
                elif ref_type == "zero":
                    del stage.zeros[index]
                    self.load_response_editor(self.selected_response)
                    return

            elif len(ref) == 2:
                ref_object, attr = ref
                try:
                    setattr(ref_object, attr, None)
                    self.load_response_editor(self.selected_response)
                    return
                except Exception as e:
                    QMessageBox.warning(
                        self, "Error", f"Could not delete attribute: {e}"
                    )
                    return


class ResponseSelectionDialog(QDialog):

    def __init__(self, nrl_root, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Instrument Response")
        self.setMinimumWidth(600)

        self.nrl = NRL(root=nrl_root)
        self.nrl_root = nrl_root

        self.sensor_response = None
        self.digitizer_response = None
        self.sensor_info = "Not selected"
        self.digitizer_info = "Not selected"
        self.final_resp = None

        self._init_ui()
        self._update_ui()

    def _init_ui(self):

        main_layout = QVBoxLayout(self)

        sensor_group = QGroupBox("Sensor Response")
        sensor_layout = QFormLayout()
        self.sensor_status_label = QLabel(self.sensor_info)
        sensor_buttons_layout = QHBoxLayout()
        sensor_file_btn = QPushButton("Load from File...")
        sensor_nrl_btn = QPushButton("Select from NRL...")
        sensor_buttons_layout.addWidget(sensor_file_btn)
        sensor_buttons_layout.addWidget(sensor_nrl_btn)
        sensor_layout.addRow(self.sensor_status_label)
        sensor_layout.addRow(sensor_buttons_layout)
        sensor_group.setLayout(sensor_layout)

        datalogger_group = QGroupBox("Datalogger (Digitizer) Response")
        datalogger_layout = QFormLayout()
        self.datalogger_status_label = QLabel(self.digitizer_info)
        datalogger_buttons_layout = QHBoxLayout()
        datalogger_file_btn = QPushButton("Load from File...")
        datalogger_nrl_btn = QPushButton("Select from NRL...")
        datalogger_buttons_layout.addWidget(datalogger_file_btn)
        datalogger_buttons_layout.addWidget(datalogger_nrl_btn)
        datalogger_layout.addRow(self.datalogger_status_label)
        datalogger_layout.addRow(datalogger_buttons_layout)
        datalogger_group.setLayout(datalogger_layout)

        main_layout.addWidget(sensor_group)
        main_layout.addWidget(datalogger_group)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        main_layout.addWidget(self.button_box)

        sensor_file_btn.clicked.connect(self.select_sensor_from_file)
        sensor_nrl_btn.clicked.connect(self.launch_sensor_wizard)
        datalogger_file_btn.clicked.connect(self.select_digitizer_from_file)
        datalogger_nrl_btn.clicked.connect(self.launch_digitizer_wizard)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def launch_sensor_wizard(self):
        wizard = NRLWizard(self.nrl_root, "sensor", self)
        if wizard.exec_() == QDialog.Accepted:
            keys, desc = wizard.get_result()
            if keys:
                try:
                    self.sensor_response = self.nrl.get_sensor_response(keys)
                    self.sensor_info = f"From NRL: {desc}"
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "NRL Error",
                        f"Failed to get sensor response:\n{e}",
                    )
                    self.sensor_response = None
            self._update_ui()

    def launch_digitizer_wizard(self):
        wizard = NRLWizard(self.nrl_root, "datalogger", self)
        if wizard.exec_() == QDialog.Accepted:
            keys, desc = wizard.get_result()
            if keys:
                try:
                    self.digitizer_response = self.nrl.get_datalogger_response(
                        keys
                    )
                    self.digitizer_info = f"From NRL: {desc}"
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "NRL Error",
                        f"Failed to get datalogger response:\n{e}",
                    )
                    self.digitizer_response = None
            self._update_ui()

    def select_sensor_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Sensor Response File",
            "",
            "StationXML (*.xml);;RESP (*.resp);;All Files (*)",
        )
        if path:
            try:
                inv = read_inventory(path)
                self.sensor_response = inv[0][0][0].response
                self.sensor_info = f"From file: {os.path.basename(path)}"
            except Exception as e:
                QMessageBox.warning(
                    self, "Error", f"Failed to read file:\n{e}"
                )
                self.sensor_response = None
            self._update_ui()

    def select_digitizer_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Digitizer Response File",
            "",
            "StationXML (*.xml);;RESP (*.resp);;All Files (*)",
        )
        if path:
            try:
                inv = read_inventory(path)
                self.digitizer_response = inv[0][0][0].response
                self.digitizer_info = f"From file: {os.path.basename(path)}"
            except Exception as e:
                QMessageBox.warning(
                    self, "Error", f"Failed to read file:\n{e}"
                )
                self.digitizer_response = None
            self._update_ui()

    def _update_ui(self):
        self.sensor_status_label.setText(wrap_text(self.sensor_info))
        self.datalogger_status_label.setText(wrap_text(self.digitizer_info))

        ok_button = self.button_box.button(QDialogButtonBox.Ok)
        ok_button.setEnabled(
            self.sensor_response is not None
            and self.digitizer_response is not None
        )

    def accept(self):
        try:
            final_response = combine_resp(
                self.sensor_response,
                self.digitizer_response,
            )
            issues = validate_response(final_response)
            if issues:
                msg = "The combined response has validation issues:\n\n"
                for severity, text in issues:
                    msg += f"  [{severity.upper()}] {text}\n"
                msg += "\nAccept anyway?"
                reply = QMessageBox.warning(
                    self,
                    "Response Validation",
                    msg,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply != QMessageBox.Yes:
                    return
            self.final_resp = final_response
            super().accept()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Response Combination Error",
                f"Could not combine responses:\n{e}",
            )
            self.final_resp = None

    def get_response(self):
        return self.final_resp, self.sensor_info, self.digitizer_info


class NRLWizard(QDialog):

    def __init__(self, nrl_root, stage, parent=None):

        super().__init__(parent)
        self.setWindowTitle(f"NRL {stage.capitalize()} Wizard")
        self.setMinimumWidth(500)
        self.setModal(True)

        self.nrl_root = nrl_root
        self.stage = stage

        initial_dir = os.path.normpath(os.path.join(self.nrl_root, self.stage))
        self.path_stack = [(initial_dir, None)]

        self.selected_keys = []
        self.selected_option = None
        self._final_xml_config = None
        self.final_description = ""

        self.auto_step_timer = QTimer(self)
        self.auto_step_timer.setSingleShot(True)
        self.auto_step_timer.timeout.connect(self.next_step)

        self.back_bool_flag = False
        self._init_ui()
        self.load_step()

    def _init_ui(self):
        self.layout = QVBoxLayout(self)
        self.question_label = QLabel("Loading...")
        self.layout.addWidget(self.question_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.back_btn = QPushButton("Back")
        self.next_btn = QPushButton("Next")
        self.cancel_btn = QPushButton("Cancel")
        button_layout.addWidget(self.back_btn)
        button_layout.addWidget(self.next_btn)
        button_layout.addWidget(self.cancel_btn)
        self.layout.addLayout(button_layout)

        self.back_btn.clicked.connect(self.go_back)
        self.next_btn.clicked.connect(self.next_step)
        self.cancel_btn.clicked.connect(self.reject)

        self.option_buttons = {}

    def load_step(self):

        if self.auto_step_timer.isActive():
            self.auto_step_timer.stop()

        self.clear_layout(self.scroll_layout)
        self.selected_option = None
        self._final_xml_config = None
        self.next_btn.setText("Next")

        current_dir, txt_file = self.path_stack[-1]
        config_filename = txt_file if txt_file else "index.txt"
        config_path = os.path.join(current_dir, config_filename)

        if not os.path.isfile(config_path):
            QMessageBox.warning(
                self, "Error", f"Missing configuration file:\n{config_path}"
            )
            self.go_back()
            return

        config = self._read_config(config_path)
        if not config:
            QMessageBox.critical(
                self,
                "Read Error",
                f"Could not read or parse the config file:\n{config_path}",
            )
            self.go_back()
            return

        self.question_label.setText(
            config.get("Main", "question", fallback="Make a selection")
        )

        self.option_buttons = {}
        base_dir = current_dir

        sections = sorted(
            [s for s in config.sections() if s != "Main"], key=natural_sort_key
        )
        for section in sections:
            raw_path = (
                config.get(section, "path", fallback="").strip().strip('"')
            )
            btn = QRadioButton(wrap_text(section))
            btn.toggled.connect(
                lambda checked, s=section: self.set_selection(s)
            )
            self.scroll_layout.addWidget(btn)

            resolved_path = os.path.normpath(os.path.join(base_dir, raw_path))
            self.option_buttons[section] = (btn, resolved_path)
        if not self.back_bool_flag:
            if len(self.option_buttons) == 1:
                only_section = next(iter(self.option_buttons))
                self.option_buttons[only_section][0].setChecked(True)
                self.auto_step_timer.start(100)

        self.back_btn.setEnabled(len(self.path_stack) > 1)

    def load_final_xml_choices(self, config):

        self._final_xml_config = config
        self.selected_option = None
        self.clear_layout(self.scroll_layout)
        self.next_btn.setText("Finish")

        question = config.get(
            "Main", "question", fallback="Select configuration"
        )
        self.question_label.setText(question)

        self.option_buttons = {}
        for section in sorted(
            [s for s in config.sections() if s != "Main"], key=natural_sort_key
                ):
            desc = (
                config.get(section, "description", fallback="")
                .strip()
                .strip('"')
            )
            xml = config.get(section, "xml", fallback="").strip().strip('"')

            label = f"{section}: {desc}"
            btn = QRadioButton(wrap_text(label))
            btn.toggled.connect(
                lambda checked, s=section: self.set_selection(s)
            )
            self.scroll_layout.addWidget(btn)
            self.option_buttons[section] = (btn, xml)

    def next_step(self):

        self.back_bool_flag = False
        if not self.selected_option:
            QMessageBox.warning(
                self, "Selection Required", "Please select an option."
            )
            return

        if self._final_xml_config:
            self.selected_keys.append(self.selected_option)
            self.final_description = self.option_buttons[self.selected_option][
                0
            ].text()
            self.accept()
            return

        _, next_path = self.option_buttons[self.selected_option]

        if os.path.isdir(next_path):
            self.selected_keys.append(self.selected_option)
            self.path_stack.append((next_path, None))
            self.load_step()
        elif os.path.isfile(next_path) and next_path.endswith(".txt"):
            config = self._read_config(next_path)
            if "Main" in config:
                sections = [s for s in config.sections() if s != "Main"]

                is_final = all(config.has_option(s, "xml") for s in sections)
                is_intermediate = all(
                    config.has_option(s, "path") for s in sections
                )

                self.selected_keys.append(self.selected_option)
                self.path_stack.append(
                    (os.path.dirname(next_path), os.path.basename(next_path))
                )

                if is_final:
                    self.load_final_xml_choices(config)
                elif is_intermediate:
                    self.load_step()
                else:
                    QMessageBox.warning(
                        self,
                        "NRL Error",
                        f"Invalid config file format:\n{next_path}",
                    )
                    self.go_back()
            else:
                QMessageBox.warning(
                    self,
                    "NRL Error",
                    f"Invalid config file format:\n{next_path}",
                )
                self.go_back()
        else:
            QMessageBox.warning(
                self,
                "NRL Error",
                f"Unrecognized or invalid path:\n{next_path}",
            )

    def go_back(self):
        self.back_bool_flag = True
        if len(self.path_stack) > 1:
            self.path_stack.pop()
            if self.selected_keys:
                self.selected_keys.pop()
            self.load_step()

    def set_selection(self, section):

        if (
            section in self.option_buttons
            and self.option_buttons[section][0].isChecked()
        ):
            self.selected_option = section

    def get_result(self):

        if self.result() == QDialog.Accepted:
            return self.selected_keys, self.final_description
        return None, None

    def _read_config(self, path):

        config = configparser.ConfigParser()
        config.optionxform = str
        try:
            config.read(path, encoding="utf-8-sig")
            return config
        except Exception:
            return None

    def clear_layout(self, layout):

        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
