---
name: ArcticBlue Event Tracker
description: The team's working ledger of in-person AI events, from fit to application to booked talk.
colors:
  arcticblue-action: "#2773c2"
  arcticblue-glacier: "#1fa0dc"
  arcticblue-glacier-deep: "#1271a8"
  ink: "#0a0a0a"
  ink-soft: "#404040"
  ink-muted: "#737373"
  ink-faint: "#a3a3a3"
  paper: "#ffffff"
  paper-2: "#fafafa"
  paper-3: "#f4f4f5"
  rule: "#e7e7e8"
  rule-strong: "#d4d4d6"
  add-green: "#047857"
  success-green: "#15803d"
  caution-amber: "#ca8a04"
  fail-red: "#b91c1c"
typography:
  app-title:
    fontFamily: "Helvetica Neue, Helvetica, Arial, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Hanken Grotesk, Inter, system-ui, sans-serif"
    fontSize: "1.3rem"
    fontWeight: 800
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Hanken Grotesk, Inter, system-ui, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: "Hanken Grotesk, Inter, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
  control:
    fontFamily: "Nunito Sans, Hanken Grotesk, system-ui, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 600
  label-mono:
    fontFamily: "Fragment Mono, JetBrains Mono, ui-monospace, monospace"
    fontSize: "0.7rem"
    fontWeight: 700
    letterSpacing: "0.08em"
rounded:
  label: "3px"
  input: "6px"
  segment: "7px"
  dialog: "8px"
  card: "10px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "22px"
  xl: "32px"
components:
  button-apply:
    backgroundColor: "{colors.arcticblue-action}"
    textColor: "{colors.paper}"
    typography: "{typography.label-mono}"
    rounded: "{rounded.pill}"
    padding: "7px 16px"
  button-add:
    backgroundColor: "{colors.add-green}"
    textColor: "{colors.paper}"
    rounded: "{rounded.input}"
  chip-segment-on:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.segment}"
    padding: "7px 13px"
  chip-action:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.label-mono}"
    rounded: "{rounded.pill}"
    padding: "3px 8px"
  label-static:
    textColor: "{colors.ink-soft}"
    typography: "{typography.label-mono}"
    rounded: "{rounded.label}"
  card-event:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "22px"
  input-search:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.input}"
    padding: "9px 13px"
  dialog-event:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.dialog}"
    width: "640px"
---

# Design System: ArcticBlue Event Tracker

## Overview

**Creative North Star: "The Field Ledger"**

A working ledger for a small team in the field. Pages are white and quiet; ink-black type carries the content; small uppercase mono labels carry dates, counts and field names the way a ledger's column heads do. Color is rationed: ArcticBlue blue means "act here", and the pipeline stage colors mean "where this stands". Nothing is decorative for its own sake.

The density is that of an operational tool (Linear, Notion and Superhuman are the team's reference points): one column of cards on a phone, two on a laptop, each card stating name, date, place and, when relevant, the one action that moves the event forward. Detail lives one click away in the event pop-up, which is where the whole application flow happens.

**Key Characteristics:**
- White paper, ink type, hairline rules (1px #e7e7e8) instead of shadows at rest.
- Three type voices: Hanken Grotesk for reading, Nunito Sans for controls, Fragment Mono uppercase for labels and metadata; Helvetica Bold only for the app title (matches the logo).
- One action blue; stage colors only for pipeline status.
- Shape encodes behavior: squared labels are static, underlined pills are clickable.

## Colors

A near-monochrome ink-and-paper palette with one working blue and a set of status colors that only ever mean pipeline stage.

### Primary
- **ArcticBlue Action** (#2773c2): the working blue. Primary actions (Apply to speak), links, focus. Passes 4.5:1 on white, so it is the blue for any text.
- **Glacier** (#1fa0dc): the logo's lighter cyan. Brand accent only: the app title at display size, large marks, decorative strokes. Fails 4.5:1 on white (2.9:1), so it never carries body text, small labels, or hover text.
- **Glacier Deep** (#1271a8): the darker shade already used for hover text on secondary buttons; a safe text color in the Glacier family.

### Secondary
- **Add Green** (#047857): the "+ Add" button only (creating a new event).

### Neutral
- **Ink** (#0a0a0a): headings, event names, body text, the selected segment chip.
- **Ink Soft** (#404040): secondary text, card meta lines, field labels.
- **Ink Muted** (#737373): tertiary text, counts, unselected chip text, quiet icons.
- **Ink Faint** (#a3a3a3): placeholders and disabled marks only, never readable content.
- **Paper** (#ffffff), **Paper 2** (#fafafa), **Paper 3** (#f4f4f5): page, raised panels, wells.
- **Rule** (#e7e7e8) and **Rule Strong** (#d4d4d6): card borders, dividers, input strokes.

### Status (pipeline stages, defined in build.py STAGE_TAGS)
Submitted sky, Initial outreach indigo, Followed up amber, Meeting held violet, Booked green, Rejected red, Attending teal. Each stage has a dot, a tint background and a dark foreground.

### Named Rules
**The One Blue Rule.** Text and interactive states use ArcticBlue Action (#2773c2) or Glacier Deep (#1271a8). Glacier (#1fa0dc) is for large brand marks only.
**The Status-Only Color Rule.** Stage colors mean pipeline status and nothing else. Purple outside the "Meeting held" stage (AI features, people, regions) competes with it and should not be added.

## Typography

**Display Font:** Helvetica Neue Bold (app title only, matching the logo)
**Body Font:** Hanken Grotesk (with Inter, system-ui)
**Control Font:** Nunito Sans 600 to 900 (search, segment chips, section headings in some panels)
**Label/Mono Font:** Fragment Mono (with JetBrains Mono, ui-monospace)

**Character:** A neutral grotesk for reading, a rounder Nunito for things you press, and a ledger-like mono for dates and field names.

### Hierarchy
- **App title** (700, 1.5rem, Glacier): the centered nav title only.
- **Headline** (800, 1.3rem): the event name in the pop-up.
- **Title** (700, 1.05rem): the event name on a card.
- **Body** (400, 1rem, line-height 1.55): descriptions, notes, pop-up fields.
- **Meta** (400, 0.85rem, Ink Soft): the card's date and place line.
- **Label** (Fragment Mono 700, 0.64 to 0.7rem, uppercase, 0.08em tracking): field names, dates, counts, chips.

### Named Rules
**The 11px Floor Rule.** No rendered text below 11px. Mono labels sit at 0.7rem (11.2px) or above; several (dates, avatars, counts, carets) currently render at 9 to 10.5px and are known violations.

## Layout

A centered column, max width 1240px. The Events list groups cards by month under collapsible month headers; cards sit in a two-column grid on desktop and a single column under ~760px. The event pop-up is a 640px centered dialog over a dimmed, lightly blurred page, scrolling internally. Spacing steps are 4, 8, 16, 22 and 32px; cards use 22px internal padding.

## Elevation & Depth

Flat at rest. Depth comes from hairline rules and paper tints, not shadows. Shadows appear on overlays only: the pop-up (0 24px 60px rgba(10,10,10,0.28)) and the selected segment chip (0 1px 3px rgba(0,0,0,0.12)).

### Named Rules
**The Flat Page Rule.** Cards and panels carry a 1px rule, not a shadow. Colored glows (for example the hidden Action Center dialog's #142844 glow) are off-system.

## Shapes

Shape encodes behavior. Static labels are squared (3px). Clickable controls are pills (999px) with an underline. Cards are softly rounded (10px), the pop-up slightly less (8px), inputs 6px, segment chips 7px.

## Components

### Buttons
- **Apply to speak (primary):** full-width pill on the card foot, ArcticBlue Action fill, white Fragment Mono uppercase label, underlined (7px 16px).
- **Add (create):** green (#047857) solid button, top right.
- **Pop-up actions (Enrich, Edit):** soft tinted buttons in the pop-up header (9px radius). Enrich currently uses a purple tint, which conflicts with the Status-Only Color Rule.
- **Secondary (q-btn):** white with a Rule Strong border; hover shifts border to blue and text to Glacier Deep.

### Chips
- **Segment chips (All / Pending / Booked / Attending, My Interests):** Nunito Sans 600; selected is solid Ink with white text and a soft shadow; unselected is quiet text.
- **Action chips (Urgent, Archive on cards):** white underlined pills, Fragment Mono uppercase.
- **Static labels (stage, priority, Archived):** squared 3px tags; stage tags use the stage tint and foreground.

### Cards / Containers
- **Event card:** white, 1px Rule border, 10px radius, 22px padding. Name (link to the event's site, with an arrow), meta line (mono date + place), a top-right cluster (star, stage icons naming people, contact icon, chat count), and an optional Apply button foot.

### Inputs / Fields
- **Search:** white, 1px Rule Strong, 6px radius, Nunito Sans 600 0.9rem.
- **Edit form fields (pop-up):** grouped into labelled zones; plain bordered inputs.

### Navigation
- **Top bar:** logo left, centered Helvetica title, date and the "Viewing as" avatar right. Below: underlined text tabs (only "Events" visible today; Action Center and Queue are hidden by switches), a count, and the green Add button.

### Event pop-up (signature component)
The working surface. Header with name and actions; stage toggles; overview, who attends, speaking and submission (contacts, follow-up log); the Sessionize block (draft, approve, apply, record) and the reach-out line under the apply step.

## Do's and Don'ts

### Do:
- **Do** use ArcticBlue Action (#2773c2) for any blue text or action, and Glacier (#1fa0dc) only for the large app title and brand marks.
- **Do** keep labels squared and clickable controls as underlined pills.
- **Do** show "contact on file" style facts as a bare icon with a tooltip, not a badge.
- **Do** keep text at 11px or larger and body copy at 4.5:1 contrast or better.

### Don't:
- **Don't** add new purple accents; purple belongs to the "Meeting held" stage.
- **Don't** put shadows or colored glows on cards or panels at rest.
- **Don't** use em dashes in UI copy.
- **Don't** replace Nunito Sans, Hanken Grotesk or Fragment Mono, or the Helvetica app title.
