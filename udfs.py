"""UDFs and UDAs for the rehearsal call board (pure Python, no table imports)."""

from __future__ import annotations

import datetime as dt
import math

import pixeltable as pxt

LATE_GRACE_MIN = 5  # Equity-style grace period before a check-in counts as late


@pxt.udf
def hours_between(start: str, end: str) -> float:
    """Length of a rehearsal call in hours from 'HH:MM' strings; raises on a malformed time."""
    t0 = dt.datetime.strptime(start, '%H:%M')
    t1 = dt.datetime.strptime(end, '%H:%M')
    if t1 <= t0:
        raise ValueError(f'call ends ({end}) before it starts ({start})')
    return round((t1 - t0).total_seconds() / 3600, 2)


@pxt.udf
def punctuality(status: str, minutes_late: int) -> str:
    """Band a check-in: on_time, grace, late or absent."""
    if status == 'absent':
        return 'absent'
    if minutes_late <= 0:
        return 'on_time'
    if minutes_late <= LATE_GRACE_MIN:
        return 'grace'
    return 'late'


@pxt.udf
def iso_duration_ms(start: str, end: str) -> float:
    """Duration between two ISO-8601 timestamps (as written by the OpenTelemetry span exporter), in ms."""
    t0 = dt.datetime.fromisoformat(start.replace('Z', '+00:00'))
    t1 = dt.datetime.fromisoformat(end.replace('Z', '+00:00'))
    return round((t1 - t0).total_seconds() * 1000, 3)


@pxt.udf
def span_family(name: str) -> str:
    """Group span names: 'pixeltable.catalog.begin_xact' -> 'catalog', 'pixeltable.insert' -> 'operation'."""
    parts = name.split('.')
    if len(parts) <= 2:
        return 'operation'
    return parts[1]


@pxt.uda
class p95(pxt.Aggregator):
    """95th percentile (nearest rank) of a float column."""

    def __init__(self) -> None:
        self.values: list[float] = []

    def update(self, value: float) -> None:
        if value is not None:
            self.values.append(value)

    def value(self) -> float | None:
        if not self.values:
            return None
        v = sorted(self.values)
        return v[max(0, math.ceil(0.95 * len(v)) - 1)]
