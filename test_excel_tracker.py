import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import numpy as np

from drone_recorder import create_session, save_recording
from excel_tracker import parse_intervals, tracker_payload, update_tracker


class TrackerTests(unittest.TestCase):
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
