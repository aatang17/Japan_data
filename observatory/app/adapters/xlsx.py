"""A minimal XLSX reader built on the standard library.

Several Japanese statistical agencies publish only Excel. Everything the
platform needs from the format is a sheet's cell values plus, for one
source, whether a cell is italic — a few dozen lines of zipfile and
ElementTree. Keeping it here means the platform takes no new runtime
dependency for a spreadsheet, and every Excel adapter reads files the
same way.

Cell values come back as *text*, exactly as stored in the file: numbers
are the raw stored digits, not a locale-formatted rendering, and an
empty cell is absent from the row rather than present as "" or 0.
Callers convert; missing stays missing.
"""
import io
import re
import zipfile
from xml.etree import ElementTree as ET

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def shared_strings(z):
    """Shared strings with furigana dropped.

    Each <si> is text runs plus optional <rPh> phonetic runs. Both hold
    <t> elements, so a naive read of 韓国 returns "韓国カンコク". Only
    <t> at the top level and inside <r> is text.
    """
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    out = []
    for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(_NS + "si"):
        parts = []
        for child in si:
            if child.tag == _NS + "t":
                parts.append(child.text or "")
            elif child.tag == _NS + "r":
                parts.append("".join(t.text or "" for t in child.iter(_NS + "t")))
        out.append("".join(parts))
    return out


def italic_styles(z):
    """Per-style-index italic flags, via each cellXf's font."""
    styles = ET.fromstring(z.read("xl/styles.xml"))
    italic = [f.find(_NS + "i") is not None for f in styles.find(_NS + "fonts")]
    return [italic[int(xf.get("fontId"))] for xf in styles.find(_NS + "cellXfs")]


def sheet_targets(z):
    """{sheet name: part path}, in workbook order."""
    rels = dict((r.get("Id"), r.get("Target")) for r in
                ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(
                    _PKG_REL + "Relationship"))
    out = {}
    for sheet in ET.fromstring(z.read("xl/workbook.xml")).iter(_NS + "sheet"):
        target = rels[sheet.get(_DOC_REL + "id")].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        out[sheet.get("name")] = target
    return out


def grid(z, shared, italics, target):
    """One sheet -> {row number: {column letter: (text, is_italic)}}.

    Empty cells are absent; a missing value is never a zero.
    """
    rows = {}
    for row in ET.fromstring(z.read(target)).iter(_NS + "row"):
        cells = {}
        for c in row.iter(_NS + "c"):
            ref = c.get("r") or ""
            m = re.match(r"[A-Z]+", ref)
            if not m:
                continue
            kind = c.get("t")
            v = c.find(_NS + "v")
            inline = c.find(_NS + "is")
            if kind == "s" and v is not None:
                text = shared[int(v.text)]
            elif kind == "inlineStr" and inline is not None:
                text = "".join(t.text or "" for t in inline.iter(_NS + "t"))
            elif v is not None:
                text = v.text
            else:
                continue
            style = c.get("s")
            cells[m.group(0)] = (
                text, bool(italics and style and italics[int(style)]))
        if cells:
            rows[int(row.get("r"))] = cells
    return rows


def sheets(raw_bytes, want_italics=False):
    """Whole workbook -> {sheet name: grid}. The common case, one call."""
    z = zipfile.ZipFile(io.BytesIO(raw_bytes))
    shared = shared_strings(z)
    italics = italic_styles(z) if want_italics else None
    return dict((name, grid(z, shared, italics, target))
                for name, target in sheet_targets(z).items())


def cell_text(cell):
    """The text of a (text, italic) cell tuple, or "" when absent."""
    return (cell[0] if cell else "") or ""
