import csv
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np

from drone_recorder import create_session, save_recording
from live_capture import RATE, Timeline, interval_text, record_live
from excel_tracker import complete_intervals


class LiveTests(unittest.TestCase):
    def test_unknown_gaps_are_explicit(self):
        self.assertEqual(complete_intervals('2-5:drone', 10),
                         [(0, 2, None), (2, 5, 'drone'), (5, 10, None)])

    def test_record_only_ignores_marking_keys_and_leaves_labels_pending(self):
        class Stream:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, frames):
                return np.zeros((frames, 1), dtype=np.float32), False
        @contextmanager
        def keys():
            yield 7
        with patch('live_capture.single_keys', keys), patch('live_capture.sd.InputStream', Stream), \
             patch('live_capture.select.select', side_effect=[([7], [], []), ([], [], [])]), \
             patch('live_capture.os.read', return_value=b'd'):
            audio, _, _, text = record_live(0.01, 1, enable_marking=False)
        self.assertEqual(len(audio), 480)
        self.assertEqual(text, '')

    def test_five_minute_timeline_round_trips_and_csv_labels(self):
        timeline = Timeline('no_drone')
        timeline.mark(10 * RATE, 'drone')
        timeline.mark(80 * RATE, 'no_drone')
        timeline.mark(90 * RATE, 'drone')
        timeline.mark(90 * RATE, 'drone')  # Duplicate key is harmless.
        intervals = timeline.intervals(300 * RATE)
        self.assertEqual(intervals, [(0, 10, 'no_drone'), (10, 80, 'drone'),
                                    (80, 90, 'no_drone'), (90, 300, 'drone')])
        with tempfile.TemporaryDirectory() as directory:
            folder = create_session(Path(directory), 'Field', {'Session ID': 'S003'})
            test = dict(name='Drone Flight', label='drone', maneuver='varied',
                        height_ft='', horizontal_ft='', radius_ft='', instructions='Fly.')
            # One second is sufficient to check actual storage; use scaled intervals.
            timeline = Timeline('no_drone')
            timeline.mark(RATE // 2, 'drone')
            save_recording(folder, [], test, np.zeros((RATE, 1), dtype=np.float32),
                           datetime.now(timezone.utc), '', '', intervals=interval_text(timeline.intervals(RATE)))
            with (folder / 'Labels.csv').open(encoding='utf-8-sig') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([r['label'] for r in rows], ['no_drone', 'drone'])
            self.assertEqual(rows[1]['t_start_s'], '0.5')
            self.assertEqual(rows[1]['session_id'], 'S003')

    def test_capture_uses_selected_mic_and_headphones_and_exact_frame_count(self):
        opened = []
        class Stream:
            def __init__(self, **kwargs):
                opened.append(kwargs)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, frames):
                return np.full((frames, 1), 0.1, dtype=np.float32), False
            def write(self, block):
                self.assertion = block.shape[1] == 2
                return False
        @contextmanager
        def keys():
            yield 0
        with patch('live_capture.single_keys', keys), patch('live_capture.sd.InputStream', Stream), \
             patch('live_capture.sd.OutputStream', Stream), patch('live_capture.select.select', return_value=([], [], [])):
            audio, _, status, text = record_live(0.05, device=7, initial_label='no_drone', monitor_device=9)
        self.assertEqual(len(audio), 2400)
        self.assertEqual(opened[0]['device'], 9)
        self.assertEqual(opened[1]['device'], 7)
        self.assertEqual(text, '0.000000000-0.050000000:no_drone')
        self.assertEqual(status, '')

    def test_keys_mark_audio_frames_and_apply_measured_delay(self):
        class Stream:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, frames):
                return np.zeros((frames, 1), dtype=np.float32), False
        @contextmanager
        def keys():
            yield 7
        readiness = [([7], [], []), ([], [], []), ([7], [], []), ([], [], []), ([], [], [])]
        with patch('live_capture.single_keys', keys), patch('live_capture.sd.InputStream', Stream), \
             patch('live_capture.select.select', side_effect=readiness), patch('live_capture.os.read', side_effect=[b'd', b'n']):
            audio, _, _, text = record_live(3072 / RATE, 1, 'no_drone', marker_delay_s=0.005)
        from excel_tracker import parse_intervals
        intervals = parse_intervals(text, len(audio) / RATE)
        self.assertEqual([label for _, _, label in intervals], ['no_drone', 'drone', 'no_drone'])
        self.assertAlmostEqual(intervals[0][1], (1024 - 240) / RATE, places=8)
        self.assertAlmostEqual(intervals[1][1], (2048 - 240) / RATE, places=8)


if __name__ == '__main__':
    unittest.main()
