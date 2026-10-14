"""Record directly into a readable, shareable session folder."""

import csv
import math
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from excel_tracker import complete_intervals, parse_intervals, read_details, update_tracker
from live_capture import record_live

ROOT = Path(__file__).resolve().parent
COLUMNS = ["File", "Test name", "Label", "Maneuver", "Height above mic (ft)",
           "Horizontal offset (ft)", "Orbit radius (ft)", "Duration (seconds)",
           "Recorded at", "Peak (dBFS)", "RMS (dBFS)", "Quality warnings",
           "Review status", "Setup instructions", "Notes before", "Notes after",
           "Recording ID", "Battery start (%)", "Battery end (%)", "Event intervals (seconds)",
           "Session ID", "Label source"]


def filename(text):
    cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "", text).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)[:80]
    if not cleaned:
        raise ValueError("Enter a name containing letters or numbers.")
    return cleaned


def ask(prompt, default=""):
    result = input(prompt + (f" [{default}]" if default != "" else "") + ": ").strip()
    return result or str(default)


def duration(default=300):
    while True:
        try:
            value = float(ask("Duration in seconds", default))
            if math.isfinite(value) and 1 <= value <= 3600:
                return value
        except ValueError:
            pass
        print("Enter a duration from 1 to 3600 seconds.")


def write_index(folder, rows):
    target = folder / "Recording_Index.csv"
    temporary = folder / "Recording_Index.tmp"
    with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(target)
    write_labels(folder, rows)


def write_labels(folder, rows):
    """Simple CNN handoff: binary interval labels in seconds, plus explicit unlabeled gaps."""
    columns = ['session_id', 'recording_id', 'file', 't_start_s', 't_end_s', 'label',
               'review_status', 'quality_warnings', 'label_source']
    temporary = folder / 'Labels.tmp'
    with temporary.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            seconds = float(row['Duration (seconds)'])
            complete = complete_intervals(row.get('Event intervals (seconds)', ''), seconds)
            for start, end, label in complete:
                writer.writerow(dict(zip(columns, [
                    row.get('Session ID') or folder.name, row['Recording ID'], row['File'],
                    start, end, label, row['Review status'], row['Quality warnings'],
                    row.get('Label source', '')])))
    temporary.replace(folder / 'Labels.csv')


def next_session_id(base):
    used = set()
    for path in base.glob('*/Session_Details.txt'):
        identifier = read_details(path.parent).get('Session ID', '')
        if identifier:
            used.add(identifier)
    index = 1
    while f'S{index:03d}' in used:
        index += 1
    return f'S{index:03d}', used


def choose_monitor(devices):
    if ask('Listen to the UMIK through connected headphones? Y/N', 'n').lower() != 'y':
        return None, 'off', 0
    outputs = [i for i, d in enumerate(devices) if d['max_output_channels'] >= 2]
    for i in outputs:
        print(f"{i}: {devices[i]['name']}")
    airpods = [i for i in outputs if 'airpods' in devices[i]['name'].lower()]
    while True:
        choice = ask('HEADPHONE output number (or N to turn monitoring off)', airpods[0] if airpods else 'n')
        if choice.lower() == 'n':
            return None, 'off', 0
        if choice.isdigit() and int(choice) in outputs:
            monitor = int(choice)
            try:
                sd.check_output_settings(device=monitor, channels=2, samplerate=48000)
                break
            except sd.PortAudioError as error:
                print(f'Output not available at 48 kHz: {error}')
    print('Listening is delayed over Bluetooth. Leave compensation at 0 until measured.')
    while True:
        try:
            delay = float(ask('Measured playback delay compensation, seconds', 0))
            if math.isfinite(delay) and 0 <= delay <= 5:
                return monitor, devices[monitor]['name'], delay
        except ValueError:
            pass
        print('Enter a delay from 0 to 5 seconds.')


def sync_excel(folder, rows):
    try:
        output = update_tracker(folder, rows)
        print(f"Excel updated: {output.name}", flush=True)
    except (OSError, RuntimeError, ValueError, TimeoutError) as error:
        print(f"Excel update failed: {error}\nWAVs and CSV are saved. Close Excel and use T to retry.")


def battery(prompt):
    while True:
        value = ask(prompt + " (blank if unknown/not applicable)")
        if not value:
            return ""
        try:
            result = float(value)
            if math.isfinite(result) and 0 <= result <= 100:
                return result
        except ValueError:
            pass
        print("Enter a battery percentage from 0 to 100, or leave blank.")


def event_intervals(row):
    seconds = float(row['Duration (seconds)'])
    print("Label audible events relative to the beginning of THIS WAV.")
    print("Enter drone or no_drone for the entire file, U if uncertain, or intervals:")
    print("Example: 0-5:no_drone;5-20:drone;20-30:no_drone")
    while True:
        existing = row.get('Event intervals (seconds)', '')
        value = ask("Audible event labels (Enter keeps live markers)", existing or 'u').lower()
        if value == 'u':
            return ""
        if value in {'drone', 'no_drone'}:
            value = f"0-{seconds:g}:{value}"
        try:
            parse_intervals(value, seconds)
            return value
        except ValueError as error:
            print(f"Invalid intervals: {error}")


def create_session(base, name, details):
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder = base / f"{stamp}_{filename(name)}"
    counter = 2
    while folder.exists():
        folder = base / f"{stamp}_{filename(name)}_{counter}"
        counter += 1
    (folder / "Recordings").mkdir(parents=True)
    (folder / "Session_Details.txt").write_text(
        f"SESSION: {name}\nCreated: {datetime.now().astimezone().isoformat()}\n\n"
        + "\n".join(f"{key}: {value}" for key, value in details.items()) + "\n"
    )
    (folder / "START_HERE.txt").write_text(
        "DRONE AUDIO RECORDINGS\n\n"
        "Recordings/: clearly named, unprocessed 48 kHz / 24-bit mono WAV files.\n"
        "Recording_Index.csv: one row per take with labels, positions, quality and notes.\n"
        "Labels.csv: session ID, recording ID, WAV, start/end seconds and drone/no_drone labels.\n"
        "Dataset_Tracker.xlsx: your team's Session Sheet and Event Log, filled automatically.\n"
        "Session_Details.txt: microphone, drone, site, weather and gain information.\n\n"
        "Share this entire session folder with the CNN team.\n"
        "Session ID is shared by all takes in this visit. Keep sessions together when splitting data.\n"
        "Height is above the microphone; offset is horizontal, not direct distance.\n"
        "Review repeat, uncertain, unreviewed and quality-warning takes before training.\n"
        "Use Labels.csv intervals for training; a drone-collection WAV may include no_drone intervals.\n"
        "Blank labels are unconfirmed and must be excluded. Review transitions for human/Bluetooth delay.\n"
        "Positions in the index are planned; conditions may vary during five-minute flights.\n"
    )
    write_index(folder, [])
    return folder


def save_recording(folder, rows, test, audio, started, status, notes, battery_start="", intervals=""):
    name = filename(test["name"])
    take = 1 + sum(row["Test name"] == test["name"] for row in rows)
    identifier = f"T{len(rows) + 1:03d}"
    session_id = read_details(folder).get('Session ID') or folder.name
    label = 'no_drone' if test['label'] in {'background', 'no_drone'} else 'drone'
    wav = folder / "Recordings" / f"{filename(session_id)}_{identifier}_{name}_{label}_Take_{take:02d}.wav"
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    db = lambda value: round(20 * math.log10(value), 1) if value > 0 else "silent"
    warnings = []
    if peak >= 0.99:
        warnings.append("Near clipping")
    if peak == 0:
        warnings.append("Silent recording")
    if status:
        warnings.append(f"Capture error: {status}")
    row = dict(zip(COLUMNS, [
        wav.relative_to(folder).as_posix(), test["name"], label, test["maneuver"],
        test["height_ft"], test["horizontal_ft"], test["radius_ft"], len(audio) / 48000,
        started.isoformat(), db(peak), db(rms), "; ".join(warnings), "unreviewed",
        test["instructions"], notes, "", identifier, battery_start, "", intervals,
        session_id, 'live manual markers' if intervals else 'unconfirmed',
    ]))
    sf.write(wav, audio, 48000, subtype="PCM_24")
    rows.append(row)
    write_index(folder, rows)
    return wav, row


def custom_test():
    name = ask("Test name (example: Hover 20ft high 50ft away)")
    filename(name)
    label = ask("Collection type: drone or no_drone", "drone").lower()
    if label not in {"drone", "no_drone"}:
        raise ValueError("Choose drone or no_drone.")
    return dict(name=name, label=label, maneuver=ask("Maneuver or background source", "hover"),
                height_ft=ask("Height ABOVE MICROPHONE in ft (blank if unknown)"),
                horizontal_ft=ask("Horizontal offset / closest approach in ft (blank if unknown)"),
                radius_ft=ask("Orbit radius in ft (blank unless orbit)"),
                duration_s=duration(), instructions=ask("Setup instructions"))


def main():
    print("DRONE RECORDER — files saved directly in Dataset/<session>/Recordings")
    devices = sd.query_devices()
    inputs = [i for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    if not inputs:
        raise ValueError("Connect the microphone; no input devices were found.")
    for i in inputs:
        print(f"{i}: {devices[i]['name']}")
    umik = [i for i in inputs if "umik" in devices[i]["name"].lower()]
    while True:
        choice = ask("Microphone number", umik[0] if umik else "")
        if choice.isdigit() and int(choice) in inputs:
            device = int(choice)
            break
        print("Choose a listed microphone number.")
    sd.check_input_settings(device=device, samplerate=48000, channels=1)
    monitor, monitor_name, marker_delay = choose_monitor(devices)
    name = ask("Session name", "Field Test")
    default_id, used = next_session_id(ROOT / 'Dataset')
    while True:
        session_id = ask('Session ID shared by this visit’s recordings', default_id)
        if session_id not in used and filename(session_id) == session_id:
            break
        print('Use an unused session ID containing letters, numbers, underscores or hyphens.')
    details = {"Session ID": session_id, "Microphone": devices[device]["name"],
               'Listening output': monitor_name, 'Marker delay compensation (seconds)': marker_delay}
    for key in ["Mic serial number", "Drone model and propellers", "Location", "Weather and wind",
                "Mic height above ground (ft)", "Analog gain (dB)", "Software input level", "Windscreen"]:
        details[key] = ask(key, "unknown")
    folder = create_session(ROOT / "Dataset", name, details)
    rows = []
    sync_excel(folder, rows)
    with (ROOT / "drone_test_plan.csv").open(newline="") as handle:
        plan = list(csv.DictReader(handle))
    print(f"\nYour shareable folder:\n{folder}")
    while True:
        print("\nFIVE-MINUTE COLLECTIONS: B = no drone | F = drone flight with live markers")
        print("PLANNED TESTS")
        for i, test in enumerate(plan, 1):
            print(f"{i}: {test['name']}")
        choice = ask("Choose B, F, test number, C for custom, T for Excel, or Q to finish", "b").lower()
        if choice == "t":
            sync_excel(folder, rows)
            continue
        if choice == "q":
            print(f"\nShare this entire folder:\n{folder}\n{len(rows)} recordings saved.")
            return
        try:
            if choice in {'b', 'f'}:
                test = dict(name='No Drone 5 Minutes' if choice == 'b' else 'Drone Flight 5 Minutes',
                            label='no_drone' if choice == 'b' else 'drone', maneuver='ambient' if choice == 'b' else 'varied_flight',
                            height_ft='', horizontal_ft='', radius_ft='', duration_s=300,
                            instructions='Keep drone motors off. Record background conditions.' if choice == 'b' else
                            'Fly under varied conditions. Mark audible/inaudible changes while recording.')
            elif choice == "c":
                test = custom_test()
            elif choice.isdigit() and 1 <= int(choice) <= len(plan):
                test = plan[int(choice) - 1]
            else:
                print("Choose B, F, a listed number, C, T, or Q.")
                continue
            print(f"\nTEST: {test['name']}\n{test['instructions']}")
            print(f"Height above mic: {test['height_ft'] or 'unknown'} ft | "
                  f"Horizontal offset: {test['horizontal_ft'] or 'unknown'} ft | "
                  f"Orbit radius: {test['radius_ft'] or 'not applicable'} ft")
            seconds = duration(test["duration_s"])
            notes = ask("Notes before recording")
            battery_start = battery("Battery % before this take")
            initial = ask('At recording start: audible drone D or no audible drone N', 'n').lower()
            if initial not in {'d', 'n'}:
                raise ValueError('Initial state must be D or N.')
            if ask("Position drone. Enter R to record or S to skip", "r").lower() != "r":
                continue
            print("Starting in 3 seconds. Keep quiet near the mic.", flush=True)
            time.sleep(3)
            try:
                audio, started, status, intervals = record_live(seconds, device,
                    'drone' if initial == 'd' else 'no_drone', monitor, marker_delay)
            except KeyboardInterrupt:
                sd.stop()
                print("Take cancelled; partial audio discarded.")
                continue
            wav, row = save_recording(folder, rows, test, audio, started, status, notes, battery_start, intervals)
            print(f"\nSaved: {wav.name}\nPEAK: {row['Peak (dBFS)']} dBFS")
            if row["Quality warnings"]:
                print(row["Quality warnings"])
            sync_excel(folder, rows)
            review = ask("Review: usable, repeat, or uncertain", "usable").lower()
            row["Review status"] = review if review in {"usable", "repeat", "uncertain"} else "uncertain"
            write_index(folder, rows)
            row["Notes after"] = ask("Actual setup / audible intervals / interruptions (example: drone audible 5-22 s)")
            write_index(folder, rows)
            row["Battery end (%)"] = battery("Battery % after this take")
            write_index(folder, rows)
            previous = row["Event intervals (seconds)"]
            row["Event intervals (seconds)"] = event_intervals(row)
            if previous != row["Event intervals (seconds)"]:
                row["Label source"] = 'manual review' if row["Event intervals (seconds)"] else 'unconfirmed'
            write_index(folder, rows)
            sync_excel(folder, rows)
        except (ValueError, sd.PortAudioError) as error:
            print(f"Unable to record: {error}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sd.stop()
        print("\nClosed. Completed recordings and their index are already saved.")
    except (ValueError, sd.PortAudioError) as error:
        raise SystemExit(str(error))
