"""Apply reviewed labels to a saved session and refresh CSVs and Excel."""

import argparse
import csv
from pathlib import Path

from drone_recorder import ROOT, ask, event_intervals, sync_excel, write_index


def apply_review(folder, rows, row, intervals, notes):
    from excel_tracker import parse_intervals
    parse_intervals(intervals, float(row['Duration (seconds)']))
    row['Event intervals (seconds)'] = intervals
    row['Label source'] = 'manual review' if intervals else 'unconfirmed'
    row['Notes after'] = notes
    write_index(folder, rows)
    sync_excel(folder, rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session_folder', type=Path, nargs='?')
    args = parser.parse_args()
    if args.session_folder is None:
        sessions = sorted((ROOT / 'Dataset').glob('*/Recording_Index.csv'))
        if not sessions:
            raise SystemExit('No recorded sessions found in Dataset.')
        for index, path in enumerate(sessions, 1):
            print(f'{index}: {path.parent.name}')
        while True:
            choice = ask('Session number to review')
            if choice.isdigit() and 1 <= int(choice) <= len(sessions):
                args.session_folder = sessions[int(choice) - 1].parent
                break
            print('Choose a listed session number.')
    folder = args.session_folder.resolve()
    with (folder / 'Recording_Index.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    # Support earlier recorder indexes without the draft column.
    for row in rows:
        row.setdefault('Draft bookmarks (seconds)', '')
    while True:
        for row in rows:
            print(f"{row['Recording ID']}: {row['Test name']} | {row['Duration (seconds)']}s | {row['Label source']}")
        choice = ask('Recording ID to label, T to refresh Excel, or Q to finish', 'q')
        if choice.lower() == 'q':
            return
        if choice.lower() == 't':
            sync_excel(folder, rows)
            continue
        row = next((row for row in rows if row['Recording ID'].lower() == choice.lower()), None)
        if row is None:
            print('Choose a listed recording ID.')
            continue
        print(f"Review WAV: {folder / row['File']}")
        print('Use your audio editor to listen and inspect the spectrogram. Times below are seconds from WAV start.')
        if row.get('Draft bookmarks (seconds)'):
            print('Draft bookmarks (not training labels): ' + row['Draft bookmarks (seconds)'])
        intervals = event_intervals(row)
        notes = ask('Review notes', row.get('Notes after', ''))
        apply_review(folder, rows, row, intervals, notes)


if __name__ == '__main__':
    main()
