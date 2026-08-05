#!/usr/bin/env python3
"""
BUILD_PACKET  v2.0  ·  Hypersourced client packet renderer  ·  2026-08-05 02:35

WHAT THIS IS, IN ONE BREATH
  Three things go in: a design template that never changes, a small content file
  holding only what differs per search, and (optionally) the scored spreadsheet
  Emerald Weapon produced. One finished packet comes out, as a single HTML file
  you can read in a browser, print to PDF, or text to somebody.

WHY IT IS SPLIT THIS WAY
  The design lives in code and no model ever touches it, so it cannot drift.
  Run this twice on the same inputs and you get two byte-identical files. That
  is the whole reason the layout is not generated per search.

TWO MODES, ONE TEMPLATE
  "report" — after the search runs. Results first, in sales order:
               01 Results       the headline numbers
               02 Your top ten  the proof, with the full case for each
               03 How we got there   the two questions that carry 350 of 400 points
               04 How we reach them  cadence plus the actual copy
               05 Zero risk         the commercial terms, and only those
               06 The full Elite band
  "plan"   — before the search runs. No candidates exist yet, so it runs the role
             narrative and requirements instead and asks for approval.
  Set it in the content file's "mode" key.

WHY RESULTS COME FIRST
  A client who has already paid does not need to be sold the method before being
  shown the outcome. Lead with what they got, prove it with ten names, then explain
  how, then what happens next, then price. The method section is much more
  persuasive AFTER somebody has read ten candidates they want to call.

NO KILL SWITCHES IN THE CLIENT VIEW
  Disqualifiers are deliberately absent from the report. Telling a client what was
  thrown away invites an argument about the discards instead of a conversation about
  the shortlist, and the one disqualifier that matters to them — we never approach
  your own staff — is stated where it lands, on the roster.

THE CURRENT-EMPLOYER RULE
  Anyone whose current company matches the hiring company is dropped from the
  candidate list and counted separately. This is the packet-side belt to the
  engine's braces: even if a bad row reaches this script, it never reaches a
  client. See drop_hiring_company() below.
"""

import json, html, re, base64, argparse, secrets, sys
from datetime import datetime
import re
from pathlib import Path

HERE = Path(__file__).parent

# ---------------------------------------------------------------------------
# POOL-RELATIVE BANDS
# Mirrors Emerald Weapon's apply_pool_relative_bands so the packet reports the
# same bands the engine does. Kept here so a packet can be rebuilt from an older
# spreadsheet that predates the engine feature.
# ---------------------------------------------------------------------------
BAND_PERCENTILES = [("Elite", .10), ("Strong", .30), ("Viable", .60),
                    ("Stretch", .85), ("Long Shot", 1.00)]
BAND_MIN_POOL = 15


def pool_bands(scores):
    """Given scores descending, return [(band, cutoff_score, count), ...].

    Ties share a band: a boundary that split two identical scores would be
    arbitrary and the client would rightly ask why.
    """
    n = len(scores)
    if n < BAND_MIN_POOL:
        return None
    out, prev = [], 0
    for name, pct in BAND_PERCENTILES:
        idx = max(1, min(n, round(pct * n)))
        while idx < n and scores[idx] == scores[idx - 1]:
            idx += 1
        if idx > prev:
            out.append((name, scores[idx - 1], idx - prev))
        prev = idx
    return out


def drop_hiring_company(rows, aliases):
    """Split candidates into (keep, dropped). Dropped are the client's own staff.

    Normalisation is deliberately strict: lowercase, strip punctuation and the
    usual legal suffixes, then require an exact match or a whole-word alias hit.
    Fuzzy matching here would silently delete real candidates, and a wrong
    exclusion is invisible to everybody downstream.
    """
    def norm(s):
        s = re.sub(r"[^\w\s]", " ", str(s or "").lower())
        s = re.sub(r"\b(inc|llc|ltd|corp|co|company|holdings|group|plc|sa|gmbh|ag|bv|nv|pbc)\b", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    norm_aliases = {norm(a) for a in aliases if norm(a)}
    keep, dropped = [], []
    for r in rows:
        c = norm(r.get("company"))
        hit = c in norm_aliases or any(
            re.search(rf"\b{re.escape(a)}\b", c) for a in norm_aliases if a)
        (dropped if hit else keep).append(r)
    return keep, dropped


# ---------------------------------------------------------------------------
# THREE BULLETS PER CANDIDATE
#
# In production the payload writes this field ("Why This Person") directly. It
# does not exist in runs made before v5.11, so this derives an equivalent from
# Score Math, which itemises every signal with its reason. That is the same
# material the model reads, so the shape here previews the shape there.
#
# One bullet each, in this order and never reordered:
#   1  what they do NOW that maps to this seat        <- Role-Responsibility line
#   2  where they have been that makes it credible    <- Company DNA / alumni / anchor
#   3  the single distinguishing fact                 <- Golden Signal / Proven Impact / Boomerang
# ---------------------------------------------------------------------------

SIGNAL_RE = re.compile(r"^\s*([+-]\d+)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$", re.M)


def three_bullets(row, score_math, education, awards):
    """Return exactly three short strings. Never fewer — a missing bullet is an
    em dash, because a blank looks like a rendering fault rather than an absence."""
    sig = {}
    for pts, name, why in SIGNAL_RE.findall(str(score_math or "")):
        if int(pts) != 0:
            sig.setdefault(name.strip(), why.strip())

    def trim(t, n=22):
        t = re.sub(r"\s+", " ", t).strip().rstrip(".")
        words = t.split()
        return " ".join(words[:n]) + ("..." if len(words) > n else "")

    # 1 — the seat they hold now
    b1 = sig.get("Role-Responsibility Match") or row.get("title") or ""
    if b1:
        b1 = re.sub(r"^(Senior|Principal|Lead|Staff)\s+", "", b1)

    # 2 — the ground under it. Prefer schools, then the employer's shape.
    edu = str(education or "").strip()
    if edu and edu.lower() not in ("nan", "n/a", ""):
        schools = [p.split(",")[0].strip() for p in edu.split(";")][:2]
        degrees = re.findall(r"\b(PhD|Ph\.D|Doctor|Master|Bachelor|MS|BS|MBA)\b", edu, re.I)
        b2 = ", ".join(dict.fromkeys(schools))
        if degrees:
            b2 += f" ({', '.join(dict.fromkeys(d.upper() for d in degrees))})"
    else:
        b2 = sig.get("Company DNA Overlap", "")

    # 3 — the thing you would say out loud, in order of how much it says
    for key in ("Proven Impact", "Golden Signal", "Boomerang", "Fast Tracker",
                "M&A Survivor", "Bilingual Bench", "The Anchor", "Top-Tier Alumni"):
        if key in sig:
            b3 = sig[key]
            break
    else:
        aw = str(awards or "").strip()
        b3 = aw if aw.lower() not in ("nan", "n/a", "") else ""

    return [trim(b) if b else "\u2014" for b in (b1, b2, b3)]


def load_candidates(xlsx_path, aliases, elite_band=None, featured=10):
    """Read the scored sheet and shape it for the report.

    Returns the funnel numbers, the Elite band, and the featured top slice.
    `why` is the last sentence of Candidate Fit — the payload writes that field
    facts-first, argument-last, so the closing sentence is always the conclusion
    and makes a clean one-liner for the long list.
    """
    import pandas as pd
    df = pd.read_excel(xlsx_path)

    def col(r, name, default=""):
        v = r.get(name, default)
        if v is None:
            return default
        s = str(v).strip()
        return default if s.lower() in ("nan", "none", "") else s

    total = len(df)
    eliminated = int((df["Score"] == -1000).sum()) + int((df["Score"] == 0).sum())
    sc = df[df["Score"] > 0].sort_values("Score", ascending=False)

    rows = []
    for _, r in sc.iterrows():
        city, state = col(r, "City"), col(r, "State")
        fit = col(r, "Candidate Fit")
        why = re.split(r"(?<=[.!?])\s+", fit.strip())[-1] if fit else ""
        rows.append(dict(
            score=int(r["Score"]),
            first=col(r, "First Name"), last=col(r, "Last Name"),
            title=col(r, "Current Job Title", "Title not listed"),
            company=col(r, "Current Company", "Employer not resolved"),
            loc=", ".join([p for p in (city, state) if p]) or "Boston area",
            reloc=col(r, "Relocation Tier"), fit=fit, why=why,
            url=col(r, "LinkedIn URL"),
            math=col(r, "Score Math"),
            outreach={
                "Email one":  (col(r, "Email 1 Subject"), col(r, "Email 1 Body")),
                "Voicemail":  ("", col(r, "Call Script")),
                "Email two":  ("", col(r, "Email Follow-Up")),
                "LinkedIn":   ("", col(r, "LinkedIn Message")),
                "Text":       ("", col(r, "Text Message 1")),
            },
        ))
        rows[-1]["bullets"] = three_bullets(
            rows[-1], col(r, "Score Math"), col(r, "Education"), col(r, "Awards"))

    keep, dropped = drop_hiring_company(rows, aliases)
    for i, r in enumerate(keep, 1):
        r["rank"] = i

    # The Elite band is the top decile of the scored pool, matching the engine.
    # Ties share a band, so the boundary walks forward past equal scores.
    n = len(keep)
    if elite_band:
        cut = min(elite_band, n)
    else:
        cut = max(1, min(n, round(0.10 * n)))
        while cut < n and keep[cut]["score"] == keep[cut - 1]["score"]:
            cut += 1

    # Band counts for the section 01 breakdown. Same percentiles the engine uses,
    # so the packet and the spreadsheet never disagree about who is Elite. Returns
    # None under BAND_MIN_POOL, and section 01 falls back to the banner alone.
    bands = pool_bands([r["score"] for r in keep])

    # THE FEATURED TEN ARE FIVE ELITE PLUS FIVE FROM THE BAND BELOW.
    # They are examples, not a shortlist. Ten straight off the top would all look
    # alike and would tell the client nothing about where the line falls; showing
    # the top of Elite against the top of Strong makes the boundary visible and
    # makes the case that the band is a judgement rather than a cut-off.
    half = featured // 2
    top = keep[:half]
    below = keep[cut:cut + (featured - half)]
    feat = top + below
    # Numbered 1..10 in the order shown. These are not overall ranks -- the second
    # five sit outside Elite entirely and do not appear in the section 06 roster.
    for i, r in enumerate(feat, 1):
        r["feat_rank"] = i

    return dict(total=total, eliminated=eliminated, scored=n, dropped=dropped,
                bands=bands, keep=keep,
                elite=keep[:cut], elite_n=cut,
                featured=feat, featured_n=len(feat))


# ---------------------------------------------------------------------------
# RENDER
# ---------------------------------------------------------------------------
E = lambda s: html.escape(str(s), quote=True)


def paras(lst):
    return "\n".join(f"<p>{E(p)}</p>" for p in lst)


def ul(items):
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def section(num, word, heading, body, brk=False):
    return f'''
<section class="block{' pagebreak' if brk else ''}">
  <div class="rail"><p class="numeral">{num}</p><p class="railword">{E(word)}</p></div>
  <div class="flow">
{f'    <h2>{E(heading)}</h2>' + chr(10) if heading else ''}{body}
  </div>
</section>'''


def facts(rows):
    out = ['<div class="facts">']
    for label, pts, sub in rows:
        out.append(f'<div class="fact"><span class="label">{E(label)}</span>'
                   f'<span class="pts">{E(pts)}</span>'
                   f'<span class="sub">{E(sub)}</span></div>')
    out.append("</div>")
    return "\n".join(out)


def tiers_block(rows, unit=" pts"):
    """Points and headcount on one line, at one size, colour-ranked.

    The top band is green and the second is mid-ink, so a client sees where the
    weight sits without reading a number. Everything below is muted — those
    bands exist to show the shape of the market, not to be studied.
    """
    out = ['<div class="scale">']
    for i, (pts, count, meaning) in enumerate(rows):
        cls = " t1" if i == 0 else (" t2" if i == 1 else "")
        n = str(pts).strip()
        who = str(count).strip()
        out.append(f'''  <div class="step">
    <p class="step-line{cls}"><b class="step-pts">{E(n)} points</b>
      <span class="step-sep">/</span><b class="step-count">{E(who)}</b></p>
    <p class="step-what">{E(meaning)}</p>
  </div>''')
    out.append("</div>")
    return "\n".join(out)


def dimension(heading, ceiling, body, tiers, extra="", newpage=False):
    """One scoring dimension as a self-contained block.

    newpage starts the block on a fresh sheet. Role match uses it: it was landing
    at the foot of the Company match page with its own tier scale pushed overleaf,
    which made the second of two equal pillars read as an afterthought to the first.
    """
    cls = "dim newpage" if newpage else "dim"
    return (f'<div class="{cls}"><p class="dim-h">{E(heading)}</p>'
            f'<p class="dim-sub">{E(ceiling)}</p></div>\n'
            + body + "\n" + tiers + ("\n" + extra if extra else ""))


def first_last(r):
    return f"{r['first']} {r['last']}".strip() or "Name not resolved"


def name_link(r):
    n = first_last(r)
    return f'<a href="{E(r["url"])}">{E(n)}</a>' if r["url"].startswith("http") else E(n)


def render_results(c, m):
    """Section 01. One banner number, then how the scored pool broke down.

    NO h2 ON THIS SECTION. The rail already says RESULTS and the bignote right
    below is the real headline, so a "What the search produced" heading between
    them said the same thing a third time. section() omits the h2 when the
    heading is empty.

    RULED OUT INCLUDES THE CLIENT'S OWN STAFF.
      Anyone currently working at the hiring company is dropped before ranking.
      They used to be reported in a separate callout, which is gone -- a client
      does not need to be told we are not poaching their own people. But the
      count still has to live somewhere or the arithmetic stops closing: 957
      analysed less 274 eliminated is 683, not the 680 we scored. They are
      folded into "ruled out" here, which is what they are, and the three
      numbers reconcile.

    THE BANDS ARE THE ENGINE'S BANDS.
      Elite / Strong / Viable / Stretch / Long Shot, cut at the same percentiles
      Emerald Weapon uses, so the packet never disagrees with the spreadsheet.
      Descriptions are per-search and live in the content file.
    """
    d = m["results"]
    ruled_out = c["eliminated"] + len(c["dropped"])
    bands = c.get("bands") or []
    desc = m.get("band_notes", {})

    # The caption and the split sit BESIDE the headline figure, not under it. Two
    # stacked lines under a 42pt number cost about forty points of vertical space,
    # which was the difference between the LinkedIn banner landing on page one and
    # being pushed onto page two.
    head = (f'<div class="fbanner"><div class="fb-n">'
            f'<p class="big">{c["total"]:,}</p></div>'
            f'<div class="fb-t">'
            f'<p class="cap">{E(d["banner_caption"])}</p>'
            f'<p class="sub">{ruled_out:,} Eliminated &middot; '
            f'{c["scored"]:,} Scored and ranked.</p></div></div>')

    if not bands:
        return (f'<h3 class="bignote">{E(d["headline"])}</h3>\n<p>{E(d["lede"])}</p>\n{head}'
                f'\n<p style="margin-top:26px">{E(d["closing"])}</p>')

    # ONE BOX, FIVE BANDS, ARROWS BETWEEN ALL OF THEM.
    # The Elite figure used to sit in its own green panel with the other four in a
    # plain strip underneath, which read as two unrelated things. It is one ladder,
    # so it is one box: Elite emphasised, then an arrow into each band below it.
    cells = []
    for i, (name, _cut, count) in enumerate(bands):
        if i:
            cells.append('<div class="a">&rsaquo;</div>')
        cls = "c lead" if i == 0 else "c"
        cells.append(f'<div class="{cls}"><p class="sn">{count:,}</p>'
                     f'<p class="sl">{E(name)}</p></div>')
    # No caption inside the box. "Listed in full in Section 6" now rides on the
    # claim line below it, where it belongs -- part of the promise, not a footnote
    # to a number.
    ladder = '<div class="ladder"><div class="rungs">' + "".join(cells) + "</div></div>"

    # The claim appears ONCE here, not again in section 02. Section 2D asks for it
    # in both, which was right when the two sections were pages apart. They now
    # share page one, so a second copy reads as a stutter rather than a refrain.
    claim = f'<p class="claim">{E(m["elite_claim"])}</p>' if m.get("elite_claim") else ""

    # No closing paragraph. It restated the five-by-five explanation that appears a
    # few lines further down in section 02.
    return (f'<h3 class="bignote">{E(d["headline"])}</h3>\n<p>{E(d["lede"])}</p>\n'
            + head + "\n" + ladder + "\n" + claim)


def render_featured(c, m, li_b64=""):
    """Section 02. The proof: ten candidates with the full written case.

    THE "N PEOPLE REMOVED" CALLOUT IS GONE, DELIBERATELY.
      It told the client we had excluded their own staff. Of course we had. The
      count now lives inside "ruled out" in section 01 so the arithmetic still
      closes -- see render_results.

    Its slot is now the LinkedIn banner, which does work the old note did not:
    every candidate name is already a link to that person's profile, and nothing
    in the document said so.

    RANK SITS ON THE RIGHT, AS A GREEN DISC.
      The row is a table, not a grid. A right-aligned cell in a grid is the exact
      construction that broke section 01 in the PDF. See the note on .cand-top.
    """
    out = [f'<p>{E(m["featured_intro"])}</p>']
    if li_b64 and m.get("li_note"):
        out.append(
            '<div class="li-note">\n'
            '  <div class="li-mark"><i aria-label="LinkedIn"></i></div>\n'
            f'  <div class="li-copy">{E(m["li_note"])}</div>\n'
            '</div>')
    out.append('<div class="pagebreak-here"></div>')
    out.append('<div class="roster">')
    for r in c["featured"]:
        reloc = (f'<span class="cand-reloc">{E(r["reloc"])}</span>'
                 if r["reloc"] and r["reloc"] != "Next Door" else "")
        bullets = "".join(f"<li>{E(b)}</li>" for b in r.get("bullets", []))
        out.append(
            '  <article class="cand">\n'
            '    <div class="cand-top">\n'
            '      <div class="cand-id">\n'
            f'        <p class="cand-name">{name_link(r)} '
            f'<b class="cand-dash">-</b> <b class="cand-score">{r["score"]}</b></p>\n'
            f'        <p class="cand-role">{E(r["title"])} &middot; {E(r["company"])}</p>\n'
            f'        <p class="cand-meta">{E(r["loc"])}{reloc}</p>\n'
            '      </div>\n'
            f'      <span class="cand-rank">'
            f'<i>{r.get("feat_rank", r["rank"])}</i></span>\n'
            '    </div>\n'
            f'    <ul class="cand-bullets">{bullets}</ul>\n'
            f'    <p class="cand-fit">{E(r["fit"])}</p>\n'
            '  </article>')
    out.append("</div>")
    return "\n".join(out)


def score_math_points(math, label):
    """Pull the points a candidate earned on one scoring dimension.

    Score Math is written by the payload as one line per dimension:
        +200 | Company DNA Overlap | Dyno Therapeutics is on the Poach Map ...
    Returns 0 when the dimension is absent, which is correct -- a dimension with
    no line scored nothing.
    """
    for line in str(math).splitlines():
        if label.lower() in line.lower():
            m = re.match(r"\s*([+-]?\d{1,3})\s*\|", line)
            if m:
                return int(m.group(1))
    return 0


def dimension_counts(keep, label, tier_points):
    """How many candidates landed on each tier of one dimension. DERIVED, NEVER TYPED.

    This used to be hand-entered in the content file, and it was wrong. The role
    tiers summed to 677 against a pool of 680, because the payload had emitted
    three candidates at point values the rubric does not define -- two at 75 and
    one at 25 -- and the typed table had no row for them. Nobody could see it
    without adding up a column in a client-facing document.

    Off-rubric values are folded into the nearest DEFINED tier at or below them,
    so the published rows always sum to the pool, and every one is reported in the
    build output so the payload problem stays visible to the operator rather than
    being silently smoothed over.
    """
    tiers = sorted({int(p) for p in tier_points}, reverse=True)
    counts = {t: 0 for t in tiers}
    odd = []
    for r in keep:
        v = score_math_points(r.get("math", ""), label)
        if v in counts:
            counts[v] += 1
            continue
        landed = next((t for t in tiers if t <= v), tiers[-1])
        counts[landed] += 1
        odd.append((r.get("first", ""), r.get("last", ""), v, landed))
    return counts, odd


def render_method(m, c=None):
    """Section 03. How the ranking was produced. No disqualifiers — see module docstring.

    The candidate counts beside each point tier come from the spreadsheet, not
    from the content file. The labels and the prose are authored; the numbers are
    counted. See dimension_counts.
    """
    d = m["method"]

    def tiers(key, label):
        rows = d[key]
        if not c or not c.get("keep"):
            return rows                      # plan mode: no pool to count yet
        counts, odd = dimension_counts(c["keep"], label, [r[0] for r in rows])
        for name, surname, got, landed in odd:
            print(f"  OFF-RUBRIC: {name} {surname} scored {got} on {label}, which is "
                  f"not a defined tier. Counted at {landed}. Fix the payload.")
        return [[p, f"{counts[int(p)]:,} candidates", *rest] for p, _old, *rest in rows]
    dna_h, _, dna_c = d["dna_heading"].partition("\u00b7")
    role_h, _, role_c = d["role_heading"].partition("\u00b7")
    return "\n".join([
        f'<p>{E(d["lede"])}</p>',
        dimension(dna_h.strip(), dna_c.strip() or "up to 200 points",
                  f'<p>{E(d["dna_body"])}</p>\n<p>{E(d["dna_axis"])}</p>',
                  tiers_block(tiers("dna_tiers", "Company DNA Overlap"))),
        dimension(role_h.strip(), role_c.strip() or "up to 150 points",
                  f'<p>{E(d["role_body"])}</p>',
                  tiers_block(tiers("role_tiers", "Role-Responsibility Match")),
                  f'<p class="aside">{E(d["role_note"])}</p>', newpage=True),
        '<div class="pagebreak-here"></div>',
        f'<div class="dim"><p class="dim-h">{E(d["rest_heading"])}</p></div>',
        f'<p>{E(d["rest_body"])}</p>',
        '<div class="signals">' + "".join(
            f'<div class="sig"><span class="sig-pts">{E(p)}</span>'
            f'<div class="sig-b"><p class="sig-n">{E(n)}<span class="sig-who">{E(who)}</span></p>'
            f'<p class="sig-w">{E(why)}</p></div></div>'
            for n, p, who, why in d["rest_examples"]) + "</div>",
        f'<p style="margin-top:22px">{E(d["rest_close"])}</p>',
    ])


def sheet_samples(top):
    """The outreach copy for the top-ranked candidate, IF the run produced any.

    WHY THIS IS OPTIONAL.
      Outreach is the expensive half of a run. Scoring a market is cheap; writing
      a personalised message for every scored candidate is not. So most pulls are
      scored only, and the sheet's outreach columns come back empty -- that is the
      normal case, not a fault. The Nabla run is one of them: 0 of 683 scored rows
      carried any.

      When the columns ARE populated, the packet must show what the engine actually
      wrote, never a fresh invention, because that copy is what the recruiter will
      send. When they are empty, the samples come from the content file, where
      Hypersourced AI has written them for this one candidate from their own
      record. See section 2D.1 of the instructions.

    Returns None when the sheet has nothing, which is the signal to fall back.
    """
    if not top or not top.get("outreach"):
        return None
    got = {k: v for k, v in top["outreach"].items() if len((v[1] or "").strip()) > 3}
    if not got:
        return None
    order = ["Email one", "Voicemail", "Email two", "LinkedIn", "Text"]
    return [[k, "", top["outreach"][k][0], top["outreach"][k][1]]
            for k in order if k in got]


def render_outreach(m, c=None):
    """Section 04. Channels and the actual copy.

    The day-by-day timeline is gone. The order of touches is decided per
    candidate by which contact details resolve, so a printed cadence was a
    promise the system could not keep — and it rendered badly at every width
    because six columns of dated markers do not fit a page.
    """
    out = [f'<p>{E(m["cadence_intro"])}</p>', '<div class="channels">']
    for name, note in m.get("channels", []):
        out.append(f'<div class="chn"><p class="chn-n">{E(name)}</p>'
                   f'<p class="chn-d">{E(note)}</p></div>')
    out.append("</div>")
    # "100% US-based" used to sit in section 05's list of core points, alongside the
    # fee and the termination terms. It is a true claim about how the work is done,
    # not a term of the agreement, and a reader scanning that list had no way to tell
    # the difference. It lives here now, next to the channels it actually describes.
    # Optional: omit outreach_note from the content file and nothing renders.
    if m.get("outreach_note"):
        out.append(f'<p class="aside">{E(m["outreach_note"])}</p>')
    out += [f'<h3>What it actually says</h3>', f'<p>{E(m["samples_intro"])}</p>']
    samples = (sheet_samples((c or {}).get("featured", [None])[0])
               if c else None) or m["samples"]
    for chan, when, subj, text in samples:
        subj_html = f'<p class="subj">{E(subj)}</p>' if subj else ""
        out.append(f'''<div class="msg">
  <div class="msg-head"><span class="chan">{E(chan)}</span></div>
  {subj_html}<p class="body">{E(text)}</p></div>''')
    return "\n".join(out)



def cta_body_html(e):
    """Closing paragraph, with the agreement hyperlinked in place of a placeholder.

    THE LINK IS A SINGLE FIELD, ON PURPOSE.
      Packets go out as PDF attachments. A PDF cannot be repaired after it is sent,
      so a link that dies takes every packet already in a client's inbox with it.
      agreement_url lives in the content file as one value, referenced by name here,
      so pointing it at a permanent address is one edit and never a search across
      rendered documents. Prefer a redirect you control over any share link a
      storage provider generated.
    """
    body = E(e["cta_body"])
    url, phrase = e.get("agreement_url"), e.get("agreement_phrase")
    if url and phrase and E(phrase) in body:
        body = body.replace(E(phrase), f'<a href="{E(url)}">{E(phrase)}</a>', 1)
    return body


def render_engagement(m):
    """Section 05. The commercial terms, and nothing that is not one.

    THERE IS NO TIER TABLE, AND THERE MUST NOT BE ONE.
      An earlier version rendered $25,000 / $22,500 / $20,000 for first, second and
      third hire "per campaign". None of that exists in the signed Master Sourcing
      Agreement, which sets a flat $25,000 Placement Fee with no volume language and
      no campaign construct at all. The table promised a client $7,500 per extra hire
      that the contract does not grant. It was deleted rather than fixed.

    EVERY BULLET HERE TRACES TO A CLAUSE.
      Nothing up front / no exclusivity  -> 01b, no pre-pay or exclusivity obligations
      Either side can walk               -> 02, termination does not end the fee
                                            obligation for candidates hired during or
                                            after it, which is why the bullet says so
      Someone you already knew           -> 01c, documented proof within three days
      Nothing owed if it does not stick  -> 01b, no fee invoiced or payable before day
                                            30, and explicitly no refund, credit or
                                            replacement search
      The fee                            -> 01a and 01b, flat $25,000, invoiced on the
                                            30th day, due on receipt, and triggered by
                                            an Engagement at the client OR an affiliate

    If a term changes, it changes in the agreement first and in this file second.
    """
    e = m["engagement"]
    pts = []
    for label, text, open_term in e["points"]:
        t = f'<span class="slot">{E(text)}</span>' if open_term else E(text)
        pts.append(f"<strong>{E(label)}.</strong> {t}")
    return (f'<p>{E(e["intro"])}</p>\n' +
            "\n<h4>The core points</h4>\n" + ul(pts) +
            "\n<h4>What we need from you</h4>\n" + ul([E(x) for x in e["asks"]]) +
            f'''\n<div class="callout"><h3>{E(e['cta_heading'])}</h3>
  <p>{cta_body_html(e)}</p>
  <a class="cta" href="{E(e.get('cta_href', 'https://meetings.hubspot.com/hypersourced/welcome'))}">{E(e['cta_label'])}</a></div>''')


def render_roster(c, m):
    """Section 06. The full Elite band. The featured ten are compact here too —
    their full case is in 02 — so the list reads as one continuous ranking."""
    out = [f'<p>{E(m["roster_intro"])}</p>', '<div class="list">']
    for r in c["elite"]:
        star = ' <span class="in02">detailed in 02</span>' if r["rank"] <= c["featured_n"] else ""
        out.append(f'''  <div class="row">
    <span class="row-n">{r['rank']:02d}</span>
    <div class="row-b">
      <p class="row-name">{name_link(r)}{star}</p>
      <p class="row-role">{E(r['title'])} &middot; {E(r['company'])}</p>
      <p class="row-why">{E(r['why'])}</p>
    </div>
    <span class="row-s">{r['score']}</span>
  </div>''')
    out.append("</div>")
    return "\n".join(out)



def og_meta(m, cands, base_url, slug):
    """Open Graph tags, emitted at the very top of <head>.

    Two things here are load-bearing and easy to get wrong:

    1. og:image MUST be an absolute https URL to a real file. Data URIs are
       ignored by every scraper, so the packet's embedded logo cannot serve as
       the preview. og.png ships alongside index.html for exactly this reason.

    2. These tags sit ABOVE the embedded font payload. Several scrapers read
       only the first chunk of a page, and 168 KB of base64 between <head> and
       the og tags is enough for some of them to give up and show a bare link.

    Note the robots directive: `noindex` on the page keeps these out of search
    results, but it does NOT block fetching. Blocking in robots.txt instead
    would also block the preview scrapers and you would get no card at all.
    """
    base = (base_url or "").rstrip("/")
    page = f"{base}/{slug}/" if base else ""
    title = f"{m['client']} · {m['role']}"
    if cands:
        desc = (f"{cands['elite_n']} candidates worth calling, ranked from "
                f"{cands['total']:,} analysed. Prepared by Hypersourced.")
        stat = f"{cands['elite_n']} candidates · ranked and researched"
    else:
        desc = f"Search plan for {m['role']} at {m['client']}. Prepared by Hypersourced."
        stat = "Search plan · ready for approval"
    tags = [
        '<meta name="robots" content="noindex, nofollow">',
        f'<meta name="description" content="{E(desc)}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Hypersourced">',
        f'<meta property="og:title" content="{E(title)}">',
        f'<meta property="og:description" content="{E(desc)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{E(title)}">',
        f'<meta name="twitter:description" content="{E(desc)}">',
        '<meta name="theme-color" content="#204652">',
    ]
    if page:
        tags += [f'<meta property="og:url" content="{E(page)}">',
                 f'<meta property="og:image" content="{E(page)}og.png">',
                 '<meta property="og:image:width" content="1200">',
                 '<meta property="og:image:height" content="630">',
                 f'<meta property="og:image:alt" content="{E(title)}">',
                 f'<meta name="twitter:image" content="{E(page)}og.png">']
    else:
        tags.append("<!-- no --base-url given, so no og:image. Link previews need "
                    "an absolute URL; rebuild with --base-url to enable them. -->")
    return "\n".join(tags), stat


def build(content, cands, template, logo_b64, meta_html="", li_b64=""):
    m = content
    report = (m.get("mode") == "report") and cands is not None
    S = []

    # Section 05 is built ONCE, here, and the same object is dropped into both the
    # report and the plan. It used to be written out twice with its title and heading
    # typed as literals in each branch, which meant the commercial section lived in
    # four places: two literals here, the copy in the content file, and a tier table
    # in the renderer. A term that has to be changed in four places eventually gets
    # changed in three. Title, heading and body now all come from content["engagement"].
    eng = m["engagement"]
    sec05 = section("05", eng["section_word"], eng["heading"],
                    render_engagement(m), brk=True)

    if report:
        S.append(section("01", "Results", "",
                         render_results(cands, m)))
        S.append(section("02", "Five by five", "Ideal candidates",
                         render_featured(cands, m, li_b64)))
        S.append(section("03", "Method", "How candidates are scored", render_method(m, cands), brk=True))
        S.append(section("04", "Outreach", "How we reach them", render_outreach(m, cands), brk=True))
        S.append(sec05)
        S.append(section("06", "The list", f"All {cands['elite_n']}, ranked",
                         render_roster(cands, m), brk=True))
    else:
        p = m["plan_only"]
        r = p["role_narrative"]
        body = (f"<h3>{E(r['company_heading'])}</h3>\n{paras(r['company'])}\n"
                f"<h3>{E(r['role_heading'])}</h3>\n{paras(r['role'])}\n"
                f"<h3>{E(r['comp_heading'])}</h3>\n{paras(r['comp'])}")
        S.append(section("01", "The role", "How we describe this job", body))
        q = p["requirements"]
        body = ("<p>These are the requirements the search will run against. If any of them is "
                "wrong, this is the moment to change it.</p>\n"
                "<h4>Must have</h4>\n" + ul([E(x) for x in q["must"]]) +
                "\n<h4>Strongly preferred</h4>\n" + ul([E(x) for x in q["preferred"]]) +
                "\n<h4>Not required, and we will say so</h4>\n" + ul([E(x) for x in q["not_required"]]))
        S.append(section("02", "Requirements", "What we will hold candidates to", body, brk=True))
        S.append(section("03", "Method", "How every candidate will be scored", render_method(m, cands), brk=True))
        S.append(section("04", "Outreach", "How we reach them", render_outreach(m, cands), brk=True))
        S.append(sec05)

    head = f'''<header class="masthead">
  <img class="mark" alt="Hypersourced" src="data:image/png;base64,{logo_b64}">
  <p class="tagline">Only the Best.</p>
</header>

<table class="status" role="presentation"><tr>
  <td class="cell"><div class="stat"><p class="k">Client</p><p class="v">{E(m['client'])}</p></div></td>
  <td class="cell mid"><div class="stat"><p class="k">Search</p><p class="v">{E(m['role'])}</p></div></td>
  <td class="cell right"><div class="stat"><p class="k">Location</p><p class="v">{E(m['location'])}</p></div></td>
</tr></table>'''

    foot = f'''<footer>
  <p>Hypersourced &middot; 1968 S. Coast Hwy #589, Laguna Beach, CA 92651<br>
  Prepared for {E(m['client'])} &middot; {E(m['role'])} &middot; {E(m['packet_date'])}</p>
</footer>'''

    # READER MODE. Extractors (Safari Reader, Firefox Reader View, Readability)
    # score nodes and keep ONE winner, discarding its siblings. With bare sibling
    # <section> elements the algorithm kept section 02 and threw away the funnel,
    # the method, the channels and the fee — 95% of the document. One <article>
    # wrapper plus a real <h1> gives it a single obvious container to keep.
    body = (head + '\n<article class="doc">\n'
            + f'<h1 class="doc-title">{E(m["client"])} &middot; {E(m["role"])}</h1>\n'
            + "\n".join(S) + "\n</article>\n" + foot)
    # THE LINKEDIN MARK IS EMBEDDED ONCE, AS A CSS BACKGROUND.
    # Inlining <img src="data:..."> per candidate put an identical 25KB payload in
    # the file eleven times and pushed the packet from 296KB to 542KB. The PDF
    # deduplicates it, but the HTML is what gets emailed. One rule here, referenced
    # by every .cand-li and by the section 02 banner.
    if li_b64:
        mark_css = ("\n<style>\n"
                    f'.li-note .li-mark i{{background-image:'
                    f'url("data:image/png;base64,{li_b64}");'
                    "background-size:contain;background-repeat:no-repeat;"
                    "background-position:center;}\n"
                    "</style>\n")
        template = template.replace("</head>", mark_css + "</head>", 1)

    doc = template.replace("{{TITLE}}", f"Hypersourced &middot; {E(m['client'])} &middot; {E(m['role'])}")
    doc = doc.replace("{{META}}", meta_html)
    return doc.replace("{{BODY}}", body)


def render_pdf(html_path, pdf_path, mark_b64=""):
    """HTML -> PDF via headless Chromium. THE ONLY RENDERER. Do not add a second.

    WHY CHROMIUM AND NOTHING ELSE:
      The packet went out as wkhtmltopdf output for months. wkhtmltopdf lays the
      page out in a ~700px viewport and then scales the result down to fit the
      sheet, measured at 0.76-0.79x across every element tested. Body text set at
      9.6pt reached clients at 7.5pt. Chromium prints what the stylesheet says.

    THE RUNNING FOOTER LIVES HERE, NOT IN THE DOCUMENT.
      The logo and the page number both sit in Chromium's footer template, which
      renders inside the bottom page margin on every sheet. The first attempt used
      a position:fixed element in the document instead; it repeats correctly on its
      own, but the moment display_header_footer is switched on for the page number
      Chromium re-resolves fixed offsets and the mark landed at the TOP of every
      page from two onward. One mechanism for the whole footer, not two.

    preferCSSPageSize honours the @page rule, so paper size and margins stay
    declared in the stylesheet and are not split between the CSS and this function.
    """
    from playwright.sync_api import sync_playwright
    logo = (f'<img src="data:image/png;base64,{mark_b64}" style="height:11mm;">'
            if mark_b64 else "")
    footer = (
        '<div style="width:100%;position:relative;height:14mm;'
        '-webkit-print-color-adjust:exact;">'
        # centred mark
        '<div style="position:absolute;left:0;right:0;bottom:1mm;text-align:center;">'
        + logo + '</div>'
        # page number, bottom right, small rounded box
        '<div style="position:absolute;right:13mm;bottom:3mm;width:24px;height:17px;'
        'border:0.8px solid #C9D4D6;border-radius:5px;color:#5A6B70;'
        'font-family:Helvetica,Arial,sans-serif;font-size:8px;line-height:17px;'
        'text-align:center;"><span class="pageNumber"></span></div>'
        '</div>')
    uri = Path(html_path).resolve().as_uri()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(uri, wait_until="networkidle")
        page.emulate_media(media="print")
        page.pdf(path=str(pdf_path), print_background=True, prefer_css_page_size=True,
                 display_header_footer=True, header_template="<div></div>",
                 footer_template=footer)
        browser.close()
    return pdf_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True)
    ap.add_argument("--xlsx", default=None)
    ap.add_argument("--template", default=str(HERE / "template.html"))
    ap.add_argument("--logo", default=str(HERE / "logo_b64.txt"))
    ap.add_argument("--no-pdf", action="store_true",
                    help="emit the HTML only. The client deliverable is the PDF; "
                         "this is for inspecting markup.")
    ap.add_argument("--li-mark", default=str(HERE / "li_b64.txt"),
                    help="base64 LinkedIn mark for the section 02 banner. "
                         "Missing file just means no banner.")
    ap.add_argument("--base-url", default=None,
                    help="e.g. https://packets.hypersourced.com — required for link previews")
    ap.add_argument("--slug", default=None,
                    help="folder name. Omit and one is generated with a random suffix.")
    ap.add_argument("-o", "--outdir", default="dist",
                    help="a folder per campaign is written here, ready to upload")
    a = ap.parse_args()

    content = json.loads(Path(a.content).read_text())
    cands = None
    if a.xlsx and content.get("mode") == "report":
        cands = load_candidates(a.xlsx, content.get("hiring_company_aliases", []),
                                content.get("elite_band"), content.get("featured", 10))

    # ── SLUG ────────────────────────────────────────────────────────────
    # Two jobs, two mechanisms, and they must not be confused:
    #
    #   UNIQUENESS  comes from the timestamp. YYMMDDHHMMSS cannot collide,
    #               because you cannot start two runs in the same second.
    #               Nothing has to be checked against anything.
    #
    #   UNGUESSABILITY comes from the four trailing characters. Without them
    #               the URL is a bare timestamp, and a year of minutes is only
    #               525,600 values — a script walks that in about a minute and
    #               finds every campaign ever published. Clause 3 of the Master
    #               Scouting Agreement makes candidate identity confidential and
    #               proprietary, so an enumerable URL undercuts a term we ask
    #               clients to sign.
    #
    # A random-only ID would invert this: short, but you would have to check it
    # against everything already deployed to prove it had not repeated.
    #
    # Result: 260731214055-k7f2. Sortable, collision-proof, not enumerable.
    slug = a.slug
    if not slug:
        stamp = datetime.now().strftime("%y%m%d%H%M%S")
        suffix = "".join(secrets.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(4))
        slug = f"{stamp}-{suffix}"

    meta_html, stat = og_meta(content, cands, a.base_url, slug)
    # Echo the agreement URL on every build. It is the one link in the packet that
    # a client is asked to act on, it ships inside a PDF that cannot be repaired
    # after sending, and it is a single string in the content file that nobody
    # would otherwise look at. Printing it makes a stale value impossible to miss.
    _ag = content.get("engagement", {}).get("agreement_url")
    if _ag:
        print(f"  AGREEMENT LINK: {_ag}")
        print("  ^ confirm this resolves before a packet goes to a client.")
    else:
        print("  NOTE: no agreement_url set, so the closing paragraph has no link in it.")

    li_path = Path(a.li_mark)
    li_b64 = li_path.read_text().strip() if li_path.exists() else ""
    if not li_b64:
        print("  NOTE: no LinkedIn mark found, so section 02 renders without the banner.")

    doc = build(content, cands, Path(a.template).read_text(),
                Path(a.logo).read_text().strip(), meta_html, li_b64)

    outdir = Path(a.outdir) / slug
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "index.html").write_text(doc)

    # The preview card. Written even without --base-url so it can be eyeballed,
    # but the og:image tag only appears when there is an absolute URL to point at.
    try:
        from make_og_card import make_card
        make_card(str(outdir / "og.png"), content["client"], content["role"], stat,
                  logo_path=str(HERE / "logo_light.png"))
    except Exception as e:
        # The preview card only matters for a hosted link. The packet ships as a
        # PDF, so on a normal build there is nothing to warn about.
        if a.base_url:
            print(f"  WARNING: preview card not generated ({e}). The link will show "
                  f"a title and description but no image.")

    kb = round(len(doc.encode()) / 1024, 1)
    print(f"wrote {outdir}/index.html  ({kb} KB)")

    # THE PDF IS THE DELIVERABLE. The HTML is an intermediate the client never sees.
    if not a.no_pdf:
        pdf_name = (f"Hypersourced_Packet_{re.sub(r'[^A-Za-z0-9]+', '', content['client'])}"
                    f"_{datetime.now():%Y-%m-%d_%H%M}.pdf")
        pdf_path = outdir / pdf_name
        try:
            render_pdf(outdir / "index.html", pdf_path,
                       (HERE / "mark_b64.txt").read_text().strip()
                       if (HERE / "mark_b64.txt").exists() else "")
            # Linearise ("fast web view"). Chromium does not, which means a reader
            # cannot render page one until it has walked the whole cross-reference
            # table. It is a one-second post-step and it is what lets Acrobat and
            # mobile viewers page through incrementally instead of stalling.
            try:
                import subprocess
                lin = pdf_path.with_suffix(".lin.pdf")
                subprocess.run(["qpdf", "--linearize", str(pdf_path), str(lin)],
                               check=True, capture_output=True)
                lin.replace(pdf_path)
            except Exception as le:
                print(f"  note: could not linearise ({le}). The PDF is still valid.")
            import fitz as _f
            with _f.open(pdf_path) as _d:
                pages = len(_d)
            size_kb = pdf_path.stat().st_size // 1024
            print(f"wrote {pdf_path}  ({pages} pages, {size_kb} KB)")
        except Exception as e:
            print(f"  PDF NOT WRITTEN: {e}")
            print("  The HTML is fine and the PDF is the client deliverable, so this "
                  "run produced nothing sendable. Do not send the HTML instead.")
    if (outdir / "og.png").exists():
        print(f"wrote {outdir}/og.png  ({(outdir / 'og.png').stat().st_size // 1024} KB)")
    if a.base_url:
        print(f"\n  LINK:  {a.base_url.rstrip('/')}/{slug}/")
    else:
        pass
    if cands:
        top = cands["featured"][0] if cands["featured"] else None
        if sheet_samples(top):
            print("  OUTREACH: taken from the sheet, as written by the engine.")
        else:
            print("  OUTREACH: none in the sheet, so the samples in the content file "
                  "were used.\n            Those must have been written for "
                  f"{(top or {}).get('first','the top candidate')} "
                  f"{(top or {}).get('last','')} from their own record.")
        print(f"\n  analysed {cands['total']:,} | ruled out {cands['eliminated']:,} "
              f"| scored {cands['scored']:,} | elite {cands['elite_n']} "
              f"| featured {cands['featured_n']}")
        for d in cands["dropped"]:
            print(f"  DROPPED (works at client): {d['first']} {d['last']} — scored {d['score']}")


if __name__ == "__main__":
    main()
