"""OpenGym CSV reader, written from docs/opengym-export-format.md only."""

import csv
from datetime import datetime

LB_TO_KG = 0.45359237  # spec 1.1
SET_TYPES = {"warmup", "normal", "failure", "drop"}  # spec 1.1
UNITS = {"kg": 1.0, "lb": LB_TO_KG}


def _number(text, convert):
    text = (text or "").strip()
    return convert(text) if text else None  # an empty cell is missing, "0" is a value


def read_opengym(path, exercise_map=None):
    """Return canonical set dicts.

    `exercise_map` maps OpenGym ids to free-exercise-db ids; an id absent from it becomes None. Without a map the
    OpenGym id is kept. Rows identical in every column are stored once.
    """
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))  # by header name, never by position
    sets, seen = [], set()
    for number, row in enumerate(rows, start=1):
        key = tuple(sorted(row.items()))
        if key in seen:
            continue
        seen.add(key)
        if row["unit"] not in UNITS:
            raise ValueError(f"row {number}: unknown unit {row['unit']!r}")
        if row["set_type"] not in SET_TYPES:
            raise ValueError(f"row {number}: unknown set_type {row['set_type']!r}")
        weight = _number(row["weight"], float)
        reps = _number(row["reps"], int)
        raw_id = row["exercise_id"]
        sets.append({
            "set_id": str(number),
            "workout_ts": datetime.strptime(row["start_time"], "%Y-%m-%d %H:%M"),
            "exercise_id": raw_id if exercise_map is None else exercise_map.get(raw_id),
            "exercise_name": row["exercise"],
            "set_type": row["set_type"],  # "failure" is taken to failure, not failed
            "weight_kg": None if weight is None else weight * UNITS[row["unit"]],
            "reps": reps,
            "rpe": _number(row["rpe"], float),
            "failed": reps == 0,
        })
    return sets
