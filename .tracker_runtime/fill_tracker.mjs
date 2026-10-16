import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const [input, output, payloadPath, previewDir, mode] = process.argv.slice(2);
const data = JSON.parse(await fs.readFile(payloadPath, 'utf8'));
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(input));
const session = wb.worksheets.getItem('Session Sheet');
const event = wb.worksheets.getItem('Event Log');
// Keep the supplied table layouts and the event-label reference list in M intact.
if (mode !== '--links-only') {
session.getRange('A2:M2580').clear({applyTo:'contents'});
event.getRange('A2:G6382').clear({applyTo:'contents'});
const literal = value => typeof value === 'string' && value.startsWith('=') ? "'"+value : value;
const noteHeight = (value, width) => Math.max(30,
  String(value || '').split('\n').reduce((count,line)=>count+Math.max(1,Math.ceil(line.length/width)),0)*15+8);
if (data.sessions.length) {
  session.getRange(`A2:M${data.sessions.length+1}`).values = data.sessions.map(row=>row.map(literal));
  session.getRange(`B2:B${data.sessions.length+1}`).setNumberFormat('mm/dd/yy');
  session.getRange(`C2:C${data.sessions.length+1}`).setNumberFormat('hh:mm:ss');
  session.getRange(`I2:J${data.sessions.length+1}`).setNumberFormat('0.00');
  session.getRange(`L2:L${data.sessions.length+1}`).setNumberFormat('[m]:ss.0');
  session.getRange(`M2:M${data.sessions.length+1}`).format.wrapText = true;
  session.getRange(`A2:M${data.sessions.length+1}`).format.verticalAlignment = 'center';
  session.getRange(`A2:M${data.sessions.length+1}`).format.autofitRows();
  data.sessions.forEach((row,i)=>{
    session.getRange(`A${i+2}:M${i+2}`).format.rowHeight = noteHeight(row[12],40);
  });
}
if (data.events.length) {
  event.getRange(`A2:G${data.events.length+1}`).values = data.events.map(row=>row.map(literal));
  event.getRange(`B2:C${data.events.length+1}`).setNumberFormat('[m]:ss.0');
  event.getRange(`E2:F${data.events.length+1}`).setNumberFormat('0.00');
  event.getRange(`G2:G${data.events.length+1}`).format.wrapText = true;
  event.getRange(`G2:G${data.events.length+1}`).format.font.size = 11;
  event.getRange(`G2:G${data.events.length+1}`).format.horizontalAlignment = 'left';
  event.getRange(`A2:G${data.events.length+1}`).format.verticalAlignment = 'center';
  event.getRange(`A2:G${data.events.length+1}`).format.autofitRows();
  data.events.forEach((row,i)=>{
    event.getRange(`A${i+2}:G${i+2}`).format.rowHeight = noteHeight(row[6],50);
  });
}
// Notes now include the WAV mapping; give this affected column room to be read.
event.getRange('G:G').format.columnWidth = 52;
}
// Link the existing ID cell, keeping the template's columns and sortable tables intact.
function addLinks(sheet, maxRow, notesColumn) {
  const rows = sheet.getRange(`A2:${notesColumn}${maxRow}`).values;
  for (let i=0; i<rows.length; i++) {
    const row=rows[i];
    const notes=String(row[row.length-1] || '');
    const file=notes.match(/^File: (.+)$/m)?.[1]?.trim();
    if (!file || !row[0]) continue;
    const cell=sheet.getRange(`A${i+2}`);
    // Native link relationships are added after export because this engine does
    // not evaluate HYPERLINK. Restore IDs from earlier formula-based trackers.
    const previous=cell.formulas?.[0]?.[0];
    const formula=previous?.match(/^=?HYPERLINK\("((?:[^"]|"")*)","((?:[^"]|"")*)"\)$/);
    cell.values=[[formula ? formula[2].replaceAll('""','"') : row[0]]];
    cell.format.font.color='#0563C1';
  }
}
addLinks(session,2580,'M');
addLinks(event,6382,'G');
wb.recalculate();
if (previewDir) {
  await fs.mkdir(previewDir,{recursive:true});
  for (const [sheet,range] of [['Session Sheet','A1:M3'],['Event Log','A1:M5']]) {
    console.log((await wb.inspect({kind:'table',range:`'${sheet}'!${range}`,include:'values,formulas',tableMaxRows:5,tableMaxCols:13,maxChars:4000})).ndjson);
    const blob=await wb.render({sheetName:sheet,range,scale:1.4,format:'png'});
    await fs.writeFile(`${previewDir}/${sheet.replaceAll(' ','_')}.png`,new Uint8Array(await blob.arrayBuffer()));
  }
}
const temporary = output + '.tmp.xlsx';
await (await SpreadsheetFile.exportXlsx(wb)).save(temporary);
await fs.rename(temporary,output);
await fs.rm(temporary + '.inspect.ndjson', {force:true});
