"""Map recorder fields into the supplied two-sheet Excel template."""

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / 'templates' / 'dataset_tracker.xlsx'
RUNTIME_NODE = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'


def numeric(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def meters(value):
    value = numeric(value)
    return round(value * 0.3048, 4) if value is not None else None


def parse_intervals(text, seconds):
    """Parse non-overlapping file-relative intervals; gaps stay unlabeled."""
    if not text.strip():
        return []
    intervals = []
    for item in text.split(';'):
        bounds, label = item.strip().split(':')
        start, end = map(float, bounds.split('-'))
        label = label.strip().lower()
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= seconds):
            raise ValueError('Intervals must lie within the WAV duration with start < end.')
        if label not in {'drone', 'no_drone'}:
            raise ValueError('Interval labels must be drone or no_drone.')
        intervals.append((start, end, label))
    intervals.sort()
    if any(a[1] > b[0] for a, b in zip(intervals, intervals[1:])):
        raise ValueError('Intervals must not overlap.')
    return intervals


def read_details(folder):
    details = {}
    for line in (folder / 'Session_Details.txt').read_text().splitlines():
        if ': ' in line:
            key, value = line.split(': ', 1)
            details[key] = value
    return details


def complete_intervals(text, seconds):
    complete, position = [], 0
    for start, end, label in parse_intervals(text, seconds):
        if start > position:
            complete.append((position, start, None))
        complete.append((start, end, label))
        position = end
    if position < seconds:
        complete.append((position, seconds, None))
    return complete


def tracker_payload(rows, details, folder):
    sessions, events = [], []
    for index, row in enumerate(rows, 1):
        identifier = row.get('Session ID') or details.get('Session ID') or folder.name
        recording_id = row.get('Recording ID') or f'T{index:03d}'
        date = datetime.fromisoformat(row['Recorded at'])
        excel_date = (date.date() - datetime(1899, 12, 30).date()).days
        excel_time = (date.hour * 3600 + date.minute * 60 + date.second + date.microsecond / 1e6) / 86400
        seconds = float(row['Duration (seconds)'])
        offset = row['Horizontal offset (ft)'] or row['Orbit radius (ft)']
        height = meters(details.get('Mic height above ground (ft)'))
        drone_height = numeric(row['Height above mic (ft)'])
        ground_height = numeric(details.get('Mic height above ground (ft)'))
        altitude = meters(drone_height + ground_height) if drone_height is not None and ground_height is not None else None
        wind = details.get('Windscreen', '').lower()
        wind = 'Y' if wind in {'y', 'yes'} else 'N' if wind in {'n', 'no'} else None
        start_battery, end_battery = row.get('Battery start (%)', ''), row.get('Battery end (%)', '')
        battery = f'{"unknown" if start_battery in ("", None) else start_battery} / {"unknown" if end_battery in ("", None) else end_battery}'
        notes = '\n'.join(part for part in [
            f"File: {row['File']}", f"Test: {row['Test name']}",
            f'Recording: {recording_id}',
            f"Label source: {row.get('Label source', 'unconfirmed')}",
            'Height: mic above ground (m). Distance: horizontal offset/radius (m).',
            f"Scenario: {row['Label']}; maneuver: {row['Maneuver']}; review: {row['Review status']}",
            f"Peak: {row['Peak (dBFS)']} dBFS; {row['Quality warnings']}",
            row.get('Notes before', ''), row.get('Notes after', '')] if part)
        sessions.append([identifier, excel_date, excel_time, details.get('Location'),
                         details.get('Weather and wind'), details.get('Drone model and propellers'),
                         battery, details.get('Microphone'), height, meters(offset), wind,
                         seconds / 86400, notes])
        text = row.get('Event intervals (seconds)', '')
        # Older CSVs and unreviewed takes are left unlabeled, not guessed.
        intervals = complete_intervals(text, seconds)
        for start, end, label in intervals:
            event_notes = f"File: {row['File']}\nRecording: {recording_id}\nManeuver: {row['Maneuver']}; review: {row['Review status']}"
            event_notes += f"\nLabel source: {row.get('Label source', 'unconfirmed')}"
            if row.get('Draft bookmarks (seconds)'):
                event_notes += '\nDraft bookmarks are in Recording_Index.csv; they are not training labels.'
            if not label:
                event_notes += '\nLabel pending: confirm audible intervals before training.'
            if row.get('Notes after'):
                event_notes += '\n' + row['Notes after']
            events.append([identifier, start / 86400, end / 86400, label, meters(offset), altitude, event_notes])
    if len(sessions) > 2579 or len(events) > 6381:
        raise ValueError('Session exceeds the template table capacity; start a new field visit.')
    return {'sessions': sessions, 'events': events}


def update_tracker(folder, rows, preview_dir=None):
    folder = Path(folder)
    payload = tracker_payload(rows, read_details(folder), folder)
    state = folder / '.tracker_data.json'
    state.write_text(json.dumps(payload, allow_nan=False))
    output = folder / 'Dataset_Tracker.xlsx'
    if output.with_name('~$' + output.name).exists():
        raise RuntimeError('Close Dataset_Tracker.xlsx in Excel before refreshing it.')
    module_link = ROOT / '.tracker_runtime' / 'node_modules'
    if not module_link.exists():
        dependencies = RUNTIME_NODE.parent.parent / 'node_modules'
        if not (dependencies / '@oai' / 'artifact-tool').exists():
            raise RuntimeError('Artifact Tool runtime not found. WAV and CSV recording still works; see README for Excel setup.')
        if module_link.is_symlink():
            module_link.unlink()
        module_link.symlink_to(dependencies, target_is_directory=True)
    # Artifact Tool runs from the supplied Codex runtime; no extra Python dependency.
    node = os.environ.get('DRONE_TRACKER_NODE') or shutil.which('node') or str(RUNTIME_NODE)
    command = [node, str(ROOT / '.tracker_runtime' / 'fill_tracker.mjs'),
               str(TEMPLATE), str(output), str(state)]
    if preview_dir:
        command.append(str(preview_dir))
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('Tracker update timed out; use T to retry.') from error
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[-1500:] or 'Excel tracker update failed.')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session_folder', type=Path)
    parser.add_argument('--preview-dir', type=Path)
    args = parser.parse_args()
    with (args.session_folder / 'Recording_Index.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    print(update_tracker(args.session_folder, rows, args.preview_dir))


if __name__ == '__main__':
    main()
