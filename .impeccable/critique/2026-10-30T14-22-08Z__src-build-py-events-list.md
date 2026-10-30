---
target: the default Events list (was My Fits)
total_score: 20
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 4
target_identity: "file:/Users/hurleywhite/Developer/arcticblue-event-tracker/src/build.py#events-list"
timestamp: 2026-10-30T14-22-08Z
slug: src-build-py-events-list
---
Method: dual-agent (A: design review sub-agent, B: detector + browser evidence sub-agent). Overlay skipped: user guardrail (no live server).

## Synthesis
Both passes agree: the ledger skin is authored but the list does not steer Thor to his next winnable event or to an organiser. Design review: 20/40, Apply shown on closed/paid/excluded events, soonest-first order buries winnable events, profile ignored, contacts not actionable, Thor locked out of triage filters. Evidence: 390px sideways scroll (seg-chip row 523px), app title 2.95:1, sub-11px chat count/+1/date, stage-mark initials 7.8px, star/archive unreachable on touch; Sync, .today-card stripe and #142844 glow do not render for Thor (dead/hidden).

# A1 · Events list, default view (Thor) · Assessment A

Evidence: live page at localhost:8766 as Thor, at 1280px and 390px wide. Writes were stubbed and 0 were recorded. Source is src/build.py. The detector was not consulted.

## 1. Design specificity
**The look is authored. The structure is generic.** The ledger skin (mono dates, hairline cards, one blue, stage marks carrying initials) belongs to this team. A chronological grid of every event, each with an Apply button, is what any conference directory shows. Thor's profile, unpaid slots, how long before the event you must apply, and the organiser contact are all missing from the screen he opens.

## 2. Nielsen heuristics
| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Visibility of status | 2 | "46 tracked · 162 manual" (208) vs "193 events" |
| 2 | Match real world | 2 | "tracked/manual" and "Pending" are system words; icon marks need hover |
| 3 | User control | 3 | Esc and focus return work; hover Archive hides an event for the whole team in one click |
| 4 | Consistency | 2 | Title goes off-site, card body opens the pop-up; two different stars |
| 5 | Error prevention | 1 | Apply shown on closed, pay-to-play and excluded events; likely duplicates shown twice |
| 6 | Recognition vs recall | 1 | Exclusions, deadlines and contact names must be remembered |
| 7 | Flexibility | 1 | No sort, shortcuts or bulk actions; Priority filter hidden from Thor |
| 8 | Minimalist design | 3 | Quiet, but all 193 cards weigh the same and Apply is the loudest thing |
| 9 | Error recovery | 3 | Clear empty state with "Clear search & filters" |
| 10 | Help | 2 | Tooltips on desktop only; no legend |
| | **Total** | **20/40** | **Acceptable, bottom edge** |

## 3. Cognitive load
**5 of 8 checks fail (high load):** single focus, chunking (116 cards under "November 2026"), visual hierarchy, minimal choices, working memory. Progressive disclosure passes but has gone too far: contacts and deadlines are hidden too deep.

**Decision points with more than 4 options:**
- The control row has 11 controls.
- Each card has 5 targets on hover.

## 4. Emotional journey
Opening the page feels calm. Then the letdowns start:
- Card one is "CDO Vision Toronto", which is tomorrow, with a full-width "Apply to speak".
- Card two is an HR forum his profile excludes.
- Next comes a contact icon he cannot act on.

Nothing is designed as a high point. The page ends in a 31,845px scroll on a phone, with the 2027 events he could still win at the bottom. Clicking Apply off-site records nothing, so the most important moment gets no reassurance.

## 5. Strengths
- **Ledger look:** month headers with counts match how a calendar works and read as a serious tool.
- **Broad search:** it matches contacts, cities and topics ("McCuaig" 1, "healthcare" 7, "London" 31).
- **Team status at a glance:** initials on stage marks (T, V, JW), cards you can focus with the keyboard, a visible focus ring.

## 6. Priority issues

**1. [P1] "Apply to speak" points the wrong way. CORE-JOB**
- **What:** It appears whenever a URL exists. That includes closed calls (AI DevCon Fall closed Oct 1, IRM UK closed Apr 17), 12 pay-to-play events and 7 HR events. It also goes straight off-site, skipping the pop-up flow, so nothing gets recorded.
- **Fix:** Show it only for open or unknown calls that fit his profile. Otherwise show a squared label: "Call closed" or "Apply by Nov 14". Rename it "Start application" and open the pop-up's apply step.
- **Where:** `src/build.py:8303-8307`, `8569`. **Effort:** M.

**2. [P1] Soonest-first order buries the events Thor can win. CORE-JOB**
- **What:** 117 of 193 events (61%) start within about 5 weeks, and 58 of them show Apply. The 30 events from Feb to Jun 2027 start about 153 cards down.
- **Fix:** Sort events that are still open to apply first, by deadline. Fold "Too late to speak, still worth attending". Add a "Chase next" strip of 3 to 5 cards.
- **Where:** `src/build.py:9485`. **Effort:** M.

**3. [P1] The list doesn't know Thor. CORE-JOB**
- **What:** "All" shows these at full weight:
  - 12 HR/L&D events, which personas.json excludes
  - 21 events where he was rejected
  - 27 likely duplicates (for example, World Business Forum NYC appears twice)

  The scoring in `_suggestionsFor` (`src/build.py:11770`) feeds only Plan Ahead and My Lineup.
- **Fix:** Put excluded events in an "Out of your profile" fold. Move rejected events and duplicates into the archived group (`opsCardTier`, `9468`). Add a short reason to the meta line, for example "Healthcare buyers".
- **Effort:** M.

**4. [P1] Contacts can't be acted on. CORE-JOB**
- **What:** 48 cards show a contact icon whose only content is a tooltip ("Contact on file: Steve McCuaig"). 65 cards have no apply link and no contact, so they show no next step. In the pop-up, the contact sits below Chat and Follow-ups.
- **Fix:** Make the card foot an underlined pill: "Email Anna Slater". When there is no contact, show "Find the organiser". Once contact is made, add the label "Reached out Oct 12".
- **Where:** `src/build.py:8188-8191`, `8314-8321`. **Effort:** S to M.

**5. [P2] Triage tools are locked to Angela, who has left. CORE-JOB**
- **What:** The Priority, Recently added and Should attend filters and the Contacts tile all check `isAngelaUser()`. 67 events are marked High priority and Thor never sees it.
- **Fix:** Switch the check to `abCanApply`. Add "Has contact" and "Open call" as quick filters.
- **Where:** `src/build.py:9241`, `9269-9275`, `10101`. **Effort:** S.

**6. [P2] Phone layout breaks. COSMETIC**
- **What:** The segment chips run to 523px, so the page scrolls sideways and "Attending" is off-screen. The star and archive buttons appear only on hover, so touch can't reach them.
- **Where:** `src/build.py:2325`, `1864-1865`. **Effort:** S.

## 7. Persona red flags
**Alex (power user):**
- No "/" shortcut for search and no j/k between cards.
- No sort control.
- No bulk archive or bulk star.
- About 4 tab stops per card, across 193 cards.

**Sam (accessibility):**
- Each card is an `<article role="button">` with links and buttons nested inside.
- Status is icon-only, with a person's initial at about 9px.
- The chat count is 9.3px (`1873`) and "+1" is 9px (`2878`), both under the 11px floor.
- Month headers are not headings, so there is nothing to jump between.
- The star tooltip still mentions "Angela's queue" (`7548`).

**Thor on the go (phone, between meetings):**
- The header date wraps and the avatar is clipped.
- 1.3 cards fit on the first screen.
- The contact icon names nobody and has no tap-to-email.
- He can't star an event from the list.
- The next speaking slot he could realistically win is about 25,000px down.

## 8. Minor observations
- At 1280px the grid shows 3 columns, but DESIGN.md says 2.
- Cards with no foot leave dead space.
- On a phone the icon cluster squeezes titles onto 3 lines.
- The empty state has two clear buttons that do the same thing.
- Existing tooltips use em dashes.
- Some Apply links go to generic pages (aim.media/discover-events).
- 129 events have a blank pay-to-play field, and searching "unpaid" finds nothing.

## Questions to consider
- What if the default view were "Chase next": an open call, a fit to his profile, and a known contact?
- Should an event that is too late to speak at sit in an "Attend only" view instead?
- If the tracker knows the contact, why does Thor write the email somewhere else?


---

# B1 · Events list (Thor): detector + browser evidence

Local http://localhost:8766/ · viewer `Thor` confirmed · desktop = pane default 1024×768 · phone = 390×844 emulated. Write guard installed after every load; `__writes` = [] at the end. **Overlay skipped: user guardrail (no live server).**

## Detector counts
- `public/index.html` (baseline-source, re-run today gives the same result): 175 findings. 168 are advisories (design-system-color 120, font-size 41, radius 7). These are legacy hexes, rem steps and radii from before the new DESIGN.md. 7 are warnings: low-contrast 1, undersized-ui-text 2, tiny-text 1, ai-color-palette 1, side-tab 1, dark-glow 1.
- `src/action-center.css`: 72 advisories + 1 side-tab. `src/sessionize.css`: 70 advisories + 1 side-tab. Neither file renders in this view.
- Rendered scans: desktop 7 (6 warnings, 1 advisory); mobile 9 (8 warnings, 1 advisory: flat-type-hierarchy).

## Findings
| rule | where rendered (Thor) | file:line | evidence | FP? |
|---|---|---|---|---|
| low-contrast #1fa0dc on white | `h1.app-title` | build.py:619 (color), 623 (phone size) | 2.95:1. Desktop is 24px bold, which counts as large text, so it needs 3:1 and fails by 0.05. Phone is 16.8px, so it needs 4.5:1 and fails clearly. | No. DESIGN.md allows Glacier only at display size. |
| low-contrast white on #1fa0dc | `#who-current-btn` avatar "T" | build.py:7008 (Thor's colour), 574-579 (`.who-init` 0.6rem, 20px) | 2.95:1 at 9.6px | No. Breaks the One Blue Rule. |
| undersized 9.6px "OCTOBER 29, 2026" | `#ab-today`, **phone only** (desktop is 11.84px) | build.py:624 (`.nav-meta` 0.6rem at ≤760px), markup 3718 | The date also wraps to 2 lines, and the avatar sits flush against the right edge with no gutter. | No |
| undersized 9.92px "Sync" | not rendered | build.py:3543-3544, markup 3864 | `#ops-sync-group` is `display:none` for Thor (build.py:9251-9252) | **Yes** (hidden) |
| tiny-text 11.2px | "Apply to speak" (96 buttons) is the only visible 11.2px text | build.py:864 (`.ops-apply-btn` 0.7rem) | White on #2773c2 = 4.86:1. Rendered scans also flag `#ops-count` at 11.52px (build.py:3562). 16 other 0.7rem rules exist, e.g. dead `.kpi-label` at 666. | Partly. The Fragment Mono label size is a DESIGN.md choice, but it is a primary button below 12px. |
| undersized `.chat-count` 9.28px, `.ops-who-more` 8.96px | 2 cards each | build.py:1874, 2878 | 4.74:1 | No |
| ai-color-palette (purple/violet) | **0 visible purple elements** in the default view (hue scan of every visible element) | Sources: 6896 (Meeting held), 16240 (Europe), 7010 (Hurley avatar), 1104 (`.qa-enrich`), 3505 (`.ab-btn--ask`), 1574, 2501, 826 | Purple only shows up here inside the filter drawer, when "Meeting held" is pressed or the Region menu is open. | **Yes for this view.** Region, Hurley and Enrich purples still break the Status-Only Color Rule elsewhere. |
| side-tab `.today-card::before` 3px | not rendered | build.py:683-687 | 0 `.today-card` elements in the DOM. It is dead CSS from the old hero. | **Yes** (dead). Also `.sz-terms` sessionize.css:50 (pop-up) and `.ac-health` action-center.css:2 (hidden). |
| dark-glow #142844 | not rendered | action-center.css:2 (`.ac-dialog` `0 24px 90px #14284438`), inlined at public/index.html:3245 | Action Center is hidden (`#ops-action[hidden]`, 0 dialogs), and the page is light, not dark. | **Yes** (dead and misread) |
| (new) tiny badge initials | mic and ticket stage icons, 71 instances | build.py:7890, 7997 (7.8), 7925 (6.8) | Real rendered size is 7.8px; white on #ca8a04 ≈ 2.9:1 | No |
| (new) tiny glyphs | month caret ▼ 9.6px; filter caret 8.8px; Pipeline "Clear" 9.92px | build.py:1786, 2452, 2504 | The filter caret is `aria-hidden`. The month caret is not. | Carets: yes. Clear: no. |
| flat-type-hierarchy (phone) | title 16.8px = card h3 16.8px | build.py:623, 2105 | step 1.24× | Advisory |
| **horizontal overflow at 390px** | `#ops-stats` segmented chips | build.py:2306-2310 (`.ops-seg` inline-flex, no wrap or scroll), 2316 (`nowrap`), 2325 (the ≤560 fix doesn't work) | scrollWidth 523 vs 390 (133px over). Content is 498px in a 342px box. "Booked" is cut off and "Attending" is off-screen. | **No: highest-impact finding** |

**Key contrast (desktop):** event title 19.8 · meta line #404040 10.37 · unselected chips 9.43 · "All" 19.8 · Add #fff/#047857 5.48 · Apply 4.86. Every #737373-on-white element measures 4.74, all at 11.5–11.8px: date, `.em-date`, counts, `#ops-shown`, `.seg-num`, search placeholder. They pass AA but are small.

**Tap targets (phone, interactive elements in this view):**
- **Below 24px:** avatar 20×20; month headers 342×22 (13); title links ~160×22 (159).
- **Below 44px:** logo 35×32; Events tab 58×39; Add 93×32; list/cal/map 34×34 ×3; segment chips 32 tall ×5; filter toggle 40×40; search 40 tall; Apply 31 tall (96); drawer dropdown buttons 41 tall; Pipeline chips 26 tall.
- **Star and Archive can't be used from the card face on touch.** They get 40×40 on coarse pointers (build.py:3695-3696) but stay at `opacity:0; pointer-events:none` (1864-1865) because there is no `hover:none` override: 0 of 571 are visible.

**Focus (keyboard only, 22 Tab stops from the logo to the second card):**
- Focus is visible on every stop.
- Most stops use the browser's default `outline:auto` ring, not a custom style.
- Cards get 2px #2773c2 (1853). Search gets a border change plus a 12%-alpha 3px glow (2530).
- Each card costs about 5 stops (card, title, star, archive, Apply), so about 900 stops for 193 cards. There is no skip link.

**Structure and naming:**
- Landmarks are only `nav` and `main` (3710, 3722). There is no banner, no search landmark and no skip link.
- Headings go h1 → 193×h3 with no h2, because month groups are buttons (9453).
- All 193 `article.ops-card[role=button][tabindex=0]` contain a link and buttons, i.e. nested interactive controls (8201-8204, 8484-8487).
- No visible control lacks an accessible name. Search uses `aria-label` only.

**Console:** 0 errors or warnings across 3 loads (I confirmed capture works with a probe log). No failed network requests.

## Skipped / failed
- Live overlay skipped (user guardrail).
- The first phone reload rendered as **Hurley**: purple "H" avatar, "My Interests 5", no Apply buttons. localStorage still read Thor, so this was most likely another tab on the same origin changing the shared key at load time. I reloaded, confirmed "Thor — profile & switch", and measured from there.
- Clicks used: the filter-drawer toggle, opening the Pipeline dropdown, Escape, and closing the drawer. Nothing was written.
- My first detector run failed (`timeout` isn't on macOS, exit 127). The re-run worked (exit 2 = findings found).
- Process slip: I ran one read-only `git status --short`, which the no-git rule forbade. Nothing was changed.
