"""Theater rehearsal call board built with Pixeltable, traced with OpenTelemetry.

A stage manager's working data for one production: the cast, the scenes, every rehearsal
call (room, times, scenes worked, production notes per department) and the check-ins.
Computed columns turn each call's JSON notes into urgent notes, department lists and a
ranked top note with pixeltable.functions filter/map/sort, and band every check-in.
The dashboard (`python dashboard.py build`) joins check-ins with the cast and the calls
and aggregates them with count/sum/mean/min/max. `python dashboard.py trace` runs the
same workload with `opentelemetry-instrumentation-pixeltable` writing every span to a
JSONL file, and loads those spans back into the `spans` table so the dashboard can
report on Pixeltable's own operations.

Layout: UDFs/UDAs live in udfs.py; this file holds table models and @pxt.query functions.
No HTTP router.

    pxt schema update app.py theater
    python seed.py
    python dashboard.py trace
    python dashboard.py build
"""

from __future__ import annotations

import pixeltable as pxt
import pixeltable.functions as pxtf

from udfs import hours_between, iso_duration_ms, punctuality, span_family

TableModel = pxt.model_base()


class Cast(TableModel, name='cast'):
    """One company member, the character they play and their track."""

    actor_id = pxt.Column(type=pxt.String, primary_key=True)
    name: pxt.String
    character: pxt.String
    track: pxt.String  # principal | ensemble | swing
    equity: pxt.Bool


class Scenes(TableModel, name='scenes'):
    """One scene of the show and who is in it."""

    scene_id = pxt.Column(type=pxt.String, primary_key=True)
    act: pxt.Int
    title: pxt.String
    run_minutes: pxt.Int
    called: pxt.Json  # list of actor_ids


class Rehearsals(TableModel, name='rehearsals'):
    """One rehearsal call: room, times, scenes worked and the production notes from it."""

    rehearsal_id = pxt.Column(type=pxt.String, primary_key=True)
    day: pxt.String
    room: pxt.String
    start: pxt.String
    end: pxt.String
    scenes: pxt.Json  # list of scene_ids
    notes: pxt.Json  # list of {dept, note, priority}

    hours = hours_between(start, end)
    urgent_notes = pxtf.filter(notes, lambda x: x.priority >= 2)
    note_depts = pxtf.map(notes, lambda x: x.dept)
    notes_ranked = pxtf.sort(notes, key=lambda x: x.priority, asc=False)
    top_note = notes_ranked[0].note.astype(pxt.String | None)
    n_scenes = scenes.len().astype(pxt.Int)

    __indexes__ = [pxt.BtreeIndex(day), pxt.BtreeIndex(room)]


class Attendance(TableModel, name='attendance'):
    """One check-in of one company member at one call."""

    checkin_id = pxt.Column(type=pxt.String, primary_key=True)
    rehearsal_id: pxt.String
    actor_id: pxt.String
    status: pxt.String  # present | absent
    minutes_late: pxt.Int

    band = punctuality(status, minutes_late)

    __indexes__ = [pxt.BtreeIndex(actor_id), pxt.BtreeIndex(rehearsal_id)]


class Spans(TableModel, name='spans'):
    """One OpenTelemetry span emitted by Pixeltable itself (loaded from the span dump)."""

    span_id = pxt.Column(type=pxt.String, primary_key=True)
    trace_id: pxt.String
    parent_id: pxt.String | None
    name: pxt.String
    start_time: pxt.String
    end_time: pxt.String
    status: pxt.String
    attributes: pxt.Json
    run: pxt.String

    duration_ms = iso_duration_ms(start_time, end_time)
    family = span_family(name)
    pxt_table = attributes['pxt.table'].astype(pxt.String | None)

    __indexes__ = [pxt.BtreeIndex(trace_id)]


@pxt.query
def checkins(actor_id: str):
    """Every check-in of one company member (the dashboard joins these with the calls)."""
    return (
        Attendance.where(Attendance.actor_id == actor_id)
        .order_by(Attendance.rehearsal_id)
        .select(Attendance.rehearsal_id, Attendance.band, Attendance.minutes_late)
    )


@pxt.query
def dept_notes(dept: str):
    """The notes for one department (props, lights, sound, costumes, ...) from every call."""
    return (
        Rehearsals.order_by(Rehearsals.day)
        .select(Rehearsals.day, Rehearsals.rehearsal_id, notes=pxtf.filter(Rehearsals.notes, lambda x: x.dept == dept))
    )


@pxt.query
def slow_spans(min_ms: float = 50.0):
    """Pixeltable operations whose span took at least min_ms milliseconds, slowest first."""
    return (
        Spans.where(Spans.duration_ms >= min_ms)
        .order_by(Spans.duration_ms, asc=False)
        .select(Spans.name, Spans.pxt_table, Spans.duration_ms, Spans.run)
    )
