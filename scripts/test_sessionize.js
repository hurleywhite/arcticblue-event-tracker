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
console.log('Sessionize link, pop-up block, email reading, matching and stage rules passed.');
