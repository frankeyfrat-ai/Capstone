import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

from drone_recorder import create_session, save_recording, write_index


class RecorderTests(unittest.TestCase):
    def test_repeated_takes_and_readable_index(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = create_session(Path(directory), "Field Test", {"Session ID": "S001", "Drone": "Example"})
            rows = []
            test = dict(name="Hover 20ft High 50ft Away", label="drone", maneuver="hover",
                        height_ft="20", horizontal_ft="50", radius_ft="", instructions="Hover.")
            audio = np.full((4800, 1), 0.1, dtype=np.float32)
            first, row = save_recording(folder, rows, test, audio, datetime.now(timezone.utc), "", "")
            second, _ = save_recording(folder, rows, test, audio, datetime.now(timezone.utc), "", "")
            self.assertIn("Take_01", first.name)
            self.assertIn("Take_02", second.name)
            self.assertEqual(sf.info(first).subtype, "PCM_24")
            self.assertEqual(sf.info(first).frames, 4800)
            row["Review status"] = "usable"
            write_index(folder, rows)
            with (folder / "Recording_Index.csv").open(encoding="utf-8-sig") as handle:
                entries = list(csv.DictReader(handle))
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["Review status"], "usable")
            self.assertEqual(entries[0]["Peak (dBFS)"], "-20.0")
            self.assertEqual([r['Session ID'] for r in entries], ['S001', 'S001'])
            self.assertEqual([r['Recording ID'] for r in entries], ['T001', 'T002'])
            self.assertTrue((folder / entries[0]["File"]).exists())
            self.assertTrue((folder / "Session_Details.txt").exists())
            with (folder / 'Labels.csv').open(encoding='utf-8-sig') as handle:
                labels = list(csv.DictReader(handle))
            self.assertEqual(labels[0]['session_id'], 'S001')
            self.assertEqual(labels[0]['label'], '')  # Do not guess unconfirmed labels.

    def test_duplicate_session_names_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            first = create_session(Path(directory), "Field Test", {})
            second = create_session(Path(directory), "Field Test", {})
            self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
