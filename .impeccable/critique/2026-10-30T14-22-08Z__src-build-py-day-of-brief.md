---
target: the day-of briefing
total_score: 13
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 3
target_identity: "file:/Users/hurleywhite/Developer/arcticblue-event-tracker/src/build.py#day-of-brief"
timestamp: 2026-10-30T14-22-08Z
slug: src-build-py-day-of-brief
---
Method: dual-agent (A: design review sub-agent, B: detector + browser evidence sub-agent). Overlay skipped: user guardrail (no live server).

## Synthesis
Both passes agree: no active user can open a brief (qrow-brief gated to isAngelaUser at build.py:11937; Day-Of view redirected; today_section never rendered). The drawer itself is a sound dialog. Design review: 13/40; first move buried, contacts not linked, stale briefs look current, credit-spending buttons under the thumb. Evidence: .bf-label 14.4px specificity bug, sub-11px brief text, Enter on Brief opens the event instead, drawer overflows at 390px (same chip overflow), Agenda link unstyled.

# A3 · Day-of brief: design review

Checked on localhost:8766, 2026-10-29, as Thor and Hurley, desktop and 390px. No writes went out (one `/api/search` POST was blocked by the guard). To read a cached brief, I set `isAngelaUser` to true in my own tab only.

## 1. Verdict
The content is specific and the delivery is generic. The sections (Why we are here, People to find + where, First move, Win, "Unconfirmed, verify on the ground") fit the job and follow "never invent". The look is a stock AI drawer: emoji section icons, mono caps, colored move/win text, and 794 words of hedged model prose. **No active user can open a brief**, so for Thor the feature does not exist.

## 2. Nielsen heuristics
| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Status | 1 | Nothing says a brief exists. Its stamp says "cached" with no date (YPO brief: Aug 11). |
| 2 | Real world | 2 | Plain words overall, but a prompt leak ("persona says 'stage'... per instruction") |
| 3 | Control | 2 | Esc, close and focus return work. Paid re-runs are one tap away. |
| 4 | Consistency | 1 | Purple Speaking badge. Sub-label 14.4px is larger than its 11.2px heading. "Targets" means two things. |
| 5 | Error prevention | 1 | Paid buttons have no confirm. A stale brief is shown as current. |
| 6 | Recognition | 1 | Thor must know the brief exists and dig for it. Contacts on file are left out. |
| 7 | Efficiency | 1 | Copy is the only shortcut. No deep link, no push, no "today" entry. |
| 8 | Minimalist | 1 | 8 sections. First move is 3.3 phone screens down. |
| 9 | Error recovery | 2 | Readable, but shows a raw `TypeError` |
| 10 | Help | 1 | The only explainer is in a view nobody can reach |
| | **Total** | **13/40** | **Poor** |

## 3. Cognitive load and emotional journey
**Load:** three overlapping people lists (Room, People to find, Spotlight). "Who is in the room: CONFIRMED" while Unconfirmed says no roster was found. 2025 news for a 2027 event.
**Journey:** The cron writes briefs the night before but sends nothing (no Slack or email in `api/briefing.py`). In the morning nothing says "today": `today_section` (build.py:3725) is built but never put into the page. Thor hunts, finds nothing and walks in without a plan. If he finds it, the brief ends on "3 link(s) could not be verified". That is a peak-end of doubt at the venue door.

## 4. Strengths
1. The content model fits the job and admits what it does not know.
2. The drawer is built right: `role=dialog`, focus trap, Esc, focus goes back to the trigger, scroll locks, full width on a phone, 40px touch buttons.
3. Copy puts the whole brief on the clipboard as plain text. Good when venue signal is bad.

## 5. Priority issues
**[P0] No active user can open a brief.** CORE-JOB. The brief button is gated to `isAngelaUser()`. I checked as Thor and as Hurley: 0 buttons, and YPO GES has a cached brief Thor cannot open. `'dayof'` redirects to `myevents`, so `renderDayOf` never runs. The event pop-up has no brief entry. On a phone the lineup sits about 31,700px down the Events list, inside a closed fold.
Fix: change the gate to `abCanApply()`. Add a "Day-of brief" action in the pop-up for Booked/Attending events. Add a "Today / Next up" strip above Events from `dayofItems()`.
`build.py:11937, 15790, 10503, 3725`. Effort: S (gate), M (pop-up + strip).

**[P1] The action is buried.** CORE-JOB. Five minutes out, Thor needs the move and the names. Today they come after 2,600px of background.
Fix: start with a "Before you walk in" block (First move, People to find with where, one angle), then Logistics. Fold the rest under "Background". Same JSON.
`build.py:10718-10760`. Effort: M.

**[P1] The brief ignores the outreach data already on file.** CORE-JOB. The YPO pop-up holds Jessica Driver's and Ajit Shah's emails and "Follow up now, 83 days". The brief says "text/email Ajit Shah and Jessica Driver" and links neither. Nothing leads to the follow-up log.
Fix: tap-to-email chips under First move, plus a "Log what happened" button that opens the follow-up log.
`build.py:10737-10745, 5829`. Effort: M.

**[P1] Stale or contradictory briefs look current.** CORE-JOB. Only 4 of 404 events have a brief, the newest from Aug 11, and the UI shows no age.
Fix: "Researched Aug 11 · 11 weeks ago", amber when older than 7 days. Hide the room "confirmed" chip when Unconfirmed is present. Drop model meta lines.
`build.py:10731, 10734`. Effort: S.

**[P2] Paid research buttons take the thumb zone.** CORE-JOB. Targets and Regenerate sit next to Copy on a phone, with no confirm, and credits are limited. A mis-tap at the door turns the brief into a long spinner.
Fix: make Copy the primary action. Move both into "More research" with "This uses research credits. Run it again?"
`build.py:10538-10543`. Effort: S.

**[P2] Off-system visuals.** COSMETIC. `.bf-sec p` overrides `.bf-label` (renders at 14.4px). Below the 11px floor: `.bf-conf` 9.3px, `.mode-badge` 9.6px, `.bf-stamp` 9.9px, `.qrow-brief` 10.2px. Purple `.mode-stage` and green `.bf-move` break the status-only color rule.
Fix: `.bf-sec .bf-label`, `stageStyle()` pills (dayofCard already uses them), at least 0.7rem, plain-text section heads instead of emoji.
`build.py:2731-2760, 2915`. Effort: S.

## 6. Persona red flags
- **Thor on the day:** no path at all. Even if unlocked, the lineup button is 64x20px and left out of the coarse-pointer rule (3694). The paid buttons sit under his thumb, and First move is at screen 3-4.
- **Sam:** the dialog is named "Day-Of brief", not the event. Emoji in headings are read aloud. Some text is 9-10px.
- **Alex:** no deep link (`?brief=257`), no list of all briefs, no age, and no keyboard path from a row to its brief.

## 7. Minor observations
- Web Summit Lisbon (Nov 9) has a brief, and Angela's "@thor ... personal text" note sits in Thor's feed. It never reaches the day-of flow because it isn't Booked or Attending.
- "In the last week" shows comments 14-15 weeks old.
- The edit label "Attending — surfaces a Day-Of brief" (5167) promises something nobody can reach, and uses an em dash.
- Loading copy says "a few seconds" (10572), but the call is allowed 300s. The YPO "Agenda" link is the ypo.org homepage.

## 8. Questions
1. Should the brief be pushed (a 7am text with First move and three names) instead of waiting to be found?
2. "People to find" is outreach Thor needs 2-3 weeks before the event. Should it move into the pop-up's outreach step, leaving the day-of view as a last-mile checklist?
3. Only 4 of 404 events have a brief, and the newest is 11 weeks old. Fix the feature or cut it?


---

# B3: Day-of briefing (detector + browser evidence)

Local only (localhost:8766), write guard installed after every load. One blocked POST `/api/search` was caught by the guard (it fired from an Angela-only render, see Method). No database writes and no paid calls. Overlay skipped because of the user's guardrail. Identity was restored to `Thor` and the viewport reset to desktop at the end.

## Headline
**No current user can open a day-of brief.**
- The only live entry point is the My Lineup `qrow-brief` button. It only shows when `isAngelaUser()` is true (`src/build.py:11937`).
- The Day-Of tab is gone: `setView` rewrites `'dayof'` to `'myevents'` (`build.py:15790`). That makes `renderDayOf` (`10503`), `dayofCard` (`10481`) and all `.dayof-*` CSS (`2697-2714`) dead code.
- `openBriefDrawer` has only those two callers (`10522`, `12160`).
- `isAngelaUser` (`9219-9222`) is true only for a name starting with "angela" or the `/angela` route. That route returns 404 locally because it is a Vercel-only rewrite.

**Who can reach it:**
- **Thor:** no. His lineup shows 2 upcoming rows (ITC London, YPO GES) and 0 Brief buttons, even though YPO GES has a cached brief.
- **Hurley:** no. Same 2 rows, 0 buttons.

**Cached briefs (`abAllItems()`):** 404 items, 4 with `briefing_json`, 3 of them upcoming:
- Web Summit Lisbon (catalog 196)
- GITEX Global (catalog 95)
- YPO GES (manual 257)

Only YPO GES has an attendee (Thor). The other two are Submitted with nobody attending, so they appear in no lineup at all. If the overnight cron still runs, it is producing briefs nobody can open.

## Method note
To get drawer evidence I swapped `window.isAngelaUser` for a function returning true, in my tab's memory only (not localStorage, nothing persisted). I opened YPO GES "✓ Brief", which renders from cache with no fetch. The `/api/search` POST was triggered by that override during a view render and was blocked.

## Findings

| rule | element | file:line | evidence | renders for Thor? | false-positive? |
|---|---|---|---|---|---|
| side-tab (detector) | `.today-card::before` 3px left stripe | build.py:683 (index.html:221) | `today_section` is assigned at 3728/3742/3755 but never interpolated. 0 `.today-card` in the DOM | No (dead CSS, still shipped at index.html:213-245, 3239) | **Yes in practice**: the stripe never paints. Recommend deleting the block. |
| design-system-color (detector) | `.bf-win` #b45309 | build.py:2759 (index.html:2297) | off-palette amber on the "Win:" line, contrast 5.02 | No (Angela-gated) | No (token drift) |
| design-system-color/font-size (detector, first hit elsewhere) | `.bf-unconf li` #92600a, `.dayof-card.is-today` #f59e0b, 0.58/0.62/0.64/0.66rem | 2769, 2705, 2755, 2752, 2915, 2744 | the same off-ramp values are reused in the brief and lineup | No / dead | No, but deduplicated: the detector only flags the first occurrence |
| hierarchy inversion (specificity bug) | `.bf-label` ("PEOPLE TO FIND") | 2758 loses to `.bf-sec p` at 2756 | renders at **14.4px #0a0a0a**, larger than its section `h3` (11.2px). Intended 0.62rem grey | No | No |
| tiny functional text (<11px) | `.bf-conf` 9.28px, `.mode-badge` 9.6px, `.bf-stamp` 9.92px, `.bf-btn` (Targets/Regenerate/Copy) 10.56px, `.bf-date` 10.56px, `.qrow-brief` 10.24px | 2755, 2731, 2752, 2744, 2766, 2915 | measured computed sizes | No | No |
| low contrast | `.bf-conf` #737373 on bg-3 | 2755 | **4.31:1** at 9.28px (AA needs 4.5) | No | No |
| unstyled link | Logistics "Agenda" link | 10763 | `.bf-sec p a` renders browser default **#0000EE** and shows the raw URL. News links are styled (`--ab-blue` #2773c2, 4.86:1, underlined) | No | No |
| keyboard trap-out (nested control) | `.qrow-brief` inside `div role="button"` row | 11951 + handler 12163-12165 | **Verified:** Enter on the focused Brief button opens the event modal instead of the brief. The row's keydown handler calls `preventDefault` and `opsOpenRef` with no `e.target` check. A button nested in a role=button is also invalid ARIA | No | No |
| tap target | `.qrow-brief` | 2915 | 64×20 at both desktop and 390px. The coarse-pointer rule (3694-3696) does not include it | No | No |
| tap targets (drawer) | Targets / Regenerate / Copy / Close | 2744-2747, 3696 | desktop 88/104/48/31 × 27. At 390 with coarse pointer: 88/104/48/40 × 40. Close gets min 40, but none reach 44 | No | No |
| phone overflow | drawer at 390px | cause: `.seg-chip` row 2312-2325 | At 390 (as plain Thor too) the segmented chips run to 523px. That widens the layout viewport to 523, and the fixed drawer is 523 wide. Copy and Close sit past x=390. On open, focus moves to Close and the view pans, cropping the left ~133px of the brief text (screenshot). The drawer itself has no internal overflow | Page overflow: yes. Drawer: no | No (Chrome emulation; confirm on a device) |
| unstyled class | `.bf-where` | 10745 | has no CSS rule, so it renders as body text | No | minor |

## What works (verified)
- **Dialog semantics:** `role="dialog"`, `aria-modal="true"`, `aria-labelledby="bf-dlg-title"`. The label reads "Day-Of brief", not the event name, which is minor.
- **Focus:** on open, focus moves to Close and the body scroll is locked.
- **Tab trap:** Tab wraps from the last link to Targets, and Shift+Tab wraps from Targets to the last link.
- **Closing:** Esc closes, focus returns to the triggering `.qrow-brief`, and the scroll lock is cleared. The focus ring is a visible amber outline.
- **Contrast:** body text, headings, `.bf-hook`, `.bf-move` and `.bf-unconf` all pass AA.

## Rendered baselines
The desktop and mobile scans contain no day-of findings. The 9.6px "OCTOBER 29, 2026" is the nav date, and "💬 2"/"+1" are card badges. The drawer is never open during a scan, so the detector cannot see it. Every drawer finding above comes from browser measurement.

## Skipped / failed
- **Regenerate, Targets, Copy:** not clicked, as instructed (Copy would write to the clipboard).
- **Uncached brief path:** not exercised. "Brief →" on ITC London would call `/api/briefing`.
- **`/angela` route:** 404 locally, so it could not be tested.
- **Detector:** the first run failed because `timeout` is not on macOS. The rerun worked (exit 2 means findings were found).
- **Shared localStorage:** another tab or agent on the same origin changed `ab.collab.name` mid-run (I saw "Hurley" after setting Thor). I re-set it to Thor at the end.
