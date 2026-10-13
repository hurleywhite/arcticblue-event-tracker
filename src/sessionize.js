// Sessionize support for the tracker (Hurley 2026-10-13).
//
// Sessionize gives speakers no API: applying always happens on sessionize.com,
// signed in. So the tracker does the three things that ARE possible:
//   1. an "Apply on Sessionize" block in the event pop-up, with the call's
//      open / close dates read from the public page, and one click to record
//      that the application went in;
//   2. a daily server check of the speaker's public profile for acceptances
//      (api/sessionize.py, nothing to do here);
//   3. pasting a Sessionize email (accepted / not selected / waitlisted /
//      received) updates the matching event, after you confirm the match.
// Everything here is plain DOM + the tracker's own root.opsWrite.
(function () {
  'use strict';
  // `root` is the page's window; under node (the tests) it is the global object.
  var root = (typeof window !== 'undefined') ? window : globalThis;
  var LINK = /https?:\/\/(?:www\.)?sessionize\.com\/[^\s)"'<>\]]+/i;
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function today() {
    var d = new Date();
    return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
  }
  function nice(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    return m ? (+m[3]) + ' ' + MONTHS[+m[2] - 1] + ' ' + m[1] : '';
  }
  function daysUntil(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    if (!m) return null;
    return Math.round((Date.UTC(+m[1], +m[2] - 1, +m[3]) - Date.parse(today() + 'T00:00:00Z')) / 86400000);
  }

  // The event's Sessionize call-for-speakers link, wherever it was typed:
  // the apply link first, then the speaking route, the website and the notes.
  function link(rec) {
    if (!rec) return '';
    var fields = [rec.apply_url, rec.speaking_route, rec.url, rec.notes];
    for (var i = 0; i < fields.length; i++) {
      var m = LINK.exec(String(fields[i] || ''));
      // Only an event page: sessionize.com/<event>/ - not the app or a help page.
      if (m && !/sessionize\.com\/(app|api|playbook|s|view)\b/i.test(m[0])) return m[0].replace(/[.,;:!?]+$/, '');
    }
    return '';
  }
  function isApplied(rec) { return (rec.stage_tags || []).indexOf('Submitted') !== -1; }

  // ── 1. The block in the event pop-up ────────────────────────────────────
  function blockHtml(rec) {
    var url = link(rec);
    if (!url) return '';
    var who = String(rec.speaker || '').trim();
    var on = (/^\d{4}-\d{2}-\d{2}/.exec(String(rec.submitted_at || '')) || [''])[0];
    var track = isApplied(rec)
      ? '<span class="sz-done">✓ Applied' + (on ? ' ' + esc(nice(on)) : '') + (who ? ' · ' + esc(who) : '') + '</span>' +
        '<button type="button" class="sz-link" data-sz-open>Change</button>'
      : '<button type="button" class="sz-btn" data-sz-open>I’ve applied — record it</button>';
    return '<div class="me-apply sz-box" data-sz-url="' + esc(url) + '">' +
      '<div class="sz-row">' +
        '<a class="modal-visit modal-apply" href="' + esc(url) + '" target="_blank" rel="noopener">Apply on Sessionize ↗</a>' +
        '<span class="sz-cfp" aria-live="polite">Checking the call for speakers…</span>' +
      '</div>' +
      '<div class="sz-row sz-track">' + track + '</div>' +
      '<form class="sz-form" hidden>' +
        '<label>Speaker<input name="speaker" value="' + esc(who || 'Thor') + '" autocomplete="off"></label>' +
        '<label class="sz-wide">Talk submitted<input name="topic" value="' + esc(rec.speaker_topic || '') + '" placeholder="Title of the talk" autocomplete="off"></label>' +
        '<label>Applied on<input type="date" name="date" value="' + esc(on || today()) + '"></label>' +
        '<div class="sz-actions"><button type="submit" class="sz-btn sz-primary">Record application</button>' +
        '<button type="button" class="sz-link" data-sz-cancel>Cancel</button></div>' +
      '</form>' +
    '</div>';
  }

  // What the public page said -> one plain line (and, for an open call whose
  // closing date the tracker does not have, an offer to save it).
  function cfpLine(info, rec) {
    if (!info || !info.ok) return { html: 'Couldn’t read that Sessionize page.', cls: 'sz-muted' };
    var closes = nice(info.closes), opens = nice(info.opens), left = daysUntil(info.closes);
    var tz = info.timezone ? ' (' + esc(info.timezone.replace(/\s*\(UTC[^)]*\)/, '')) + ')' : '';
    if (info.status === 'closed') {
      return { html: 'Call for speakers closed' + (closes ? ' ' + esc(closes) : '') + '.', cls: 'sz-muted' };
    }
    if (info.status === 'not_open_yet') {
      return { html: 'Call for speakers opens ' + esc(opens) + (closes ? ', closes ' + esc(closes) : '') + '.', cls: '' };
    }
    if (info.status === 'open') {
      var soon = left != null && left <= 14;
      var txt = 'Call for speakers is open' + (closes ? ' · closes ' + esc(closes) + tz : '') +
        (soon ? ' · ' + (left <= 0 ? 'last day' : left + (left === 1 ? ' day' : ' days') + ' left') : '') + '.';
      var have = String(rec.deadline || '');
      var offer = (info.closes && have.indexOf(info.closes) === -1 && have.indexOf(closes) === -1)
        ? ' <button type="button" class="sz-link" data-sz-deadline="' + esc(info.closes) + '">Save as CFP deadline</button>' : '';
      return { html: txt + offer, cls: soon ? 'sz-warn' : 'sz-ok' };
    }
    return { html: 'Call for speakers page found; no dates listed.', cls: 'sz-muted' };
  }

  function wire(body, rec) {
    var box = body && body.querySelector ? body.querySelector('.sz-box') : null;
    if (!box) return;
    var url = box.getAttribute('data-sz-url');
    var form = box.querySelector('.sz-form');
    var line = box.querySelector('.sz-cfp');

    function redraw() {
      var tmp = document.createElement('div');
      tmp.innerHTML = blockHtml(rec);
      if (tmp.firstChild && box.parentNode) { box.parentNode.replaceChild(tmp.firstChild, box); wire(body, rec); }
    }

    fetch('/api/sessionize?cfp=' + encodeURIComponent(url))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (info) {
        if (!line.isConnected) return;                 // the pop-up moved on
        if (!info) { line.textContent = ''; return; }  // no server here (local preview): say nothing
        var out = cfpLine(info, rec);
        line.className = 'sz-cfp ' + out.cls;
        line.innerHTML = out.html;
        var save = line.querySelector('[data-sz-deadline]');
        if (save) save.addEventListener('click', function () {
          var iso = save.getAttribute('data-sz-deadline');
          rec.deadline = iso;
          if (root.opsWrite) root.opsWrite(rec._table, rec._key, { deadline: iso });
          save.outerHTML = '<span class="sz-done">✓ Deadline saved</span>';
        });
      })
      .catch(function () { if (line.isConnected) line.textContent = ''; });

    var open = box.querySelector('[data-sz-open]');
    if (open) open.addEventListener('click', function () {
      form.hidden = !form.hidden;
      if (!form.hidden) { var t = form.querySelector('[name=topic]'); if (t && !t.value) t.focus(); }
    });
    var cancel = box.querySelector('[data-sz-cancel]');
    if (cancel) cancel.addEventListener('click', function () { form.hidden = true; });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!root.opsWrite) return;
      var speaker = form.speaker.value.trim(), topic = form.topic.value.trim();
      var date = /^\d{4}-\d{2}-\d{2}$/.test(form.date.value) ? form.date.value : today();
      var patch = { submitted_at: date };
      rec.submitted_at = date;
      if (!isApplied(rec)) {
        // The tracker's own rule for turning a stage on, so this click and the
        // Submitted button can never disagree about what "applied" sets.
        patch.status_tags = root.abApplyStageToggle
          ? root.abApplyStageToggle(rec, 'Submitted').tags
          : (rec.stage_tags = (rec.stage_tags || []).concat(['Submitted']));
      }
      if (speaker) { patch.speaker = speaker; rec.speaker = speaker; }
      if (topic) { patch.speaker_topic = topic; rec.speaker_topic = topic; }
      // Keep the link where the tracker's Apply button looks for it, unless a
      // different apply link was already saved there on purpose.
      if (!String(rec.apply_url || '').trim()) { patch.apply_url = url; rec.apply_url = url; }
      root.opsWrite(rec._table, rec._key, patch);
      if (root.abRepaintStages) { try { root.abRepaintStages(rec); } catch (err) {} }
      redraw();
      if (root.opsRefresh) root.opsRefresh();
    });
  }

  // ── 3. Pasting a Sessionize email ───────────────────────────────────────
  var OUTCOMES = {
    accepted:   { label: 'Accepted', stage: 'Booked',    note: 'Accepted' },
    declined:   { label: 'Not selected', stage: 'Rejected', note: 'Not selected' },
    waitlisted: { label: 'Waitlisted', stage: '',         note: 'Waitlisted' },
    submitted:  { label: 'Application received', stage: 'Submitted', note: 'Application received' }
  };
  // Organisers write their own wording, so these are the phrases that recur,
  // checked most-specific first: a refusal usually contains the word "accepted".
  var SIGNS = [
    ['declined', /\b(?:not|n[o’']t|unable to|cannot|can[’']t)\s+(?:be(?:en)?\s+)?(?:accept|select|includ|offer|accommodat)\w*|\bwas(?:n[’']t| not)\s+(?:chosen|picked|successful)|\b(?:declined|unsuccessful|regret to|regretfully|we regret|unfortunately)\b|\bdid(?:n[’']t| not) make (?:it|the)\b/i],
    ['waitlisted', /\bwait[\s-]?list(?:ed)?\b|\breserve list\b|\bbackup speaker\b/i],
    ['accepted', /\b(?:has|have|had|was|were|been|is|are)\s+(?:been\s+)?(?:accepted|selected|approved|chosen)\b|\bcongratulations\b|\b(?:pleased|happy|delighted|excited|thrilled) to (?:inform|let you know|tell you|announce|confirm|invite)\b|\bwe(?:’d|'d| would) love to have you\b|\bconfirm your participation\b/i],
    ['submitted', /\b(?:successfully\s+)?submitted\b|\bsubmission (?:has been )?(?:received|confirmed)\b|\bthank you for (?:your )?(?:submission|submitting)\b|\bwe(?:’ve| have) received your\b/i]
  ];

  function parseEmail(text) {
    text = String(text || '');
    if (!/sessionize/i.test(text)) return null;       // not from Sessionize: leave it to the normal extractor
    for (var i = 0; i < SIGNS.length; i++) {
      var m = SIGNS[i][1].exec(text);
      if (m) {
        var from = Math.max(0, m.index - 60), to = Math.min(text.length, m.index + m[0].length + 80);
        return { outcome: SIGNS[i][0], evidence: text.slice(from, to).replace(/\s+/g, ' ').trim() };
      }
    }
    return { outcome: '', evidence: '' };             // Sessionize, but no verdict we recognise
  }

  var FILLER = { the: 1, a: 1, an: 1, and: 1, of: 1, 'for': 1, at: 1, 'in': 1, on: 1, by: 1, to: 1 };
  function tokens(s) {
    return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
      .replace(/\b(?:19|20)\d{2}\b/g, ' ').replace(/[^a-z0-9]+/g, ' ').split(' ')
      .filter(function (w) { return w && !FILLER[w]; });
  }
  // How much of an event's name appears in the email (0..1). Whole words only.
  function nameScore(name, textSet) {
    var t = tokens(name);
    if (!t.length) return 0;
    var hit = t.filter(function (w) { return textSet[w]; }).length;
    if (t.length === 1) return (hit && t[0].length >= 6) ? 0.7 : 0;   // one short word proves nothing
    return hit / t.length;
  }
  // Events the email could be about, best first. Applications still in flight
  // come before everything else, because that is what such an email answers.
  function rankItems(text, items) {
    var set = {};
    tokens(text).forEach(function (w) { set[w] = 1; });
    return (items || []).map(function (it) {
      var st = it.stages || [];
      var live = st.indexOf('Submitted') !== -1 && st.indexOf('Booked') === -1 && st.indexOf('Rejected') === -1;
      return { item: it, score: nameScore(it.name, set), live: live };
    }).filter(function (x) { return x.score >= 0.6 || x.live; })
      .sort(function (a, b) {
        return (b.score - a.score) || ((b.live ? 1 : 0) - (a.live ? 1 : 0)) || String(a.item.name).localeCompare(String(b.item.name));
      });
  }

  function withStage(tags, stage) {
    tags = (tags || []).slice();
    if (!stage) return tags;
    if (stage === 'Booked' || stage === 'Rejected') {
      // An outcome ends the application: the other outcome and the in-flight
      // steps retire; Submitted stays as the record (the tracker's own rule).
      tags = tags.filter(function (t) { return ['Booked', 'Rejected', 'Initial outreach', 'Followed up'].indexOf(t) === -1; });
    }
    if (tags.indexOf(stage) === -1) tags.push(stage);
    return root.abStageImply ? root.abStageImply(tags) : tags;
  }

  // Returns true when the text was a Sessionize email and this took over.
  function handlePaste(text, host, deps) {
    var hit = parseEmail(text);
    if (!hit) return false;
    var ranked = rankItems(text, deps.items());
    var old = host.parentNode.querySelector('.sz-email');
    if (old) old.remove();
    var panel = document.createElement('div');
    panel.className = 'sz-email';
    var best = ranked.length && ranked[0].score >= 0.75 ? ranked[0] : null;
    var opts = ranked.slice(0, 40).map(function (r, i) {
      var it = r.item;
      return '<option value="' + i + '"' + (best && i === 0 ? ' selected' : '') + '>' + esc(it.name) +
        (it.date_str ? ' · ' + esc(it.date_str) : '') + (it.speaker ? ' · ' + esc(it.speaker) : '') + '</option>';
    }).join('');
    var outs = Object.keys(OUTCOMES).map(function (k) {
      return '<option value="' + k + '"' + (k === hit.outcome ? ' selected' : '') + '>' + esc(OUTCOMES[k].label) + '</option>';
    }).join('');
    panel.innerHTML =
      '<p class="sz-email-h">This looks like a Sessionize email.</p>' +
      (hit.evidence ? '<p class="sz-email-q">“…' + esc(hit.evidence) + '…”</p>' : '') +
      (ranked.length
        ? '<label>What it says<select data-sz-outcome>' + (hit.outcome ? '' : '<option value="" selected>Choose…</option>') + outs + '</select></label>' +
          '<label>Which event<select data-sz-event>' + (best ? '' : '<option value="" selected>Choose the event…</option>') + opts + '</select></label>' +
          '<div class="sz-actions"><button type="button" class="sz-btn sz-primary" data-sz-apply>Update the tracker</button>' +
          '<span class="sz-email-msg" aria-live="polite"></span></div>'
        : '<p class="sz-email-msg">No application in the tracker matches it. Add the event first, then paste the email again.</p>');
    host.textContent = '';
    host.parentNode.insertBefore(panel, host.nextSibling);
    var go = panel.querySelector('[data-sz-apply]');
    if (go) go.addEventListener('click', function () {
      var msg = panel.querySelector('.sz-email-msg');
      var ok = OUTCOMES[panel.querySelector('[data-sz-outcome]').value];
      var pick = ranked[+panel.querySelector('[data-sz-event]').value];
      var chosen = panel.querySelector('[data-sz-event]').value;
      if (!ok || chosen === '' || !pick) { msg.textContent = 'Choose what it says and which event.'; return; }
      var it = pick.item, tags = withStage(it.stages, ok.stage);
      var noteLine = ok.note + ' (Sessionize email, recorded ' + today() + ')';
      var notes = String(it.notes || '').replace(/\s+$/, '');
      var patch = { status_tags: tags, notes: (notes ? notes + '\n' : '') + noteLine };
      go.disabled = true;
      Promise.resolve(deps.write(it.kind === 'manual' ? 'manual_events' : 'event_state', it.key, patch)).then(function (resp) {
        if (resp && resp.error) { go.disabled = false; msg.textContent = 'Save failed: ' + resp.error.message; return; }
        panel.innerHTML = '<p class="sz-email-h">✓ ' + esc(it.name) + ': ' + esc(ok.label) +
          (ok.stage ? ' — marked ' + esc(ok.stage) : ' — noted, stage unchanged') + '.</p>';
        if (deps.done) deps.done(it);
      });
    });
    return true;
  }

  root.ABSessionize = { link: link, blockHtml: blockHtml, wire: wire, parseEmail: parseEmail,
    rankItems: rankItems, withStage: withStage, handlePaste: handlePaste, _cfpLine: cfpLine };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.ABSessionize;
})();
