/* Shared booking rules. No network or UI dependencies.

   Two layers of truth, in this order:
     1. A booking decision someone typed (booking.action/owner/due/next_action/reason).
     2. What the record already says on its own — a real application, a booked
        slot, a confirmed attendance, a live deadline. These DERIVE a default
        action so the Action Center is populated from day one instead of
        opening on five zeros and eighty-five "Decide" buttons (Hurley 2026-09-10).
   A typed decision always wins over a derived one. Derived rows carry
   `derived:true` so the UI can say so.
*/
(function(root) {
  'use strict';
  const STATES = ['Apply','Outreach','Book Meetings','Attend','Stack Trip','Pass'];
  const PEOPLE = ['thor','verma','jerome','carlos'];
  const fold = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
  const day = d => /^\d{4}-\d{2}-\d{2}$/.test(d || '') && !isNaN(Date.parse(d)) && new Date(d).toISOString().slice(0,10)===d ? d : '';
  const plus = (d,n) => new Date(Date.parse(d+'T12:00:00Z')+n*86400000).toISOString().slice(0,10);
  const diff = (a,b) => Math.round((Date.parse(b+'T12:00:00Z')-Date.parse(a+'T12:00:00Z'))/86400000);
  const safeUrl = s => { try { const u=new URL(s); return ['http:','https:'].includes(u.protocol) ? u.href : ''; } catch(e) { return ''; } };
  const first = s => fold(s).split(/[\s,]+/)[0] || '';
  const weight = {end_user_speakers:20,audience_breakdown:30,advisory_board:10,prior_attendees:15,sponsors:5,public_attendance:20,company_event_page:20,organizer_claim:10};

  // ── Where is it? ────────────────────────────────────────────────────
  // Locations arrive as "Hynes Convention Center, Boston, MA" or "22 Bishopsgate"
  // or "Munich". The city is the LAST segment that isn't a country/state and
  // isn't a venue. Falling back to a venue-looking segment is deliberate:
  // "22 Bishopsgate" alone can't be placed and returns ''.
  const REGION = /^(usa|us|u\.s\.a?|united states|uk|u\.k\.|united kingdom|england|scotland|germany|france|spain|italy|greece|netherlands|the netherlands|portugal|switzerland|belgium|luxembourg|austria|ireland|sweden|denmark|norway|finland|poland|czech republic|hungary|romania|lithuania|estonia|latvia|uae|united arab emirates|saudi arabia|saudi|ksa|qatar|bahrain|oman|kuwait|egypt|morocco|singapore|japan|india|china|hong kong|sar|taiwan|south korea|korea|thailand|malaysia|indonesia|vietnam|philippines|australia|new zealand|canada|mexico|brazil|argentina|colombia|chile|peru|uruguay|ecuador|dominican republic|puerto rico|panama|costa rica|guatemala|turkey|türkiye|south africa|nigeria|ghana|kenya|rwanda|israel|[a-z]{2})$/;
  const VENUE = /\b(center|centre|hotel|hall|convention|arena|resort|expo|palais|brewery|olympia|venetian|javits|hynes|bishopsgate|aldersgate|convene|westin|hyatt|sofitel|marriott|hilton|sheraton|ritz|carlton|waldorf|mandalay|moscone|excel|rds|society|estate|winery|campus|street|st\.|avenue|ave\.|road|rd\.|suite|floor|room|club|stadium|theatre|theater|museum|university|college|school|event park|business park|rai|jw|kongresshaus|kongress|messe|exhibition)\b|^\d/;
  const ALIAS = {'nyc':'new york','new york city':'new york','manhattan':'new york','brooklyn':'new york','jersey city':'new york','hoboken':'new york','münchen':'munich','munchen':'munich','sao paulo':'sao paulo','são paulo':'sao paulo','santiago de chile':'santiago','washington dc':'washington','washington d.c.':'washington','d.c.':'washington','dc':'washington','national harbor':'washington','arlington':'washington','burlingame':'san francisco','santa clara':'san francisco','san jose':'san francisco','dana point':'los angeles','anaheim':'los angeles','irving':'dallas','disney springs':'orlando','lake buena vista':'orlando','multiple':'','various':'','tbc':''};
  // The city is the last comma segment that is neither a country/state nor a
  // venue. If only a venue-looking segment survives ("ExCeL London", "JW
  // Marriott Nashville") the venue words are stripped and a single remaining
  // word is accepted; "22 Bishopsgate" alone still returns ''.
  function cityOf(r) {
    if (r && r.city) { const c=fold(r.city); if (c in ALIAS) return ALIAS[c]; if (!VENUE.test(c)) return c; }
    const loc = fold(r && (r.location || r.loc) || '');
    if (!loc || /^(unknown|tbd|tbc|online|remote|virtual|multiple|various)$/.test(loc)) return '';
    const parts = loc.split(/[,;|·]/).map(s=>s.replace(/\(.*?\)/g,'').trim()).filter(Boolean);
    // Drop trailing country/state segments, but never the first one: "Singapore,
    // Singapore" and "Hong Kong, SAR" are cities whose names are also countries.
    const place = parts.slice();
    while (place.length>1 && REGION.test(place[place.length-1])) place.pop();
    const cities = place.filter(p=>!VENUE.test(p));
    let c = cities.length>=2 ? cities[cities.length-2] : (cities[0] || '');
    if (!c && parts.length>1) {
      const rest = place[place.length-1].replace(new RegExp(VENUE.source,'g'),'').replace(/[^a-z ]/g,' ').trim().split(/\s+/).filter(w=>w.length>=4);
      if (rest.length===1) c = rest[0];
    }
    return c in ALIAS ? ALIAS[c] : c;
  }
  function sameCity(a,b) {
    const ca = typeof a === 'string' ? cityOf({location:a}) : cityOf(a);
    const cb = typeof b === 'string' ? cityOf({location:b}) : cityOf(b);
    return !!ca && ca === cb;
  }

  function qualify(r,today) {
    const b=r.booking || {}, seen=new Set();
    const evidence=(b.evidence || []).filter(e => weight[e.kind] && safeUrl(e.url) && e.note && day(e.checked) && e.checked<=today && e.checked>=plus(today,-365));
    let score=0;
    evidence.forEach(e=>{if(!seen.has(e.kind)){score+=weight[e.kind];seen.add(e.kind);}});
    score=Math.min(score,100);
    const excluded=!!b.exclusion || /african internet governance|afigf|chief ai officer summit boston/i.test(r.name || '');
    return {score: evidence.length ? score : null, evidence, excluded, strong: score>=40 && b.buyer_fit==='strong', label: !evidence.length ? 'Buyer evidence unknown' : score>=60 ? 'Strong buyer evidence' : score>=30 ? 'Some buyer evidence' : 'Limited buyer evidence'};
  }

  // Is there any sign a human actually applied? A bare "Submitted" tag with
  // no date, no chase, no contact and no note is a legacy import stamp — 26
  // of them were feeding "follow-ups due" with events nobody applied to.
  function applicationEvidence(r) {
    const b=r.booking || {};
    const out=[];
    if (day(r.submitted_at) || day(b.submitted_at)) out.push('date');
    if ((r.follow_ups || []).length) out.push('chased');
    if (r.poc_email || r.poc_name || r.contact_info) out.push('contact');
    if (/submit|applied|application|proposal|cfp|pitch/i.test(r.notes || '')) out.push('notes');
    return out;
  }

  function normalize(r,op,today) {
    const b=r.booking || {}, q=qualify(r,today), tags=r.status_tags || [];
    const evidence=applicationEvidence(r);
    const submittedDate=day(r.submitted_at) || day(b.submitted_at);
    const submitted=submittedDate || (tags.includes('Submitted') ? (evidence.length ? 'recorded' : 'tag-only') : '');
    const realApplication=!!submittedDate || (submitted==='recorded');
    const booked=tags.includes('Booked') || !!b.speaking_booked_at;
    const attending=tags.includes('Attending') || (r.attendees || []).length>0;
    const rejected=tags.includes('Rejected') || r.decision==='Reject';
    const completed=!!b.completed_at;
    const start=day(r.start_date), end=day(r.end_date)||start;
    const past=!!(end && end<today);
    const deadline=day(r.deadline);
    const owner=fold(b.owner) || (op && fold(op.owner_person)) || first(r.speaker) || first((r.attendees || [])[0]) || first((r.outreach_assignees || [])[0]) || '';
    const sleeping=!!b.recheck_on && b.recheck_on>today;
    const wake=!!day(b.recheck_on) && b.recheck_on<=today;
    const priorFollowups=(r.follow_ups || []).map(f=>day(f.date || f.sent_at || f.at)).filter(Boolean).sort();
    const lastFollowup=priorFollowups[priorFollowups.length-1];
    const followup=day(b.follow_up_due) || (realApplication && !b.organizer_reply_at && !booked && !attending && !rejected ? plus(lastFollowup || submittedDate || today,7) : '');

    // 1. typed decision
    let action=STATES.includes(b.action) ? b.action : '';
    let due=day(b.due), next=b.next_action || '', reason=b.reason || '', derived=false;
    // 2. derived from the record itself
    if(!action && !sleeping && !past && !r.hidden && !completed) {
      if (rejected) { action='Pass'; reason=reason||'Organiser declined'; }
      else if (booked) { action='Attend'; derived=true; due=due||start; next=next||'Confirm logistics, prep the talk, book buyer meetings around it'; reason=reason||'Speaking slot booked'; }
      else if (attending) { action='Attend'; derived=true; due=due||start; next=next||'Confirm travel and book buyer meetings around it'; reason=reason||'Marked attending'; }
      else if (realApplication) { action='Outreach'; derived=true; due=due||followup||plus(today,7); next=next||(b.organizer_reply_at?'Organiser replied — get to a decision':'Chase the organiser for a decision'); reason=reason||('Application on record ('+evidence.join(', ')+')'); }
      else if (deadline && deadline>=today && diff(today,deadline)<=45 && owner && PEOPLE.includes(owner)) { action='Apply'; derived=true; due=due||deadline; next=next||'Decide whether to apply — deadline '+deadline; reason=reason||'Deadline inside 45 days'; }
    }
    const active=!!action && action!=='Pass' && !!owner && !!next && !!due && !!reason && !sleeping && !past && !r.hidden && !completed;
    const working=!r.hidden && !past && !sleeping && action!=='Pass' && !completed;
    const needsDecision=working && !active && (wake || !!action || realApplication || !!booked || !!attending || q.strong || !!(op && ['apply_now','reach_out','conflicts'].includes(op.queue_stage)));
    let recommendation=action;
    if(!recommendation) {
      if(q.excluded) recommendation='Pass';
      else if(q.strong && b.speaking_quality==='earned' && safeUrl(r.apply_url)) recommendation='Apply';
      else if(q.strong) recommendation=r.poc_name || r.contact_info ? 'Outreach' : 'Book Meetings';
      else if(op && op.queue_stage==='apply_now') recommendation='Apply';
      else if(op && op.queue_stage==='reach_out') recommendation='Outreach';
    }
    return {...r,suggestedNextAction:op?.next_action||next||'',suggestedReason:op?.rationale||reason||'',b:{...b,next_action:b.next_action||next,reason:b.reason||reason},q,owner,due,action,recommendation,derived,submitted,realApplication,evidence,booked,attending,rejected,followup,past,active,needsDecision,sleeping,wake,completed,city:cityOf(r),start,end};
  }

  function groups(rows,today) {
    const active=rows.filter(r=>r.active), soon=plus(today,7);
    return {
      applications:active.filter(r=>r.action==='Apply' && !r.realApplication && r.due<=soon),
      contacts:active.filter(r=>r.action==='Outreach' && !(r.followup && r.followup<=today)),
      meetings:active.filter(r=>r.action==='Book Meetings'),
      followups:rows.filter(r=>!r.hidden && !r.past && !r.sleeping && !r.completed && r.action!=='Pass' && r.realApplication && r.followup && r.followup<=today && !r.booked && !r.attending),
      decisions:rows.filter(r=>r.needsDecision)
    };
  }

  // ── The real calendar: what people are actually going to ────────────
  // Booked or Attending only. Applications are wishes, and clashes between
  // wishes are normal (57 out for Thor); they matter once one is accepted.
  function agenda(rows,today) {
    const per={};
    PEOPLE.forEach(p=>per[p]=[]);
    rows.forEach(r=>{
      if(r.past || r.hidden || !r.start) return;
      const names=new Set();
      if(r.booked) String(r.speaker||'').split(/[,&/]+/).map(first).filter(Boolean).forEach(n=>names.add(n));
      if(r.attending) { const att=(r.attendees||[]).map(first).filter(Boolean); (att.length?att:[r.owner]).filter(Boolean).forEach(n=>names.add(n)); }
      names.forEach(n=>{ if(per[n]) per[n].push({...r, why: r.booked && String(r.speaker||'').toLowerCase().includes(n) ? 'Speaking' : 'Attending'}); });
    });
    const overlap=(a,b)=>a.start<=b.end && b.start<=a.end;
    const near=(a,b)=>Math.abs(diff(a.start,b.start))<=4;
    const out={people:{},cross:[]};
    PEOPLE.forEach(p=>{
      const list=per[p].sort((a,b)=>a.start.localeCompare(b.start));
      const clashes=[], stacks=[];
      for(let i=0;i<list.length;i++) for(let j=i+1;j<list.length;j++){
        const a=list[i], b=list[j];
        if(overlap(a,b)) clashes.push([a,b]);
        else if(a.city && a.city===b.city && near(a,b)) stacks.push([a,b]);
      }
      out.people[p]={list,clashes,stacks};
    });
    const all=[];
    PEOPLE.forEach(p=>per[p].forEach(r=>all.push([p,r])));
    const seen=new Set();
    for(let i=0;i<all.length;i++) for(let j=i+1;j<all.length;j++){
      const [pa,a]=all[i],[pb,b]=all[j];
      if(pa===pb || !a.city || a.city!==b.city || !near(a,b)) continue;
      const k=[a._id||a.name,b._id||b.name].sort().join('|'); if(seen.has(k)) continue; seen.add(k);
      out.cross.push({a:pa,b:pb,ea:a,eb:b,city:a.city});
    }
    return out;
  }

  // ── Pipeline health per person: the number the boss actually needs ──
  function health(rows,today) {
    const soon=plus(today,30), out={}, ag=agenda(rows,today);
    PEOPLE.forEach(p=>{
      const mine=rows.filter(r=>r.owner===p && !r.hidden);
      const up=mine.filter(r=>!r.past);
      // Booked/attending come from the SAME per-person assignment the agenda
      // uses (named attendees, or the speaker when Booked) — "Thor is the
      // speaker but Jerome is the one attending" must not count for Thor.
      const commit=(ag.people[p]||{}).list||[];
      out[p]={
        applications: up.filter(r=>r.realApplication && !r.booked && !r.rejected).length,
        booked: commit.filter(r=>r.why==='Speaking').length,
        attending: commit.filter(r=>r.why!=='Speaking').length,
        undated: up.filter(r=>(r.booked || r.attending) && !r.start).length,
        rejected: mine.filter(r=>r.rejected && (!r.past || r.realApplication)).length,
        deadlines: up.filter(r=>day(r.deadline) && r.deadline>=today && r.deadline<=soon && !r.realApplication).length,
        overdue: up.filter(r=>r.realApplication && r.followup && r.followup<today).length,
      };
    });
    return out;
  }

  function metrics(rows) {
    return {applications:rows.filter(r=>r.realApplication).length,replies:rows.filter(r=>r.b.organizer_reply_at).length,
      slots:rows.filter(r=>r.booked).length,meetings:rows.reduce((n,r)=>n+(Number(r.b.meetings_booked)||0),0),
      attended:rows.filter(r=>r.b.attended_at).length,opportunities:rows.reduce((n,r)=>n+(Number(r.b.qualified_opportunities)||0),0),
      trips:new Set(rows.filter(r=>r.b.trip_id && r.b.trip_confirmed).map(r=>r.b.trip_id)).size};
  }
  function tripPack(trip,rows,accounts) {
    const lo=plus(trip.start_date,-4),hi=plus(trip.end_date,4), tc=cityOf({city:trip.city});
    const nearby=rows.filter(r=>!r.hidden && r.action!=='Pass' && !r.q.excluded && day(r.start_date) && r.start_date<=hi && (r.end_date||r.start_date)>=lo && !!tc && cityOf(r)===tc);
    const targets=accounts.filter(a=>cityOf({city:a.city})===tc && !!tc);
    return {trip,nearby,targets,lo,hi};
  }
  const api={STATES,PEOPLE,fold,day,plus,diff,safeUrl,cityOf,sameCity,qualify,applicationEvidence,normalize,groups,agenda,health,metrics,tripPack};
  if(typeof module!=='undefined') module.exports=api;
  else root.BookingCore=api;
})(typeof window!=='undefined'?window:this);
