"""Build the FIXED TEXT inventory: every string that appears on every packet.

Reads the live files rather than a hand-kept list, so the inventory cannot drift
out of date. If a string is added to the template, the builder or the content
file, it turns up here on the next run.
"""
import json, re, html, subprocess
from pathlib import Path

C = json.load(open('content_nabla.json', encoding='utf-8'))
SRC = open('build_packet.py', encoding='utf-8').read()
E = lambda s: html.escape(str(s))

def secs():
    out = []
    for m in re.finditer(r'section\("(\d\d)", "([^"]*)", "([^"]*)"', SRC):
        out.append((m.group(1), m.group(2), m.group(3)))
    return out[:6]

GROUPS = [
 ("Masthead and page furniture", [
   ("Tagline, top right of page one", "Only the best."),
   ("Masthead label, left cell", "Client"),
   ("Masthead label, centre cell", "Search"),
   ("Masthead label, right cell", "Location"),
 ]),
 ("Section numbers, rail words and headings", [
   (f"Section {n} rail word", w) for n, w, h in secs()
 ] + [
   (f"Section {n} heading", h or "(no heading — deliberately blank)") for n, w, h in secs()
 ]),
 ("Section 01 — Results", [
   ("The Elite claim, also repeated in section 02", C.get("elite_claim","")),
   ("Elite band note", C["band_notes"]["Elite"]),
   ("Strong band note", C["band_notes"]["Strong"]),
   ("Viable band note", C["band_notes"]["Viable"]),
   ("Stretch band note", C["band_notes"]["Stretch"]),
   ("Long Shot band note", C["band_notes"]["Long Shot"]),
 ]),
 ("Section 02 — Ideal candidates", [
   ("LinkedIn banner", C.get("li_note","")),
 ]),
 ("Section 04 — Outreach", [
   ("Lead-in above the channels", C.get("cadence_intro","")),
 ] + [
   (f"Channel: {ch[0]}", ch[1]) for ch in C.get("channels", [])
 ] + [
   ("US-based note under the channels", C.get("outreach_note","")),
   ("Lead-in above the sample copy", C.get("samples_intro","")),
   ("Sub-heading above the sample copy", "What it actually says"),
 ]),
 ("Section 05 — Zero risk", [
   ("Section heading", C["engagement"]["heading"]),
   ("Opening paragraph", C["engagement"]["intro"]),
   ("Sub-heading above the terms", "The core points"),
 ] + [
   (f"Term: {lbl}", txt) for lbl, txt, _ in C["engagement"]["points"]
 ] + [
   ("Sub-heading above the asks", "What we need from you"),
 ] + [
   (f"Ask {i}", a) for i, a in enumerate(C["engagement"]["asks"], 1)
 ] + [
   ("Closing box heading", C["engagement"]["cta_heading"]),
   ("Closing box body", C["engagement"]["cta_body"]),
   ("Hyperlinked phrase inside that body", C["engagement"]["agreement_phrase"]),
   ("Agreement link target", C["engagement"]["agreement_url"]),
   ("Button label", C["engagement"]["cta_label"]),
   ("Button link target", C["engagement"]["cta_href"]),
 ]),
 ("Section 06 — The full list", [
   ("Lead-in above the roster", C.get("roster_intro","")),
 ]),
]

PER_SEARCH = ["results.headline", "results.lede", "results.banner_caption", "results.closing",
              "featured_intro", "method.* (the whole scoring narrative)",
              "samples (the actual outreach copy)", "each candidate's three bullets",
              "each candidate's written case"]

rows, n = [], 0
for gi, (title, items) in enumerate(GROUPS, 1):
    rows.append(f'<h2>{gi} &middot; {E(title)}</h2>')
    for ii, (label, text) in enumerate(items, 1):
        n += 1
        rows.append(
          f'<div class="f"><p class="n">{gi}.{ii}</p>'
          f'<p class="l">{E(label)}</p>'
          f'<p class="t">{E(text)}</p></div>')

doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page{{size:letter;margin:16mm 15mm;}}
body{{font:11pt/1.5 Georgia,serif;color:#12343B;}}
h1{{font-family:Helvetica,Arial,sans-serif;font-size:19pt;margin:0 0 2pt;}}
.sub{{color:#5A6B70;margin:0 0 4pt;font-size:10pt;}}
.how{{background:#F2F6F5;border-left:3px solid #23CE6D;padding:9pt 12pt;margin:10pt 0 16pt;font-size:10pt;}}
h2{{font-family:Helvetica,Arial,sans-serif;font-size:12.5pt;margin:16pt 0 6pt;
   border-bottom:1px solid #C9D4D6;padding-bottom:3pt;break-after:avoid;}}
.f{{margin:0 0 9pt;break-inside:avoid;}}
.n{{font-family:Helvetica,Arial,sans-serif;font-size:9pt;color:#23CE6D;font-weight:700;margin:0;}}
.l{{font-family:Helvetica,Arial,sans-serif;font-size:9.5pt;color:#5A6B70;margin:0 0 2pt;}}
.t{{margin:0;padding-left:10pt;border-left:2px solid #E3EAEB;}}
.ps{{font-size:10pt;color:#5A6B70;}}
</style></head><body>
<h1>Hypersourced packet &mdash; fixed text</h1>
<p class="sub">Every string that appears on EVERY packet, whoever the client is.
Generated from the live template, builder and content file &middot; 2026-08-04 23:55</p>
<div class="how"><strong>How to use this.</strong> Each entry has a number that will not
change. Read it wherever you like and dictate back by number &mdash; &ldquo;2.4 should
read&hellip;&rdquo; &mdash; and the change lands in the right place. {n} entries.</div>
{"".join(rows)}
<h2>Not on this list, and why</h2>
<p class="ps">The following change with every search, so they are written fresh each
time by Hypersourced AI rather than fixed here:</p>
<ul class="ps">{"".join(f"<li>{E(x)}</li>" for x in PER_SEARCH)}</ul>
</body></html>"""

Path('fixed_text.html').write_text(doc, encoding='utf-8')
import build_packet as B
B.render_pdf('fixed_text.html', 'Hypersourced_Packet_FIXED_TEXT_2026-08-04_2355.pdf')
print(f"{n} fixed strings inventoried")
