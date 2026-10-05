import os
from collections import namedtuple
from copy import deepcopy

from obspy import Inventory, read
from obspy.core.inventory import Channel, Network, Station
from obspy.core.inventory.response import Response
from obspy.io.mseed.core import _is_mseed

from SRM_core.utils import make_export_inventory, orientation_for


TraceInfo = namedtuple(
    "TraceInfo",
    ["network", "station", "location", "channel", "sampling_rate",
     "starttime", "endtime"],
)

ChannelEpoch = namedtuple(
    "ChannelEpoch", ["location", "channel", "sample_rate", "start", "end"]
)

ScannedStation = namedtuple(
    "ScannedStation", ["network", "station", "epochs"]
)


class ScanReport(namedtuple("ScanReport",
                            ["n_files", "not_mseed", "unreadable"])):

    __slots__ = ()

    @property
    def n_mseed(self):
        return self.n_files - len(self.not_mseed) - len(self.unreadable)

    def summary(self):
        parts = [f"{self.n_mseed} MiniSEED"]
        if self.not_mseed:
            parts.append(f"{len(self.not_mseed)} not MiniSEED")
        if self.unreadable:
            parts.append(f"{len(self.unreadable)} unreadable")
        plural = "s" if self.n_files != 1 else ""
        return f"{self.n_files} file{plural} scanned: " + ", ".join(parts)

    def details(self):
        lines = []
        if self.unreadable:
            lines.append("Unreadable (looked like MiniSEED, failed to parse):")
            lines += [f"  {path}: {error}" for path, error in self.unreadable]
        if self.not_mseed:
            lines.append("Skipped (not MiniSEED):")
            lines += [f"  {path}" for path in self.not_mseed]
        return "\n".join(lines)


def list_candidate_files(folder):

    paths = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            if os.path.isfile(path):
                paths.append(path)
    paths.sort()
    return paths


def scan_mseed_file(path):

    # The same sniff ObsPy's format autodetection runs; it reads only the
    # start of the file, so non-data files cost almost nothing.
    if not _is_mseed(path):
        return None
    stream = read(path, format="MSEED", headonly=True)
    return [
        TraceInfo(
            tr.stats.network, tr.stats.station, tr.stats.location,
            tr.stats.channel, float(tr.stats.sampling_rate),
            tr.stats.starttime, tr.stats.endtime,
        )
        # headonly leaves tr.data empty; npts still holds the sample count.
        for tr in stream if tr.stats.npts > 0
    ]


def _rate_key(rate):
    # MiniSEED rates are normally exact factor/multiplier pairs, but a
    # blockette 100 float can add noise in the last digits. Seven
    # significant digits keep such a channel in one epoch while still
    # separating any real rate change.
    return float(f"{float(rate):.7g}")


def aggregate(trace_infos):

    spans = {}
    for info in trace_infos:
        key = (info.network, info.station, info.location, info.channel,
               _rate_key(info.sampling_rate))
        span = spans.get(key)
        if span is None:
            spans[key] = [info.starttime, info.endtime]
            continue
        if info.starttime < span[0]:
            span[0] = info.starttime
        if info.endtime > span[1]:
            span[1] = info.endtime

    by_station = {}
    for (net, sta, loc, cha, rate), (start, end) in spans.items():
        by_station.setdefault((net, sta), []).append(
            ChannelEpoch(loc, cha, rate, start, end)
        )
    return [
        ScannedStation(net, sta, sorted(
            epochs, key=lambda e: (e.location, e.channel, e.start)
        ))
        for (net, sta), epochs in sorted(by_station.items())
    ]


def group_key(epoch):

    return (epoch.location, epoch.channel[:-1], epoch.sample_rate)


def group_label(key):
    loc, prefix, rate = key
    return f"{loc or '--'}.{prefix}? @ {rate:g} Hz"


def response_groups(stations):
    """``{group key: (channel count, station count)}``, sorted by key."""
    channels = {}
    station_sets = {}
    for scanned in stations:
        for epoch in scanned.epochs:
            key = group_key(epoch)
            channels[key] = channels.get(key, 0) + 1
            station_sets.setdefault(key, set()).add(
                (scanned.network, scanned.station)
            )
    return {
        key: (channels[key], len(station_sets[key]))
        for key in sorted(channels)
    }


def response_output_rate(response):
    """Sample rate at the end of the response's decimation chain, or None
    when it states none (an empty or sensor-only response)."""
    try:
        rates = response.get_sampling_rates()
    except (ValueError, NotImplementedError):
        return None
    if not rates:
        return None
    return rates[max(rates)].get("output_sampling_rate")


def rate_mismatch(response, sample_rate):
    """The response's output rate when it contradicts ``sample_rate``,
    else None. A datalogger response is specific to one output rate (its
    FIR decimation chain), so putting it on channels recording at another
    rate is wrong even when every other stage matches."""
    out = response_output_rate(response)
    if out is None or abs(out - sample_rate) <= 1e-6 * sample_rate:
        return None
    return out


def build_inventory(stations, responses=None, coords=None, open_ended=True,
                    source="Station Response Manager"):

    responses = responses or {}
    coords = coords or {}
    notes = {"no_azimuth": [], "overlaps": []}
    networks = {}
    for scanned in stations:
        lat, lon, ele = coords.get(
            (scanned.network, scanned.station), (0.0, 0.0, 0.0)
        )
        by_channel = {}
        for epoch in scanned.epochs:
            by_channel.setdefault(
                (epoch.location, epoch.channel), []
            ).append(epoch)

        channels = []
        for (loc, cha), epochs in by_channel.items():
            epochs = sorted(epochs, key=lambda e: e.start)
            seed_id = f"{scanned.network}.{scanned.station}.{loc}.{cha}"
            azimuth, dip = orientation_for(cha)
            if azimuth is None:
                notes["no_azimuth"].append(seed_id)
            if any(nxt.start < prev.end
                   for prev, nxt in zip(epochs, epochs[1:])):
                notes["overlaps"].append(seed_id)
            for i, epoch in enumerate(epochs):
                is_latest = i == len(epochs) - 1
                response = responses.get(group_key(epoch))
                channels.append(Channel(
                    code=cha,
                    location_code=loc,
                    latitude=lat,
                    longitude=lon,
                    elevation=ele,
                    depth=0.0,
                    azimuth=azimuth,
                    dip=dip,
                    sample_rate=epoch.sample_rate,
                    start_date=epoch.start,
                    end_date=(None if open_ended and is_latest
                              else epoch.end),
                    response=(deepcopy(response) if response is not None
                              else Response()),
                ))

        start = min(e.start for e in scanned.epochs)
        end = None if open_ended else max(e.end for e in scanned.epochs)
        networks.setdefault(scanned.network, []).append(Station(
            code=scanned.station,
            latitude=lat,
            longitude=lon,
            elevation=ele,
            creation_date=start,
            start_date=start,
            end_date=end,
            channels=channels,
        ))

    inventory = Inventory(
        networks=[
            Network(code=net, stations=stas)
            for net, stas in sorted(networks.items())
        ],
        source=source,
    )
    return inventory, notes


def split_by_station(inventory):
    """One ``(filename, Inventory)`` per station, named ``NET.STA.xml``."""
    out = []
    for net in inventory.networks:
        for sta in net.stations:
            inv, name = make_export_inventory(
                "station", sta, network=net, source=inventory.source
            )
            if not net.code:
                name = f"{sta.code}.xml"
            out.append((name, inv))
    return out
