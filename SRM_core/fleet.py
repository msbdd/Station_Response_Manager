"""What is deployed where: channel epochs folded into deployments.

A station records one instrument on several channels — three components,
often at several sample rates — so the Instruments view and its filter work
on *deployments*: the channels of one station location that share a sensor,
digitizer and pre-amplifier. By default only current epochs count (each
channel's open one, else its latest), so counts describe today's fleet
rather than every epoch a file has ever held.

No Qt here: the Manager filters its tree, map and timeline from the same
deployments the Instruments tab charts.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, FrozenSet, List

from SRM_core.instrumentation import (
    DETECTED,
    NOT_STATED,
    ROLES,
    UNNAMED,
    InstrumentEntry,
    resolve_instruments,
)
from SRM_core.utils import utc_to_ts

STATED_KIND, DETECTED_KIND, UNSTATED_KIND, OTHER_KIND = (
    "stated", "detected", "unstated", "other",
)
# Bar keys: one per instrument category; the folded tail has its own.
UNSTATED_KEY, OTHER_KEY = "unstated", "other"

# Selection: role -> category keys. Within a role any key matches; across
# roles a deployment must match them all ("STS-2s recorded by a Q330").
Selection = Dict[str, FrozenSet[str]]


def _norm(text):
    return " ".join(str(text).split()).casefold()


@dataclass
class Deployment:
    filepath: str
    network: str
    station: str
    location: str
    # The channel epochs in it, ordered by code then start.
    channels: list = field(default_factory=list)
    # The <Station> elements holding them: a station code can span several.
    blocks: list = field(default_factory=list)
    # role -> InstrumentEntry, for each role an instrument is known.
    entries: Dict[str, InstrumentEntry] = field(default_factory=dict)

    @property
    def code(self):
        return f"{self.network}.{self.station}"

    @property
    def start(self):
        starts = [c.start_date for c in self.channels if c.start_date]
        return min(starts) if starts else None

    @property
    def end(self):
        """The last end date, or None while any channel is open."""
        ends = [c.end_date for c in self.channels]
        if not ends or any(e is None for e in ends):
            return None
        return max(ends)

    @property
    def bands(self):
        return fold_codes(self.channels)


def fold_codes(channels):
    """Channel codes with components folded: BHZ/BHN/BHE -> "BH?"."""
    by_prefix = {}
    for c in channels:
        by_prefix.setdefault(c.code[:-1], set()).add(c.code)
    return ", ".join(
        f"{prefix}?" if len(codes) > 1 else next(iter(codes))
        for prefix, codes in sorted(by_prefix.items())
    )


def _is_open(channel, now_ts):
    end = utc_to_ts(channel.end_date)
    return end is None or end > now_ts


def _now_ts():
    return datetime.now(tz=timezone.utc).timestamp()


def _current(epochs, now_ts):
    """A channel's current epoch: its open one, else its latest."""
    return max(epochs, key=lambda item: (
        _is_open(item[0], now_ts),
        utc_to_ts(item[0].start_date) or float("-inf"),
    ))


def _entry_key(entry):
    if entry is None:
        return None
    return (entry.source, _norm(entry.name or ""), entry.serial)


def deployments(loaded_files, nrl_index, current_only=True, now_ts=None):
    """The deployments of every loaded inventory, in station order."""
    if now_ts is None:
        now_ts = _now_ts()
    epochs = {}
    for filepath, inventory in loaded_files.items():
        for net in inventory.networks:
            for sta in net.stations:
                for ch in sta.channels:
                    key = (filepath, net.code, sta.code,
                           ch.location_code or "", ch.code)
                    epochs.setdefault(key, []).append((ch, sta))
    groups = {}
    for (filepath, net, sta, loc, _code), items in epochs.items():
        if current_only:
            items = [_current(items, now_ts)]
        for ch, block in items:
            entries = {e.role: e for e in resolve_instruments(
                nrl_index, ch.response, ch)}
            key = (filepath, net, sta, loc) + tuple(
                _entry_key(entries.get(role)) for role, _attr in ROLES)
            dep = groups.get(key)
            if dep is None:
                dep = groups[key] = Deployment(
                    filepath, net, sta, loc, entries=entries)
            dep.channels.append(ch)
            if all(b is not block for b in dep.blocks):
                dep.blocks.append(block)
    for dep in groups.values():
        dep.channels.sort(
            key=lambda c: (c.code, utc_to_ts(c.start_date) or 0))
    return sorted(groups.values(), key=lambda d: (
        d.code, d.location, d.bands, utc_to_ts(d.start) or 0))


def category(entry):
    """``(key, label, kind)`` a deployment counts under for a role.

    Stated names are compared case- and space-insensitively, since files
    spell one model several ways ("nanometrics CENTAUR"); a detection is
    its own category, as it is a guess, not a statement."""
    if entry is None or entry.source == UNNAMED:
        return UNSTATED_KEY, NOT_STATED, UNSTATED_KIND
    if entry.source == DETECTED:
        return (f"detected:{_norm(entry.name)}",
                f"{entry.name} (detected)", DETECTED_KIND)
    return f"stated:{_norm(entry.name)}", entry.name, STATED_KIND


@dataclass
class Bar:
    key: str
    label: str
    kind: str
    stations: int
    channels: int
    # The category keys the bar stands for: one, or the folded tail's.
    keys: FrozenSet[str]


def tally(deps, role, unit="stations", top=12):
    """The bars charting ``role`` over ``deps``: the ``top`` largest
    categories, the rest folded into one Other bar, and the deployments
    with no known model last, kept apart from the ranking so missing
    metadata always shows."""
    acc = {}
    for dep in deps:
        key, label, kind = category(dep.entries.get(role))
        a = acc.setdefault(key, {
            "labels": Counter(), "kind": kind, "stations": set(),
            "channels": 0,
        })
        a["labels"][label] += len(dep.channels)
        a["stations"].add((dep.filepath, dep.code))
        a["channels"] += len(dep.channels)

    def size(a):
        return len(a["stations"]) if unit == "stations" else a["channels"]

    ranked = sorted(
        (k for k in acc if k != UNSTATED_KEY),
        key=lambda k: (-size(acc[k]), acc[k]["labels"].most_common(1)[0][0]
                       .casefold()),
    )
    bars = [
        # Of a model's spellings, the most used one names its bar.
        Bar(k, acc[k]["labels"].most_common(1)[0][0], acc[k]["kind"],
            len(acc[k]["stations"]), acc[k]["channels"], frozenset([k]))
        for k in ranked[:top]
    ]
    tail = ranked[top:]
    if tail:
        stations = set().union(*(acc[k]["stations"] for k in tail))
        bars.append(Bar(
            OTHER_KEY, f"Other ({len(tail)} models)", OTHER_KIND,
            len(stations), sum(acc[k]["channels"] for k in tail),
            frozenset(tail)))
    if UNSTATED_KEY in acc:
        a = acc[UNSTATED_KEY]
        bars.append(Bar(UNSTATED_KEY, NOT_STATED, UNSTATED_KIND,
                        len(a["stations"]), a["channels"],
                        frozenset([UNSTATED_KEY])))
    return bars


def matches(dep, selection: Selection, except_role=None):
    """Whether ``dep`` fits every role's selection but ``except_role``'s."""
    for role, keys in selection.items():
        if role == except_role or not keys:
            continue
        if category(dep.entries.get(role))[0] not in keys:
            return False
    return True


def selected(deps, selection: Selection, except_role=None) -> List[Deployment]:
    return [d for d in deps if matches(d, selection, except_role)]


def station_blocks(deps):
    """Identities of the <Station> elements ``deps`` live in."""
    return {id(block) for dep in deps for block in dep.blocks}


def timeline_groups(deps):
    """The Timeline's ``(NET.STA, filepath)`` row groups of ``deps``."""
    return {(dep.code, dep.filepath) for dep in deps}
