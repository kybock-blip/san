import glob, zipfile, xml.etree.ElementTree as ET

docx_files = glob.glob('*.docx')
with zipfile.ZipFile(docx_files[0]) as z:
    tree = ET.fromstring(z.read('word/document.xml'))
    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    
    lines = []
    body = tree.find(f'{ns}body')
    for elem in body:
        tag = elem.tag.replace(ns, '')
        if tag == 'p':
            t = ''.join([node.text for node in elem.iter(f'{ns}t') if node.text]).strip()
            if t:
                lines.append(f"[P] {t}")
        elif tag == 'tbl':
            lines.append("--- [TABLE START] ---")
            for row in elem.iter(f'{ns}tr'):
                cells = []
                for cell in row.iter(f'{ns}tc'):
                    cell_text = ' '.join([node.text for node in cell.iter(f'{ns}t') if node.text]).strip()
                    cells.append(cell_text)
                lines.append(" | ".join(cells))
            lines.append("--- [TABLE END] ---\n")

with open('api_spec_utf8.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('Done!')
