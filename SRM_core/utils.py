# core/parser.py
from copy import deepcopy
from obspy import read_inventory
import os
import sys
import re
import colorsys
from datetime import datetime, timezone as _tz


def parse_response(path):
    try:
        return read_inventory(path)
    except Exception as e:
        return e


def combine_resp(sensor_resp, recorder_resp):
    result = deepcopy(recorder_resp)
    sensor_stage0 = deepcopy(sensor_resp.response_stages[0])
    result.response_stages.pop(0)
    result.response_stages.insert(0, sensor_stage0)
    result.instrument_sensitivity.input_units = \
        sensor_stage0.input_units
    result.instrument_sensitivity.input_units_description = \
        sensor_stage0.input_units_description
    try:
        result.recalculate_overall_sensitivity()
    except ValueError:
        pass
    return result


def wrap_text(text, max_len=75):
    lines = []
    while len(text) > max_len:
        semi_idx = text.rfind(";", 0, max_len)
        space_idx = text.rfind(" ", 0, max_len)
        break_idx = -1

        if semi_idx != -1:
            break_idx = semi_idx + 1
        elif space_idx != -1:
            break_idx = space_idx
        else:
            break_idx = max_len

        lines.append(text[:break_idx].strip())
        text = text[break_idx:].strip()

    lines.append(text)
    return "\n".join(lines)


def resource_path(relative_path):

    if getattr(sys, '_MEIPASS', None):
        base_path = sys._MEIPASS
    elif getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def convert_inventory_to_xml(input_path: str, output_path: str):
    try:
        inventory = read_inventory(input_path)
        inventory.write(output_path, format="STATIONXML")

        success_message = (
            f"Successfully converted and saved file to:\n{output_path}"
        )
        return True, success_message

    except Exception as e:
        error_message = f"An error occurred during conversion.\n\nDetails: {e}"
        return False, error_message


def validate_response(response):

    issues = []

    if not response:
        issues.append(("error", "Response object is None."))
        return issues

    stages = response.response_stages
    if not stages:
        issues.append(("warning", "Response has no stages."))
        return issues

    # Check stage sequence numbers are consecutive starting from 1
    for i, stage in enumerate(stages):
        expected = i + 1
        actual = getattr(stage, 'stage_sequence_number', None)
        if actual is not None and actual != expected:
            issues.append((
                "warning",
                f"Stage {i+1} has sequence number {actual} "
                f"(expected {expected})."
            ))

    # Check unit chain continuity between stages
    for i in range(len(stages) - 1):
        out_units = getattr(stages[i], 'output_units', None)
        in_units = getattr(stages[i + 1], 'input_units', None)
        if out_units and in_units and out_units != in_units:
            issues.append((
                "warning",
                f"Unit mismatch: stage {i+1} outputs '{out_units}' "
                f"but stage {i+2} expects '{in_units}'."
            ))

    # Check sensitivity exists and units match first/last stage
    sens = response.instrument_sensitivity
    if not sens:
        issues.append((
            "warning",
            "Response has no instrument sensitivity defined."
        ))
    else:
        if sens.value is None or sens.value == 0:
            issues.append((
                "warning",
                "Instrument sensitivity value is zero or None."
            ))
        first_in = getattr(stages[0], 'input_units', None)
        if first_in and sens.input_units and first_in != sens.input_units:
            issues.append((
                "warning",
                f"Sensitivity input units '{sens.input_units}' "
                f"don't match first stage input '{first_in}'."
            ))
        last_out = getattr(stages[-1], 'output_units', None)
        if last_out and sens.output_units and last_out != sens.output_units:
            issues.append((
                "warning",
                f"Sensitivity output units '{sens.output_units}' "
                f"don't match last stage output '{last_out}'."
            ))

    # Check for stages with zero gain
    for i, stage in enumerate(stages):
        gain = getattr(stage, 'stage_gain', None)
        if gain is not None and gain == 0:
            issues.append((
                "warning",
                f"Stage {i+1} has zero gain."
            ))

    return issues


def natural_sort_key(s: str):
    return [
        (0, int(chunk)) if chunk.isdigit() else (1, chunk.lower())
        for chunk in re.split(r"(\d+)", s)
    ]


def utc_to_ts(utc):
    if utc is None:
        return None
    try:
        return utc.datetime.replace(tzinfo=_tz.utc).timestamp()
    except Exception:
        return None


def ts_to_label(ts):
    return datetime.fromtimestamp(
        ts, tz=_tz.utc
    ).strftime("%Y-%m-%d")


def shift_color(base_hex, index):
    if index == 0:
        return base_hex
    r = int(base_hex[1:3], 16)
    g = int(base_hex[3:5], 16)
    b = int(base_hex[5:7], 16)
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    h = (h + 0.10 * index) % 1.0
    s = max(0.25, s - 0.08 * index)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return "#{:02x}{:02x}{:02x}".format(
        int(r2 * 255), int(g2 * 255), int(b2 * 255)
    )


BASE_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
    "#9c755f", "#bab0ac",
]


def is_dark_theme():
    from PyQt5.QtWidgets import QApplication
    pal = QApplication.instance().palette()
    bg = pal.color(pal.Window)
    # luminance: dark if < 128
    return (bg.red() * 0.299 + bg.green() * 0.587 + bg.blue() * 0.114) < 128
