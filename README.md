# Drone field recorder

Run in VS Code's terminal:

```bash
python3 -m pip install -r requirements.txt
python3 drone_recorder.py
```

Choose the UMIK-2 input. If desired, enable listening and select your connected AirPods Max as the output. Name the field visit and choose a session ID (the program suggests the next unused S001/S002/etc.). All recordings from this visit share that session ID. Each WAV gets a separate T001/T002/etc. recording ID. Allow VS Code microphone access if prompted.

Choose **B** for a five-minute background clip, **F** for a five-minute drone flight under varied conditions, a planned test number, or **C** for a custom test. The duration is adjustable. Live listening is optional and defaults off. Live bookmarks are optional and default off too. With the default settings, simply position the drone and enter **R**; recording starts after three seconds and all flight labels remain pending later review. During capture, keep the integrated terminal focused:

- **D/N/Space:** optional draft audible/inaudible bookmarks, only if enabled before capture. These are not verified training labels.
- **Q:** stop early and save the captured portion.
- **Ctrl+C:** cancel this take and discard its partial audio.

These keys take effect immediately; no Enter is needed. Marking does not pause or mute the WAV. Completed recordings and the index are saved before post-take notes. A background take is labeled no_drone only if you explicitly confirm no drone was audible anywhere in it. Otherwise, labels remain blank. At the main menu, **Q** finishes the session. A take being marked usable describes capture quality, not verification of its acoustic labels.

## Review labels afterward

```bash
python3 review_recordings.py
```

Select a saved session and recording ID. Listen to the WAV and inspect its spectrogram in your audio editor, then enter confirmed time intervals in the program. Example for a 300-second recording: `0-80:drone;100-300:drone` leaves 80–100 seconds unlabeled if ambiguous. Enter `drone` or `no_drone` to label a whole file, or `U` to leave it pending. Draft live bookmarks are displayed as reference only; enter corrected intervals after review. The reviewer automatically updates `Recording_Index.csv`, `Labels.csv`, and both Excel sheets. It does not alter or split the WAV. You can also pass a session path directly: `python3 review_recordings.py "Dataset/your_session_folder"`.

## CNN labels and AirPods listening

`Labels.csv` is the simple handoff file: `session_id`, `recording_id`, `file`, `t_start_s`, `t_end_s`, `label`, review status, quality warnings, and label source. Times are seconds relative to each WAV. Labels are exactly `drone` or `no_drone`; blank means unconfirmed and must be excluded. A drone-collection WAV can include both labels. Use these interval labels instead of treating the whole file's collection type as ground truth. Rows cover the whole recording, including explicitly unlabeled gaps after manual edits.

The index's `Label` column and the WAV name describe the planned collection type, not verified labels for every second. The CNN should use `Labels.csv` after review and skip its blank labels. An inaudible drone is not automatically confirmed absent: uncertain low-signal intervals should remain unlabeled rather than become negative training examples. `Draft bookmarks (seconds)` preserves optional live marks separately for review.

AirPods Max are monitoring output only; their microphone is not used. The WAV stores the UMIK signal before headphone playback. Bluetooth playback and human reaction add delay, so review boundaries before training and consider excluding windows near transitions. The program accepts a measured playback-delay compensation in seconds; leave it at zero until measured, rather than guessing. Compensation shifts manual markers earlier but does not modify the audio. The AirPods Digital Crown is not bound to labels; use D/N/Space on the keyboard. There is no automatic detection or calibrated audibility threshold. Monitor at a fixed comfortable volume so the manual audibility criterion stays consistent. Label ambiguous sections as unconfirmed during review.

## Automatic Excel tracker

Click **Play audio** in Notes (or the blue **ID** cell) in either sheet to open that row's WAV in your default audio player. The long filename stays in the hyperlink target rather than appearing in Notes. The links use relative `Recordings/...wav` paths: keep the workbook and its Recordings folder together when sharing, and extract a ZIP before opening the workbook. Excel may request permission to open the linked file.

Every new session includes `Dataset_Tracker.xlsx`, using your friend's two original sheets and table formatting. The original workbook is retained in `templates/dataset_tracker.xlsx`. No extra Python packages are required. Excel generation uses Artifact Tool and the Node runtime installed with Codex on this Mac. After a fresh checkout, the program creates a local `.tracker_runtime/node_modules` link to that runtime automatically; this machine-specific link is excluded from Git. A different computer needs that dependency configured before tracker generation works. Without it, WAV and CSV collection remain available and the program reports the Excel update failure.

- **Session Sheet:** one row per WAV with the shared session ID; date, time, site, weather, drone, battery start/end, microphone, microphone height above ground in meters, horizontal offset/orbit radius in meters, windscreen Y/N, measured recording duration, and notes identifying the WAV and its recording ID.
- **Event Log:** the matching shared session ID, file-relative start/end times, confirmed `drone`/`no_drone` labels, planned horizontal distance in meters, and planned drone altitude above ground in meters. Notes identify which WAV and recording ID each event belongs to. Altitude is microphone height above ground plus drone height above the microphone. Unknown values remain blank. During varied-condition five-minute flights, positions stay unknown unless you supply a planned value; this is not flight telemetry.

Enter battery percentages before/after a take or leave them blank. Flight labels stay pending until you use the reviewer. Reviewer inputs are seconds from the start of that WAV; intervals must not overlap or exceed its duration. Unspecified gaps remain explicitly unlabeled in both CSV and Excel. Legacy background/mixed test-plan entries are accepted and mapped to no_drone/drone collection types, respectively.

Excel date/time/duration cells are numeric, not text. Event times and Total Time display as elapsed minutes:seconds. If a data loader reads raw Excel values, multiply duration/time fractions by 86,400 to obtain seconds. Battery start/end is a text pair because that is the supplied template's combined column. The event-label reference list in column M is preserved; template example entries are replaced by actual recording data.

The tracker updates after capture and after annotations. Keep it closed in Excel while recording. **T** refreshes it if a save failed. The CSV and session text are the authoritative inputs: refreshing rebuilds the generated tracker, so manual tracker edits are not retained. To rebuild an existing visit, run:

```bash
python3 excel_tracker.py "Dataset/your_session_folder"
```

Everything is readable from the moment it is saved:

```text
Dataset/
  2026-10-14_11-00-00_Field_Test/
    START_HERE.txt
    Session_Details.txt
    Recording_Index.csv
    Labels.csv
    Dataset_Tracker.xlsx
    Recordings/
      S001_T001_No_Drone_5_Minutes_no_drone_Take_01.wav
      S001_T002_Drone_Flight_5_Minutes_drone_Take_01.wav
```

Share the entire session folder. No export or conversion is needed. To email it as one attachment, right-click the session folder in Finder and choose **Compress**. Recordings are unprocessed 48 kHz / 24-bit mono WAV. `Recording_Index.csv` has one row per take with filename, label, distances, duration, peak/RMS, quality warnings and notes. Session details are in plain text. CSV is also readable by the CNN team's Python tools. Names and timestamps are examples; the program generates the actual values.

Edit `drone_test_plan.csv` to pre-name your tests. Keep its header and quote text containing commas. Height means vertical distance **above the microphone**. Horizontal offset means hover offset or a straight pass's closest horizontal approach. Orbit radius is a separate value. Positions are planned values; record actual deviations, speed and direction in notes. A microphone 4 ft above ground with a drone 20 ft above it means drone altitude is 24 ft above ground.

Start with 3–5 independent takes per setup across at least three field visits. Adjust distances to the intended detection range. Collect comparable drone-free recordings, including naturally occurring voices, wind, birds, traffic and machinery, across the same visits. Keep the same microphone placement and gain within a session; document changes. Use a windscreen, check the loudest/closest pass for clipping, and keep the operator away from the microphone and flight path. These are starting collection targets; model evaluation determines how much more data is needed.

Retain original files and flag unusable takes rather than treating them as clean training examples. Keep all takes with the same session ID together when splitting training, validation and test data before cutting short audio windows. Five-minute mono 48 kHz / 24-bit WAVs are about 43.2 MB each; a pair is about 86.4 MB before ZIP compression, so a shared download link may be more practical than an email attachment. No CNN, flight control, calibration processing or automated time labeling is included.
