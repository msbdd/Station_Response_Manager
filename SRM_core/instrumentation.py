"""Which instruments a channel uses, and how SRM knows.

A StationXML channel can state them itself (<Sensor>, <DataLogger>,
<PreAmplifier>); when it does not, the NRL index can guess the sensor and
digitizer from the response. Stated always wins: real files carry these
elements on nearly every channel, while a guess from a digital filter chain
that many digitizers share is often wrong. Every view renders the entries
built here, so the precedence and the placeholder rules live in one place.
"""
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Optional

from obspy.core.inventory.util import Equipment

from SRM_core.nrl_index import DetectionResult, distinct_models

STATED = "stated"
DETECTED = "detected"
# The element states a serial number but names no model, and detection
# found nothing to name it with either.
UNNAMED = "unnamed"
# How an instrument whose model is unknown reads in every view.
NOT_STATED = "model not stated"

# (role, Channel attribute), in display order. A pre-amplifier is never
# detected: the NRL index folds preamp stages into the datalogger.
ROLES = (
    ("sensor", "sensor"),
    ("datalogger", "data_logger"),
    ("preamplifier", "pre_amplifier"),
)

# Serial numbers that stand for "unknown". SeisComP's fdsnxml2inv fills a
# missing one with xxxx/yyyy and data centres serving from SeisComP pass
# them on: 120 of IS's 162 serials are such placeholders.
_PLACEHOLDER_SERIAL = re.compile(
    r"^(x+|y+|\?+|-+|n/?a|none|null|unknown)$", re.IGNORECASE
)

# StationXML element order.
_FIELD_LABELS = (
    ("type", "Type"),
    ("description", "Description"),
    ("manufacturer", "Manufacturer"),
    ("vendor", "Vendor"),
    ("model", "Model"),
    ("serial_number", "Serial number"),
    ("installation_date", "Installation date"),
    ("removal_date", "Removal date"),
)

# Fields that name an instrument model. Recording a different NRL pick
# replaces them; Type and Vendor are cleared rather than kept, as they
# would still describe the previous model. Serial number and dates are
# kept: whether the physical unit changed is the user's call, and they can
# be edited in the Explorer.
_NAME_FIELDS = ("type", "description", "manufacturer", "vendor", "model")

# NRL "manufacturers" that are not instruments: GenericUnity holds unity
# placeholder responses for when the real instrument is unknown, so a pick
# from it names nothing that may be written down as stated.
_NRL_PLACEHOLDER_MAKERS = {"genericunity"}


def _clean(value):
    """Stripped text, or None for a missing or blank value."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _norm(text):
    return " ".join(str(text or "").split()).casefold()


def is_placeholder_serial(serial):
    text = _clean(serial)
    return text is not None and _PLACEHOLDER_SERIAL.match(text) is not None


def stated_name(equipment):
    """The instrument a stated <Sensor>/<DataLogger>/<PreAmplifier> names,
    or None when it names none (GE writes resourceId-only stubs).

    Data centres fill different fields — Manufacturer + Model (IRIS), Type
    only (HU), Description only (CZ, GE sensors) — so take the most specific
    one present. Text is shown as stated, case included."""
    if equipment is None:
        return None
    manufacturer = _clean(equipment.manufacturer)
    model = _clean(equipment.model)
    if model:
        if manufacturer and not model.casefold().startswith(
                manufacturer.casefold()):
            return f"{manufacturer} {model}"
        return model
    return (_clean(equipment.type) or _clean(equipment.description)
            or manufacturer)


def equipment_fields(equipment):
    """``(label, text)`` for every field the element states, in StationXML
    order; a placeholder serial number is marked as one."""
    if equipment is None:
        return []
    fields = []
    for attr, label in _FIELD_LABELS:
        text = _clean(getattr(equipment, attr, None))
        if text is None:
            continue
        if attr == "serial_number" and is_placeholder_serial(text):
            text += " (placeholder)"
        fields.append((label, text))
    dates = [str(d) for d in (equipment.calibration_dates or [])]
    if dates:
        fields.append(("Calibration dates", ", ".join(dates)))
    resource_id = _clean(equipment.resource_id)
    if resource_id:
        fields.append(("resourceId", resource_id))
    return fields


def _detected(role, result):
    """``(best, candidates, gain_matches)`` detected for a role."""
    if result is None:
        return None, [], []
    if role == "sensor":
        best, candidates, gain = result.sensor, result.sensor_candidates, None
    elif role == "datalogger":
        best, candidates = result.datalogger, result.datalogger_candidates
        gain = result.datalogger_gain_matches
    else:
        return None, [], []
    if best is None:
        return None, [], []
    return best, list(candidates or [best]), list(gain or [])


# A family's label names this many models before counting the rest.
_LISTED = 3


def _is_boundary(word, k):
    """Whether ``word`` can be cut before index ``k``: at its end, a
    separator, a lower-to-upper case step (TitanEA) or a letter-to-digit
    one after a real word (Trident305, but not Mk1)."""
    if k >= len(word):
        return True
    if word[k] in "-_ ./" or word[k - 1] in "-_ ./":
        return True
    if word[k].isupper() and (word[k - 1].islower() or word[k - 1].isdigit()):
        return True
    if word[k].isdigit() and word[k - 1].isalpha():
        return len(re.search(r"[A-Za-z]*$", word[:k]).group()) >= 3
    return False


# Shorter shared leads are product-line prefixes ("CMG", "GEO"), which
# would fold unrelated models together.
_MIN_LEAD = 4


def _shared_lead(a, b):
    """The longest leading name ``a`` and ``b`` share, cut at a boundary in
    both ("TitanEA", "TitanSMA" -> "Titan"), or None if too short."""
    k = 0
    while k < min(len(a), len(b)) and a[k].casefold() == b[k].casefold():
        k += 1
    while k >= _MIN_LEAD and not (_is_boundary(a, k) and _is_boundary(b, k)):
        k -= 1
    lead = a[:k].rstrip("-_ ./")
    return lead if len(lead) >= _MIN_LEAD else None


def _fold(models):
    """Fold each maker's model variants under their shared leading name:
    Centaur and CentaurHighGain read "Centaur", TitanEA and TitanSMA
    "Titan". A lead is fixed by its first two members, so Trillium120BH
    and Trillium240 do not collapse to a bare "Trillium"."""
    by_maker = {}
    for maker, model in models:
        by_maker.setdefault(maker, []).append(model)
    folded = []
    for maker, names in by_maker.items():
        names = sorted(set(names), key=str.casefold)
        i = 0
        while i < len(names):
            lead = (_shared_lead(names[i], names[i + 1])
                    if i + 1 < len(names) else None)
            j = i + 1
            if lead:
                while (j < len(names)
                       and names[j].casefold().startswith(lead.casefold())
                       and _is_boundary(names[j], len(lead))):
                    j += 1
            folded.append((maker, lead or names[i]))
            i = j
    return folded


def _by_name(models):
    # Alphabetical: listing the gain match first would read as a pick.
    return sorted(models, key=lambda m: (m[0].casefold(), m[1].casefold()))


def _family_label(models):
    """'Quanterra Q330Mplus / Q330Splus'; past three models, variants fold
    and the rest is counted: 'Nanometrics Centaur / EuropaT / Meridian +3
    more (10 models)'."""
    models = _by_name(models)
    items = models if len(models) <= _LISTED else _fold(models)
    shown = items[:_LISTED]
    parts, previous = [], None
    for maker, model in shown:
        # The maker is named once per run of its models.
        parts.append(model if maker == previous else f"{maker} {model}")
        previous = maker
    text = " / ".join(parts)
    if len(items) > _LISTED:
        text += f" +{len(items) - _LISTED} more"
    if len(items) != len(models) or len(items) > _LISTED:
        text += f" ({len(models)} models)"
    return text


def detected_text(role, result):
    """How a detected instrument is named, or None if none was detected.

    One model sharing the response is named; several are a family, listed
    — the response cannot tell them apart, so none is picked."""
    best, candidates, _gain = _detected(role, result)
    if best is None:
        return None
    models = distinct_models(candidates)
    if len(models) == 1:
        maker, model = models[0]
        return f"{maker} {model}"
    return _family_label(models)


def candidates_tooltip(role, result):
    """What the detection rests on: the NRL entry or the family's models,
    and for a digitizer which configurations match the gain too."""
    best, candidates, gain = _detected(role, result)
    if best is None:
        return None
    models = distinct_models(candidates)
    lines = []
    if len(models) == 1:
        lines.append(f"NRL: {best.description or best.nrl_path}")
        if len(candidates) > 1:
            lines.append(f"{len(candidates)} NRL configurations share this "
                         "response.")
    else:
        what = "digital chain" if role == "datalogger" else "response"
        lines.append(f"Same {what} in the NRL ({len(models)} models):")
        lines += [f"  • {maker} {model}" for maker, model in _by_name(models)]
    if role == "datalogger":
        if gain:
            lines.append("Gain matches: " + ", ".join(
                f"{maker} {model}" for maker, model in distinct_models(gain)))
        else:
            lines.append("No NRL configuration has this gain.")
    return "\n".join(lines)


@dataclass
class InstrumentEntry:
    role: str
    source: str
    # None only for an UNNAMED entry.
    name: Optional[str]
    serial: Optional[str] = None
    # The stated element, if the channel has one — also for a detected
    # entry, whose element then named no model.
    equipment: Optional[Equipment] = None
    detection: Optional[DetectionResult] = None
    # What the response matches in the NRL, for a stated entry: shown
    # alongside, never compared or flagged.
    nrl_match: Optional[str] = None

    @property
    def serial_placeholder(self):
        return is_placeholder_serial(self.serial)


def _detect(nrl_index, response):
    if nrl_index is None or response is None:
        return DetectionResult()
    return nrl_index.detect_instrument(response)


def resolve_instruments(nrl_index, response, channel=None):
    """One entry per instrument known for ``channel``: the stated one, else
    the one detected from ``response``.

    Without a channel only detection is possible, which is what the views
    showed before stated instruments were read."""
    detection = _detect(nrl_index, response)
    entries = []
    for role, attr in ROLES:
        equipment = getattr(channel, attr, None)
        name = stated_name(equipment)
        serial = _clean(getattr(equipment, "serial_number", None))
        detected = detected_text(role, detection)
        if name:
            entries.append(InstrumentEntry(
                role, STATED, name, serial, equipment, detection,
                nrl_match=detected,
            ))
        elif detected:
            entries.append(InstrumentEntry(
                role, DETECTED, detected, serial, equipment, detection,
            ))
        elif serial:
            entries.append(InstrumentEntry(
                role, UNNAMED, None, serial, equipment, detection,
            ))
    return entries


def nrl_pick_equipment(keys, description=None):
    """The <Sensor>/<DataLogger> for an instrument picked in the NRL, or
    None when the pick names no instrument.

    The NRL tree is laid out manufacturer / model / configuration, so the
    first two keys name the instrument, and the chosen leaf's description
    ("Streckeisen; STS-2.5; Long-Period_Corner 120 s; …") records the
    configuration. Serial number and dates stay unset: the NRL can't know
    them."""
    keys = [_clean(k) for k in (keys or [])]
    if len(keys) < 2 or not keys[0] or not keys[1]:
        return None
    if keys[0].casefold() in _NRL_PLACEHOLDER_MAKERS:
        return None
    return Equipment(
        manufacturer=keys[0], model=keys[1],
        description=_clean(description),
    )


def classify_pick(channel, attr, picked):
    """What recording ``picked`` as the channel's ``attr`` would do: None
    (nothing to record, or that instrument is already stated), "fill"
    (nothing is named yet) or "replace" (another instrument is stated —
    the user has to agree first)."""
    if picked is None:
        return None
    current = stated_name(getattr(channel, attr, None))
    if current is None:
        return "fill"
    if _norm(current) == _norm(stated_name(picked)):
        return None
    return "replace"


def apply_pick(channel, attr, picked):
    """Record ``picked`` as the channel's ``attr`` instrument.

    Returns the ``[(obj, attr, old_value)]`` edits made, in order, so the
    caller can undo them. An existing element is updated in place, keeping
    its serial number and dates. A nameless stub keeps its resourceId too,
    as the same record now gets a name; a different instrument the user
    agreed to replace loses it, since StationXML expects equipment sharing
    a resourceId to hold the same information (TX even writes NRL paths
    such as "NRL/Guralp/CMG40T.60_100.800" there)."""
    current = getattr(channel, attr, None)
    if current is None:
        setattr(channel, attr, deepcopy(picked))
        return [(channel, attr, None)]
    fields = _NAME_FIELDS
    if stated_name(current) is not None:
        fields += ("resource_id",)
    edits = []
    for field in fields:
        new = getattr(picked, field, None)
        old = getattr(current, field, None)
        if new != old:
            edits.append((current, field, old))
            setattr(current, field, new)
    return edits
