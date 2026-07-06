# core/parser.py
from copy import copy, deepcopy
from obspy import read_inventory
from obspy import Inventory
import difflib
import io
import os
import sys
import re
import tempfile
import colorsys
from datetime import datetime, timezone as _tz


_VOLT_UNITS = ('V', 'VOLT', 'VOLTS')


def _norm_unit(units):
    return str(units or '').strip().upper()


def combine_resp(sensor_resp, recorder_resp):
    """Combine a sensor-only and a datalogger-only response into one chain.

    Both NRL conventions are handled, detected from the stages themselves:

    - NRLv1 files carry unity-gain placeholder stages marking where the
      other instrument plugs in: datalogger files start with a sensor
      placeholder (ground-motion input, e.g. ``M/S -> V``) and sensor files
      end with a digitizer placeholder (``V -> COUNTS``). Placeholders are
      dropped and replaced by the real stages.
    - NRLv2 files have no placeholders: the datalogger's first stage is a
      real stage (typically a gain-only preamp with volts or blank input)
      and every stage is kept — dropping it would silently corrupt the
      overall sensitivity.
      A blank first-stage input unit is filled from the sensor output so
      the unit chain stays continuous.
    """
    result = deepcopy(recorder_resp)
    sensor_stages = [deepcopy(s) for s in sensor_resp.response_stages]

    # NRLv1 sensor files end with a unity V->COUNTS digitizer placeholder;
    # a real sensor never outputs counts.
    while sensor_stages and \
            'COUNT' in _norm_unit(sensor_stages[-1].output_units):
        sensor_stages.pop()
    if not sensor_stages:
        raise ValueError("Sensor response has no usable analog stages.")

    dl_stages = result.response_stages
    if dl_stages:
        in_u = _norm_unit(dl_stages[0].input_units)
        out_u = _norm_unit(dl_stages[0].output_units)
        # A first stage that converts a non-volt physical unit to volts can
        # only be an NRLv1 sensor placeholder — a real datalogger stage
        # never sees ground motion. Volts or blank input means a real NRLv2
        # stage and is kept.
        if out_u in _VOLT_UNITS and in_u and in_u not in _VOLT_UNITS:
            dl_stages.pop(0)

    # Gain-only NRLv2 preamps often have blank input units; fill from the
    # sensor output so the unit chain stays continuous.
    if dl_stages and not _norm_unit(dl_stages[0].input_units):
        last_sensor = sensor_stages[-1]
        dl_stages[0].input_units = last_sensor.output_units
        dl_stages[0].input_units_description = \
            last_sensor.output_units_description

    result.response_stages = sensor_stages + dl_stages
    for i, stage in enumerate(result.response_stages):
        stage.stage_sequence_number = i + 1

    sens = result.instrument_sensitivity
    if sens is not None:
        sens.input_units = sensor_stages[0].input_units
        sens.input_units_description = \
            sensor_stages[0].input_units_description
        last_stage = result.response_stages[-1]
        sens.output_units = last_stage.output_units
        sens.output_units_description = last_stage.output_units_description
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


def atomic_write_inventory(inventory, path, fmt="STATIONXML"):
    """Write ``inventory`` to ``path`` atomically.

    The data is first written to a temporary file in the same directory and
    then ``os.replace``d into place. ``os.replace`` is atomic within a single
    filesystem, so an interrupted or failing write can never truncate or
    corrupt an existing file at ``path`` — the original stays intact and the
    temporary file is removed on error.
    """
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(
        prefix=".srm_tmp_", suffix=".xml", dir=directory
    )
    os.close(fd)
    try:
        inventory.write(tmp_path, format=fmt)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def convert_inventory_to_xml(input_path: str, output_path: str):
    try:
        inventory = read_inventory(input_path)
        atomic_write_inventory(inventory, output_path, fmt="STATIONXML")

        success_message = (
            f"Successfully converted and saved file to:\n{output_path}"
        )
        return True, success_message

    except Exception as e:
        error_message = f"An error occurred during conversion.\n\nDetails: {e}"
        return False, error_message


def make_export_inventory(item_type, obj, network=None, station=None,
                          inventory=None,
                          source="Station Response Manager"):
    """Return (Inventory, default_filename) containing only the selected
    node.

    ``item_type`` is one of "file" | "network" | "station" | "channel";
    ``network``/``station`` are the parent ObsPy objects for station and
    channel exports; ``inventory`` is the full Inventory (with its display
    name in ``obj``) when ``item_type`` is "file".

    Parent containers are shallow-copied with their child list *reassigned*
    (never mutated), so the live inventory is untouched and the leaf
    objects are shared, which is safe because ``Inventory.write`` does not
    mutate them.
    """
    if item_type == "file":
        name = os.path.basename(str(obj))
        if not name.lower().endswith(".xml"):
            name = os.path.splitext(name)[0] + ".xml"
        return inventory, name
    if item_type == "network":
        return (
            Inventory(networks=[obj], source=source),
            f"{obj.code}.xml",
        )
    if item_type == "station":
        net_copy = copy(network)
        net_copy.stations = [obj]
        return (
            Inventory(networks=[net_copy], source=source),
            f"{network.code}.{obj.code}.xml",
        )
    if item_type == "channel":
        sta_copy = copy(station)
        sta_copy.channels = [obj]
        net_copy = copy(network)
        net_copy.stations = [sta_copy]
        parts = [network.code, station.code]
        if obj.location_code:
            parts.append(obj.location_code)
        parts.append(obj.code)
        return (
            Inventory(networks=[net_copy], source=source),
            ".".join(parts) + ".xml",
        )
    raise ValueError(f"Cannot export item of type {item_type!r}")


# Header lines that differ between serializations without reflecting a
# real metadata change.
_VOLATILE_XML_TAGS = ("<Created>", "<Module>", "<ModuleURI>")


def inventory_to_stationxml_lines(inventory):
    """Serialize to StationXML text lines, dropping volatile header
    lines so two serializations of equal inventories compare equal."""
    buf = io.BytesIO()
    inventory.write(buf, format="STATIONXML")
    # Objects built in memory serialize slightly differently from ones
    # that passed through the reader (e.g. a plain-float SampleRate has
    # no unit attribute), so round-trip once and serialize the fixed
    # point the reader normalizes to.
    try:
        buf.seek(0)
        normalized = read_inventory(buf)
        buf = io.BytesIO()
        normalized.write(buf, format="STATIONXML")
    except Exception:
        pass
    return [
        line for line in buf.getvalue().decode("utf-8").splitlines()
        if not any(tag in line for tag in _VOLATILE_XML_TAGS)
    ]


def diff_inventory_vs_file(path, inventory):
    """Unified diff of the in-memory ``inventory`` against the file at
    ``path``, both serialized through the same StationXML writer so
    formatting differences cancel out. Returns "" when identical and an
    explanatory message when the on-disk baseline cannot be read."""
    try:
        baseline = read_inventory(path)
    except Exception as e:
        return f"! Could not read on-disk baseline:\n! {e}"
    name = os.path.basename(path)
    diff = difflib.unified_diff(
        inventory_to_stationxml_lines(baseline),
        inventory_to_stationxml_lines(inventory),
        fromfile=f"{name} (on disk)",
        tofile=f"{name} (edited)",
        lineterm="",
    )
    return "\n".join(diff)


def _units_equal(a, b):
    # Unit strings are case/whitespace-insensitive (e.g. "M/S" == "m/s"),
    # matching how the NRL detector normalizes units.
    return _norm_unit(a) == _norm_unit(b)


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
        if out_units and in_units and not _units_equal(out_units, in_units):
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
        if (first_in and sens.input_units
                and not _units_equal(first_in, sens.input_units)):
            issues.append((
                "warning",
                f"Sensitivity input units '{sens.input_units}' "
                f"don't match first stage input '{first_in}'."
            ))
        last_out = getattr(stages[-1], 'output_units', None)
        if (last_out and sens.output_units
                and not _units_equal(last_out, sens.output_units)):
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


def count_channels_with_issues(inventory):
    """Number of channels in ``inventory`` whose response has >=1 validation
    issue. Channels without a response are skipped (nothing to validate)."""
    count = 0
    for net in inventory.networks:
        for sta in net.stations:
            for chan in sta.channels:
                if chan.response and validate_response(chan.response):
                    count += 1
    return count


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
