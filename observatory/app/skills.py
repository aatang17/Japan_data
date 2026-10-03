# -*- coding: utf-8 -*-
"""The team's skills: named playbooks an AI follows, kept in Admin.

A skill is a name, one line saying when to use it, the steps — written in
plain Markdown by the team, not code — and one switch: whether it may change
the draft. A skill that may not (Brainstorm, Review) answers in the AI panel
only; its run is not given the draft-changing tools. The research desk's AI
tab offers the skills as a choice before a run; the AI is also told which
exist and can open one itself with the read_skill tool. The house style is a
separate team text sent with every run.

Skills live in the team store (staff.db) rather than with research articles:
they are the team's way of working, and the investment assistant can draw on
the same library when the two products merge.

Nine skills are seeded on first use: the steps of writing a note (Brainstorm,
Plan, Draft, Find Charts, Edit, Review, Fact Check, Headlines) and Data Flash,
adapted from the news-brief and research-report skills the team uses in
Claude Code. A seeded skill is the team's to edit or delete; a deleted seed is
not put back.
"""
import re
import time

from . import staff

NAME_MAX = 60
DESCRIPTION_MAX = 300
INSTRUCTIONS_MAX = 20000
STYLE_MAX = 8000
SKILLS_MAX = 40
_SLUG = re.compile(r"[^a-z0-9]+")


class SkillError(ValueError):
    """Worded for the person editing."""


HOUSE_STYLE = """\
Write as an institutional research note for professional investors (sell-side and
buy-side analysts), not a magazine column.

- Lead with the finding, then the evidence. No set-up-and-reveal, no hooks, no
  rhetorical questions, no one-line paragraphs for emphasis.
- Third person throughout; never address the reader as "you".
- Standard financial vocabulary, unglossed. Measured verbs: "suggests", "indicates",
  "is consistent with" — not "proves" or "turns out".
- Complete sentences; vary their length rather than clipping everything short.
- Every number exactly as published, with its unit, period and basis. Rates we
  calculate (year-on-year, spreads, ratios) say so. One decimal for rates and index
  levels (2.7%, 108.3), two for contributions (0.24 pp), none for yen prices (¥487).
- "pp" for a change in a percentage, "%" for a change in a level. A true minus sign.
- Missing is "—", never zero. No cause the data does not show; no forecasts of
  levels or dates; no advice on what policymakers should do.
- Headings name the measure and the cut ("Loan Margins by Bank Size"), never a
  question or a flourish. Chart titles state the message.
"""

# Seeds, in the order the AI tab lists them: the steps of writing a note first
# (brainstorm → plan → draft → charts → edit → review → check → headlines),
# then whole formats. A skill with "writes": False answers in the AI panel
# only: its run is not given the tools that change the draft.
SEEDS = [
    {"seed": "brainstorm", "name": "Brainstorm", "writes": False, "position": 10,
     "description": "Five to eight angles worth writing, each with the number that backs it. "
                    "Each angle can be planned with one click.",
     "instructions": """\
# Brainstorm — angles worth writing

Do not change the draft. Your reply is the product.

1. Read the draft (`get_draft`) and the writer's instruction: a topic, a news item, notes,
   or nothing. With nothing to go on, look for what changed in Plover data recently
   (`get_vintages`, `get_overview`).
2. Find five to eight angles. An angle is a claim a reader would care about, not a topic:
   "Regional banks gain more from rate rises than the megabanks", not "bank margins". Each
   must be checkable in data we hold or a source you opened; check the data exists
   (`search`, `describe_dataset`). Never suggest data from memory.
3. For each angle pull one number that shows it is worth writing (`get_series`), with its
   period.
4. Prefer angles with an implication: who gains, who pays, by how much.

Reply as a numbered list. For each: the angle in bold, as one sentence; the evidence in one
sentence with the number, its period and the dataset; who it matters to. End with one line
naming the strongest angle and why.

Then offer every angle with `offer_next_step`: label "Plan This: <three to five words>",
skill "Plan", instruction "Plan an article on this angle: <the angle, the evidence, the
dataset and series>."
""",
     },
    {"seed": "plan", "name": "Plan", "writes": True, "position": 20,
     "description": "An outline in the draft for the writer to approve: the question, the "
                    "expected answer, the sections and the data for each. Writes no article.",
     "instructions": """\
# Plan — an outline to approve before writing

Write a plan into the draft for the writer to approve. Do not write the article.

1. Read the draft (`get_draft`). Keep everything the writer wrote: it goes under a heading
   "## Writer's Notes" at the end.
2. Check the data before promising it: for each piece of evidence find the Plover dataset
   and series (`search`, `describe_dataset`) and pull its latest value (`get_series`), or
   open the outside source (`read_page`).
3. Write the plan with `replace_draft`, a working title first ('# Title' stating the
   finding), then "## Plan":
   - **Question** — the one question the article answers, and who reads it.
   - **Expected answer** — one line, written so the data could prove it wrong.
   - **Outline** — one line per section: the heading, its claim, the chart or table.
   - **Data** — for each claim, the dataset and series with its latest value and period,
     or the outside source, or "drop this point".
   - **Implications** — who gains, who pays, how much, where the data can size it.
   - **Out of scope** — one or two lines.
4. If the data does not support the angle, say so in your reply instead of planning
   around it, and suggest a better question.

Reply in two or three sentences: the question, what the data already shows, anything the
writer must decide. Then `offer_next_step`: label "Draft It", skill "Draft", instruction
"Write the article from the plan in the draft."
""",
     },
    {"seed": "draft", "name": "Draft", "writes": True, "position": 30,
     "description": "Writes the article from the plan or notes in the draft, every number "
                    "pulled fresh, with charts, implications and footnotes.",
     "instructions": """\
# Draft — write the article

Write the article into the draft from what is there: a plan, notes, or the instruction.

1. Read the draft (`get_draft`). Follow a plan's outline if there is one; otherwise use the
   writer's notes. If the draft is empty and the instruction gives only a topic, do not
   guess an article: say so, and offer the Plan step with `offer_next_step`.
2. Work section by section. Pull every number with the tools (`get_series`,
   `get_breakdown`, `screen`); a number you did not pull does not go in. If a planned claim
   fails, leave it out and say so in your reply.
3. Write it with `replace_draft`. Remove the plan. Keep any notes you did not use under
   "## Writer's Notes" at the end.
   - The finding in the first paragraph, with values and dates.
   - Headings name the measure and the cut. One idea per section.
   - Every number has its period and a source (a footnote), and a sentence saying what it
     means.
   - One to three charts, each with its message as the title. Prefer live Plover charts.
   - Implications: who gains, who pays, how much, and what it depends on.
   - The limits in one or two sentences.
4. `set_details` with a standfirst and a one-sentence summary, then `check_article`.

Reply with the word count, the number of figures traced, and anything left open. Then
`offer_next_step` twice: "Review It" (skill "Review") and "Fact Check" (skill "Fact Check").
""",
     },
    {"seed": "find-charts", "name": "Find Charts", "writes": False, "position": 40,
     "description": "Proposes three or four charts that carry the draft's argument, checked "
                    "against the data. Adds only the ones the writer picks.",
     "instructions": """\
# Find Charts — charts that carry the argument

Do not change the draft. Propose charts; the writer picks.

1. Read the draft (`get_draft`) and list its main claims.
2. For each claim a chart would carry, find the Plover data (`search`, `describe_dataset`)
   and pull it (`get_series`) to check it shows what the text says over the range you
   choose. Company and page charts count too: use the `cite` addresses the data tools return.
3. Propose three or four charts. Drop any whose data does not support the claim, and say so.

Reply as a numbered list. For each chart: its title in bold, stating the message; what it
shows, with the latest value and its period; where it goes (after which heading).

Then offer each with `offer_next_step`: label "Add: <short title>", no skill, instruction
"Add this chart after the heading '<heading>', with one sentence introducing it:
![<title>](<the exact chart address>)". Give the exact chart line, so the next run does not
search again.
""",
     },
    {"seed": "edit", "name": "Edit", "writes": True, "position": 50,
     "description": "Tightens the writing. Keeps the argument, the structure and every number, "
                    "chart and footnote.",
     "instructions": """\
# Edit — tighten the writing

Edit the draft's prose. Keep the argument, the structure and every number, chart, table and
footnote exactly as they are.

- Cut repetition, filler and throat-clearing. One idea per sentence.
- Lead each paragraph with its point.
- Replace a vague word with the specific one. "Coincides with", not "caused", unless the
  data shows the cause.
- Follow the house style for numbers, units and headings.
- Add no claims and no numbers. If a sentence needs a number it lacks, leave it and say so.
- If the writer gives notes (from a review, say), address each one.

Save with `replace_draft`. Reply with the word count before and after, and the three biggest
changes.
""",
     },
    {"seed": "review", "name": "Review", "writes": False, "position": 60,
     "description": "An editor's notes on the draft: weak claims, missing implications, "
                    "counter-arguments, with one click to fix them.",
     "instructions": """\
# Review — an editor's notes

Do not change the draft. Read it as a demanding editor at a research house would.

Check:
- **The point** — is the finding in the first paragraph? Could a reader say it in one
  sentence?
- **Evidence** — does every claim have a number with its period and source? Pull the two or
  three that matter most (`get_series`) and check them.
- **Implications** — does it say who gains, who pays and how much? A read-out of data with
  no consequence is the commonest failure: flag it.
- **Counter-arguments** — what would a sceptical reader say? Look for data we hold that
  cuts against the claim.
- **Causes** — any "because", "drove" or "caused" the data does not show.
- **Structure** — sections that repeat, no limits paragraph, a chart with no message.
- **House style.**

Reply with five to ten notes, most important first, as a numbered list: what is wrong,
where (quote a few words), and the fix. No praise. End with one line: ready to publish,
nearly, or needs work.

Then `offer_next_step`: label "Fix These", skill "Edit", instruction "Address these review
notes: <the notes, briefly>".
""",
     },
    {"seed": "fact-check", "name": "Fact Check", "writes": True, "position": 70,
     "description": "Check every number and comparative claim in the draft against Plover "
                    "data; correct what is wrong and list what cannot be traced.",
     "instructions": """\
# Fact Check — every number, traced

Read the draft (`get_draft`). Make a list of every number and every comparative claim:
"highest since", "first time", "Nth month in a row", "fastest", "twice", rankings.

For each one:
1. Find the series it comes from (`search`, `describe_dataset`) and pull it (`get_series`).
2. Check the value, the period, the unit and the basis (official or calculated; year-on-year
   or level). Rates are given to one decimal unless the house style says otherwise.
3. For a comparative claim, check **every** period it covers — count the run of months,
   find the last time the level was matched — never infer from a sample.
4. Check outside figures against the source the footnote names (`read_page`).

Then correct the draft (`replace_draft`, keeping everything else exactly as written):
- Fix a wrong number or claim, and say in your reply what it was and what it is now.
- A number you cannot trace stays, but tell the writer — do not delete their work.

Reply with a short table: claim → source → result (correct / corrected / cannot trace).
""",
     },
    {"seed": "headlines", "name": "Headlines", "writes": False, "position": 80,
     "description": "Five headline options, a standfirst and a Substack teaser. Each headline "
                    "can be used with one click.",
     "instructions": """\
# Headlines — titles and a teaser

Do not change the draft.

1. Read the draft (`get_draft`) and find its one finding.
2. Write five headline options. Each states the finding with its size, under 90
   characters: no question, no pun, no colon and subtitle. Vary the emphasis: the number,
   who it affects, the comparison.
3. Write a standfirst (one sentence: the finding and why it matters) and a Substack teaser
   (two or three sentences for a professional reader, one number, no hype).

Reply with the five headlines as a numbered list, then the standfirst, then the teaser.
Then offer each headline with `offer_next_step`: label "Use: <its first four words>", no
skill, instruction "Set the title to exactly: <headline>. Set the standfirst to exactly:
<standfirst>. Change nothing else."
""",
     },
    {"seed": "data-flash", "name": "Data Flash", "writes": True, "position": 90,
     "description": "A 300–450 word post on one new number: the fact, what it touches in a "
                    "second dataset, who gains or pays and by how much, one chart.",
     "instructions": """\
# Data Flash — one fact, its implications, one chart

A data flash reports what the data says and what follows from it, the same day. It
carries no forecast and no policy opinion. **No implications, no flash**: a read-out of
one series is not worth posting, and neither is a comparison that never says what it
means.

## 1. Find the fact
If the writer named the story, use it. Otherwise look for what changed, with the Plover
tools (never memory): `get_vintages` for new releases and revisions, `get_series` and
`get_overview` for a series at its highest or lowest in years or crossing a round number,
`screen` on buybacks, large shareholdings and earnings for unusual filings. Pick the
strongest: new this week, graspable in one line, chartable from data we hold.

## 2. Verify before writing
Pull every number fresh with `get_series`. For "highest since X" or "first time above N",
check **every** period between X and now, and state the last date it was matched. Quote
official figures exactly; label rates we calculate. If the claim fails, do not soften
it — say so in your reply and stop.

## 3. Find the angle
Set the fact beside a **second dataset we hold** that shows who pays, who earns or what
now looks out of line (a yield against bank loan rates; a CPI item against its weight;
visitor arrivals against guest-nights by prefecture). Same measure type only. Test how
unusual the comparison is across the whole overlapping history. State any mismatch in
dates or kind.

## 4. Turn the angle into two to four implications
Each one names who it falls on, states the consequence as a sentence with a verb, sizes
it in yen or points where we hold the base (labelled as calculated, not a forecast), and
says what it depends on. If none survives, write no flash: say why and suggest the next
candidate.

## 5. Write it into the draft (`replace_draft`)
300–450 words:
1. Title — the implication with its size, not the series name.
2. First paragraph — the fact, the angle and the headline implication, with values and dates.
3. One Plover chart showing the angle (usually two series), with a `Source:` line.
4. How unusual it is, ending "N implications follow."
5. One short paragraph per implication, opening with the implication in bold.
6. The limits in one or two sentences.
7. Footnotes for every source.
Then `set_details` with a one-sentence summary.

## 6. Check
Run `check_article`. In your reply list each number you used and where it came from.
Then `offer_next_step`: "Review It" (skill "Review").
""",
     },
]


def _now():
    return int(time.time())


_refreshed = set()      # store paths whose untouched seeds were brought up to date


def _seed_once():
    """Add each seed the first time it is seen, and mark it seen: a seed the
    team deleted is never put back, and a seed added in a later version still
    arrives. A seed nobody has edited takes this version's wording."""
    c = staff.conn()
    if str(staff.DB_PATH) not in _refreshed:
        _refreshed.add(str(staff.DB_PATH))
        with staff._lock:
            for s in SEEDS:
                c.execute("UPDATE team_skills SET description = ?, instructions = ?, writes = ? "
                          "WHERE seed = ? AND updated_by = 'Plover' AND (description != ? OR instructions != ?)",
                          (s["description"], s["instructions"], int(s["writes"]), s["seed"],
                           s["description"], s["instructions"]))
            c.commit()
    todo = [s for s in SEEDS if not c.execute("SELECT 1 FROM team_settings WHERE key = ?",
                                              ("skill_seed:" + s["seed"],)).fetchone()]
    if not todo:
        return
    with staff._lock:
        for s in todo:
            if not c.execute("SELECT 1 FROM team_skills WHERE seed = ? OR slug = ? OR lower(name) = lower(?)",
                             (s["seed"], s["seed"], s["name"])).fetchone():
                c.execute("INSERT INTO team_skills (slug, name, description, instructions, enabled, writes, "
                          "position, seed, created_at, created_by, updated_at, updated_by) "
                          "VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
                          (s["seed"], s["name"], s["description"], s["instructions"], int(s["writes"]),
                           s["position"], s["seed"], _now(), "Plover", _now(), "Plover"))
            c.execute("INSERT OR IGNORE INTO team_settings (key, value) VALUES (?, 'added')",
                      ("skill_seed:" + s["seed"],))
        # seeds added before skills had an order take their place in it
        for s in SEEDS:
            c.execute("UPDATE team_skills SET position = ? WHERE seed = ? AND position = 100",
                      (s["position"], s["seed"]))
        c.commit()


def _shape(r):
    return {"id": r["id"], "slug": r["slug"], "name": r["name"], "description": r["description"],
            "instructions": r["instructions"], "enabled": bool(r["enabled"]),
            "writes": bool(r["writes"]), "position": r["position"],
            "seeded": bool(r["seed"]), "updated_at": r["updated_at"], "updated_by": r["updated_by"]}


def list_skills(enabled_only=False):
    _seed_once()
    sql = "SELECT * FROM team_skills" + (" WHERE enabled = 1" if enabled_only else "") + " ORDER BY position, name"
    return [_shape(r) for r in staff.conn().execute(sql).fetchall()]


def get(ref):
    """A skill by id or slug, or None."""
    _seed_once()
    c = staff.conn()
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        r = c.execute("SELECT * FROM team_skills WHERE id = ?", (int(ref),)).fetchone()
    else:
        r = c.execute("SELECT * FROM team_skills WHERE slug = ? OR lower(name) = lower(?)",
                      (str(ref or "").strip().lower(), str(ref or "").strip())).fetchone()
    return _shape(r) if r else None


def _clean(name, description, instructions):
    name = " ".join((name or "").split())
    description = " ".join((description or "").split())
    instructions = (instructions or "").replace("\r\n", "\n").strip()
    if not name:
        raise SkillError("Give the skill a name.")
    if len(name) > NAME_MAX:
        raise SkillError("Keep the name under %d characters." % NAME_MAX)
    if not description:
        raise SkillError("Say in one line when to use it: the AI reads this to choose.")
    if len(description) > DESCRIPTION_MAX:
        raise SkillError("Keep the description under %d characters." % DESCRIPTION_MAX)
    if not instructions:
        raise SkillError("Write the steps the AI should follow.")
    if len(instructions) > INSTRUCTIONS_MAX:
        raise SkillError("Keep the steps under %d characters." % INSTRUCTIONS_MAX)
    return name, description, instructions


def _slug(name):
    return _SLUG.sub("-", name.lower()).strip("-")[:60] or "skill"


def create(name, description, instructions, by, writes=True):
    name, description, instructions = _clean(name, description, instructions)
    _seed_once()
    c = staff.conn()
    with staff._lock:
        if c.execute("SELECT COUNT(*) AS n FROM team_skills").fetchone()["n"] >= SKILLS_MAX:
            raise SkillError("The team has %d skills, the most it can keep. Delete one first." % SKILLS_MAX)
        base = slug = _slug(name)
        n = 2
        while c.execute("SELECT 1 FROM team_skills WHERE slug = ?", (slug,)).fetchone():
            slug = "%s-%d" % (base, n)
            n += 1
        if c.execute("SELECT 1 FROM team_skills WHERE lower(name) = lower(?)", (name,)).fetchone():
            raise SkillError("A skill called %s already exists." % name)
        cur = c.execute("INSERT INTO team_skills (slug, name, description, instructions, enabled, writes, "
                        "created_at, created_by, updated_at, updated_by) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
                        (slug, name, description, instructions, int(bool(writes)), _now(), by, _now(), by))
        c.commit()
    return get(cur.lastrowid)


def update(skill_id, by, name=None, description=None, instructions=None, enabled=None, writes=None):
    cur = get(int(skill_id))
    if cur is None:
        raise SkillError("No such skill.")
    name, description, instructions = _clean(
        cur["name"] if name is None else name,
        cur["description"] if description is None else description,
        cur["instructions"] if instructions is None else instructions)
    c = staff.conn()
    with staff._lock:
        if c.execute("SELECT 1 FROM team_skills WHERE lower(name) = lower(?) AND id != ?",
                     (name, cur["id"])).fetchone():
            raise SkillError("A skill called %s already exists." % name)
        c.execute("UPDATE team_skills SET name = ?, description = ?, instructions = ?, enabled = ?, "
                  "writes = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                  (name, description, instructions,
                   int(cur["enabled"] if enabled is None else bool(enabled)),
                   int(cur["writes"] if writes is None else bool(writes)), _now(), by, cur["id"]))
        c.commit()
    return get(cur["id"])


def delete(skill_id):
    c = staff.conn()
    with staff._lock:
        c.execute("DELETE FROM team_skills WHERE id = ?", (int(skill_id),))
        c.commit()


def house_style():
    return staff.team_setting("house_style", HOUSE_STYLE)


def set_house_style(text):
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) > STYLE_MAX:
        raise SkillError("Keep the house style under %d characters." % STYLE_MAX)
    staff.set_team_setting("house_style", text or HOUSE_STYLE)
    return house_style()


def menu_text(skills):
    """The list of skills the AI is shown, one line each."""
    return "\n".join("- %s%s: %s" % (s["name"], "" if s["writes"] else " (answers only; leaves the draft alone)",
                                     s["description"]) for s in skills)
