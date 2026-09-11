"""Create a narrow, reviewable calendar patch. Never modify a repository in place."""
from __future__ import annotations
import argparse
import difflib
import hashlib
from pathlib import Path

EXPECTED_BLOB = '65445c15882b11301c7c552c0fd56c1395fe2ab4'
TARGET = 'src/optimization/common/service_calendar.py'


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def patched_source(original: str) -> str:
    replacements = [
        ('        "holiday",\n', '        "holiday",\n        "sunhol",\n        "sunholiday",\n        "sundayorholiday",\n'),
        ('    if text in {"saturdayholiday", "weekendholiday", "土休日"}:',
         '    if text in {\n        "saturdayholiday", "weekendholiday", "土休日",\n        "sathol", "satholiday", "weekendorholiday",\n    }:'),
        ('    declared_holiday_dates = _declared_holiday_dates(simulation_config)',
         '    unverifiable_row_indices = [\n'
         '        index\n'
         '        for index, row in enumerate(timetable_rows)\n'
         '        if not isinstance(row, Mapping) or _trip_day_type(row) is None\n'
         '    ]\n'
         '    declared_holiday_dates = _declared_holiday_dates(simulation_config)'),
        ('    errors: list[str] = []',
         '    errors: list[str] = []\n'
         '    if unverifiable_row_indices:\n'
         '        errors.append("timetable_contains_unverifiable_day_type_rows")'),
        ('        "timetable_row_count": len(timetable_rows),',
         '        "timetable_row_count": len(timetable_rows),\n'
         '        "unverifiable_row_count": len(unverifiable_row_indices),\n'
         '        "unverifiable_row_indices": unverifiable_row_indices,'),
    ]
    for old, new in replacements:
        if original.count(old) != 1:
            raise ValueError('Source context changed: review against the pinned commit; no automatic patch.')
        original = original.replace(old, new, 1)
    compile(original, TARGET, 'exec')
    return original


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    # Accept platform line endings only after normalising; no semantic mismatches accepted.
    normalised = raw.replace(b'\r\n', b'\n')
    if git_blob_sha(normalised) != EXPECTED_BLOB:
        raise SystemExit('Source blob mismatch. Stop and review; the script made no changes.')
    original = normalised.decode('utf-8')
    fixed = patched_source(original)
    patch = ''.join(difflib.unified_diff(original.splitlines(True), fixed.splitlines(True),
                                       fromfile='a/' + TARGET, tofile='b/' + TARGET))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(patch)
    print('Created diff only:', args.output)

if __name__ == '__main__':
    main()
