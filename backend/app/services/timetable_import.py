"""Parsing and conflict detection for administrator timetable/roster uploads.

Owner: Cyber 2, Phase 1.

Deliberately has no OCR path. A CSV or XLSX cell is either read correctly or the
row is rejected - never guessed at. A misread digit here would silently put a
student in the wrong session, which is worse than failing loudly.

This module is DB-agnostic on purpose: BBIS's ORM models (Session, Lecturer,
Student, Timetable) aren't in yet. `parse_timetable` / `parse_roster` return
plain dataclasses so the route handler can persist them however the schema
ends up looking, and so this logic is unit-testable without a database.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import time

import openpyxl
from rapidfuzz import fuzz, process

from app.core.errors import ValidationError

# --- What a "known" lecturer/student looks like, until BBIS's models land ---
# The route handler will eventually pass in real roster/staff lists pulled
# from the DB; for now callers can pass an empty list and everything reports
# as unmatched, which is still useful (a real DB miss should be treated the same
# as an upload that references someone who was never enrolled).
FUZZY_MATCH_THRESHOLD = 88  # rapidfuzz score, 0-100. Below this: unmatched.

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

REQUIRED_TIMETABLE_COLUMNS = {
    "course_code",
    "lecturer",
    "day",
    "start_time",
    "end_time",
    "room",
}
REQUIRED_ROSTER_COLUMNS = {"student_email", "student_name", "course_code"}


@dataclass
class TimetableRow:
    course_code: str
    lecturer: str
    day: str
    start_time: time
    end_time: time
    room: str
    row_number: int  # 1-indexed, header excluded - for error messages


@dataclass
class RosterRow:
    student_email: str
    student_name: str
    course_code: str
    row_number: int


@dataclass
class ParsedImport:
    timetable_rows: list[TimetableRow] = field(default_factory=list)
    roster_rows: list[RosterRow] = field(default_factory=list)
    rows_read: int = 0
    unmatched_lecturers: list[str] = field(default_factory=list)
    unmatched_students: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def _read_rows(filename: str, raw: bytes) -> list[dict[str, str]]:
    """Read a CSV or XLSX into a list of {column: value} dicts, header-normalized.

    Raises ValidationError for anything that isn't clean structured data -
    wrong extension, empty file, or a header that doesn't match what we expect.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "csv":
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp1252")
            except UnicodeDecodeError as exc:
                raise ValidationError(
                    "Could not read this file as text. It may be saved in an unsupported encoding.",
                    {"filename": filename},
                ) from exc
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValidationError("File has no header row.", {"filename": filename})
        rows = [
            {k.strip().lower(): (v or "").strip() for k, v in row.items() if k is not None}
            for row in reader
        ]
    elif ext == "xlsx":
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception as exc:
            raise ValidationError(
                "Could not read this file as .xlsx. It may be corrupt or not a real Excel file.",
                {"filename": filename},
            ) from exc

        try:
            ws = wb.active
            if ws is None:
                raise ValidationError(
                    "This .xlsx file has no active sheet.",
                    {"filename": filename},
                )

            it = ws.iter_rows(values_only=True)
            try:
                header = [str(c).strip().lower() if c is not None else "" for c in next(it)]
            except StopIteration:
                raise ValidationError("File has no header row.", {"filename": filename}) from None
            rows = []
            for raw_row in it:
                if all(c is None for c in raw_row):
                    continue  # skip fully blank rows, common at the end of a sheet
                row = {
                    header[i]: ("" if c is None else str(c).strip())
                    for i, c in enumerate(raw_row)
                    if i < len(header) and header[i]
                }
                rows.append(row)
        finally:
            wb.close()
    else:
        raise ValidationError(
            "Only .csv and .xlsx files are accepted.",
            {"filename": filename, "extension": ext or None},
        )

    if not rows:
        raise ValidationError("File has a header but no data rows.", {"filename": filename})

    return rows


def _parse_time(value: str, row_number: int, column: str) -> time:
    value = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p"):
        try:
            from datetime import datetime as _dt

            return _dt.strptime(value, fmt).time()
        except ValueError:
            continue
    raise ValidationError(
        f"Row {row_number}: could not parse '{column}' value '{value}' as a time. "
        "Expected HH:MM, 24-hour.",
        {"row": row_number, "column": column, "value": value},
    )


_DAY_ALIASES = {
    "monday": "Monday",
    "mon": "Monday",
    "tuesday": "Tuesday",
    "tue": "Tuesday",
    "tues": "Tuesday",
    "wednesday": "Wednesday",
    "wed": "Wednesday",
    "thursday": "Thursday",
    "thu": "Thursday",
    "thurs": "Thursday",
    "friday": "Friday",
    "fri": "Friday",
    "saturday": "Saturday",
    "sat": "Saturday",
    "sunday": "Sunday",
    "sun": "Sunday",
}


def _parse_day(value: str, row_number: int) -> str:
    normalized = _DAY_ALIASES.get(value.strip().lower())
    if normalized is None:
        raise ValidationError(
            f"Row {row_number}: '{value}' is not a recognized day of the week.",
            {"row": row_number, "value": value},
        )
    return normalized


def parse_timetable(filename: str, raw: bytes) -> tuple[list[TimetableRow], int]:
    """Parse a timetable CSV/XLSX. Returns (rows, rows_read).

    Raises ValidationError on the first structural problem (bad header, bad
    extension, empty file). Per-row problems (bad time format) also raise -
    partial imports are not attempted, so an admin never has to guess which
    half of a file actually landed.
    """
    rows = _read_rows(filename, raw)

    header_cols = set(rows[0].keys())
    missing = REQUIRED_TIMETABLE_COLUMNS - header_cols
    if missing:
        raise ValidationError(
            f"Timetable file is missing required columns: {', '.join(sorted(missing))}.",
            {
                "missing_columns": sorted(missing),
                "found_columns": sorted(header_cols),
            },
        )

    parsed: list[TimetableRow] = []
    for i, row in enumerate(rows, start=1):
        course_code = row["course_code"].strip()
        lecturer = row["lecturer"].strip()
        day = _parse_day(row["day"], i)
        room = row["room"].strip()

        if not course_code or not lecturer or not day or not room:
            raise ValidationError(
                f"Row {i}: course_code, lecturer, day and room are all required.",
                {"row": i},
            )

        start = _parse_time(row["start_time"], i, "start_time")
        end = _parse_time(row["end_time"], i, "end_time")
        if end <= start:
            raise ValidationError(
                f"Row {i}: end_time ({row['end_time']}) is not after start_time "
                f"({row['start_time']}).",
                {"row": i},
            )

        parsed.append(
            TimetableRow(
                course_code=course_code,
                lecturer=lecturer,
                day=day,
                start_time=start,
                end_time=end,
                room=room,
                row_number=i,
            )
        )

    return parsed, len(rows)


def parse_roster(filename: str, raw: bytes) -> tuple[list[RosterRow], int]:
    """Parse a student roster CSV/XLSX. Returns (rows, rows_read)."""
    rows = _read_rows(filename, raw)

    header_cols = set(rows[0].keys())
    missing = REQUIRED_ROSTER_COLUMNS - header_cols
    if missing:
        raise ValidationError(
            f"Roster file is missing required columns: {', '.join(sorted(missing))}.",
            {
                "missing_columns": sorted(missing),
                "found_columns": sorted(header_cols),
            },
        )

    parsed: list[RosterRow] = []
    for i, row in enumerate(rows, start=1):
        email = row["student_email"].strip().lower()
        name = row["student_name"].strip()
        course_code = row["course_code"].strip()

        if not _EMAIL_RE.match(email):
            raise ValidationError(
                f"Row {i}: '{row['student_email']}' is not a valid email address.",
                {"row": i, "value": row["student_email"]},
            )
        if not name or not course_code:
            raise ValidationError(
                f"Row {i}: student_name and course_code are required.",
                {"row": i},
            )

        parsed.append(
            RosterRow(
                student_email=email,
                student_name=name,
                course_code=course_code,
                row_number=i,
            )
        )

    return parsed, len(rows)


MAX_REPORTED_CONFLICTS = 200


def detect_timetable_conflicts(rows: list[TimetableRow]) -> list[str]:
    """Same lecturer, same day, overlapping time ranges = a conflict.

    Also flags double-booked rooms, since a lecturer conflict and a room
    conflict are different problems an admin needs to resolve differently.

    Rows are bucketed by day first, since overlaps already requires
    a.day == b.day - comparing rows on different days is always wasted work.
    Within a day, rows are sorted by start_time, so once b.start_time is past
    a.end_time nothing later in the sorted list can overlap a either, and the
    inner loop breaks early. That turns what was an unconditional O(n^2) scan
    into roughly O(n log n): at the 50 MB upload limit (~1.6M rows), a full
    quadratic scan measured at ~24 days of CPU on one worker - not viable at
    any upload size worth supporting.

    MAX_REPORTED_CONFLICTS is a separate, second safeguard: it bounds the
    size of the response, not the comparison cost, which the day-bucketing
    above already handles.
    """
    conflicts: list[str] = []
    total = 0

    by_day: dict[str, list[TimetableRow]] = {}
    for row in rows:
        by_day.setdefault(row.day, []).append(row)

    for day_rows in by_day.values():
        day_rows.sort(key=lambda r: r.start_time)
        for i, a in enumerate(day_rows):
            for b in day_rows[i + 1 :]:
                if b.start_time >= a.end_time:
                    break  # sorted by start_time: nothing further can overlap a
                if a.lecturer.strip().lower() == b.lecturer.strip().lower():
                    total += 1
                    if len(conflicts) < MAX_REPORTED_CONFLICTS:
                        conflicts.append(
                            f"Lecturer '{a.lecturer}' double-booked on {a.day}: "
                            f"row {a.row_number} ({a.course_code}) overlaps row {b.row_number} "
                            f"({b.course_code})."
                        )
                if a.room.strip().lower() == b.room.strip().lower():
                    total += 1
                    if len(conflicts) < MAX_REPORTED_CONFLICTS:
                        conflicts.append(
                            f"Room '{a.room}' double-booked on {a.day}: "
                            f"row {a.row_number} ({a.course_code}) overlaps row {b.row_number} "
                            f"({b.course_code})."
                        )

    if total > len(conflicts):
        conflicts.append(f"...and {total - len(conflicts)} more conflicts not shown.")

    return conflicts


def match_names(
    candidates: list[str],
    known: list[str],
    threshold: int = FUZZY_MATCH_THRESHOLD,
) -> tuple[list[str], dict[str, str]]:
    """Fuzzy-match uploaded names against a known roster (e.g. Teams display names).

    Returns (unmatched, matched) where matched maps candidate -> best known match.
    Uses rapidfuzz per the dependency already pinned for this ("match Teams
    display names against the admin roster"). Exact and near-exact matches
    (typos, extra whitespace, case differences) resolve automatically; anything
    below `threshold` is left for the admin to resolve by hand rather than
    guessed at, for the same reason there's no OCR path.
    """
    if not known:
        return list(dict.fromkeys(candidates)), {}

    unmatched: list[str] = []
    matched: dict[str, str] = {}
    for name in dict.fromkeys(candidates):  # de-dupe, preserve order
        result = process.extractOne(name, known, scorer=fuzz.WRatio)
        if result and result[1] >= threshold:
            matched[name] = result[0]
        else:
            unmatched.append(name)

    return unmatched, matched
