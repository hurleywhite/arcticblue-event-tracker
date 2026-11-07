# Event operator

The tracker lists events. The operator works them. Every Monday it prepares
Thor's speaking outreach for the week, and Thor approves and sends it from one
screen at `/week` in about 15 minutes.

## Why this exists

Thor's feedback on the tracker (Granola, July and October 2026):

- He did not trust the statuses. Submitted and booked counts were wrong.
- Filters, pills and labels buried the list.
- At a glance he wants two things: what he is attending, and what has been
  submitted with its real status.
- Batches of about 30 a week, in date order. 100 is too many. He does not trust
  priority labels, but wants to be able to jump ahead for major events.
- Apply 6 to 12 months out. Skip events that need about $20K of sponsorship to
  speak. Keep "mixed" events (sponsorship plus a free route) visible.
- Follow up on submissions and on losses, to learn and to catch late openings.

Since Angela left, nobody prepares the work. Thor does it himself, one event at
a time, from inside each event's pop-up.

## The weekly loop

| When | What happens | Who |
|---|---|---|
| Monday 5am ET | Plan: pick this week's events and give each a lane | GitHub Action |
| Monday 5 to 6am ET | Prepare: find missing organiser contacts, draft every application and message | GitHub Action |
| Monday morning | Slack post: what is ready, with a link to `/week` | Slack webhook |
| During the week | Approve, send, record. About 15 minutes | Thor |
| Any time | Replies, acceptances and rejections recorded against the event | Thor, or the Sessionize check |

Nothing is sent or submitted by the operator. LinkedIn has no messaging API and
Sessionize has no speaker API, so a person presses send. Approved form and email
items are handed to Claude's event-apply skill (the existing "Apply for me"
contract, `decision = 'apply'`), which fills the form or drafts the Gmail and
waits for a yes.

## Which events (Thor, by default)

An event is in this week's batch when all of these hold:

1. It fits Thor: his healthcare-buyer profile, or he is already engaged with it
   (interested, speaker, asked to reach out). If those leave the batch short,
   executive enterprise-AI events fill the rest, marked "Broader fit". Broad
   fill never takes another speaker's territory: an event whose name, or most
   of whose topics, say banking, insurance, finance or fintech stays Verma's
   even when the blurb says "executives". A CIO summit that lists banking
   among many sectors is still open.
2. It is not HR or L&D, not a clinician event, not in Africa, not a
   non-English event, not archived, and not assigned to another speaker.
3. It is not pay-to-play. `pay_to_play = Yes` with no free route is skipped.
   Both / Mix / Partial stays in, marked "Mixed: check the free route".
4. Timing: an event up to 12 months out. A known open call (a Sessionize call,
   or a form with a deadline still ahead) can be as close as 14 days. Anything
   else, a form with no deadline or organiser outreach, must be at least 60 days
   away, so there is time to get a slot.
5. Nothing has been sent for it yet. Events already in flight go to Follow-ups.

Order: anything whose call closes in the next 21 days first, then by event date.
Major events (priority High) are marked so Thor can jump ahead. The cap is 30.
If fewer qualify, the screen says how many and why, rather than padding.

## Lanes

Each event gets exactly one lane, the most direct route to a speaking slot:

| Lane | When | Prepared | Thor's action |
|---|---|---|---|
| Sessionize | The event's call is on Sessionize and open | Application from his talk library (existing drafter) | Apply for me, or open the call and paste |
| Form | An apply-to-speak link that is not Sessionize | Application answers from the talk library | Apply for me, or open the form and copy answers |
| LinkedIn | An organiser with a LinkedIn profile | Connection note (200 characters max) plus the message for after they accept | Copy the note, open the profile, send, press Sent |
| Email | An organiser email and no LinkedIn | Subject and body | Open in Gmail (or Apply for me), send, press Sent |
| Find contact | None of the above | The prep run researches the programme director. If nothing is found, a LinkedIn search link | Search, paste the contact, or skip |

Messages are framed as teaching (a talk the audience learns from), not selling.
They use only facts from Thor's speaker facts and the chosen talk, no em
dashes, and any number not in those sources is flagged for checking.

## Statuses Thor can trust

A status only changes when an action is recorded, and each action leaves a
receipt in the event's follow-up log: the channel, who it went to, the exact
text, the date, and who pressed the button. The screen shows the receipt next
to the status.

- Sent on LinkedIn or email: adds "Initial outreach".
- Submitted a form or Sessionize application: adds "Submitted" and the date.
- Follow-up sent: adds "Followed up".
- Reply recorded: Meeting held, Booked or Rejected, with the same rules as the
  tracker's own buttons (an outcome retires the in-flight steps).
- Sessionize acceptances keep arriving from the existing daily check.

Events tagged Submitted or Initial outreach with no date and no log entry show
under "Needs a record": confirm the date or clear the stage. That is how the old
wrong counts get cleaned up once and stay clean.

## The /week screen

1. **You're attending:** upcoming events where Thor is speaking or attending.
2. **Out now:** applications and outreach in flight, with the last touch, days
   waiting, the receipt, and when a follow-up is due.
3. **Ready this week:** the batch in date order. Approve all, or open one.
4. **Follow-ups:** in-flight items 14 days quiet (sooner near the event), and
   thank-you notes after a rejection asking about late openings and next year.
5. **Needs a record:** the cleanup list above.

Skipping asks for one reason: not a fit, pays to speak, timing or travel, or
not this week. The first three archive the event for the team, as archiving
does today. "Not this week" lets it come back next Monday.

## Data

No new tables or migrations. Everything rides on columns that already exist:
the operator's state lives in `booking.operator` on `event_state` and
`manual_events` (as `booking.sessionize_draft` already does); contacts in
`poc_name`, `poc_email`, `poc_linkedin`, `poc_note`, `poc_lookup_at`; receipts
in `follow_ups`; stages in `status_tags`; dates in `submitted_at`.

```
booking.operator = {
  week: "2026-W46", person: "thor", lane: "linkedin", order: 3,
  fit: "profile|engaged|broad", why: "...", flags: [...],
  status: "planned|ready|approved|sent|skipped|error",
  draft: {...} | message: {...}, checks: [...],
  prepared_at, approved_at, sent: {channel, to, text, at, by},
  skip: {reason, at, by}
}
```

## Code

- `api/_operator_core.py`: the rules above as pure functions (selection,
  lanes, receipts, follow-up timing). Unit tested, no network.
- `api/operator.py`: GET the week; POST plan, prepare, digest (cron, behind
  `EVENTS_INGEST_SECRET`) and the screen's actions (same-origin, like the rest
  of the tracker). Reuses `api/sessionize.py` drafting and the contact
  research prompt.
- `public/week.html`: the screen. Self-contained, Nunito Sans, white.
- `.github/workflows/event-operator.yml`: the Monday run.
- `scripts/test_operator.py`: tests.

## Setup

1. Thor approves two or three talks in My Profile. Every talk is still a draft,
   so every application is flagged until he does.
2. Optional: add `SLACK_WEBHOOK_URL` in Vercel for the Monday post.
3. Merge the branch, then run the "Event operator" workflow once by hand, or
   press Prepare this week on `/week`.

## Two-week test

Pass when, for two consecutive weeks:

- at least 25 items go out per week,
- Thor spends under 15 minutes per batch,
- every status on the screen has a receipt.

If Thor will not approve in a batch, the drafts are the problem, not the
screen: look at which ones he edited or skipped and why.
