# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Thor Ernstsson (primary).** CEO and co-founder of ArcticBlue. Runs his own speaking outreach since the coordinator role (Angela) ended. Uses the tracker to decide which events to chase, apply to calls for speakers, and reach organisers. Also uses it on the go (phone) around events.
- **Speakers: Verma, Jerome, Scott.** Each has their own targeting profile (cities, industries, buyer titles) and marks events they are interested in, speaking at, or attending.
- **Operator: Hurley.** Runs and maintains the tracker. Does not speak or attend, and is never treated as an interested attendee.
- Former users, for context only: Joe (left 2026-10-16), Carlos (off the pipeline 2026-09-15), Angela (former coordinator, left 2026-09-10). Their events were archived; none of them is an active user.

## Product Purpose

Find in-person AI events worth speaking at, ideally unpaid speaking slots that build Thor's credibility as a keynote-level speaker, and get from "this looks right" to an application and a real conversation with the right organiser. The tracker also records, per person, whether they are speaking, attending, or only interested.

Success is outreach that actually happens: the right events picked, applications submitted, the organiser contact found and contacted, and talks booked. The current, stated problem (Thor): the tracker does not do enough to help source the right events or drive outreach. That outranks visual polish.

## Positioning

An internal tool shaped around ArcticBlue's own targeting, not a generic event list:
- per-person targeting profiles (config/personas.json): cities, industries, buyer titles, include and exclude rules (for Thor: healthcare buyers and executives, not clinicians; no HR or L&D events);
- Thor's talk library (config/talks/thor.json) feeding drafted Sessionize applications;
- the team's own pipeline stages, follow-up log, and day-of briefs on every event.

## Operating Context

- One static page built by `src/build.py` (Python template producing `public/index.html`), hosted on Vercel, data in Supabase. A GitHub Action rebuilds daily at 09:00 UTC; pushing `main` deploys.
- No sign-in: anyone with the URL can edit; "Viewing as" (the avatar menu) is attribution, not authentication.
- Main surfaces: the Events list (default home: All, plus a My Interests chip, segmented Pending / Booked / Attending, a filter drawer, search), Calendar and Map views, the event pop-up (detail, stages, edit form, Sessionize block, reach-out line, follow-up log), My Lineup / My Events with the day-of brief, and My Profile (materials, talk library).
- Pipeline stages: Submitted, Initial outreach, Followed up, Meeting held, Booked, Rejected, Attending.
- The application flow lives in the event pop-up (Thor's request, 2026-10-16): draft the application, approve it, submit on the organiser's site (Sessionize when the event uses it), record it, then mark the organiser reached out. The separate Application queue tab is hidden (`SHOW_QUEUE = False`); skipping an event means archiving it.
- Automation: daily ingest of new events, enrichment, a daily Sessionize check (acceptances, call status, closing dates), overnight day-of briefs.

## Capabilities and Constraints

- Events come from a static catalog (~270) plus manual events (~350). Both are edited through the same pop-up.
- Hidden features kept in code behind switches in build.py: Action Center, Find new events (AI), Application queue.
- Sessionize has no speaker API: submitting always happens on sessionize.com, by a person.
- Geography: ArcticBlue is shifting away from Africa (2026-10-16); Africa events are archived and must not be suggested.
- Facts are never invented: no made-up URLs, contacts, dates, metrics, or speaker claims (AGENT-CONTEXT.md). An unknown stays visibly unknown.
- For this review (impeccable-review branch): UI and copy only. No changes to the Supabase schema, data, API routes, or business logic.

## Brand Commitments

- Typography: keep Nunito Sans and the existing type stack.
- Color: keep the ArcticBlue blue; darker shades of it are fine for text.
- Components: keep the pill / chip / button system unless a finding shows it is broken. Its existing convention: a rectangular (3px radius) shape is a static label, an underlined pill is clickable, solid primary buttons stay as they are.
- A plain icon (no frame, default cursor) is preferred over a badge for a pure "we have X" indicator (contact on file).
- Benchmarks the team likes: Linear, Notion, Superhuman.
- Copy: plain language for non-technical users; no em dashes in any UI copy written from now on.

## Evidence on Hand

- `config/personas.json`: targeting profiles per speaker.
- `config/talks/thor.json`: Thor's five starter talks (all draft until he approves them in My Profile).
- `public/events.json` and the Supabase tables: the live catalog, stages, contacts, follow-up log.
- Thor's bio and materials in the `profiles` storage bucket.
- No user research, analytics, or usage metrics exist beyond the stakeholder feedback recorded in the repo. Do not fabricate any.

## Product Principles

1. **Outreach over browsing.** Every event surface should make the next step toward an organiser obvious: apply, find the contact, reach out, follow up.
2. **The right few events beat many.** Fit to the targeting profile (city, buyers, unpaid speaking slot) matters more than volume.
3. **One flow, inside the event.** Thor works an event from its pop-up start to finish; no parallel lists to keep in sync.
4. **Never invent.** Unknown contacts, dates, and links are shown as unknown, never guessed.
5. **Plain and quiet.** Labels say what to do next in plain words; status is shown, not decorated.

## Accessibility & Inclusion

- Text contrast meets WCAG 2.1 AA (4.5:1 for body text, 3:1 for large text).
- No text below 11px.
- Works on a phone (390px wide) as well as desktop.
