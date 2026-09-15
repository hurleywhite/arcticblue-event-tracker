# Booking Action Center

The production homepage is `/events` (generated `public/index.html`). `/` now redirects there. The original Lineup, Events, calendar, map, record editor and collaboration remain available. `/opportunities` is a legacy separate interface; it was not replaced by this work.

The Action Center reads the original catalog plus Supabase `event_state` and `manual_events`. It preserves the original duplicate filtering and uses `event_opportunities` only for recommendations matched by source table/key. No event records are copied. Daily builds embed `src/booking-core.js`, `src/action-center.js` and `src/action-center.css` into the original self-contained page.

## Workflow

- Every active booking decision is Apply, Outreach, Book Meetings, Attend or Stack Trip, with an owner, next action, due date and reason. Pass requires a reason.
- Unqualified events and future rechecks remain in Background. Expired recheck dates produce a decision task. Completed actions leave the working queue.
- Existing submissions and booked/attending status are read from the original records. Existing curated recommendations enter Decisions until the team commits a complete action. Missing owners and due dates are explicit.
- Application drafts, submitted dates, organizer replies, follow-up dates and outcomes persist in the original records. Nothing sends outreach or submits an application automatically.
- Saves match the previously loaded booking document, and show a conflict if another session has changed it.

## Qualification

Public evidence requires a type, HTTP(S) source, checked date and description. Evidence older than a year is excluded from the current score. Each evidence type contributes once: audience breakdown 30; end-user speakers/public attendance/company event page 20 each; prior attendees 15; advisory board/organizer claims 10; sponsors 5. Score is capped at 100 and is an evidence index, not attendance probability. A strong buyer fit and 40 evidence points are required for an automatic qualification recommendation. Without sources the score is Unknown. Known negative examples are excluded from recommendations; no records are deleted.

Speaker lists, organizer claims and public attendee announcements are separately typed evidence. Private attendee portals remain the source for verified attendance; no private attendee lists are put in the public tracker.

## Travel and target accounts

The existing approved-editor API protects target accounts and recorded travel. The UI supports editor magic-link sign-in, account creation/editing, recorded trips and searches anchored on target companies/executive roles or a trip's city/dates. Added search results enter Background.

Trip packs match the same city within four days of recorded travel and list target accounts whose office city is recorded. Live, authorized all-day calendar locations can also generate packs. This date-only calendar implementation cannot establish free time slots and does not expand recurring entries; it explicitly says so. Relationship intelligence remains deferred.

At release, production `/api/calendars` reports `configured:false`. To enable live feeds, configure `TEAM_CALENDARS` in the existing Vercel project using the format documented in `api/calendars.py`. Sharing a calendar with the tools account alone does not configure this ICS-based endpoint. Keep secret feed URLs server-side. Target accounts were empty; add the actual approved companies rather than manufacturing a target list.

## Data and deployment

Migration `booking_action_center` adds a `booking` JSON object to the two original event tables and `city`/`executive_roles` to `target_accounts`. Existing RLS/access rules are preserved; travel/targets remain behind editor authorization. Database application was verified, including an update rolled back without retained test data.

Push `main` to the existing GitHub repository to trigger the connected Vercel production deployment. Check its Vercel commit status and verify `/events`, `/` and API responses.

## Validation

- `node scripts/test_booking.js`: booking rules, missing evidence, deadlines, snoozes, outcomes, geography, routing and every generated script's syntax.
- `python3 -m unittest scripts/test_booking_api.py`: authorization, invalid dates, trip validation, target writes and private-data gating.
- Local DOM integration using representative existing records: Action Center default, decision rows, booking dialog/save, calendar connection status, targets and original Lineup navigation. The temporary DOM test library is outside the application; no production dependency was added.


## Application workflow update — September 15, 2026

- `Prepare & contact` opens a private workspace keyed to the original event.
  Choose speaker pitch, warm introduction, follow-up or meeting request; record
  a contact and verified relationship context; build and edit a draft; save
  actual sent/reply dates and a next follow-up. Drafts do not mark email sent.
- Attio: approved editors can connect a read-only token in Applications. The
  backend searches people and retrieves the selected contact's email, role and
  canonical Attio record URL. No attendee or warm-relationship claims are
  inferred. Drafts are saved in this tracker, not Attio's native draft store;
  use Copy email plus Open contact in Attio, or Open in email app.
- Trips: Thor, Verma and Jerome have individual Google iCal connection cards.
  A secret Google iCal address is verified and kept in a service-only table.
  Refresh reads connected feeds; no background auto-import is claimed.
  Calendar exports are supported as an alternative. All-day city markers and
  travel entries become suggestions requiring date/destination review. After
  review they upsert the original travel_windows record by person/source UID.
  Recurrences are skipped; dates are not free/busy availability. Cancelled and
  virtual entries are excluded. Calendar export contents are not retained.
- Existing ChatGPT Calendar access is separate from application integration.
  No calendar or Attio credentials were available during this implementation;
  connections must be completed in the new editor controls. Existing four
  recorded travel windows were preserved; no new trips were fabricated.
- Product / innovation topic fit now needs a concrete agenda source before a
  new Apply decision. Buyer density and deadlines alone cannot establish fit.
  BAFT 2027 was marked Pass + hidden in production with the user's reason, and
  explicit exclusion is enforced even if the automated model gate is disabled.
- Private data: `event_integrations` and `event_application_workspaces` have
  RLS enabled and no anon/authenticated grants. The approved-editor server API
  is their only application entry point. Credentials are never returned.
  This preserves public event records without placing personal contacts or
  private drafts in booking JSON. Optimistic versions protect parallel edits.
- Migration: `scripts/application_workflow_schema.sql`, applied to production
  as `private_application_workflow`. Existing project and deployment retained.
- Verification: booking rules/generated script syntax; API auth, calendar
  source validation, cancellation/exclusive-end handling, draft state,
  concurrency and idempotent trip update; DOM contact→draft→save flow; private
  table grants and a rolled-back database save/version query.
