// Tests for src/sessionize.js. Run: node scripts/test_sessionize.js
const assert = require('assert');
const Z = require('../src/sessionize.js');

// The Sessionize link is found wherever it was typed, and only an event page counts.
assert.equal(Z.link({ apply_url: 'https://sessionize.com/aidevworld-2027/' }), 'https://sessionize.com/aidevworld-2027/');
assert.equal(Z.link({ notes: 'Applied via https://sessionize.com/ai-devcon-fall. Two tracks.' }), 'https://sessionize.com/ai-devcon-fall');
assert.equal(Z.link({ speaking_route: 'Open CFP (https://www.sessionize.com/opengov-africa/)' }), 'https://www.sessionize.com/opengov-africa/');
assert.equal(Z.link({ notes: 'Via Sessionize' }), '');                       // mentioned, no link
assert.equal(Z.link({ apply_url: 'https://sessionize.com/app/speaker' }), ''); // the app, not an event
assert.equal(Z.link({ apply_url: 'https://example.com/cfp' }), '');
assert.equal(Z.link(null), '');
assert.equal(Z.link({ speaking_route: 'OPEN CFP via Sessionize: sessionize.com/ai-risk-summit-2026' }), 'https://sessionize.com/ai-risk-summit-2026');
assert.equal(Z.link({ notes: 'mail cfp@sessionize.com/x or see notsessionize.com/y' }), '');   // an address or another site is not a link

// The pop-up block: nothing without a link; applied vs not applied.
assert.equal(Z.blockHtml({ notes: 'Via Sessionize' }), '');
const fresh = Z.blockHtml({ apply_url: 'https://sessionize.com/x/', stage_tags: [] });
assert.ok(fresh.includes('Apply on Sessionize') && fresh.includes('record it') && fresh.includes('value="Thor"'));
const done = Z.blockHtml({ apply_url: 'https://sessionize.com/x/', stage_tags: ['Submitted'], submitted_at: '2026-07-24', speaker: 'Thor' });
assert.ok(done.includes('Applied 24 Jul 2026') && done.includes('Thor') && !done.includes('record it'));
assert.ok(!Z.blockHtml({ apply_url: 'https://sessionize.com/x/"><script>alert(1)</script>' }).includes('<script>'));

// The line under the button says what the public page says.
const line = (info, rec) => Z._cfpLine(Object.assign({ ok: true }, info), rec || {});
assert.ok(line({ status: 'closed', closes: '2026-09-18' }).html.includes('closed 18 Sep 2026'));
assert.ok(line({ status: 'not_open_yet', opens: '2027-01-05', closes: '2027-03-01' }).html.includes('opens 5 Jan 2027'));
const far = line({ status: 'open', closes: '2099-03-01', timezone: 'Pacific Daylight Time (UTC-07:00)' });
assert.ok(far.html.includes('closes 1 Mar 2099 (Pacific Daylight Time)') && far.html.includes('Save as CFP deadline') && far.cls === 'sz-ok');
assert.ok(!line({ status: 'open', closes: '2099-03-01' }, { deadline: '2099-03-01' }).html.includes('Save as CFP deadline')); // already saved
assert.ok(Z._cfpLine({ ok: false }, {}).html.includes('Couldn'));

// Pasted emails: only Sessionize ones, and a refusal is never read as an acceptance.
assert.equal(Z.parseEmail('Hi, thanks for registering for Web Summit.'), null);
const said = t => Z.parseEmail('Sent via Sessionize.com\n' + t).outcome;
assert.equal(said('Congratulations! Your session has been accepted for AI DevWorld 2027.'), 'accepted');
assert.equal(said('We are pleased to inform you that your talk was selected.'), 'accepted');
assert.equal(said('Unfortunately your session has not been accepted this year.'), 'declined');
assert.equal(said('We were unable to accept your proposal.'), 'declined');
assert.equal(said('Your session wasn’t successful this time, though it was a strong field.'), 'declined');
assert.equal(said('Your session has been placed on the waitlist.'), 'waitlisted');
assert.equal(said('Thank you for your submission. Your session was successfully submitted.'), 'submitted');
assert.equal(said('The session you submitted has been accepted.'), 'accepted');
assert.equal(said('Reminder: the schedule is now live.'), '');                 // Sessionize, no verdict

// Matching the email to an event: the name has to really be in the email.
const items = [
  { kind: 'manual', key: 'a', name: 'AI DevWorld', stages: ['Submitted'], speaker: 'Thor' },
  { kind: 'manual', key: 'b', name: 'AI DevCon Fall', stages: ['Submitted'], speaker: 'Verma' },
  { kind: 'catalog', key: 7, name: 'Web Summit', stages: [] },
  { kind: 'manual', key: 'c', name: 'AI Engineer New York', stages: ['Submitted', 'Rejected'] },
];
const r = Z.rankItems('Your session has been accepted for AI DevWorld 2027. Sessionize', items);
assert.equal(r[0].item.key, 'a'); assert.equal(r[0].score, 1);
assert.ok(r.some(x => x.item.key === 'b'));       // a live application stays pickable
assert.ok(!r.some(x => x.item.key === 7));        // an unrelated event is not offered
assert.ok(!r.some(x => x.item.key === 'c'));      // nor one already decided
assert.ok(Z.rankItems('Sessionize: schedule update', items)[0].score < 0.75); // no name in the email: nothing preselected

// Stage rules match the tracker's own buttons.
assert.deepEqual(Z.withStage(['Submitted', 'Initial outreach', 'Followed up'], 'Booked'), ['Submitted', 'Booked']);
assert.deepEqual(Z.withStage(['Submitted', 'Booked'], 'Rejected'), ['Submitted', 'Rejected']);
assert.deepEqual(Z.withStage(['Submitted'], 'Submitted'), ['Submitted']);
assert.deepEqual(Z.withStage(['Submitted', 'Followed up'], ''), ['Submitted', 'Followed up']); // waitlisted: no change
// The drafted application in the pop-up.
const D = { status: 'ready', talk_title: 'Fail or Scale', talk_status: 'draft', fit: 'strong', generated_at: '2026-10-16T18:00:00Z',
  title: 'Fail or Scale <b>', abstract: 'Para one.\nPara two.', short_abstract: '', format: '', track: 'Main Stage', level: 'Intermediate',
  takeaways: ['One', 'Two'], answers: [{ question: 'Why you?', answer: 'Because.' }], checks: ['Not approved yet.'],
  terms: [{ kind: 'fee', text: '$499 package', why_it_matters: 'Pay-to-play.' }], unknowns: ['Session formats'] };
const base = { apply_url: 'https://sessionize.com/x/', stage_tags: [], _table: 'event_state', _key: 9 };
assert.deepEqual(Z.draftFields(D).map(f => f.label), ['Title', 'Abstract', 'Track', 'Level', 'Takeaways', 'Why you?']);   // blanks skipped
assert.equal(Z.draftFields(D)[4].text, '1. One\n2. Two');
const withDraft = Z.blockHtml(Object.assign({ sz_draft: D }, base));
assert.ok(withDraft.includes('Draft ready') && withDraft.includes('strong fit') && withDraft.includes('drafted 16 Oct 2026'));
assert.ok(withDraft.includes('Not approved yet.') && withDraft.includes('$499 package') && withDraft.includes('Session formats'));
assert.ok(withDraft.includes('Fail or Scale &lt;b&gt;') && !withDraft.includes('<b>'));                // escaped
assert.ok(withDraft.includes('value="Fail or Scale &lt;b&gt;"'));                                      // the record form starts from the drafted title
assert.ok(withDraft.includes('data-sz-key="event_state:9"'));
assert.ok(withDraft.includes('Approve this application') && !withDraft.includes('ready to submit'));    // draft: approve first
const approved = Z.blockHtml(Object.assign({ sz_draft: D, decision: 'approved' }, base));
assert.ok(approved.includes('Approved: ready to submit') && !approved.includes('Approve this application'));
assert.ok(!Z.blockHtml(Object.assign({ sz_draft: D }, base, { stage_tags: ['Submitted'] })).includes('Approve this application'));  // already in
assert.ok(Z.blockHtml(base).includes('Draft the application'));                                        // no draft yet
assert.ok(!Z.blockHtml(Object.assign({}, base, { stage_tags: ['Submitted'] })).includes('Draft the application'));  // applied: no new draft
globalThis.abCanApply = () => false;
assert.ok(!Z.blockHtml(base).includes('Draft the application'));                                       // only the people who apply can draft
delete globalThis.abCanApply;

// The talk library's rules.
const T = require('../src/talks.js');
const talk = { id: 'a', status: 'approved', title: 'Old', approved_by: 'Thor', approved_at: 'x' };
assert.equal(T.applyEdit(talk, { title: 'New' }, 'Thor Ernstsson', 'thor').status, 'approved');      // the speaker's own edit keeps it
const byOther = T.applyEdit(talk, { title: 'New' }, 'Hurley', 'thor');
assert.ok(byOther.status === 'draft' && byOther.approved_by === '' && byOther.title === 'New');      // anyone else's sends it back
assert.equal(talk.title, 'Old');                                                                       // never mutates the original
const ok = T.setStatus({ id: 'a', status: 'draft' }, 'approved', 'Thor');
assert.ok(ok.status === 'approved' && ok.approved_by === 'Thor' && ok.approved_at);
assert.equal(T.setStatus(ok, 'draft', 'Thor').approved_by, '');
globalThis.AB_TALK_SEEDS = { thor: { talks: [{ id: 'a' }] } };
assert.deepEqual(T.people(), ['thor']);
const sd = T.seed('thor'); sd.talks.push({ id: 'b' });
assert.equal(T.seed('thor').talks.length, 1);                                                          // seed handed out as a copy
assert.equal(T.seed('verma'), null);
T.load(null, 'thor').then(r => { assert.equal(r.where, 'starting set'); assert.equal(r.lib.talks.length, 1); });
const html = T._talkHtml({ id: 'a', status: 'draft', title: '<i>x</i>', takeaways: ['t1'], notes_for_thor: 'Check this.' }, 0, true);
assert.ok(html.includes('Approve this talk') && html.includes('&lt;i&gt;') && html.includes('Check this.'));
assert.ok(!T._talkHtml({ id: 'a', status: 'draft', title: 'x' }, 0, false).includes('Approve this talk'));

console.log('Sessionize link, pop-up block, drafts, email reading, matching, stage rules and talk library passed.');
