# Hypersourced Packet Toolkit

The renderer that turns a scored candidate sheet into the client packet PDF.

**You do not run anything in here.** This repository exists so that Hypersourced
AI can download it inside a chat and build the packet for you. Nothing on this
page is a task.

---

## What each file is

**build_packet.py** — the renderer. Reads the scored spreadsheet and a content
file, and writes the packet PDF.

**template.html** — the design. Every rule about how the packet looks lives
here and no model ever edits it. This is the only reason "the same design every
time" can be true: nothing is regenerating the design.

**logo_b64.txt** — the Hypersourced logo, embedded so the PDF carries it.

**li_b64.txt** — the LinkedIn mark used beside each candidate.

**examples/content_nabla.json** — a complete, real content file from the Nabla
Bio search. This doubles as the schema. Anything writing a new content file
should copy this structure key for key.

---

## How a build happens

Hypersourced AI runs this, not you:

    curl -sL https://codeload.github.com/OWNER/REPO/tar.gz/refs/tags/v1.1 | tar xz
    cd hypersourced-packet-1.1
    python3 build_packet.py --content content.json --xlsx scored.xlsx

The PDF lands in `dist/`. That is the file the client receives.

Pin to a tag rather than to `main` so a packet built today and a packet built in
six months come out identical. Move the tag when a change is meant to go live.

---

## Rules that are not style preferences

**PDF only.** The HTML is an intermediate the client never sees. If the PDF step
fails, the run says so — do not send the HTML instead.

**Chromium is the only renderer.** The packet previously rendered through
wkhtmltopdf, which lays out in a small viewport and scales the result down to
fit the sheet. Measured at 0.76–0.79x across every element: body text set at
9.6pt reached clients at 7.5pt. Chromium prints what the stylesheet says. Do not
add a second renderer.

**Numbers come from the spreadsheet, never from a model.** Anything typed by
hand drifts. The role-tier counts in the Nabla content file summed to 677
against a scored pool of 680, because one table was updated after three
candidates were removed and the other was not.

**The commercial terms must match the signed Master Sourcing Agreement.** Flat
fee, no tiers, no retainer, no exclusivity, invoiced on the candidate's 30th
day, no invoice at all if they do not reach it. If the agreement changes, it
changes there first and here second.

---

## Versioning

Tag this repository to match the Hypersourced AI instruction version it pairs
with. The template and the instructions share assumptions about section order
and content keys, and they disagree if either moves alone.
