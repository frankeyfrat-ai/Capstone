import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import csv
import hashlib

import numpy as np

from drone_recorder import create_session, save_recording
from excel_tracker import parse_intervals, tracker_payload, update_tracker
from review_recordings import apply_review


def worksheet_cells(path, sheet):
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(path) as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(x.itertext()) for x in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        result = {}
        for cell in ET.fromstring(archive.read(sheet)).findall('.//m:sheetData/m:row/m:c', ns):
            value, inline = cell.find('m:v', ns), cell.find('m:is', ns)
            text = value.text if value is not None else ''.join(inline.itertext()) if inline is not None else ''
            if cell.get('t') == 's':
                text = shared[int(text)]
            result[cell.attrib['r']] = text
        return result


class TrackerTests(unittest.TestCase):
    def test_pending_then_reviewed_labels_update_saved_excel_and_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            details = {'Session ID': 'S009', 'Microphone': 'UMIK-2',
                       'Mic height above ground (ft)': '4', 'Location': 'Field Alpha',
                       'Weather and wind': 'Clear; wind 3 kt', 'Drone model and propellers': 'Test Drone',
                       'Windscreen': 'yes'}
            folder = create_session(Path(directory), 'Review workflow', details)
            rows = []
            test = dict(name='Flight', label='drone', maneuver='flyby', height_ft='20',
                        horizontal_ft='50', radius_ft='', instructions='Fly past mic.')
            wav, row = save_recording(folder, rows, test, np.full((48000, 1), .1, dtype=np.float32),
                                      datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc), '', 'initial note', 90)
            row['Battery end (%)'] = 0  # Zero must not become unknown.
            row['Draft bookmarks (seconds)'] = '0-0.5:no_drone;0.5-1:drone'
            original_hash = hashlib.sha256(wav.read_bytes()).hexdigest()
            path = update_tracker(folder, rows)
            with ZipFile(path) as archive:
                ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                for sheet in ('sheet1', 'sheet2'):
                    root = ET.fromstring(archive.read(f'xl/worksheets/{sheet}.xml'))
                    link = root.find('.//m:hyperlink[@ref="A2"]', ns)
                    link_id = link.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                    rels = ET.fromstring(archive.read(f'xl/worksheets/_rels/{sheet}.xml.rels'))
                    relation = next(r for r in rels if r.get('Id') == link_id)
                    self.assertEqual(relation.get('Target'), row['File'])
                    self.assertNotIn(str(folder), relation.get('Target'))
            # A moved session retains valid relative link targets.
            import shutil
            moved = Path(directory) / 'Moved Session'
            shutil.copytree(folder, moved)
            self.assertTrue((moved / row['File']).is_file())
            session = worksheet_cells(path, 'xl/worksheets/sheet1.xml')
            event = worksheet_cells(path, 'xl/worksheets/sheet2.xml')
            self.assertEqual(session['A2'], 'S009')
            self.assertEqual(session['D2'], 'Field Alpha')
            self.assertEqual(session['E2'], 'Clear; wind 3 kt')
            self.assertEqual(session['F2'], 'Test Drone')
            self.assertEqual(session['G2'], '90 / 0')
            self.assertEqual(session['K2'], 'Y')
            self.assertAlmostEqual(float(session['L2']) * 86400, 1)
            self.assertEqual(event.get('D2', ''), '')
            self.assertIn('Label pending', event['G2'])
            # Review includes an uncertain gap, which must stay blank in both handoff files.
            apply_review(folder, rows, row, '0-0.25:no_drone;0.5-1:drone', 'Reviewed in audio editor')
            event = worksheet_cells(path, 'xl/worksheets/sheet2.xml')
            self.assertEqual([event.get(f'D{i}', '') for i in (2, 3, 4)], ['no_drone', '', 'drone'])
            self.assertAlmostEqual(float(event['B4']) * 86400, .5)
            self.assertAlmostEqual(float(event['C4']) * 86400, 1)
            self.assertEqual(event['A4'], 'S009')
            self.assertIn('Reviewed in audio editor', event['G4'])
            with (folder / 'Labels.csv').open(encoding='utf-8-sig') as handle:
                labels = list(csv.DictReader(handle))
            self.assertEqual([r['label'] for r in labels], ['no_drone', '', 'drone'])
            self.assertEqual(labels[-1]['session_id'], 'S009')
            self.assertEqual(hashlib.sha256(wav.read_bytes()).hexdigest(), original_hash)

    def test_intervals_validate_boundaries_and_overlap(self):
        self.assertEqual(parse_intervals('0-5:no_drone;5-10:drone', 10),
                         [(0, 5, 'no_drone'), (5, 10, 'drone')])
        for bad in ['0-11:drone', '0-6:drone;5-10:no_drone', '0-10:ambient', 'nan-10:drone']:
            with self.assertRaises(ValueError):
                parse_intervals(bad, 10)

    def test_two_takes_write_both_sheets_and_preserve_reference_list(self):
        with tempfile.TemporaryDirectory() as directory:
            details = {'Session ID': 'S001', 'Microphone': 'UMIK-2', 'Mic height above ground (ft)': '4',
                       'Location': 'Test field', 'Windscreen': 'yes'}
            folder = create_session(Path(directory), 'Test', details)
            rows = []
            test = dict(name='Hover', label='drone', maneuver='hover', height_ft='20',
                        horizontal_ft='50', radius_ft='', instructions='Hover.')
            for _ in range(2):
                _, row = save_recording(folder, rows, test, np.zeros((48000, 1), dtype=np.float32),
                                        datetime.now(timezone.utc), '', '', 90)
                row['Battery end (%)'] = 85
                row['Event intervals (seconds)'] = '0-0.5:no_drone;0.5-1:drone'
            payload = tracker_payload(rows, details, folder)
            self.assertEqual([r[0] for r in payload['sessions']], ['S001', 'S001'])
            self.assertAlmostEqual(payload['sessions'][0][8], 1.2192)
            self.assertAlmostEqual(payload['events'][0][4], 15.24)
            self.assertAlmostEqual(payload['events'][0][5], 7.3152)
            self.assertAlmostEqual(payload['events'][1][2] * 86400, 1)
            path = update_tracker(folder, rows)
            ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            with ZipFile(path) as archive:
                sheets = ET.fromstring(archive.read('xl/workbook.xml')).find('m:sheets', ns)
                self.assertEqual([s.attrib['name'] for s in sheets], ['Session Sheet', 'Event Log'])
                self.assertEqual(len([p for p in archive.namelist() if p.startswith('xl/tables/') and p.endswith('.xml')]), 2)
                shared = []
                if 'xl/sharedStrings.xml' in archive.namelist():
                    shared = [''.join(x.itertext()) for x in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
                def cells(sheet):
                    result = {}
                    for cell in ET.fromstring(archive.read(sheet)).findall('.//m:sheetData/m:row/m:c', ns):
                        value = cell.find('m:v', ns)
                        inline = cell.find('m:is', ns)
                        text = value.text if value is not None else ''.join(inline.itertext()) if inline is not None else ''
                        if cell.get('t') == 's':
                            text = shared[int(text)]
                        result[cell.attrib['r']] = text
                    return result
                session = cells('xl/worksheets/sheet1.xml')
                event = cells('xl/worksheets/sheet2.xml')
                self.assertEqual(session['A3'], 'S001')
                self.assertEqual(event['D2'], 'no_drone')
                self.assertEqual(event['D3'], 'drone')
                self.assertEqual(event['A5'], 'S001')
                self.assertEqual(event['M2'], 'ambient')
                self.assertEqual(event['M10'], 'negative_train')


if __name__ == '__main__':
    unittest.main()
