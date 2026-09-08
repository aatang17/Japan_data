"""A minimal legacy-Excel (BIFF8 .xls) reader built on the standard library.

Companion to `xlsx.py`, and deliberately its twin: `sheets()` here returns
exactly what `sheets()` there returns — {sheet name: {row number: {column
letter: (text, is_italic)}}} — so one adapter can parse a source that
changed file format partway through its history without caring which half
it is reading.

It exists because Japanese ministries keep their archives in the format
they were published in. MAFF's monthly rice contract-price tables are
.xlsx from the 2019 crop year onward and .xls for the eleven crop years
before it, so reading only the modern half would throw away 2008-2018 —
most of the history, which on this platform is the asset. A few hundred
lines of the standard library buys it back with no new dependency.

Scope is deliberately narrow: the OLE2 container (FAT, mini-FAT and
directory, enough to pull out the "Workbook" stream) and the BIFF8
records statistical tables actually use — BOUNDSHEET, SST with its
CONTINUE blocks, and the cell records LABELSST, LABEL, RSTRING, NUMBER,
RK, MULRK and FORMULA (whose cached result is read, never recomputed;
a text result arrives in the STRING record that follows).

Not supported, because nothing here needs it: BIFF5/BIFF7 (Excel 5/95),
encrypted workbooks, and cell formatting — `is_italic` is always False,
so a caller that needs italics must use the .xlsx reader. Dates come back
as the raw serial number exactly as stored; this module never guesses at
a number's meaning.

Cell values are *text*, as in the .xlsx reader: an integral number
renders without a decimal point, and an empty or blank cell is absent
from the row rather than present as "" or 0. Missing stays missing.
"""
import struct

_FREE, _ENDOFCHAIN = 0xFFFFFFFF, 0xFFFFFFFE

_BOF = 0x0809
_EOF = 0x000A
_BOUNDSHEET = 0x0085
_SST = 0x00FC
_CONTINUE = 0x003C
_LABELSST = 0x00FD
_LABEL = 0x0204
_RSTRING = 0x00D6
_NUMBER = 0x0203
_RK = 0x027E
_MULRK = 0x00BD
_FORMULA = 0x0006
_STRING = 0x0207

# Cell records carry (row, col) in their first four bytes and are the only
# records the sheet walk cares about.
_CELL_RECORDS = (_LABELSST, _LABEL, _RSTRING, _NUMBER, _RK, _MULRK, _FORMULA)


class FormatError(Exception):
    """The bytes are not a BIFF8 workbook this reader can read."""


# --- the OLE2 container ------------------------------------------------------

class _Compound(object):
    """Just enough of a compound document to read one named stream."""

    def __init__(self, raw):
        if raw[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise FormatError("not an OLE2 compound document")
        self.ssz = 1 << struct.unpack_from("<H", raw, 0x1E)[0]
        # A published file whose last sector was cut short still reads: MAFF
        # serves the 2018 crop-year price table 340 bytes shy of a whole
        # sector, and has since 2024. The final partial sector is zero-filled;
        # anything missing beyond it still fails the chain walk below.
        short = (-(len(raw) - 512)) % self.ssz
        if short:
            raw = raw + b"\x00" * short
        self.raw = raw
        self.mini_ssz = 1 << struct.unpack_from("<H", raw, 0x20)[0]
        self.mini_cutoff = struct.unpack_from("<I", raw, 0x38)[0]
        dir_start = struct.unpack_from("<I", raw, 0x30)[0]
        minifat_start = struct.unpack_from("<I", raw, 0x3C)[0]
        difat_start = struct.unpack_from("<I", raw, 0x44)[0]
        n_difat = struct.unpack_from("<I", raw, 0x48)[0]

        # FAT sector numbers: 109 in the header, the rest chained through
        # DIFAT sectors whose last slot points at the next DIFAT sector.
        fat_sectors = [s for s in struct.unpack_from("<109I", raw, 0x4C)
                       if s not in (_FREE, _ENDOFCHAIN)]
        node, seen = difat_start, 0
        while node not in (_FREE, _ENDOFCHAIN) and seen < n_difat:
            entries = struct.unpack("<%dI" % (self.ssz // 4), self._sector(node))
            fat_sectors.extend(s for s in entries[:-1]
                               if s not in (_FREE, _ENDOFCHAIN))
            node, seen = entries[-1], seen + 1

        self.fat = []
        for s in fat_sectors:
            self.fat.extend(struct.unpack("<%dI" % (self.ssz // 4), self._sector(s)))

        self.directory = self._chain(dir_start)
        self.minifat = []
        for word in struct.iter_unpack("<I", self._chain(minifat_start)):
            self.minifat.append(word[0])
        # The mini stream itself hangs off the root directory entry (#0).
        root_start = struct.unpack_from("<I", self.directory, 0x74)[0]
        root_size = struct.unpack_from("<I", self.directory, 0x78)[0]
        self.mini_stream = self._chain(root_start)[:root_size] \
            if root_start not in (_FREE, _ENDOFCHAIN) else b""

    def _sector(self, n):
        off = 512 + n * self.ssz
        chunk = self.raw[off:off + self.ssz]
        if len(chunk) < self.ssz:
            raise FormatError("sector %d runs past the end of the file" % n)
        return chunk

    def _chain(self, start, mini=False):
        table = self.minifat if mini else self.fat
        size = self.mini_ssz if mini else self.ssz
        out, node, guard = [], start, 0
        while node not in (_FREE, _ENDOFCHAIN):
            if node >= len(table):
                raise FormatError("sector %d is outside the allocation table" % node)
            if mini:
                out.append(self.mini_stream[node * size:(node + 1) * size])
            else:
                out.append(self._sector(node))
            node = table[node]
            guard += 1
            if guard > len(table) + 1:
                raise FormatError("sector chain does not terminate")
        return b"".join(out)

    def stream(self, name):
        """One stream's bytes, by directory-entry name."""
        for off in range(0, len(self.directory), 128):
            entry = self.directory[off:off + 128]
            if len(entry) < 128:
                break
            name_len = struct.unpack_from("<H", entry, 0x40)[0]
            if not name_len:
                continue
            entry_name = entry[:max(0, name_len - 2)].decode("utf-16-le", "replace")
            if entry_name != name:
                continue
            start = struct.unpack_from("<I", entry, 0x74)[0]
            size = struct.unpack_from("<I", entry, 0x78)[0]
            mini = size < self.mini_cutoff
            return self._chain(start, mini=mini)[:size]
        raise FormatError("no stream named %r in the document" % name)


# --- BIFF8 records -----------------------------------------------------------

def _records(stream):
    """(record id, payload) in order, CONTINUE records left in place."""
    pos, end = 0, len(stream)
    while pos + 4 <= end:
        rid, length = struct.unpack_from("<HH", stream, pos)
        pos += 4
        yield rid, stream[pos:pos + length]
        pos += length


def _unicode_string(buf, pos, extra_bytes, blocks):
    """One BIFF8 Unicode string, following CONTINUE blocks.

    `blocks` is the list of remaining CONTINUE payloads; a string may run
    off the end of one record and resume in the next, where a fresh flags
    byte says whether the continuation is 8- or 16-bit. Returns
    (text, new pos, remaining blocks, current buffer).
    """
    length = struct.unpack_from("<%s" % ("H" if extra_bytes else "B"), buf, pos)[0]
    pos += 2 if extra_bytes else 1
    flags = buf[pos]
    pos += 1
    wide = bool(flags & 0x01)
    rich = bool(flags & 0x08)
    far_east = bool(flags & 0x04)
    n_runs = n_ext = 0
    if rich:
        n_runs = struct.unpack_from("<H", buf, pos)[0]
        pos += 2
    if far_east:
        n_ext = struct.unpack_from("<I", buf, pos)[0]
        pos += 4

    chars, want = [], length
    while want > 0:
        avail = (len(buf) - pos) // (2 if wide else 1)
        take = min(want, avail)
        if take:
            raw = buf[pos:pos + take * (2 if wide else 1)]
            chars.append(raw.decode("utf-16-le" if wide else "latin-1"))
            pos += take * (2 if wide else 1)
            want -= take
        if want:
            if not blocks:
                raise FormatError("string runs past the end of the record")
            buf, blocks = blocks[0], blocks[1:]
            wide = bool(buf[0] & 0x01)
            pos = 1
    # Rich-text runs and Far-East extension data trail the characters.
    pos += n_runs * 4 + n_ext
    while pos > len(buf) and blocks:
        pos -= len(buf)
        buf, blocks = blocks[0], blocks[1:]
    return "".join(chars), pos, blocks, buf


def _shared_strings(sst_payload, continues):
    """The SST as a list of strings, spanning its CONTINUE records."""
    if len(sst_payload) < 8:
        return []
    unique = struct.unpack_from("<I", sst_payload, 4)[0]
    out, buf, pos, blocks = [], sst_payload, 8, list(continues)
    for _ in range(unique):
        if pos >= len(buf):
            if not blocks:
                break
            buf, blocks, pos = blocks[0], blocks[1:], 0
        text, pos, blocks, buf = _unicode_string(buf, pos, True, blocks)
        out.append(text)
    return out


def _rk_value(word):
    """A 30-bit RK number: two flag bits, then an int or a truncated double."""
    cents = word & 0x01
    is_int = word & 0x02
    if is_int:
        value = float(word >> 2 if word >> 2 < 0x20000000 else (word >> 2) - 0x40000000)
    else:
        value = struct.unpack("<d", struct.pack("<Q", (word & 0xFFFFFFFC) << 32))[0]
    return value / 100.0 if cents else value


def _number_text(value):
    """Render a stored number the way the .xlsx reader's raw text does."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def _column_letter(index):
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


# --- the public shape --------------------------------------------------------

def sheets(raw_bytes, want_italics=False):
    """Whole workbook -> {sheet name: grid}, matching `xlsx.sheets`.

    `want_italics` is accepted so the two readers are drop-in
    interchangeable, but .xls formatting is not read: every cell comes
    back with is_italic False.
    """
    del want_italics
    book = _Compound(raw_bytes).stream("Workbook")
    records = list(_records(book))
    if not records or records[0][0] != _BOF:
        raise FormatError("the Workbook stream does not start with a BOF record")
    version = struct.unpack_from("<H", records[0][1], 0)[0] if records[0][1] else 0
    if version < 0x0600:
        raise FormatError(
            "BIFF version 0x%04x is Excel 95 or older; this reader is BIFF8 only"
            % version)

    # Globals: the shared string table and the sheet directory.
    shared, boundsheets = [], []
    for i, (rid, payload) in enumerate(records):
        if rid == _EOF:
            break
        if rid == _SST:
            continues = []
            for rid2, payload2 in records[i + 1:]:
                if rid2 != _CONTINUE:
                    break
                continues.append(payload2)
            shared = _shared_strings(payload, continues)
        elif rid == _BOUNDSHEET:
            offset = struct.unpack_from("<I", payload, 0)[0]
            name, _pos, _blocks, _buf = _unicode_string(payload, 6, False, [])
            boundsheets.append((offset, name))

    # Sheets, located by the byte offset of their own BOF inside the stream.
    starts, pos = {}, 0
    for rid, payload in records:
        starts[pos] = (rid, payload)
        pos += 4 + len(payload)
    order = sorted(starts)
    index_of = dict((off, i) for i, off in enumerate(order))

    out = {}
    for offset, name in boundsheets:
        if offset not in index_of:
            raise FormatError("sheet %r points at offset %d, which is not a "
                              "record boundary" % (name, offset))
        out[name] = _grid(records, index_of[offset], shared)
    return out


def _grid(records, start, shared):
    """One sheet's cells -> {row number: {column letter: (text, False)}}."""
    rows = {}

    def put(r, c, text):
        if text is None or text == "":
            return
        rows.setdefault(r + 1, {})[_column_letter(c)] = (text, False)

    pending_formula = None
    for i in range(start + 1, len(records)):
        rid, payload = records[i]
        if rid == _EOF:
            break
        if rid == _BOF:
            break
        if rid == _STRING and pending_formula is not None:
            text, _pos, _blocks, _buf = _unicode_string(payload, 0, True, [])
            put(pending_formula[0], pending_formula[1], text)
            pending_formula = None
            continue
        if rid not in _CELL_RECORDS:
            continue
        row, col = struct.unpack_from("<HH", payload, 0)
        if rid == _LABELSST:
            index = struct.unpack_from("<I", payload, 6)[0]
            if index < len(shared):
                put(row, col, shared[index])
        elif rid in (_LABEL, _RSTRING):
            text, _pos, _blocks, _buf = _unicode_string(payload, 6, True, [])
            put(row, col, text)
        elif rid == _NUMBER:
            put(row, col, _number_text(struct.unpack_from("<d", payload, 6)[0]))
        elif rid == _RK:
            put(row, col, _number_text(
                _rk_value(struct.unpack_from("<I", payload, 6)[0])))
        elif rid == _MULRK:
            # row, first column, then one (XF, RK) pair per cell, then the
            # last column: the pairs start at byte 4, not after an XF field.
            last = struct.unpack_from("<H", payload, len(payload) - 2)[0]
            for n, c in enumerate(range(col, last + 1)):
                word = struct.unpack_from("<I", payload, 4 + n * 6 + 2)[0]
                put(row, c, _number_text(_rk_value(word)))
        elif rid == _FORMULA:
            # Bytes 6..13 are the cached result: a special value when the
            # two high bytes are 0xFFFF, otherwise an IEEE double.
            result = payload[6:14]
            if len(result) == 8 and result[6:8] == b"\xff\xff":
                kind = result[0]
                if kind == 0:                      # a string, in the next record
                    pending_formula = (row, col)
                elif kind == 1:                    # boolean
                    put(row, col, "TRUE" if result[2] else "FALSE")
                # kind 2 (error) and 3 (empty string) stay missing.
            else:
                put(row, col, _number_text(struct.unpack("<d", result)[0]))
    return rows


def cell_text(cell):
    """The text of a (text, italic) cell tuple, or "" when absent."""
    return (cell[0] if cell else "") or ""
