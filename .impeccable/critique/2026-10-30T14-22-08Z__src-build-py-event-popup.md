---
target: the event card and event detail pop-up
total_score: 19
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 3
target_identity: "file:/Users/hurleywhite/Developer/arcticblue-event-tracker/src/build.py#event-popup"
timestamp: 2026-10-30T14-22-08Z
slug: src-build-py-event-popup
---
Method: dual-agent (A: design review sub-agent, B: detector + browser evidence sub-agent). Overlay skipped: user guardrail (no live server).

## Synthesis
Both passes agree the pop-up is well built as a dialog but puts the organiser and next step last. Design review: 19/40; P0 reach line ignores contact_info/additional_contacts and says No contact yet under named contacts; no next-step strip; Apply shown regardless of state; one-flow only exists for Sessionize. Evidence: pop-up clipped at 390px by the seg-chip overflow, Edit button white on #1fa0dc 2.95:1, field labels 10.24px, card role=button with nested controls and no name, qa-step lacks aria-pressed, chat input unlabeled.

# A2 · Design review: event card + event pop-up

Tested locally (localhost:8766) as Thor, desktop and 390x844. Write stub on: one intercepted `opsWrite` (event_state 216, from "Mark followed up"), nothing reached the database. I did not click any paid action.

## 1. Design-specificity verdict
**The look is specific to this product. The structure is generic.** The Field Ledger comes through clearly: mono labels, hairline rules, squared labels vs pill controls, and a stage control drawn as a route. Nothing here looks like a template. But the pop-up is laid out like a generic record page (Notes, Overview, Who attends) rather than around outreach, and the organiser contact comes last. A few things are off-system: the purple Enrich button (build.py:1104) and the Sessionize block's own 5px-radius buttons (sessionize.css:10-15).

## 2. Nielsen heuristics
| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Visibility of status | 2 | After "Mark followed up" the pop-up re-renders and jumps back to the top with no confirmation |
| 2 | Match with real world | 2 | The stage says "Initial outreach", the log says "Reached out"; "Closed, paid slots only" gets a green ✓ |
| 3 | User control | 2 | Esc inside a follow-up note closes the whole pop-up and drops the text |
| 4 | Consistency | 1 | Four controls log a follow-up; the reach line contradicts the Contacts field |
| 5 | Error prevention | 2 | Enrich and Find someone cost money and give no warning; Apply is offered after the CFP has closed |
| 6 | Recognition over recall | 2 | The contact appears in 3 places; "Find someone to contact" is ~800px "above" |
| 7 | Flexibility/efficiency | 1 | No shortcuts; every visit means scrolling about 3 screens to act |
| 8 | Minimalist design | 2 | Quiet visually, but 28 to 33 controls and 6 to 11 zones per pop-up |
| 9 | Error recovery | 3 | Plain messages ("No one new found, try again", "Couldn't read that Sessionize page") |
| 10 | Help | 2 | Helpful tooltips, but some are stale (the star still says "Angela's queue") |
| | **Total** | **19/40** | **Poor (12-19).** It looks finished, but the core job is hard to complete. |

## 3. Cognitive load
**Checklist failures:** single focus (no primary action at the top), visual hierarchy (the action sits at the bottom, and Apply stays the primary button after you have applied), minimal choices, working memory (the contact is split across Notes, Contact info and the reach line), and progressive disclosure (Overview and Who attends are always open, above the action).

**Decision points with more than 4 options:**
- Stage route: 6 pills plus "+/−", so 8 options.
- Header: 6 controls (Enrich, Edit, Close, title link, star, archive).
- Logging a follow-up: 4 alternative controls.
- Whole pop-up: 28 visible controls on Protectors Insurance and 33 on Evanta CHRO, across up to 11 zones.

## 4. Emotional journey
1. **List.** It reads calm, but nothing says which of the 193 events need Thor. About half the cards carry a blue Apply button, which creates false urgency.
2. **Opening a pop-up.** The first things you see are a purple Enrich button and a 6-step route.
3. **Follow-ups.** A red "Follow up now, 72 days" alarm appears with no contact next to it, which causes anxiety.
4. **Three screens down.** The reach line says "No contact yet" right under two named contacts, so Thor stops trusting the screen.
5. **After clicking "Mark followed up".** He is thrown back to the top with no confirmation and doesn't know if it worked.

So the visit ends on a contradiction.

## 5. Strengths
- **It never invents.** A contact has to be a person, not a domain (build.py:5545-5568). Private events are never linked. The contact note is written in words rather than a score.
- **The stage route is well modelled.** Finished steps go inactive, there is a ×N count and a "−" undo (4454-4531). The basic dialog works: focus trap, Esc, focus returns to the card, and cards open from the keyboard (6468-6543, 6583-6589).
- **The Sessionize draft fits the job.** Each field has its own Copy button and a character count, and there is a "Decide before you press Submit" list of terms (sessionize.js:139-151).

## 6. Priority issues
1. **[P0] The reach line contradicts the contacts on file. CORE-JOB.**
   - **What:** It reads only `poc_name`/`poc_email` and ignores the `contact_info` and `additional_contacts` that the pop-up shows above it. On Protectors Insurance it says "No contact yet" under Jay Weintraub's and Sonya Larson's emails, then offers "Mark followed up" anyway.
   - **Why:** This is the one line meant to drive outreach, and it is wrong.
   - **Fix:** Build the reach target from the same sources `hasEmailContact` uses (build.py:8163-8174). Show a mailto link plus Copy. Put the "Find someone to contact" button inline when there is no contact.
   - **Where / effort:** build.py:5970-5982. **S**.
2. **[P1] No "next step" at the top. CORE-JOB.**
   - **What:** The apply and reach-out block is the last thing in the pop-up, about 1,960 to 2,140px down (3.1 screens on a phone).
   - **Fix:** Add a "Next step" strip under the stage route with one sentence and one primary button, worked out from the event's state:
     - "Draft the application"
     - "Find someone to contact"
     - "Email Jay Weintraub" with "Mark reached out"
     - "Follow up with Jay, last contact 18 Aug" with "Mark followed up"
     - "Closed: paid slots only"
   - Move the contacts into that strip.
   - **Where / effort:** build.py:5510-5514, 5949, 5953-5983. **M**.
3. **[P1] Apply is shown whatever state the event is in. CORE-JOB.**
   - **What:** 21 of the 52 visible Submitted/Booked cards still show a solid "Apply to speak". So do paid-only closed events (Evanta CHRO) and events with a past CFP (IRM UK, deadline 17 April). 58 cards with Apply start within 30 days.
   - **Fix:** Show Apply only when the event isn't submitted, closed or past its deadline. Otherwise show a static label such as "Applied 24 Jul". Once applied, turn "Apply on Sessionize" into a plain text link.
   - **Where / effort:** build.py:8304-8307, 8567-8570, 5955-5966; sessionize.js:72-78. **S**.
4. **[P1] The "one flow" exists only for Sessionize, and its steps are in the wrong order. CORE-JOB.**
   - **What:** Only 6 of 571 events have a Sessionize link, and all 6 are already Submitted, so Draft and Approve currently appear on no live event. The block also shows Apply (solid) first, then Draft (outline), then Record.
   - **Fix:** Number the steps 1 Draft, 2 Approve, 3 Apply, 4 Record, and make only the current step the primary button. Render at least Apply and "I've submitted, record it" for every event with an apply link.
   - **Where / effort:** sessionize.js:63-87, 116-136; build.py:5960-5966. **M** for the UI; **L** if drafting goes beyond Sessionize.
5. **[P2] Four ways to log a follow-up, in two vocabularies. CORE-JOB.**
   - **What:** The "Followed up" pill, its "+", the "Log a follow-up" form, and the "Mark followed up" link all log a chase. The "Initial outreach" stage and "Mark reached out" are also two names for one step.
   - **Fix:** Make the next-step strip the single action and treat the pills as status.
   - **Where / effort:** build.py:4495-4531, 5714-5733, 5975-5979. **M**.
6. **[P2] Keyboard data loss and focus loss. COSMETIC (a11y).**
   - **Esc loses the note:**
     - **What:** Inline editors call `preventDefault`, but the document-level Esc handler doesn't check for it, so Esc closes the pop-up and the typed note is lost.
     - **Fix:** `if (ev.defaultPrevented) return;`
     - **Where:** build.py:6294, 6365, 6539-6541.
   - **Focus lost after in-pop-up actions:**
     - **What:** Mark reached out, Use and Approve re-run `openEventModal`. That sets `lastFocus` to a node it then destroys, resets the scroll to 0, and on close focus falls to `<body>` (verified).
     - **Fix:** Only set `lastFocus` when the overlay is hidden, and keep the scroll position.
     - **Where:** 6468-6472, 6012.
   - **Effort:** **S**.

## 7. Persona red flags
**Alex (power user)**
- No J/K or prev/next between events, and no key to mark someone reached out.
- About 4 tab stops per card.
- Has to scroll 3 screens on every event.

**Sam (accessibility)**
- Each card is `role=button` with no accessible name but holds links and buttons (build.py:8203-8204).
- Text below 11px:
  - ×2 count at 8.4px (1998)
  - Follow-up type at 9.6px (1273)
  - Field labels at 10.2px (1023)
- "Follow up now" amber #b9770e is about 3.7:1 contrast (sessionize.css:110).
- Stage pills are 27px tall.
- Shift+Tab from Close reaches the paid Enrich button in two presses.
- Plus the Esc and focus bugs in issue 6.

**Thor on the go (390px)**
- The pop-up is cropped: it renders 483px wide because the segment-chip row overflows to 523px (build.py:2312-2325). Focusing Close pans the view so the title and the route are cut off.
- The email first appears as free text inside Notes (around 550px down). The contact field is around 1,350px down and "Mark followed up" around 2,140px. That button is a 13px text link.
- Star and archive are invisible on touch cards: `.ops-hover` has opacity 0 and no `hover: none` override (1864-1865).

## 8. Minor observations
- **Em dashes in live copy:**
  - "No contact yet — …" (build.py:5981)
  - "I've submitted — record it" (sessionize.js:71)
  - The archive and follow-up labels
- **Stale copy:** the star tooltip still says "Angela's queue" (7548), and the Edit form still offers Carlos and Jim as speakers.
- **Paid actions look free:**
  - Enrich is the most prominent header button.
  - Find someone shows a 🔍 emoji and no cost hint.
- **Bad link text:** "Speaking Notes" turns a whole sentence into the link text (5771-5782).
- **Off-profile events with no signal:** about a dozen HR/L&D events (Richmond CLO, HRFest, Evanta CHRO) sit in Thor's default list, and nothing on the card says they are off-profile.
- **Unconfirmed, once:** the applier-only sections disappeared briefly for a few opens while `abCanApply()` returned true. Not reproduced.

## Provocative questions
1. If the pop-up exists to get Thor to an organiser, why is the organiser the last thing in it?
2. Should the card face say what to do next on that event (Apply, Find contact, Follow up due, Waiting) instead of an Apply button that is wrong for most submitted events?
3. Is a 193-card list the right home for "the right few beat many"? What would "5 events need you this week" look like?


---

# B2: event card and event pop-up (detector + browser evidence)

**Setup:** own tab (tab-4) on localhost:8766 as Thor, write guards installed before any interaction; `__writes` was `[]` at the end. Desktop checked at 1024x768, phone at 390x844 with touch emulation (viewport reset afterwards). Overlay skipped: user guardrail.

## Findings

| # | Rule | Element | Source | Evidence | False positive? |
|---|---|---|---|---|---|
| 1 | undersized-ui-text | `.chat-count` "💬 2" | build.py:1874 | 9.28px | No |
| 2 | undersized-ui-text | `.ops-who-more` "+1" | build.py:2878 | 8.96px | No |
| 3 | font-size off ramp, <11px | `.modal-field .k` field labels | build.py:1024 | 10.24px mono, 10.37:1. Only text under 11px in the pop-up | No |
| 4 | side-tab | `.sz-terms` | sessionize.css:50 | 3px #ff6b5e (off-palette) stripe. Not rendered: no drafts exist locally | Partly: the warning is intended, the form is the flagged pattern |
| 5 | font-size off ramp | Sessionize block | sessionize.css (21 hits) | Fixed px sizes; `.sz-fk` and `.sz-copy` are 11px (lines 44, 46) | Advisory |
| 6 | low-contrast (scan missed it: pop-up was closed) | Edit button `#modal-edit-toggle` | build.py:1090–1096, :6428 | White on #1fa0dc = **2.95:1** at 13.6px | No |
| 7 | non-text contrast + tiny text | Card stage marks | build.py:7814, :7008, :7890, :7997, :7925 | Submitted mic #ca8a04 2.94:1 and Thor's star #1fa0dc 2.95:1 (both under 3:1). White initials on them 2.94:1 at **7.8px** (6.8px on the ticket mark). 69 on screen | No |
| 8 | dead tooltip | `.ops-stage-ico[title]` | build.py:1953 | `pointer-events:none`, so "Submitted — Thor" never shows on hover | No |
| 9 | nested interactive | `article.ops-card[role=button]` | build.py:8203, 8316–8338 | Contains a link and 2–3 buttons; role=button makes them presentational. With no aria-label, the card's name is everything inside it ("Open website for AIBC Rome I'm interested Archive event for everyone Submitted — Thor November 2–5 · Rome, Italy"). 193 cards = **868 tab stops** | No |
| 10 | touch reachability | Star and archive (`.ops-hover`) | build.py:1864–1865 | `opacity:0; pointer-events:none` at rest, with no `(hover:none)` override (unlike :2051). Unreachable from the card on a phone; the pop-up has equivalents | No |
| 11 | missing state | Stage toggles `.qa-step` | build.py:4469 | No `aria-pressed`; "on" is shown by colour only | No |
| 12 | missing label | `#chat-input` | build.py:18189 | Placeholder only | No |
| 13 | **pop-up clipped at 390px** | Overlay and pop-up card | build.py:934–948; cause build.py:2312–2325 | The filter `.seg-chip` row runs to 523px, widening the layout viewport. The overlay becomes 523 wide and the card 483, but only 390 is visible. Screenshot: left 113px cut off. At pan 0, Edit and × (x 454–488) are off-screen | No (high) |
| 14 | target <24px | `.qa-fu-btn` 26x22; `.sz-link` 45x21; `.q-link` 103x20 | build.py:2039; sessionize.css:16; build.py:5976 | Measured | The last two may pass on spacing |
| 15 | target <44px (phone) | ×, `.mt-ico`, `.qa-step`, card Apply, Edit, title link | build.py:986, 1163, 1989, 861 | 34x34, 26x26, 27px, 31px, 36px, 22px tall | Advisory |
| 16 | type consistency | Section heads | build.py:1880 vs 1537 | "Chat with the team" is mono 11.2px; the other heads are sans 12.8px | Design |
| 17 | interaction model | Card title link | build.py:8319 vs :6548 | The title opens the external website; the rest of the card opens the pop-up. The comment at :6548 says titles open the detail card | Design |

**Out of scope (page chrome):** app title, `#who-current-btn`, `#ops-count`, `#ab-today`.

## What passed
- **Keyboard:** card focus shows a 2px #2773c2 ring. Enter opens the pop-up (Space is handled too). Focus moves to ×. Tab cycles through 17 stops and stays inside. Esc closes and focus goes back to the card.
- **Dialog markup:** `role=dialog`, `aria-modal=true`, `aria-labelledby=modal-title`.
- **Names:** all icon-only buttons are named (×, star, archive, `.mt-ico`, +/−). Contact and stage marks are `role=img` with aria-labels.
- **Contrast:** card Apply 4.86:1, `.em-date` 4.74:1, Sessionize Apply 4.86:1, `.sz-done` 5.12:1, `.q-link` 5.44:1. The mailto link is underlined.
- **Console:** only a 404 on `/api/sessionize?cfp=`. The local static server has no API, so the call dates stay blank; expected locally.

## Card internals
The card is an `article` with `role=button`, `tabindex=0` and no aria-label. It opens on Enter or Space, or a click anywhere off its own controls. Inside:
- `a.event-name-link` "Open website for {name}"
- `button.saved-star` "I'm interested", hidden at rest (40x40 with a coarse pointer)
- `button.ops-chip.urgent` "Urgent", `display:none`
- `button.ops-archive-x` "Archive event for everyone", 24x24, hidden at rest
- `a.ops-apply-btn` "Apply to speak ↗", on 96 of 193 cards
- Static marks: `.ops-contact-ico` and `.ops-stage-ico` (both `role=img`), `.chat-count` (title only)

## Skipped or not verified
- Overlay and live-server: user guardrail.
- Draft panel (`.sz-terms`, `.sz-copy`): no drafts locally, so source-only.
- Not clicked: Enrich, Find someone/more people, Draft, Record application, Send, stage toggles.
- Desktop checked at 1024px, not 1440.
- Card names approximated from the DOM, not the real accessibility tree.
- Detect CLI not re-run; used today's baselines.
