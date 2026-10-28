"""Rehearsal call board: trace a workload with OpenTelemetry, then build the dashboard.

    python dashboard.py trace      # run the stage manager's daily workload with Pixeltable's
                                   # OpenTelemetry bridge on, append every span to
                                   # output/spans.jsonl, then load them into theater/spans
    python dashboard.py build      # write output/dashboard.md and output/dashboard.html
    THEATER_CATALOG=pxt://<org>:<db> python dashboard.py build           # Pixeltable Cloud

Tracing needs no collector: `span_dump=` makes the bridge write one JSON span per line.
Set OTEL_EXPORTER_OTLP_ENDPOINT (and OTEL_EXPORTER_OTLP_HEADERS) to also ship the spans to
Grafana, Langfuse, Honeycomb or any OTLP backend.
"""

from __future__ import annotations

import html
import json
import os
import sys
import time
from pathlib import Path

import pixeltable as pxt
import pixeltable.functions as pxtf

from udfs import p95

CATALOG = os.environ.get('THEATER_CATALOG', 'theater')
OUT = Path(__file__).parent / 'output'
SPAN_DUMP = OUT / 'spans.jsonl'


def t(name: str) -> pxt.Table:
    return pxt.get_table(f'{CATALOG}/{name}')


# ---------------------------------------------------------------- trace

def workload(run: str) -> None:
    """A stage manager's day: log tonight's call and check-ins, then read the reports."""
    rehearsals, attendance, cast = t('rehearsals'), t('attendance'), t('cast')
    rid = f'R-T{run[-6:]}'
    rehearsals.insert([{
        'rehearsal_id': rid, 'day': '2026-10-24', 'room': 'Main stage', 'start': '18:00', 'end': '22:30',
        'scenes': ['3.4', '5.1'],
        'notes': [{'dept': 'lights', 'note': 'blackout before 5.1 is late', 'priority': 2},
                  {'dept': 'props', 'note': 'reset letter for second show', 'priority': 1}],
    }])
    attendance.insert([
        {'checkin_id': f'{rid}/A04', 'rehearsal_id': rid, 'actor_id': 'A04', 'status': 'present', 'minutes_late': 0},
        {'checkin_id': f'{rid}/A06', 'rehearsal_id': rid, 'actor_id': 'A06', 'status': 'present', 'minutes_late': 9},
    ])
    attendance.where(attendance.checkin_id == f'{rid}/A06').update({'minutes_late': 6})
    attendance.join(cast, on=attendance.actor_id == cast.actor_id).group_by(cast.track).select(
        cast.track, n=pxtf.count(attendance.checkin_id)).collect()
    rehearsals.select(rehearsals.rehearsal_id, rehearsals.urgent_notes).collect()
    rehearsals.where(rehearsals.rehearsal_id == rid).delete()
    attendance.where(attendance.rehearsal_id == rid).delete()


def cmd_trace() -> None:
    import opentelemetry.instrumentation.pixeltable as pxt_otel
    from opentelemetry import trace

    OUT.mkdir(exist_ok=True)
    run = time.strftime('%Y%m%dT%H%M%S')
    start_line = SPAN_DUMP.read_text().count('\n') if SPAN_DUMP.exists() else 0
    pxt_otel.init(span_dump=str(SPAN_DUMP), span_level='debug', service_name='rehearsal-call-board')
    workload(run)
    trace.get_tracer_provider().force_flush()
    lines = SPAN_DUMP.read_text().splitlines()[start_line:]
    rows = []
    for line in lines:
        s = json.loads(line)
        rows.append({
            'span_id': s['context']['span_id'],
            'trace_id': s['context']['trace_id'],
            'parent_id': s.get('parent_id'),
            'name': s['name'],
            'start_time': s['start_time'],
            'end_time': s['end_time'],
            'status': s['status']['status_code'],
            'attributes': s.get('attributes') or {},
            'run': f'{run} {CATALOG}',
        })
    spans = t('spans')
    if rows:
        spans.insert(rows)
    print(f'{len(rows)} spans from run {run} loaded into {CATALOG}/spans ({spans.count()} total)')


# ---------------------------------------------------------------- build

def fmt(v) -> str:
    if v is None:
        return '-'
    if isinstance(v, float):
        return f'{v:.2f}'
    if isinstance(v, list):
        return ', '.join(fmt(x) for x in v)
    return str(v)


def section(title: str, rs) -> tuple[str, str]:
    rows = list(rs)
    if not rows:
        return f'## {title}\n\n_no rows_\n', f'<h2>{html.escape(title)}</h2><p><em>no rows</em></p>'
    cols = list(rows[0].keys())
    md = [f'## {title}', '', '| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    md += ['| ' + ' | '.join(fmt(r[c]) for c in cols) + ' |' for r in rows]
    th = ''.join(f'<th>{html.escape(c)}</th>' for c in cols)
    trs = ''.join('<tr>' + ''.join(f'<td>{html.escape(fmt(r[c]))}</td>' for c in cols) + '</tr>' for r in rows)
    return '\n'.join(md) + '\n', f'<h2>{html.escape(title)}</h2><table><tr>{th}</tr>{trs}</table>'


def cmd_build() -> None:
    cast, scenes, reh, att, spans = t('cast'), t('scenes'), t('rehearsals'), t('attendance'), t('spans')
    secs = []

    secs.append(section('Rehearsal hours by room', reh.where(reh.hours != None).group_by(reh.room).select(
        reh.room, calls=pxtf.count(reh.rehearsal_id), hours=pxtf.sum(reh.hours), mean_hours=pxtf.mean(reh.hours),
        first=pxtf.min(reh.day), last=pxtf.max(reh.day)).order_by(pxtf.sum(reh.hours), asc=False).collect()))

    secs.append(section('Punctuality by company member (check-ins joined with the cast)',
        att.join(cast, on=att.actor_id == cast.actor_id).group_by(cast.name, cast.track).select(
            cast.name, cast.track, calls=pxtf.count(att.checkin_id), minutes_late=pxtf.sum(att.minutes_late),
            worst=pxtf.max(att.minutes_late)).order_by(pxtf.sum(att.minutes_late), asc=False).limit(6).collect()))

    secs.append(section('Absences and late arrivals by call (three-way join)',
        att.join(cast, on=att.actor_id == cast.actor_id)
        .join(reh, on=att.rehearsal_id == reh.rehearsal_id)
        .where(att.band != 'on_time')
        .order_by(reh.day)
        .select(reh.day, reh.room, cast.name, cast.character, att.band, att.minutes_late).collect()))

    secs.append(section('Who has never been called (left join cast -> check-ins)',
        cast.join(att, on=cast.actor_id == att.actor_id, how='left').where(att.actor_id == None)
        .select(cast.name, cast.character, cast.track).collect()))

    secs.append(section('Urgent notes per call (filter over the JSON notes)',
        reh.where(reh.urgent_notes.len() > 0).order_by(reh.day).select(
            reh.day, reh.rehearsal_id, depts=reh.note_depts, top_note=reh.top_note,
            urgent=pxtf.map(reh.urgent_notes, lambda x: x.dept)).collect()))

    secs.append(section('Data health: calls whose hours failed',
        reh.where(reh.hours.errortype != None).select(
            reh.rehearsal_id, reh.start, reh.end, error=reh.hours.errormsg).collect()))

    if spans.count() > 0:
        secs.append(section('Pixeltable operations (OpenTelemetry spans, by name)', sorted(
            spans.group_by(spans.family, spans.name).select(
                spans.family, spans.name, spans_=pxtf.count(spans.span_id), mean_ms=pxtf.mean(spans.duration_ms),
                p95_ms=p95(spans.duration_ms), max_ms=pxtf.max(spans.duration_ms),
                total_ms=pxtf.sum(spans.duration_ms))
            # a Python UDA (p95) runs the aggregation in Python, which keeps the group_by order:
            # rank by total time here instead of order_by(sum(...))
            .collect(), key=lambda r: -r['total_ms'])[:15]))
        secs.append(section('Traces (one per Pixeltable operation)',
            spans.where(spans.parent_id == None).order_by(spans.start_time).select(
                spans.run, spans.name, spans.pxt_table, spans.duration_ms, spans.status).collect()))

    OUT.mkdir(exist_ok=True)
    title = 'Rehearsal call board: Twelfth Night'
    (OUT / 'dashboard.md').write_text(f'# {title}\n\n' + '\n'.join(m for m, _ in secs))
    css = 'body{font-family:system-ui;margin:2rem;max-width:72rem}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.25rem .5rem;text-align:left}'
    (OUT / 'dashboard.html').write_text(
        f'<!doctype html><meta charset=utf-8><title>{title}</title><style>{css}</style><h1>{title}</h1>'
        + ''.join(h for _, h in secs))
    print(f'wrote {OUT / "dashboard.md"} and {OUT / "dashboard.html"} ({len(secs)} sections)')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'build'
    {'trace': cmd_trace, 'build': cmd_build}[cmd]()
