# core/parser.py
from obspy import read_inventory
import os
import sys
import re


def parse_response(path):
    try:
        return read_inventory(path)
    except Exception as e:
        return e


def combine_resp(sensor_resp, recorder_resp):
    recorder_resp.response_stages.pop(0)
    sensor_stage0 = sensor_resp.response_stages[0]
    recorder_resp.response_stages.insert(0, sensor_stage0)
    recorder_resp.instrument_sensitivity.input_units = \
        sensor_stage0.input_units
    recorder_resp.instrument_sensitivity.input_units_description = \
        sensor_stage0.input_units_description
    try:
        recorder_resp.recalculate_overall_sensitivity()
    except ValueError:
        msg = "Failed to recalculate overall sensitivity."
        print(msg)
    return recorder_resp


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

    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
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


def natural_sort_key(s: str):
    return [
        (0, int(chunk)) if chunk.isdigit() else (1, chunk.lower())
        for chunk in re.split(r"(\d+)", s)
    ]
