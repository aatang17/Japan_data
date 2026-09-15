"""Ceres Analytics — investor / tech-park deck (v2: product-led, plain English).

Layout engine first, content second. Every text box reports an estimated
rendered height, slides are laid out with a flowing cursor, and a validator at
the end fails the build on any text-to-text collision or slide overflow.
"""
import math
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# --------------------------------------------------------------- palette
NAVY   = RGBColor(0x1A, 0x4D, 0x8F)
INK    = RGBColor(0x0F, 0x17, 0x2A)
TEXT   = RGBColor(0x33, 0x41, 0x55)
MUTED  = RGBColor(0x64, 0x74, 0x8B)
FAINT  = RGBColor(0x94, 0xA3, 0xB8)
BORDER = RGBColor(0xD8, 0xE0, 0xEA)
SUBTLE = RGBColor(0xF6, 0xF9, 0xFC)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
RUST   = RGBColor(0xC2, 0x41, 0x0C)
GREEN  = RGBColor(0x15, 0x80, 0x3D)
SKY    = RGBColor(0x8F, 0xBD, 0xE8)
DEEP   = RGBColor(0x12, 0x3A, 0x6D)
ONNAVY = RGBColor(0xC5, 0xD7, 0xEC)

SANS, MONO = "Helvetica Neue", "Menlo"
W, H = 13.333, 7.5
M = 0.8
CW = W - 2 * M
FOOT_Y = H - 0.5

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(W), Inches(H)
BLANK = prs.slide_layouts[6]
_reg = []          # (slide_index, kind, x, y, w, h_est, label)
_cont = []         # container rects: (slide_index, x, y, w, h)
_html = {}         # slide_index -> list of html fragments
PX = 96.0


def _hx(v):
    return "%.1f" % (v * PX)


def _rgb(c):
    return "#%02X%02X%02X" % (c[0], c[1], c[2])
_n = {"i": 0}

SCR = ("/private/tmp/claude-501/-Users-aatang17-Japan-data-Japan-data/"
       "a252b001-a7b3-4dd9-900f-1442ced34c7b/scratchpad/deck/")


# --------------------------------------------------------------- measuring
def _cw(size, bold, caps, mono):
    f = 0.625 if mono else (0.538 if bold else 0.51)
    if caps:
        f *= 1.16
    return size * f


def measure(paras, width, size, bold, caps, spacing, font, space_after=0):
    """Estimated rendered height in inches."""
    total = 0.0
    for p in paras:
        pieces = [(p, {})] if isinstance(p, str) else p
        txt = "".join(t for t, _ in pieces)
        if not txt.strip():
            total += size * spacing / 72.0
            continue
        mx = max(o.get("size", size) for _, o in pieces)
        wsum = sum(len(t) * _cw(o.get("size", size), o.get("bold", bold),
                                o.get("caps", caps), o.get("font", font) == MONO)
                   for t, o in pieces)
        avg = wsum / max(1, len(txt))
        per_line = max(1.0, (width * 72.0) / avg * 0.95)
        lines = max(1, math.ceil(len(txt) / per_line))
        total += lines * mx * spacing / 72.0 + space_after / 72.0
    return total * 1.06


# --------------------------------------------------------------- primitives
DARK = set()


def slide(dark=False):
    s = prs.slides.add_slide(BLANK)
    f = s.background.fill
    f.solid()
    f.fore_color.rgb = NAVY if dark else WHITE
    _n["i"] += 1
    if dark:
        DARK.add(_n["i"])
    return s


def box(s, x, y, w, h, fill=None, line=None, lw=1.0, shape=MSO_SHAPE.RECTANGLE):
    sh = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.shadow.inherit = False
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(lw)
    if h >= 0.6 and w >= 1.0 and (fill is not None or line is not None):
        _cont.append((_n["i"], x, y, w, h))
    st = "position:absolute;left:%spx;top:%spx;width:%spx;height:%spx;" % (
        _hx(x), _hx(y), _hx(w), _hx(h))
    if shape == MSO_SHAPE.OVAL:
        st += "border-radius:50%;"
    st += "background:%s;" % (_rgb(fill) if fill is not None else "transparent")
    if line is not None:
        st += "border:%.1fpx solid %s;box-sizing:border-box;" % (lw * 1.33, _rgb(line))
    _html.setdefault(_n["i"], []).append('<div style="%s"></div>' % st)
    return sh


def txt(s, x, y, w, runs, size=13, bold=False, color=TEXT, font=SANS,
        align=PP_ALIGN.LEFT, spacing=1.2, caps=False, space_after=0, track=True):
    """Draw text; return its estimated height. Height is always measured."""
    paras = runs if isinstance(runs, list) else [runs]
    if isinstance(runs, str):
        paras = [runs]
    h = measure(paras, w, size, bold, caps, spacing, font, space_after)
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h + 0.04))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP
    for i, p in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        para.line_spacing = spacing
        para.space_after = Pt(space_after)
        pieces = [(p, {})] if isinstance(p, str) else p
        for t, o in pieces:
            r = para.add_run()
            r.text = t.upper() if o.get("caps", caps) else t
            fo = r.font
            fo.size = Pt(o.get("size", size))
            fo.bold = o.get("bold", bold)
            fo.color.rgb = o.get("color", color)
            fo.name = o.get("font", font)
    al = {PP_ALIGN.LEFT: "left", PP_ALIGN.RIGHT: "right",
          PP_ALIGN.CENTER: "center"}.get(align, "left")
    frag = ['<div style="position:absolute;left:%spx;top:%spx;width:%spx;'
            'text-align:%s;outline:1px dashed rgba(200,0,0,0);">' % (
                _hx(x), _hx(y), _hx(w), al)]
    for p in paras:
        pieces = [(p, {})] if isinstance(p, str) else p
        frag.append('<div style="line-height:%.2f;margin:0;">' % spacing)
        for t, o in pieces:
            tt = (t.upper() if o.get("caps", caps) else t)
            tt = (tt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            frag.append('<span style="font-size:%.1fpt;font-weight:%s;color:%s;'
                        'font-family:%s;">%s</span>' % (
                            o.get("size", size),
                            "700" if o.get("bold", bold) else "400",
                            _rgb(o.get("color", color)),
                            "Menlo,monospace" if o.get("font", font) == MONO
                            else "'Helvetica Neue',Helvetica,Arial,sans-serif",
                            tt or "&nbsp;"))
        frag.append("</div>")
    frag.append("</div>")
    _html.setdefault(_n["i"], []).append("".join(frag))
    if track:
        _reg.append((_n["i"], "text", x, y, w, h, (paras[0] if isinstance(paras[0], str)
                     else "".join(t for t, _ in paras[0]))[:42]))
    return h


def head(s, kicker, title, sub=None, tsize=30):
    y = 0.5
    y += txt(s, M, y, CW * 0.95, title, size=tsize, bold=True, color=INK,
             spacing=1.0) + 0.16
    if sub:
        y += txt(s, M, y, CW * 0.93, sub, size=13.5, color=MUTED, spacing=1.18) + 0.18
    box(s, M, y, CW, 0.014, fill=BORDER)
    return y + 0.28


def foot(s, label=""):
    txt(s, M, FOOT_Y, CW * 0.7, label, size=9, color=FAINT, caps=True,
        spacing=1.0, track=False)
    txt(s, W - M - 1.0, FOOT_Y, 1.0, str(_n["i"]), size=9, color=FAINT,
        align=PP_ALIGN.RIGHT, spacing=1.0, track=False)


def bullets(s, x, y, w, items, size=15, gap=0.4, dot=NAVY):
    for lead, rest in items:
        box(s, x, y + size / 72.0 * 0.42, 0.07, 0.07, fill=dot, shape=MSO_SHAPE.OVAL)
        y += txt(s, x + 0.24, y, w - 0.24,
                 [[(lead, {"bold": True, "color": INK}), (rest, {})]],
                 size=size, spacing=1.22) + gap
    return y


def stat(s, x, y, w, value, unit, label, note="", vs=40):
    h = txt(s, x, y, w, [[(value, {"size": vs, "bold": True, "color": INK}),
                          (unit, {"size": vs * 0.44, "bold": True, "color": MUTED})]],
            spacing=0.98)
    y += h + 0.08
    y += txt(s, x, y, w, label, size=9, bold=True, color=MUTED, caps=True,
             spacing=1.05) + 0.08
    if note:
        y += txt(s, x, y, w, note, size=11, color=FAINT, spacing=1.2)
    return y


def card(s, x, y, w, h, title, body, kicker=None, accent=NAVY, ts=15.5, bs=13):
    box(s, x, y, w, h, fill=WHITE, line=BORDER)
    box(s, x, y, w, 0.04, fill=accent)
    yy = y + 0.24
    if kicker:
        yy += txt(s, x + 0.24, yy, w - 0.48, kicker, size=8.5, bold=True,
                  color=accent, caps=True, spacing=1.0) + 0.1
    yy += txt(s, x + 0.24, yy, w - 0.48, title, size=ts, bold=True, color=INK,
              spacing=1.1) + 0.14
    txt(s, x + 0.24, yy, w - 0.48, body, size=bs, spacing=1.22)


def divider(s, kicker, title, sub):
    txt(s, M, 2.7, CW, kicker, size=10.5, bold=True, color=ONNAVY, caps=True,
        spacing=1.0, track=False)
    txt(s, M, 3.05, CW * 0.8, title, size=44, bold=True, color=WHITE, spacing=1.0,
        track=False)
    box(s, M, 4.18, 1.4, 0.03, fill=SKY)
    txt(s, M, 4.44, CW * 0.55, sub, size=14, color=ONNAVY, spacing=1.25, track=False)


# ============================================================== 1 · title
s = slide(dark=True)
box(s, 0, 0, W, 0.1, fill=SKY)
txt(s, M, 1.9, CW, "Investor & partner briefing · September 2026", size=11,
    bold=True, color=ONNAVY, caps=True, spacing=1.0, track=False)
txt(s, M, 2.34, CW, "Ceres Analytics", size=56, bold=True, color=WHITE,
    spacing=1.0, track=False)
txt(s, M, 3.42, CW * 0.78,
    "We make the public financial record usable.", size=22, color=WHITE,
    spacing=1.2, track=False)
txt(s, M, 4.0, CW * 0.62,
    "Company filings and official statistics, cleaned up, stored properly, and traceable "
    "back to the document they came from. You can reach it through an API, through your "
    "own AI assistant, or through specialists we run for you.",
    size=13, color=ONNAVY, spacing=1.35, track=False)
box(s, M, 5.24, CW * 0.5, 0.014, fill=DEEP)
txt(s, M, 5.46, CW * 0.5,
    [[("[FOUNDER 1] · [FOUNDER 2]", {"bold": True, "color": WHITE, "size": 12.5})],
     [("[EMAIL] · ceresanalytics.[tld]", {"color": ONNAVY, "size": 11})]],
    spacing=1.4, track=False)
txt(s, W - M - 3.8, 5.46, 3.8,
    [[("Running today in Japan", {"bold": True, "color": WHITE, "size": 12.5})],
     [("Nothing in the system is specific to Japan", {"color": ONNAVY, "size": 11})]],
    align=PP_ALIGN.RIGHT, spacing=1.4, track=False)

# ============================================================== 2 · problem
s = slide()
y = head(s, "", "Unusable public data",
         "Most of it cannot actually be used. It is free to download, but making it "
         "usable is where the cost is, and every firm pays that cost on its own.")
y2 = bullets(s, M, y, CW * 0.52, [
    ("Filings are documents, not data. ",
     "Thousands of companies publish long reports in their own language, mostly in the "
     "same few weeks of the year."),
    ("Statistics come formatted for print. ",
     "Old text encodings, layouts that change without notice, and blank cells that get "
     "read as zeros."),
    ("Revisions overwrite history. ",
     "What you download today is not what anyone could see last year, so a backtest run "
     "on it is wrong."),
    ("So every firm rebuilds the same thing. ",
     "They extract the same filings, get some of it wrong, and lose the work when the "
     "analyst leaves."),
], gap=0.3)
bx = M + CW * 0.57
bh = y2 - y - 0.3
box(s, bx, y, CW * 0.43, bh, fill=SUBTLE, line=BORDER)
iy = y + 0.32
iy += txt(s, bx + 0.3, iy, CW * 0.43 - 0.6, "What this sounds like in practice", size=9,
          bold=True, color=MUTED, caps=True, spacing=1.0) + 0.24
iy += txt(s, bx + 0.3, iy, CW * 0.43 - 0.6,
          "“Twenty of my companies filed this month. I will read three of them properly "
          "and never open the rest.”", size=19, color=INK, spacing=1.32) + 0.36
txt(s, bx + 0.3, iy, CW * 0.43 - 0.6,
    "An analyst covering Asian equities. The gap between what companies disclose and what "
    "anyone actually reads is the whole opportunity.", size=12, color=MUTED, spacing=1.25)
foot(s, "The problem")

# ============================================================== 3 · what we built
s = slide()
y = head(s, "", "Ingest, store, serve",
         "We pull from official sources, store everything in one schema with its "
         "provenance, and let people get at it however suits them.")
layers = [
    ("Sources", FAINT, "Statistics agencies, filing regulators, central banks, customs",
     "any country"),
    ("Adapters", NAVY, "Download, parse, check it makes sense, archive the original",
     "one small module per source"),
    ("The database", DEEP, "Series, observations, releases, every past version, provenance",
     "one schema for everything"),
    ("Tool layer", NAVY, "One set of functions that everything else is built on",
     "shared by every surface"),
]
yy = y + 0.02
for name, col, body, right in layers:
    box(s, M, yy, CW, 0.74, fill=SUBTLE if col is FAINT else WHITE, line=BORDER)
    box(s, M, yy, 0.05, 0.74, fill=col)
    txt(s, M + 0.3, yy + 0.18, 2.1, name, size=14.5, bold=True, color=INK, spacing=1.1)
    txt(s, M + 2.55, yy + 0.22, CW * 0.5, body, size=12, color=TEXT, spacing=1.15)
    txt(s, M + CW - 2.9, yy + 0.22, 2.6, right, size=11, color=MUTED,
        align=PP_ALIGN.RIGHT, spacing=1.15)
    yy += 0.74
    txt(s, M + CW / 2 - 0.1, yy - 0.02, 0.2, "↓", size=11, color=FAINT,
        align=PP_ALIGN.CENTER, spacing=1.0, track=False)
    yy += 0.16
cw3 = (CW - 0.6) / 3
for i, (t, b, col) in enumerate([
    ("An API", "For engineers and quant teams who want the data inside their own systems.",
     NAVY),
    ("An MCP server", "So anyone's AI assistant can query it directly, with nothing to "
     "install.", RUST),
    ("Specialists", "Analysts we wrote and run, which watch your companies and report "
     "back.", RUST),
]):
    xx = M + i * (cw3 + 0.3)
    box(s, xx, yy, cw3, 0.98, fill=WHITE, line=col, lw=1.4)
    txt(s, xx + 0.24, yy + 0.2, cw3 - 0.48, t, size=14, bold=True, color=col, spacing=1.1)
    txt(s, xx + 0.24, yy + 0.5, cw3 - 0.48, b, size=11, color=TEXT, spacing=1.2)
foot(s, "What we built")

# ============================================================== 4 · what's in it
s = slide()
y = head(s, "", "What we cover",
         "Every listed Japanese company, six years of its filings, and the main national "
         "statistics. All of it from official sources, none of it retyped.")
pw = CW * 0.5
crop = 0.44
ph = pw * (1800.0 * (1 - crop)) / 2880.0
pic = s.shapes.add_picture(SCR + "site-holdings.png", Inches(M), Inches(y),
                           width=Inches(pw), height=Inches(ph))
pic.crop_bottom = crop
_html.setdefault(_n["i"], []).append(
    "<div style='position:absolute;left:%spx;top:%spx;width:%spx;height:%spx;"
    "overflow:hidden;'><img src='site-holdings.png' style='width:100%%;'></div>"
    % (_hx(M), _hx(y), _hx(pw), _hx(ph)))
box(s, M, y, pw, ph, fill=None, line=BORDER)
txt(s, M, y + ph + 0.18, pw,
    "Every cross-shareholding that every listed company discloses, with the reason it "
    "gives for holding it. About ¥59tn in total. A terminal will show you one company's "
    "disposal. It will not let you rank all of them.", size=11.5, spacing=1.25)
bx = M + pw + 0.42
bw2 = CW - pw - 0.42
by = y
for kicker, body in [
    ("How a new source gets added",
     "Each source is one small module that downloads, parses and checks that one thing. "
     "Everything else is shared. We have never had to change the database to fit a new "
     "source, so when a customer asks for wages or rents the answer is weeks, not "
     "quarters."),
    ("How the filings get read",
     "Getting from a 200-page securities report to a row you can sort on is most of the "
     "engineering here. The useful parts arrive as text blobs, companies write their "
     "holdings out by hand, and some filings do not add up. We handle the first two and "
     "flag the third rather than hide it."),
]:
    h_body = measure([body], bw2 - 0.56, 12, False, False, 1.28, SANS)
    bh = h_body + 0.86
    box(s, bx, by, bw2, bh, fill=SUBTLE, line=BORDER)
    iy = by + 0.26
    iy += txt(s, bx + 0.28, iy, bw2 - 0.56, kicker, size=9, bold=True, color=NAVY,
              caps=True, spacing=1.0) + 0.18
    txt(s, bx + 0.28, iy, bw2 - 0.56, body, size=12, spacing=1.28)
    by += bh + 0.22
foot(s, "The data")

# ============================================================== 4b · hard formats
s = slide()
y = head(s, "", "Fix difficult formats",
         "A real Bank of Japan file, republished every ten days, listing every government "
         "bond it owns. Most of this was never meant to be read by a machine.")

gw = CW * 0.46
box(s, M, y, gw, 3.4, fill=WHITE, line=BORDER)
txt(s, M + 0.18, y + 0.12, gw - 0.36, "mei260831.xlsx, as published", size=8.5, bold=True,
    color=MUTED, caps=True, spacing=1.0)
colw = [0.66, 1.26, 0.98, 1.52]
gx = M + 0.18
tw = sum(colw)
txt(s, gx, y + 0.38, tw, "（単位：億円）", size=8, color=MUTED, align=PP_ALIGN.RIGHT,
    spacing=1.0)
txt(s, gx, y + 0.54, tw, "(100 million yen)", size=8, color=MUTED,
    align=PP_ALIGN.RIGHT, spacing=1.0)
gy = y + 0.78
box(s, gx, gy, tw, 0.19, fill=SUBTLE)
cx = gx
for i2, h in enumerate(["B", "C", "D", "E"]):
    txt(s, cx, gy + 0.028, colw[i2], h, size=7.5, color=FAINT, align=PP_ALIGN.CENTER,
        spacing=1.0)
    cx += colw[i2]
gy += 0.22
GREY = RGBColor(0xE8, 0xEC, 0xF2)
rows_spec = [
    ("", "銘柄", "回号", "保有残高"),
    ("", "Issue", "Issue Number", "Amount Outstanding"),
    ("", "2年債", "464", "14,875"),
    ("", "2-Year JGB", "465", "12,234"),
    ("", "", "466", "7,884"),
    ("", "", "467", "6,029"),
    ("", "", "…", "…"),
    ("", "5年債", "149", "66,733"),
    ("", "5-Year JGB", "150", "57,060"),
    ("", "", "151", "36,523"),
]
RH = 0.213
for b, c, d, e in rows_spec:
    cx = gx
    for i2, v in enumerate([b, c, d, e]):
        box(s, cx, gy, colw[i2], RH, fill=None, line=GREY, lw=0.5)
        if v:
            al = PP_ALIGN.LEFT
            if i2 >= 2 and v not in ("回号", "Issue Number", "保有残高",
                                     "Amount Outstanding"):
                al = PP_ALIGN.RIGHT
            txt(s, cx + 0.05, gy + 0.045, colw[i2] - 0.1, v, size=8, color=INK,
                align=al, spacing=1.0)
        cx += colw[i2]
    gy += RH
txt(s, gx + tw + 0.1, y + 0.86, gw - tw - 0.28,
    [[("###########", {"color": RUST, "font": MONO, "size": 8.5})],
     [("a column too narrow", {"color": MUTED, "size": 8})],
     [("for its own date", {"color": MUTED, "size": 8})]], spacing=1.2)
txt(s, M, y + 3.5, gw,
    "339 issues · 9 bond types · ¥517.7tn · reissued every ten days",
    size=10, color=MUTED, spacing=1.0)

bx = M + gw + 0.42
bw2 = CW - gw - 0.42
by = y
by += txt(s, bx, by, bw2, "What a parser has to work out", size=9, bold=True,
          color=NAVY, caps=True, spacing=1.0) + 0.26
for n, lead, rest in [
    ("1", "Fifteen rows of furniture first. ",
     "Titles, a department, a phone number and the units, before any data starts."),
    ("2", "257 columns, six of them used. ",
     "The rest are empty and have to be ignored rather than trusted."),
    ("3", "The bond type is a label, not a column. ",
     "2年債 is on one row, 2-Year JGB on the next, then twenty-one blank rows that still "
     "belong to it."),
    ("4", "The unit sits in a floating cell. ",
     "Everything is in 億円, so every figure is multiplied by a hundred million."),
    ("5", "Two languages in one merged cell, ", "split by a line break."),
]:
    txt(s, bx, by, 0.22, n, size=11, bold=True, color=FAINT, spacing=1.15)
    by += txt(s, bx + 0.28, by, bw2 - 0.28,
              [[(lead, {"bold": True, "color": INK}), (rest, {})]],
              size=12, spacing=1.22) + 0.22

ry = y + 3.72
box(s, M, ry, CW, 0.88, fill=SUBTLE, line=BORDER)
txt(s, M + 0.28, ry + 0.14, 2.2, "What comes out", size=9, bold=True, color=GREEN,
    caps=True, spacing=1.0)
txt(s, M + 0.28, ry + 0.38, CW * 0.52,
    [[("10-Year JGB · issue 378 · ¥2,930.0bn · 2026-08-31 · mei260831.xlsx",
       {"font": MONO, "size": 11, "color": INK})]], spacing=1.1)
txt(s, M + CW * 0.58, ry + 0.24, CW * 0.4,
    "One row per issue, the tenor carried down, the unit applied, and the file it came "
    "from recorded.", size=11, color=MUTED, align=PP_ALIGN.RIGHT, spacing=1.2)
foot(s, "Hard formats")

# ============================================================== 5 · point in time
s = slide()
y = head(s, "", "Point-in-time history",
         "You can ask what a number was, not just what it is now. Agencies revise and "
         "overwrite. We never do, so every revision sits next to the version it replaced.")
y2 = bullets(s, M, y, CW * 0.5, [
    ("Quant teams cannot work without this. ",
     "Test a signal on today's numbers and you have tested it on information nobody had "
     "at the time. We can give you the data exactly as it stood on any date."),
    ("Nobody can build it later. ",
     "Once an agency overwrites a number, that version is gone unless someone was "
     "recording it. We were."),
    ("It gets better on its own. ",
     "Every month the ingest runs, the record gets deeper. Someone starting in 2028 "
     "starts with nothing and stays two years behind."),
], gap=0.34)
bx = M + CW * 0.55
box(s, bx, y, CW * 0.45, y2 - y - 0.34, fill=SUBTLE, line=BORDER)
iy = y + 0.3
iy += txt(s, bx + 0.3, iy, CW * 0.45 - 0.6, "What that looks like", size=9, bold=True,
          color=NAVY, caps=True, spacing=1.0) + 0.22
txt(s, bx + 0.3, iy, CW * 0.45 - 0.6,
    [[("A statistic as first published: ", {"color": MUTED}),
      ("1.9%", {"bold": True, "color": INK})],
     [("The same month after a later revision: ", {"color": MUTED}),
      ("2.0%", {"bold": True, "color": INK})],
     [("", {})],
     [("Every other source now shows only the revised figure. We can show you either, "
       "and tell you which one a trader would have seen on the day.", {})]],
    size=12.5, spacing=1.4)
foot(s, "Point-in-time")

# ============================================================== 6 · AI access
s = slide()
y = head(s, "", "Agent access",
         "Any AI assistant can query the database directly, as tools over MCP. One line "
         "to connect it, then people just ask.")
bullets(s, M, y, CW * 0.42, [
    ("Nothing to install. ",
     "One address pasted into Claude, an internal copilot or a code editor."),
    ("They ask, it answers. ",
     "Our tools return the numbers and the source. The assistant does the chart, the "
     "table or the note."),
    ("Same code underneath. ",
     "The website, the API and the assistant call the same functions, so the numbers "
     "cannot drift apart."),
], gap=0.38)

# --- assistant panel with a chart it produced
px = M + CW * 0.47
pwid = CW * 0.53
box(s, px, y, pwid, 3.52, fill=WHITE, line=BORDER)
box(s, px, y, pwid, 0.34, fill=INK)
txt(s, px + 0.2, y + 0.09, pwid - 0.4,
    [[("$ ", {"color": FAINT}), ("claude mcp add ceres https://[host]/mcp",
                                 {"color": WHITE})]],
    size=10.5, font=MONO, spacing=1.0)

qy = y + 0.52
txt(s, px + 1.3, qy, pwid - 1.5,
    "Which of the big financials cut the most cross-shareholdings last year? Chart it.",
    size=11.5, color=INK, align=PP_ALIGN.RIGHT, spacing=1.25)
qy += 0.48
for name, out in [("get_unwind_ranking", "4 filers · FY2026"),
                  ("get_company_holdings", "as filed · with sources")]:
    txt(s, px + 0.2, qy, 0.18, "✓", size=10.5, color=GREEN, spacing=1.0)
    txt(s, px + 0.42, qy, pwid - 2.6, name, size=10.5, color=NAVY, font=MONO, spacing=1.0)
    txt(s, px + pwid - 1.9, qy, 1.7, out, size=10, color=MUTED,
        align=PP_ALIGN.RIGHT, spacing=1.0)
    qy += 0.26

qy += 0.14
txt(s, px + 0.2, qy, pwid - 0.4, "Positions reduced, latest fiscal year", size=9,
    bold=True, color=MUTED, caps=True, spacing=1.0)
qy += 0.26
BARS = [("MS&AD", 52), ("Mizuho FG", 15), ("SMFG", 13), ("MUFG", 9)]
lab_w, bar_max = 1.25, pwid - 2.5
for nm, v in BARS:
    txt(s, px + 0.2, qy + 0.02, lab_w, nm, size=10.5, color=INK, spacing=1.0)
    bw = bar_max * v / 52.0
    box(s, px + 0.2 + lab_w, qy + 0.035, bw, 0.17, fill=NAVY)
    txt(s, px + 0.28 + lab_w + bw, qy + 0.02, 0.6, str(v), size=10.5, bold=True,
        color=INK, spacing=1.0)
    qy += 0.3
box(s, px + 0.2, qy + 0.04, pwid - 0.4, 0.012, fill=BORDER)
txt(s, px + 0.2, qy + 0.16, pwid - 0.4,
    "Source: annual securities reports, FY2026. Every bar links to the filing.",
    size=9.5, color=MUTED, spacing=1.15)
foot(s, "AI access")

# ============================================================== 7 · why MCP matters
s = slide()
y = head(s, "", "Our way in",
         "This is how we get into a firm. We are not trying to win the interface, we sit "
         "behind whichever assistant the customer already uses.")
steps = [("First", "Someone pastes one address",
          "Into Claude, their code editor, or the copilot their employer has rolled out."),
         ("Then", "Our tools show up",
          "Their assistant can now answer questions about filings, statistics and their "
          "own saved screens."),
         ("And", "Every answer cites a filing",
          "So the analyst can check it, and so can the person who has to sign off on it.")]
cw3 = (CW - 0.6) / 3
for i, (n, t, b) in enumerate(steps):
    xx = M + i * (cw3 + 0.3)
    box(s, xx, y, cw3, 2.2, fill=WHITE, line=BORDER)
    box(s, xx, y, cw3, 0.042, fill=NAVY)
    txt(s, xx + 0.26, y + 0.26, cw3 - 0.52, n, size=10, bold=True, color=FAINT,
        caps=True, spacing=1.0)
    txt(s, xx + 0.26, y + 0.52, cw3 - 0.52, t, size=16, bold=True, color=INK, spacing=1.05)
    txt(s, xx + 0.26, y + 1.18, cw3 - 0.52, b, size=12, spacing=1.22)
    if i < 2:
        txt(s, xx + cw3 + 0.07, y + 0.9, 0.2, "›", size=20, color=FAINT,
            spacing=1.0, track=False)
y += 2.46
bullets(s, M, y, CW, [
    ("Trying it costs nothing. ",
     "There is no software to approve, so an analyst can test it on a Tuesday afternoon "
     "without asking anyone. That is how a company our size gets into a bank."),
    ("Once it is in, taking it out hurts. ",
     "When an assistant already answers these questions, removing us is a step backwards "
     "that the analyst notices the same day."),
], gap=0.26)
foot(s, "AI access")

# ============================================================== 8 · the desk
s = slide()
y = head(s, "", "The desk",
         "What your specialists found overnight. You tell us which companies you cover, "
         "and they report back with the filing attached to every claim.")
pw = CW * 0.56
ph = pw * 900.0 / 1440.0
s.shapes.add_picture(SCR + "ui-Desk.png", Inches(M), Inches(y), width=Inches(pw),
                     height=Inches(ph))
_html.setdefault(_n["i"], []).append(
    "<img src='ui-Desk.png' style='position:absolute;left:%spx;top:%spx;width:%spx;"
    "height:%spx;'>" % (_hx(M), _hx(y), _hx(pw), _hx(ph)))
box(s, M, y, pw, ph, fill=None, line=BORDER)
bx = M + pw + 0.4
bullets(s, bx, y + 0.05, CW - pw - 0.4, [
    ("It tells you what happened, in a sentence. ",
     "“MS&AD cut 52 cross-holdings this year.” You can act on that."),
    ("You can see what is watching. ",
     "Each specialist shows when it last ran and when it runs next."),
    ("Everything is sourced. ",
     "The filing, the badge, and the tool calls behind each line."),
    ("The desk belongs to the team, ", "not to one person's login."),
], gap=0.22)
foot(s, "The desk")

# ============================================================== 9 · specialists
s = slide()
y = head(s, "", "Add specialists",
         "Each is an analyst with a written brief, a fixed set of tools it may use, a "
         "schedule and somewhere to report. We write them, version them and maintain them.")
pw = CW * 0.54
ph = pw * 960.0 / 1440.0
s.shapes.add_picture(SCR + "ui-Main.png", Inches(M), Inches(y), width=Inches(pw),
                     height=Inches(ph))
_html.setdefault(_n["i"], []).append(
    "<img src='ui-Main.png' style='position:absolute;left:%spx;top:%spx;width:%spx;"
    "height:%spx;'>" % (_hx(M), _hx(y), _hx(pw), _hx(ph)))
box(s, M, y, pw, ph, fill=None, line=BORDER)
bx = M + pw + 0.4
bw2 = CW - pw - 0.4
by = y + 0.02
by += txt(s, bx, by, bw2, "Why we write them rather than let customers do it", size=9,
          bold=True, color=MUTED, caps=True, spacing=1.0) + 0.26
for t, b in [("They have version numbers",
              "You accept an update the way you would for any software. A prompt that "
              "quietly changes its behaviour is not something a firm can rely on."),
             ("We can say exactly what they can reach",
              "Each one has a fixed list of tools, so we can answer the security question "
              "precisely instead of vaguely."),
             ("One fix reaches everybody",
              "Nine briefs we maintain is a product. Ten thousand that customers wrote is "
              "a support problem we could not survive.")]:
    by += txt(s, bx, by, bw2, t, size=14, bold=True, color=INK, spacing=1.1) + 0.08
    by += txt(s, bx, by, bw2, b, size=12, spacing=1.24) + 0.3
foot(s, "Specialists")

# ============================================================== 10 · one up close
s = slide()
y = head(s, "", "One up close",
         "The Cross-Shareholding Monitor reads the policy-shareholding section of every "
         "annual report on your names, and tells you who is selling down and why.")
pw = CW * 0.52
ph = pw * 980.0 / 1440.0
s.shapes.add_picture(SCR + "ui-Agent.png", Inches(M), Inches(y), width=Inches(pw),
                     height=Inches(ph))
_html.setdefault(_n["i"], []).append(
    "<img src='ui-Agent.png' style='position:absolute;left:%spx;top:%spx;width:%spx;"
    "height:%spx;'>" % (_hx(M), _hx(y), _hx(pw), _hx(ph)))
box(s, M, y, pw, ph, fill=None, line=BORDER)
bx = M + pw + 0.4
bullets(s, bx, y + 0.02, CW - pw - 0.4, [
    ("Why this one matters. ",
     "Japanese companies still hold about ¥59tn of each other's shares and are under "
     "pressure to sell. Every disposal is disclosed, and almost nobody reads them."),
    ("It explains itself. ",
     "The page says what it watches, which tools it uses for each part, and what it "
     "needs from you."),
    ("You can see every run. ",
     "When it ran, what set it off, what it found, and what it did about it."),
    ("You can ask it things. ",
     "Threads sit alongside the scheduled work and keep their own memory."),
], gap=0.3)
foot(s, "One up close")

# ============================================================== 11 · control
s = slide()
y = head(s, "", "Approval and audit",
         "It can read everything, but it cannot send anything until you have approved it. "
         "These are the two screens a compliance officer asks about first.")
pw = (CW - 0.45) / 2
PH = 2.45
for i, (img, ih, cap) in enumerate([
    ("ui-Inbox.png", 760.0,
     "Before a specialist posts to Slack or sends an email, it stops and shows you the "
     "exact words. Reading the database never needs approval. Anything leaving the desk "
     "always does."),
    ("ui-Audit.png", 900.0,
     "Every tool, who used it and how often, and the runs, calls and tokens behind them. "
     "You can answer “what has this thing been doing?” precisely."),
]):
    xx = M + i * (pw + 0.45)
    natural = pw * ih / 1440.0
    pic = s.shapes.add_picture(SCR + img, Inches(xx), Inches(y), width=Inches(pw),
                               height=Inches(PH))
    pic.crop_bottom = max(0.0, 1.0 - PH / natural)
    _html.setdefault(_n["i"], []).append(
        "<div style='position:absolute;left:%spx;top:%spx;width:%spx;height:%spx;"
        "overflow:hidden;'><img src='%s' style='width:100%%;'></div>"
        % (_hx(xx), _hx(y), _hx(pw), _hx(PH), img))
    box(s, xx, y, pw, PH, fill=None, line=BORDER)
    txt(s, xx, y + PH + 0.2, pw, cap, size=11.5, spacing=1.25)
y2 = y + PH + 0.98
box(s, M, y2, CW, 0.9, fill=SUBTLE, line=BORDER)
txt(s, M + 0.34, y2 + 0.22, CW - 0.68,
    [[("There is no tool that can place a trade, and no way to add one. ",
       {"bold": True, "color": INK}),
      ("We are not in the order path and do not intend to be. That is usually the "
       "sentence that settles the room.", {})]], size=13, spacing=1.28)
foot(s, "Control")

# ============================================================== 12 · how it runs
s = slide()
txt(s, M, 0.5, CW, "Under the hood", size=30, bold=True, color=INK, spacing=1.0,
    track=False)
txt(s, M, 1.02, CW, "How a specialist actually runs. The tools it may use are enforced by "
    "our runner, not by the wording of its brief, and every call is written down.",
    size=13.5, color=MUTED, spacing=1.18, track=False)
box(s, M, 1.5, CW, 0.014, fill=BORDER)
dh = 4.42
dw = dh * 2580.0 / 1260.0
s.shapes.add_picture(SCR + "arch-diagram.png", Inches((W - dw) / 2), Inches(1.7),
                     width=Inches(dw), height=Inches(dh))
_html.setdefault(_n["i"], []).append(
    "<img src='arch-diagram.png' style='position:absolute;left:%spx;top:%spx;width:%spx;"
    "height:%spx;'>" % (_hx((W - dw) / 2), _hx(1.7), _hx(dw), _hx(dh)))
txt(s, M, 6.36, CW,
    [[("Blue is the work the model does: it reads through tools, then acts through four "
       "of them. Amber is the only line that matters, and crossing it needs a person. ",
       {}),
      ("The model runs on the customer's own account, not ours.",
       {"bold": True, "color": INK})]],
    size=11, spacing=1.2, track=False)
foot(s, "Under the hood")

# ============================================================== 13 · who uses it
s = slide()
y = head(s, "", "Users and tiers",
         "Four kinds of user on the same database, with the same provenance. What differs "
         "is what each needs from it and how they pay.")
cw2 = (CW - 0.4) / 2
users = [
    ("Investment firms", NAVY, "Firm tier",
     "Analysts, portfolio managers and quant teams. They want a watch on the companies "
     "they cover, history they can test against, and screens a terminal does not offer."),
    ("Researchers", NAVY, "Free",
     "Economists and finance academics. They need data they can cite and reproduce years "
     "later. We give it away, because their citations make us the obvious source."),
    ("Journalists", RUST, "Individual tier",
     "Financial and investigative reporters. One sourced answer to one question, with the "
     "filing attached. The assistant does the reading."),
    ("Private investors", RUST, "Individual tier",
     "Serious individuals and family offices. The same company facts the professionals "
     "have, at a price one person can pay without asking anyone."),
]
for i, (t, col, tier, b) in enumerate(users):
    xx = M + (i % 2) * (cw2 + 0.4)
    yy = y + (i // 2) * 1.86
    box(s, xx, yy, cw2, 1.66, fill=WHITE, line=BORDER)
    box(s, xx, yy, 0.05, 1.66, fill=col)
    txt(s, xx + 0.3, yy + 0.24, cw2 - 2.5, t, size=16.5, bold=True, color=INK, spacing=1.05)
    txt(s, xx + cw2 - 1.9, yy + 0.3, 1.6, tier, size=10, bold=True, color=col, caps=True,
        align=PP_ALIGN.RIGHT, spacing=1.0)
    txt(s, xx + 0.3, yy + 0.66, cw2 - 0.6, b, size=12, spacing=1.25)
txt(s, M, y + 3.86, CW,
    [[("Free ", {"bold": True, "color": INK}),
      ("is the website and citable links. ", {}),
      ("Individual ", {"bold": True, "color": INK}),
      ("adds a coverage list, alerts, API and AI access, and specialists. ", {}),
      ("Firm ", {"bold": True, "color": INK}),
      ("adds shared desks, an audit trail, a licence and someone to call. Prices come "
       "after the first customers have told us what they will pay.", {})]],
    size=12.5, spacing=1.3)
foot(s, "Who uses it")

# ============================================================== 14 · defensibility
s = slide()
y = head(s, "", "Why it holds",
         "Everything we ingest is free and public, so the first question in every meeting "
         "is why a customer cannot just do it themselves. Three answers.")
cw3 = (CW - 0.6) / 3
for i, (t, b, col) in enumerate([
    ("The history we have already recorded",
     "Millions of stored versions of numbers that have since been revised. Nobody can go "
     "back and collect those, and the gap grows every month we keep running.", NAVY),
    ("The detail underneath the headline",
     "Individual item prices, shareholdings with the reason given, named customers, board "
     "ages, vote results. Terminals stop at the top line.", NAVY),
    ("It is cheaper than building it",
     "A bank could rebuild this with a team in a year, then lose it when that team moves "
     "on. We cost less than the build, every year, and we keep going.", RUST),
]):
    xx = M + i * (cw3 + 0.3)
    box(s, xx, y, cw3, 2.6, fill=WHITE, line=BORDER)
    box(s, xx, y, cw3, 0.042, fill=col)
    txt(s, xx + 0.28, y + 0.3, cw3 - 0.56, t, size=16, bold=True, color=INK, spacing=1.08)
    txt(s, xx + 0.28, y + 1.02, cw3 - 0.56, b, size=12.5, spacing=1.28)
foot(s, "Defensibility")

# ============================================================== 15 · where we are
s = slide()
y = head(s, "", "Where we are",
         "What is running today, and what is not. Plover Analytics is the first "
         "deployment, built by two of us and in production since August 2026.")
cw3 = (CW - 0.6) / 3
for i, (t, items, col) in enumerate([
    ("Working now", ["The ingest runs without anyone watching it",
                     "A public API and website",
                     "The MCP server, live and connectable",
                     "Every listed company, six years of filings"], GREEN),
    ("Being built", ["The specialists and the runner",
                     "Accounts, keys and the desk",
                     "Approvals and delivery"], NAVY),
    ("Not there yet", ["Nobody is paying us yet",
                       "No signed pilots",
                       "First revenue is the next milestone"], RUST),
]):
    xx = M + i * (cw3 + 0.3)
    txt(s, xx, y, cw3, t, size=10.5, bold=True, color=col, caps=True, spacing=1.0)
    box(s, xx, y + 0.26, 0.5, 0.028, fill=col)
    yy = y + 0.48
    for it in items:
        yy += txt(s, xx, yy, cw3, it, size=13.5, spacing=1.22) + 0.2
foot(s, "Where we are")

# ============================================================== 16 · next
s = slide()
y = head(s, "", "What happens next",
         "Get someone paying before adding another country. The first firm that pays us "
         "will teach us more than the next ten datasets would.")
cw3 = (CW - 0.7) / 3
for i, (when, what, items, col) in enumerate([
    ("Now to end of 2026", "Find out if people pay",
     ["Accounts, keys and the desk", "Two specialists running for real",
      "Approvals and the morning email", "Aim: three people paying"], NAVY),
    ("First half of 2027", "Sign a firm",
     ["The full set of specialists", "Shared desks and audit for teams",
      "Licence wording and support", "Aim: one firm signed"], NAVY),
    ("Second half of 2027", "Add a second market",
     ["Korea or Taiwan, same machinery", "Ask for the data as it stood on any date",
      "Distribution through partners", "Aim: five firms, costs covered"], RUST),
]):
    xx = M + i * (cw3 + 0.35)
    box(s, xx, y, cw3, 3.1, fill=WHITE, line=BORDER)
    box(s, xx, y, cw3, 0.042, fill=col)
    yy = y + 0.3
    yy += txt(s, xx + 0.26, yy, cw3 - 0.52, when, size=9, bold=True, color=col,
              caps=True, spacing=1.0) + 0.14
    yy += txt(s, xx + 0.26, yy, cw3 - 0.52, what, size=16, bold=True, color=INK,
              spacing=1.05) + 0.24
    for j, it in enumerate(items):
        last = j == len(items) - 1
        yy += txt(s, xx + 0.26, yy, cw3 - 0.52, it, size=12.5,
                  color=INK if last else TEXT, bold=last, spacing=1.25) + 0.24
foot(s, "What happens next")

# ============================================================== 17 · team
s = slide()
y = head(s, "", "The team",
         "One of us has sold to these customers for years. The other builds the system.")
cw2 = (CW - 0.5) / 2
for i, (name, role, body) in enumerate([
    ("[FOUNDER 1]", "Market and product",
     "[Years] selling equities to institutions across Asia, and the author of Asia "
     "Economics Observations, which is how we reach our first customers. Clients have "
     "been asking for these numbers for years."),
    ("[FOUNDER 2]", "[Engineering]",
     "[Their name, what they have built before, and one concrete thing that shows they "
     "can do this at scale. Two or three lines.]"),
]):
    xx = M + i * (cw2 + 0.5)
    box(s, xx, y, cw2, 2.25, fill=WHITE, line=BORDER)
    box(s, xx, y, cw2, 0.045, fill=NAVY)
    box(s, xx + 0.3, y + 0.4, 0.56, 0.56, fill=SUBTLE, line=BORDER, shape=MSO_SHAPE.OVAL)
    txt(s, xx + 1.04, y + 0.44, cw2 - 1.34, name, size=16, bold=True, color=INK,
        spacing=1.05)
    txt(s, xx + 1.04, y + 0.72, cw2 - 1.34, role, size=10, bold=True, color=NAVY,
        caps=True, spacing=1.05)
    txt(s, xx + 0.3, y + 1.22, cw2 - 0.6, body, size=12.5, spacing=1.28)
y += 2.5
box(s, M, y, CW, 1.3, fill=SUBTLE, line=BORDER)
txt(s, M + 0.34, y + 0.26, CW - 0.68,
    [[("What the two of us have already done: ", {"bold": True, "color": INK}),
      ("a working system with a public API and an AI interface, covering every listed "
       "company in Japan, built in a few weeks. So the question is not whether we can "
       "build it. It is whether we can sell it, and that is what the next year is for.",
       {})]], size=14, spacing=1.32)
foot(s, "Team")

# ============================================================== 18 · ask
s = slide(dark=True)
box(s, 0, 0, W, 0.1, fill=SKY)
txt(s, M, 1.0, CW, "What we are asking for", size=11, bold=True, color=ONNAVY, caps=True,
    spacing=1.0, track=False)
txt(s, M, 1.36, CW * 0.8, "[AMOUNT] to reach first revenue.", size=40, bold=True,
    color=WHITE, spacing=1.0, track=False)
txt(s, M, 2.16, CW * 0.58,
    "Eighteen months for the two of us, the hosting, and the selling that turns a working "
    "system into a paying one.", size=14, color=ONNAVY, spacing=1.25, track=False)
box(s, M, 2.94, CW, 0.014, fill=DEEP)
cw3 = (CW - 0.8) / 3
for i, (pct, t, b) in enumerate([
    ("[%]", "Building", "The specialists, accounts, and the adapters for the next market."),
    ("[%]", "Selling", "The newsletter, conferences, and getting in front of forty desks."),
    ("[%]", "Running it", "Hosting, monitoring, licensing, and the compliance answers "
     "firms ask for."),
]):
    xx = M + i * (cw3 + 0.4)
    txt(s, xx, 3.2, cw3, pct, size=28, bold=True, color=WHITE, spacing=1.0, track=False)
    txt(s, xx, 3.72, cw3, t, size=12.5, bold=True, color=SKY, caps=True, spacing=1.0,
        track=False)
    txt(s, xx, 4.0, cw3, b, size=11, color=ONNAVY, spacing=1.25, track=False)
box(s, M, 5.0, CW, 0.014, fill=DEEP)
txt(s, M, 5.28, CW * 0.62,
    [[("The most useful thing you could do", {"bold": True, "color": WHITE, "size": 13.5})],
     [("Introduce us to one fund or one head of research. Right now that is worth more "
       "to us than the money.", {"color": ONNAVY, "size": 12.5})]], spacing=1.35,
    track=False)
txt(s, W - M - 3.8, 5.28, 3.8,
    [[("[EMAIL]", {"bold": True, "color": WHITE, "size": 13})],
     [("ceresanalytics.[tld]", {"color": ONNAVY, "size": 11.5, "font": MONO})]],
    align=PP_ALIGN.RIGHT, spacing=1.35, track=False)

# ============================================================== validate
EI = 914400
issues = []
by_slide = {}
for rec in _reg:
    by_slide.setdefault(rec[0], []).append(rec)
for idx, recs in by_slide.items():
    for i in range(len(recs)):
        _, _, x1, y1, w1, h1, l1 = recs[i]
        if y1 + h1 > FOOT_Y - 0.04:
            issues.append("slide %d: text runs into footer (bottom %.2f) %r"
                          % (idx, y1 + h1, l1))
        for j in range(i + 1, len(recs)):
            _, _, x2, y2, w2, h2, l2 = recs[j]
            if (x1 < x2 + w2 - 0.03 and x1 + w1 > x2 + 0.03
                    and y1 < y2 + h2 - 0.03 and y1 + h1 > y2 + 0.03):
                issues.append("slide %d: OVERLAP %r <> %r" % (idx, l1, l2))

for rec in _reg:
    idx, _, x, y, w, h, lab = rec
    for ci, cx, cy, cw_, ch in _cont:
        if ci != idx:
            continue
        inside_x = x >= cx - 0.02 and x < cx + cw_ - 0.05
        inside_y = y >= cy - 0.02 and y < cy + ch - 0.05
        if inside_x and inside_y:
            if y + h > cy + ch - 0.06:
                issues.append("slide %d: text spills out of its card (text bottom "
                              "%.2f > card bottom %.2f) %r" % (idx, y + h, cy + ch, lab))
            if x + w > cx + cw_ + 0.02:
                issues.append("slide %d: text wider than its card %r" % (idx, lab))

for idx, sl in enumerate(prs.slides, 1):
    for sh in sl.shapes:
        if sh.shape_type == 13 and sh.top is not None:
            if (sh.top + sh.height) / EI > FOOT_Y - 0.06:
                issues.append("slide %d: picture runs into the footer (bottom %.2f)"
                              % (idx, (sh.top + sh.height) / EI))
        if sh.left is None:
            continue
        if (sh.left < -0.02 * EI or sh.top < -0.02 * EI
                or sh.left + sh.width > (W + 0.02) * EI
                or sh.top + sh.height > (H + 0.02) * EI):
            issues.append("slide %d: shape out of bounds" % idx)

def emit_html(path):
    out = ["<!doctype html><meta charset='utf-8'><style>body{margin:0;background:#555;}"
           ".sl{position:relative;width:%dpx;height:%dpx;background:#fff;margin:14px auto;"
           "overflow:hidden;}.dk{background:#1A4D8F;}</style>" % (int(W * PX), int(H * PX))]
    for i in range(1, _n["i"] + 1):
        dark = i in DARK
        out.append("<div class='sl%s'>" % (" dk" if dark else ""))
        out.extend(_html.get(i, []))
        out.append("</div>")
    open(path, "w").write("".join(out))


emit_html(SCR + "preview.html")

if issues:
    print("FAILED with %d issue(s):" % len(issues))
    for it in issues[:40]:
        print("  ", it)
else:
    out = SCR + "Ceres-Analytics-Pitch.pptx"
    prs.save(out)
    print("clean · %d slides · saved %s" % (len(prs.slides._sldIdLst), out))
