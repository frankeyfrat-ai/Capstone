"""Add native relative WAV hyperlinks, a capability missing from Artifact Tool."""

import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE = 'http://schemas.openxmlformats.org/package/2006/relationships'
TYPE = REL + '/hyperlink'
MC = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
EXTENSIONS = {
    'x14ac': 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac',
    'xr': 'http://schemas.microsoft.com/office/spreadsheetml/2014/revision',
    'xr2': 'http://schemas.microsoft.com/office/spreadsheetml/2015/revision2',
    'xr3': 'http://schemas.microsoft.com/office/spreadsheetml/2016/revision3',
}
NS = {'m': MAIN}
ET.register_namespace('x', MAIN)
ET.register_namespace('r', REL)
ET.register_namespace('mc', MC)
for prefix, uri in EXTENSIONS.items():
    ET.register_namespace(prefix, uri)


def serialize_sheet(root):
    # ElementTree drops unused namespace declarations, but mc:Ignorable contains
    # prefix names as text. Keep only prefixes whose declarations will be emitted.
    used = set()
    for node in root.iter():
        for name in [node.tag, *node.attrib]:
            if name.startswith('{'):
                used.add(name[1:].split('}', 1)[0])
    key = f'{{{MC}}}Ignorable'
    if key in root.attrib:
        remaining = [prefix for prefix, uri in EXTENSIONS.items() if uri in used]
        if remaining:
            root.set(key, ' '.join(remaining))
        else:
            del root.attrib[key]
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def add_audio_links(path):
    """Patch only worksheet hyperlinks and their relationships after authoring."""
    with ZipFile(path) as archive:
        entries = {info.filename: (info, archive.read(info.filename)) for info in archive.infolist()}
    shared = []
    if 'xl/sharedStrings.xml' in entries:
        shared = [''.join(node.itertext()) for node in ET.fromstring(entries['xl/sharedStrings.xml'][1])]
    def text(cell):
        value = cell.find('m:v', NS)
        if cell.get('t') == 's' and value is not None:
            return shared[int(value.text)]
        inline = cell.find('m:is', NS)
        return ''.join(inline.itertext()) if inline is not None else value.text if value is not None else ''
    updates = {}
    count = 0
    for sheet, notes_col in [('sheet1', 'M'), ('sheet2', 'G')]:
        name = f'xl/worksheets/{sheet}.xml'
        root = ET.fromstring(entries[name][1])
        rel_name = f'xl/worksheets/_rels/{sheet}.xml.rels'
        rels = ET.fromstring(entries[rel_name][1]) if rel_name in entries else ET.Element(f'{{{PACKAGE}}}Relationships')
        links = root.find('m:hyperlinks', NS)
        if links is None:
            links = ET.Element(f'{{{MAIN}}}hyperlinks')
            following = {'printOptions', 'pageMargins', 'pageSetup', 'headerFooter', 'rowBreaks', 'colBreaks',
                         'customProperties', 'cellWatches', 'ignoredErrors', 'drawing', 'legacyDrawing',
                         'legacyDrawingHF', 'picture', 'oleObjects', 'controls', 'webPublishItems', 'tableParts', 'extLst'}
            index = next((i for i, child in enumerate(root) if child.tag.rsplit('}', 1)[-1] in following), len(root))
            root.insert(index, links)
        for row in root.findall('m:sheetData/m:row', NS):
            number = row.get('r')
            notes = row.find(f'm:c[@r="{notes_col}{number}"]', NS)
            identifier = row.find(f'm:c[@r="A{number}"]', NS)
            match = re.search(r'^File: (.+)$', text(notes) or '', re.M) if notes is not None else None
            prior = next((link for link in links if link.get('ref') in {f'A{number}', f'{notes_col}{number}'}), None)
            old_target = next((rel.get('Target') for rel in rels if prior is not None and rel.get('Id') == prior.get(f'{{{REL}}}id')), None)
            if (not match and not old_target) or identifier is None or notes is None:
                continue
            target = match.group(1).strip() if match else old_target
            # Keep the actual filename in the link target, not in the visible text.
            content = text(notes) or ''
            content = re.sub(r'^File: .+$', 'Play audio', content, count=1, flags=re.M)
            if not content.startswith('Play audio'):
                content = 'Play audio\n' + content
            for child in list(notes):
                notes.remove(child)
            notes.set('t', 'inlineStr')
            inline = ET.SubElement(notes, f'{{{MAIN}}}is')
            ET.SubElement(inline, f'{{{MAIN}}}t').text = content
            references = {f'A{number}', f'{notes_col}{number}'}
            for old in list(links):
                if old.get('ref') in references:
                    old_id = old.get(f'{{{REL}}}id')
                    for relation in list(rels):
                        if relation.get('Id') == old_id:
                            rels.remove(relation)
                    links.remove(old)
            used = {relation.get('Id') for relation in rels}
            index = 1
            while f'audioLink{index}' in used:
                index += 1
            link_id = f'audioLink{index}'
            ET.SubElement(rels, f'{{{PACKAGE}}}Relationship', Id=link_id, Type=TYPE, Target=target, TargetMode='External')
            for reference in sorted(references):
                ET.SubElement(links, f'{{{MAIN}}}hyperlink', {'ref': reference, f'{{{REL}}}id': link_id,
                              'display': 'Play audio' if reference.startswith(notes_col) else text(identifier),
                              'tooltip': 'Open this recording in your audio player'})
                count += 1
        updates[name] = serialize_sheet(root)
        updates[rel_name] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
    temporary = path.with_suffix('.linked.xlsx')
    with ZipFile(temporary, 'w') as archive:
        for name, (info, data) in entries.items():
            archive.writestr(info, updates.pop(name, data))
        for name, data in updates.items():
            archive.writestr(name, data)
    temporary.replace(path)
    return count
