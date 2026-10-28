"""Seed the call board: 10 company members, 8 scenes, 9 rehearsal calls and their check-ins.

    python seed.py                              # local catalog 'theater'
    python seed.py pxt://<org>:<db>             # a Pixeltable Cloud database

One call (R-09) has a typo in its end time on purpose: its `hours` cell fails, and
`pxt errors theater/rehearsals --col hours` shows the row and the exception.
"""

from __future__ import annotations

import sys

import pixeltable as pxt

CATALOG = sys.argv[1] if len(sys.argv) > 1 else 'theater'

CAST = [
    ('A01', 'Maya Okafor', 'Viola', 'principal', True),
    ('A02', 'Tom Reyes', 'Orsino', 'principal', True),
    ('A03', 'Priya Nair', 'Olivia', 'principal', True),
    ('A04', 'Sam Whitlock', 'Malvolio', 'principal', True),
    ('A05', 'Jo Lindqvist', 'Feste', 'principal', False),
    ('A06', 'Ade Bello', 'Sir Toby Belch', 'principal', True),
    ('A07', 'Lena Park', 'Maria', 'ensemble', False),
    ('A08', 'Chris Dunn', 'Sebastian', 'ensemble', False),
    ('A09', 'Rosa Vidal', 'Antonio', 'ensemble', False),
    ('A10', 'Kit Moreau', 'swing (all ensemble)', 'swing', False),
]

SCENES = [
    ('1.1', 1, "Orsino's court: if music be the food of love", 6, ['A02', 'A05']),
    ('1.2', 1, 'The sea coast: Viola shipwrecked', 5, ['A01', 'A09']),
    ('1.3', 1, "Olivia's house: Sir Toby and Maria", 7, ['A06', 'A07']),
    ('1.5', 1, 'Viola woos Olivia for Orsino', 12, ['A01', 'A03', 'A04', 'A05', 'A07']),
    ('2.3', 2, 'The midnight carousing', 10, ['A04', 'A05', 'A06', 'A07']),
    ('2.5', 2, 'The letter scene (box tree)', 11, ['A04', 'A06', 'A07', 'A08']),
    ('3.4', 3, 'Malvolio in yellow stockings', 14, ['A03', 'A04', 'A06', 'A07', 'A09']),
    ('5.1', 5, 'Recognition: Viola and Sebastian', 16, ['A01', 'A02', 'A03', 'A04', 'A05', 'A06', 'A08', 'A09']),
]


def n(dept: str, note: str, priority: int) -> dict:
    return {'dept': dept, 'note': note, 'priority': priority}


REHEARSALS = [
    ('R-01', '2026-10-12', 'Studio A', '10:00', '13:00', ['1.1', '1.2', '1.3'],
     [n('props', 'need rehearsal lute for Feste', 1), n('sound', 'storm cue for 1.2 by Thursday', 2)]),
    ('R-02', '2026-10-13', 'Studio A', '10:00', '14:00', ['1.5'],
     [n('costumes', "Viola's doublet must allow a full kneel", 2), n('props', 'ring for Malvolio to throw', 1)]),
    ('R-03', '2026-10-14', 'Studio B', '18:00', '22:00', ['2.3', '2.5'],
     [n('lights', 'box tree special, downstage left', 2), n('props', 'breakaway tankards x4', 3),
      n('sound', 'catch song needs a pitch note', 1)]),
    ('R-04', '2026-10-15', 'Studio B', '18:00', '21:30', ['2.5'],
     [n('props', 'letter: 3 copies, wax seal', 3), n('set', 'box tree must hold two people', 2)]),
    ('R-05', '2026-10-17', 'Studio A', '12:00', '17:00', ['3.4'],
     [n('costumes', 'yellow stockings + cross-garters, 2 pairs', 3), n('stage management', 'fight call before 3.4', 2)]),
    ('R-06', '2026-10-19', 'Main stage', '13:00', '18:00', ['1.1', '1.2', '1.3', '1.5'],
     [n('lights', 'shipwreck flicker too long', 1), n('sound', 'storm cue level -6 dB', 1)]),
    ('R-07', '2026-10-20', 'Main stage', '13:00', '19:00', ['2.3', '2.5', '3.4'],
     [n('set', 'box tree wobbles on the rake', 3), n('lights', 'yellow gel for 3.4 special', 2)]),
    ('R-08', '2026-10-22', 'Main stage', '18:00', '23:00', ['5.1'],
     [n('costumes', 'Sebastian and Viola need matching hats', 2), n('stage management', 'twins blocking spike marks', 1)]),
    ('R-09', '2026-10-23', 'Main stage', '18:00', '23:O0', ['1.1', '1.2', '1.3', '1.5', '2.3', '2.5', '3.4', '5.1'],
     [n('stage management', 'first full run: time every act', 2)]),
]

# (rehearsal, actor, status, minutes_late); everyone in a called scene is called
LATE = {('R-03', 'A06'): 12, ('R-05', 'A04'): 4, ('R-07', 'A06'): 20, ('R-08', 'A08'): 7, ('R-06', 'A05'): 3}
ABSENT = {('R-04', 'A08'), ('R-07', 'A09')}


def main() -> None:
    cast = pxt.get_table(f'{CATALOG}/cast')
    scenes = pxt.get_table(f'{CATALOG}/scenes')
    rehearsals = pxt.get_table(f'{CATALOG}/rehearsals')
    attendance = pxt.get_table(f'{CATALOG}/attendance')

    cast.insert([dict(actor_id=a, name=nm, character=c, track=t, equity=e) for a, nm, c, t, e in CAST])
    scenes.insert([dict(scene_id=s, act=a, title=t, run_minutes=m, called=c) for s, a, t, m, c in SCENES])
    rehearsals.insert(
        [dict(rehearsal_id=r, day=d, room=rm, start=s, end=e, scenes=sc, notes=no)
         for r, d, rm, s, e, sc, no in REHEARSALS],
        on_error='ignore',
    )
    by_scene = {s[0]: s[4] for s in SCENES}
    rows = []
    for r, *_rest in REHEARSALS:
        sc = _rest[4]
        called = sorted({a for s in sc for a in by_scene[s]})
        for a in called:
            status = 'absent' if (r, a) in ABSENT else 'present'
            rows.append(dict(checkin_id=f'{r}/{a}', rehearsal_id=r, actor_id=a, status=status,
                             minutes_late=LATE.get((r, a), 0)))
    attendance.insert(rows)
    print(f'seeded {CATALOG}: {cast.count()} cast, {scenes.count()} scenes, '
          f'{rehearsals.count()} calls, {attendance.count()} check-ins')


if __name__ == '__main__':
    main()
