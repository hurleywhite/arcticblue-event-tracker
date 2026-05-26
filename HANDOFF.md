# Handoff — ArcticBlue Event Tracker

For the next AI agent or engineer picking this up.

---

## What's done

- ✅ Parses 82 events from `data/ArcticBlue AI 2026 Event Tracker.docx` (Q2/Q3 2026 window)
- ✅ Auto-buckets events into TODAY / UPCOMING / ARCHIVED based on the build date
- ✅ Auto-archives events whose end-date is in the past
- ✅ White-primary internal aesthetic (HRF parity: clean, monochrome, sharp typography)
- ✅ ArcticBlue logo and brand fonts (Hanken Grotesk + Fragment Mono)
- ✅ KPI strip, today/up-next callout, filters (search / priority / region / type)
- ✅ Real ArcticBlue logo from `framerusercontent.com` saved to `public/arcticblue-logo.png`
- ✅ Verified URL linking — 18 of 82 events have a hyperlink confirmed from the source doc
- ✅ No-hallucination rule enforced in code — cards without verified URLs are deliberately non-clickable
- ✅ Mobile responsive (KPI grid stacks, filters stack, cards stack, archive collapses)
- ✅ Live on Vercel at `https://arcticblue-event-tracker-deploy.vercel.app/`

---

## What's NOT done — ranked by impact

### High value

1. **Backfill the 67 events without verified URLs.** Open the source `.docx`, visit each event in a browser, paste the verified URL into `data/event-urls-manual.json`. Don't guess — only add URLs that load a real page about the event. Each manual entry should be a deliberate human verification.

2. **Calendar view toggle.** Today the page is grid-only. A monthly calendar layout (event chips on day cells) would make "what's coming up in June?" visually trivial. The existing `data-priority`, `data-region`, `data-type`, and start-date attributes already exist on each card — reuse them.

3. **Auto-rebuild on a daily cron.** Right now `build.py` is manual. A GitHub Action that runs `python3 src/extract-urls.py && python3 src/build.py && vercel deploy` daily would keep TODAY / UPCOMING / ARCHIVED always current without anyone clicking anything.

### Medium value

4. **Source the .docx from Google Docs directly.** Currently `data/ArcticBlue AI 2026 Event Tracker.docx` is a local snapshot. The original lives at `https://docs.google.com/document/d/1Gi358-ohqpcCf_H5ykcaGpLXq3CQVcM0sVSKNkRxxT8/edit`. The Google Docs API would let `extract-urls.py` and `build.py` pull live state on every build — eliminating "snapshot is stale" risk.

5. **Email-scraping ingestion.** The original ask said this tracker would receive emails about new events. A small ingestion pipeline (parse forwarded emails → extract event name + date + URL → append to the doc OR to a sidecar JSON) would close the "Hurley forwards an event invite" loop end-to-end. Out of scope for the static page; would need a Cloudflare Worker or similar.

6. **Map view.** Each event has a city/country. A choropleth or pin-map of upcoming events (lit up red for the next 30 days, gray after) would be visually compelling for the team. Use a vector world SVG (Natural Earth) — do NOT load Mapbox or similar from a third-party CDN.

7. **Tier-level prioritization metadata.** Currently each event has High / Medium / Low priority. The doc has richer info per event (pay-to-play y/n, speaking deadline, contact email). Expose those on a card-flip or details disclosure.

### Polish

8. **More descriptive "no URL on file" affordance.** Right now non-linked cards show a faint `·` after the title with a `title` attribute. Better UX would be a small "no link" pill in the footer area, or a "request URL" button that emails ops@arcticblue.

9. **Print stylesheet.** Thor occasionally prints these for offsite reading. A `@media print` block that flattens to a single column, removes filters, and shows the URL inline next to each linked event would be useful.

10. **A11y audit.** Screen-reader testing on the today/up-next callout. The current ARIA labels are sparse.

---

## What NOT to break

These are correct as designed — don't "fix" them:

- **Cards without URLs are non-clickable.** This is intentional. The no-hallucination rule says we'd rather show an unlinked card than guess a URL. If you want every card linked, fill `event-urls-manual.json` from the source doc — don't make the build invent URLs.
- **White background, not dark.** Internal ArcticBlue tools are white-primary. The marketing site (arcticblue.ai) is dark — different aesthetic register.
- **Inline CSS and JS in `public/index.html`.** No build pipeline. No bundlers. The page must work when opened with `file:///`.
- **One single HTML file as the deploy target.** Adding `public/about.html` or splitting into a SPA is out of scope until ArcticBlue explicitly asks for multi-page.
- **No tracking / no analytics scripts.** The page is intentionally analytics-free.

---

## Known gotchas

- **The .docx hyperlink XPath is fragile.** `extract-urls.py` reads `<w:hyperlink r:id=...>` elements directly. If the doc gets opened and re-saved in a different Word version, the relationship-XML structure may shift. If extraction starts returning zero URLs, that's the first place to look.

- **Today-date is baked in at build time.** The page doesn't know today's real date — it knows the date `build.py` was run. If you want true "current day" behavior, either: (a) run a daily cron + redeploy, or (b) move TODAY / UPCOMING / ARCHIVED classification to client-side JS using `new Date()`.

- **The TODAY constant in `build.py` is hardcoded to 2026-05-21.** Update it to `date.today()` before adding the daily cron, otherwise every rebuild will think it's May 21.

- **Vercel project switching.** This deploys to a project called `arcticblue-event-tracker-deploy`. The HRF/QA repo also has projects called `hrf-qa-preview` and `hrf-preview-deploy` — don't confuse them. The `.vercel/project.json` inside `public/` will reflect which project is currently linked.

---

## Files you can safely edit without breaking the build

- `data/event-urls-manual.json` — add manual URL overrides
- `data/ArcticBlue AI 2026 Event Tracker.docx` — update the source doc (then re-run both scripts)
- `src/build.py` — content / layout / styling changes (keep the no-hallucination contract intact)
- `src/extract-urls.py` — URL-extraction logic (keep the no-hallucination contract intact)
- `public/arcticblue-logo.png` — swap in a different logo asset

## Files you should leave alone

- `public/index.html` — this is the BUILD OUTPUT. Edit the generators, not the output, or you'll lose your changes on next build.
