// Talk library (Hurley 2026-10-16): each speaker's standard talks, which the
// Sessionize drafter (api/sessionize.py) tailors to every call for speakers.
//
// The starting set ships with the code (config/talks/<person>.json, embedded by
// build.py as window.AB_TALK_SEEDS). The first edit or approval saves the whole
// library to Supabase storage at profiles/<person>/talks/library.json, and from
// then on that saved copy is the library: the drafter reads it too.
//
// Every talk starts as "draft" and the drafter flags any application built on
// an unapproved talk, so nothing goes out on a talk the speaker hasn't signed
// off. An edit by anyone other than the speaker sends an approved talk back to
// draft for the same reason.
//
// Set window.AB_TALKS_DRY_RUN = true to edit without saving (testing).
(function () {
  'use strict';
  var root = (typeof window !== 'undefined') ? window : globalThis;
  var BUCKET = 'profiles';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function path(person) { return person + '/talks/library.json'; }
  function seed(person) { var s = (root.AB_TALK_SEEDS || {})[person]; return s ? clone(s) : null; }
  function people() { return Object.keys(root.AB_TALK_SEEDS || {}); }
  function niceDate(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    if (!m) return '';
    return (+m[3]) + ' ' + ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][+m[2] - 1];
  }
  function first(name) { return String(name || '').trim().split(/\s+/)[0] || ''; }
  function slug(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'talk';
  }

  // The saved copy if there is one, else the starting set: {lib, where}.
  function load(sb, person) {
    var fallback = function () { var s = seed(person); return { lib: s, where: s ? 'starting set' : '' }; };
    if (!sb || !sb.storage) return Promise.resolve(fallback());
    return sb.storage.from(BUCKET).download(path(person)).then(function (r) {
      if (!r || r.error || !r.data) return fallback();
      return r.data.text().then(function (txt) {
        try {
          var lib = JSON.parse(txt);
          if (lib && lib.talks && lib.talks.length) return { lib: lib, where: 'saved' };
        } catch (e) { /* unreadable saved copy: show the starting set */ }
        return fallback();
      });
    }, fallback);
  }

  function save(sb, person, lib, who) {
    lib.saved_by = who || '';
    lib.saved_at = new Date().toISOString();
    if (root.AB_TALKS_DRY_RUN) {
      if (root.console) console.log('AB_TALKS_DRY_RUN: would save', path(person), lib);
      return Promise.resolve({ dry: true });
    }
    var blob = new Blob([JSON.stringify(lib, null, 2)], { type: 'application/json' });
    return sb.storage.from(BUCKET).upload(path(person), blob, { upsert: true, cacheControl: '0', contentType: 'application/json' });
  }

  // ── Pure helpers (also used by the tests) ──────────────────────────────
  // An edit: the fields change; approval survives only the speaker's own edit.
  function applyEdit(talk, fields, who, person) {
    var t = clone(talk);
    Object.keys(fields).forEach(function (k) { t[k] = fields[k]; });
    t.edited_by = who || '';
    t.edited_at = new Date().toISOString();
    if (t.status === 'approved' && first(who).toLowerCase() !== person) {
      t.status = 'draft';
      t.approved_by = ''; t.approved_at = '';
    }
    return t;
  }
  function setStatus(talk, status, who) {
    var t = clone(talk);
    t.status = status;
    t.approved_by = status === 'approved' ? (who || '') : '';
    t.approved_at = status === 'approved' ? new Date().toISOString() : '';
    return t;
  }
  function lines(v) { return String(v || '').split('\n').map(function (s) { return s.trim(); }).filter(Boolean); }
  function readForm(form) {
    var get = function (n) { var el = form.querySelector('[name="' + n + '"]'); return el ? el.value : ''; };
    return {
      title: get('title').trim(),
      alt_titles: lines(get('alt_titles')),
      level: get('level').trim(),
      formats: get('formats').split(',').map(function (s) { return s.trim(); }).filter(Boolean),
      audience: get('audience').trim(),
      short_abstract: get('short_abstract').trim(),
      abstract: get('abstract').trim(),
      takeaways: lines(get('takeaways'))
    };
  }

  // ── Rendering ──────────────────────────────────────────────────────────
  function talkHtml(t, i, canApprove) {
    var approved = t.status === 'approved';
    var meta = [t.level, (t.formats || []).join(', ')].filter(Boolean).join(' · ');
    var who = approved && t.approved_by ? ' by ' + esc(first(t.approved_by)) + (t.approved_at ? ' ' + esc(niceDate(t.approved_at)) : '') : '';
    var read =
      (t.notes_for_thor ? '<p class="tl-note">' + esc(t.notes_for_thor) + '</p>' : '') +
      '<div class="tl-k">Short abstract <span class="tl-n">' + (t.short_abstract || '').length + ' characters</span></div><p class="tl-v">' + esc(t.short_abstract) + '</p>' +
      '<div class="tl-k">Abstract <span class="tl-n">' + (t.abstract || '').length + ' characters</span></div><div class="tl-v">' +
        (t.abstract || '').split(/\n+/).map(function (p) { return '<p>' + esc(p) + '</p>'; }).join('') + '</div>' +
      '<div class="tl-k">Takeaways</div><ol class="tl-v tl-take">' + (t.takeaways || []).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ol>' +
      (t.audience ? '<div class="tl-k">For</div><p class="tl-v">' + esc(t.audience) + '</p>' : '') +
      ((t.alt_titles || []).length ? '<div class="tl-k">Also titled</div><p class="tl-v">' + (t.alt_titles || []).map(esc).join('<br>') + '</p>' : '') +
      ((t.history || []).length ? '<div class="tl-k">Track record</div><p class="tl-v tl-small">' + (t.history || []).map(esc).join('<br>') + '</p>' : '') +
      ((t.sources || []).length ? '<div class="tl-k">Facts come from</div><p class="tl-v tl-small">' + (t.sources || []).map(esc).join('<br>') + '</p>' : '');
    var acts = '<div class="tl-actions">' +
      (canApprove
        ? (approved
            ? '<button type="button" class="sz-link" data-tl-status="draft" data-i="' + i + '">Move back to draft</button>'
            : '<button type="button" class="sz-btn sz-primary" data-tl-status="approved" data-i="' + i + '">Approve this talk</button>')
        : '') +
      '<button type="button" class="sz-btn" data-tl-edit="' + i + '">Edit</button>' +
      '<button type="button" class="sz-link tl-remove" data-tl-remove="' + i + '">Remove</button>' +
    '</div>';
    var form = '<form class="tl-form" data-i="' + i + '" hidden>' +
      '<label>Title<input name="title" value="' + esc(t.title) + '"></label>' +
      '<label>Short abstract <span class="tl-count" data-for="short_abstract"></span><textarea name="short_abstract" rows="4">' + esc(t.short_abstract) + '</textarea></label>' +
      '<label>Abstract <span class="tl-count" data-for="abstract"></span><textarea name="abstract" rows="10">' + esc(t.abstract) + '</textarea></label>' +
      '<label>Takeaways <span class="tl-hint">one per line</span><textarea name="takeaways" rows="4">' + esc((t.takeaways || []).join('\n')) + '</textarea></label>' +
      '<div class="tl-row"><label>Level<input name="level" value="' + esc(t.level) + '"></label>' +
      '<label>Formats <span class="tl-hint">comma-separated</span><input name="formats" value="' + esc((t.formats || []).join(', ')) + '"></label></div>' +
      '<label>For (audience)<input name="audience" value="' + esc(t.audience) + '"></label>' +
      '<label>Also titled <span class="tl-hint">one per line</span><textarea name="alt_titles" rows="2">' + esc((t.alt_titles || []).join('\n')) + '</textarea></label>' +
      '<div class="tl-actions"><button type="submit" class="sz-btn sz-primary">Save talk</button><button type="button" class="sz-link" data-tl-cancel>Cancel</button></div>' +
    '</form>';
    return '<details class="tl-talk" data-i="' + i + '">' +
      '<summary><span class="tl-title">' + esc(t.title || 'Untitled talk') + '</span>' +
        '<span class="tl-pill ' + (approved ? 'is-ok' : 'is-draft') + '">' + (approved ? 'Approved' + who : 'Draft') + '</span>' +
        (meta ? '<span class="tl-meta">' + esc(meta) + '</span>' : '') + '</summary>' +
      '<div class="tl-body"><div class="tl-read">' + read + acts + '</div>' + form + '</div>' +
    '</details>';
  }

  function summaryLine(lib, where, person) {
    var talks = lib.talks || [];
    var ok = talks.filter(function (t) { return t.status === 'approved'; }).length;
    var name = (lib.speaker && first(lib.speaker.name)) || (person.charAt(0).toUpperCase() + person.slice(1));
    var src = where === 'saved'
      ? 'Saved' + (lib.saved_by ? ' by ' + esc(first(lib.saved_by)) : '') + (lib.saved_at ? ' ' + esc(niceDate(lib.saved_at)) : '')
      : 'Starting set, not edited yet';
    return '<p class="tl-sum"><strong>' + ok + ' of ' + talks.length + ' approved.</strong> ' +
      (ok < talks.length ? 'Applications drafted from a talk ' + esc(name) + ' hasn’t approved are flagged. ' : '') +
      '<span class="tl-src">' + src + '.</span></p>';
  }

  // Render one person's library into host. opts: {sb, person, who, canApprove, status}
  function mount(host, opts) {
    if (!host) return;
    var person = opts.person, sb = opts.sb || root.sb;
    var state = { lib: null, where: '' };
    var say = opts.status || function () {};
    host.innerHTML = '<p class="tl-sum">Loading talks…</p>';

    function paint(openIdx) {
      var lib = state.lib;
      if (!lib) { host.innerHTML = '<p class="tl-sum">No talk library yet.</p>'; return; }
      host.innerHTML = summaryLine(lib, state.where, person) +
        '<div class="tl-list">' + (lib.talks || []).map(function (t, i) { return talkHtml(t, i, opts.canApprove); }).join('') + '</div>' +
        '<button type="button" class="sz-btn tl-add" data-tl-add>+ Add a talk</button>' +
        '<span class="tl-msg" aria-live="polite"></span>';
      if (openIdx != null) {
        var d = host.querySelector('.tl-talk[data-i="' + openIdx + '"]');
        if (d) d.open = true;
      }
      wire();
    }
    function msg(t, bad) {
      var m = host.querySelector('.tl-msg');
      if (m) { m.textContent = t; m.className = 'tl-msg' + (bad ? ' is-bad' : ''); }
    }
    function commit(next, openIdx, note) {
      var prev = state.lib;
      state.lib = next;
      // One save at a time: each save writes the whole library, so a second
      // click landing before the first save finished could be overwritten.
      host.querySelectorAll('button, input, textarea').forEach(function (el) { el.disabled = true; });
      msg('Saving…');
      return Promise.resolve(save(sb, person, next, opts.who)).then(function (r) {
        if (r && r.error) {
          state.lib = prev; paint(openIdx);
          msg('Could not save: ' + r.error.message, true);
          say('Could not save the talk library: ' + r.error.message, 'error');
          return;
        }
        if (!(r && r.dry)) state.where = 'saved';
        paint(openIdx);
        msg(r && r.dry ? note + ' (test mode: not saved)' : note);
      }, function (e) {
        state.lib = prev; paint(openIdx);
        msg('Could not save: ' + (e && e.message || e), true);
      });
    }
    function counts(form) {
      form.querySelectorAll('.tl-count').forEach(function (c) {
        var ta = form.querySelector('[name="' + c.getAttribute('data-for') + '"]');
        var upd = function () { c.textContent = ta.value.length + ' characters'; };
        ta.addEventListener('input', upd); upd();
      });
    }
    function wire() {
      host.querySelectorAll('[data-tl-status]').forEach(function (b) {
        b.addEventListener('click', function () {
          var i = +b.getAttribute('data-i'), next = clone(state.lib);
          var to = b.getAttribute('data-tl-status');
          next.talks[i] = setStatus(next.talks[i], to, opts.who);
          commit(next, i, to === 'approved' ? 'Approved.' : 'Moved back to draft.');
        });
      });
      host.querySelectorAll('[data-tl-edit]').forEach(function (b) {
        b.addEventListener('click', function () {
          var i = b.getAttribute('data-tl-edit');
          var box = host.querySelector('.tl-talk[data-i="' + i + '"]');
          box.querySelector('.tl-read').hidden = true;
          var f = box.querySelector('.tl-form'); f.hidden = false; counts(f);
          var t = f.querySelector('[name=title]'); if (t) t.focus();
        });
      });
      host.querySelectorAll('[data-tl-cancel]').forEach(function (b) {
        b.addEventListener('click', function () { paint(+b.closest('.tl-form').getAttribute('data-i')); });
      });
      host.querySelectorAll('.tl-form').forEach(function (f) {
        f.addEventListener('submit', function (e) {
          e.preventDefault();
          var i = +f.getAttribute('data-i'), fields = readForm(f);
          if (!fields.title) { msg('A talk needs a title.', true); return; }
          var next = clone(state.lib);
          var was = next.talks[i].status;
          next.talks[i] = applyEdit(next.talks[i], fields, opts.who, person);
          commit(next, i, (was === 'approved' && next.talks[i].status !== 'approved')
            ? 'Saved. Back to draft: ' + (first(next.speaker && next.speaker.name) || person) + ' approves it again.'
            : 'Saved.');
        });
      });
      host.querySelectorAll('[data-tl-remove]').forEach(function (b) {
        b.addEventListener('click', function () {
          var i = +b.getAttribute('data-tl-remove'), t = state.lib.talks[i];
          if (!root.confirm || !root.confirm('Remove “' + (t.title || 'this talk') + '” from the library?')) return;
          var next = clone(state.lib);
          next.talks.splice(i, 1);
          commit(next, null, 'Removed.');
        });
      });
      var add = host.querySelector('[data-tl-add]');
      if (add) add.addEventListener('click', function () {
        var next = clone(state.lib);
        var ids = {}; next.talks.forEach(function (t) { ids[t.id] = 1; });
        var id = slug('new talk'), n = 2;
        while (ids[id]) id = slug('new talk') + '-' + (n++);
        next.talks.push({ id: id, status: 'draft', title: 'New talk', alt_titles: [], level: '', formats: [],
          audience: '', short_abstract: '', abstract: '', takeaways: [], history: [], sources: [],
          edited_by: opts.who || '', edited_at: new Date().toISOString() });
        state.lib = next;
        paint(next.talks.length - 1);
        var b = host.querySelector('[data-tl-edit="' + (next.talks.length - 1) + '"]');
        if (b) b.click();
        msg('Fill it in and press Save talk.');
      });
    }

    load(sb, person).then(function (r) { state.lib = r.lib; state.where = r.where; paint(null); },
      function () { state.lib = seed(person); state.where = 'starting set'; paint(null); });
  }

  root.ABTalks = { people: people, seed: seed, load: load, save: save, mount: mount,
    applyEdit: applyEdit, setStatus: setStatus, readForm: readForm, _talkHtml: talkHtml };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.ABTalks;
})();
