/* Shared booking rules. No network or UI dependencies. */
(function(root) {
  'use strict';
  const STATES = ['Apply','Outreach','Book Meetings','Attend','Stack Trip','Pass'];
  const fold = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
  const day = d => /^\d{4}-\d{2}-\d{2}$/.test(d || '') && !isNaN(Date.parse(d)) && new Date(d).toISOString().slice(0,10)===d ? d : '';
  const plus = (d,n) => new Date(Date.parse(d+'T12:00:00Z')+n*86400000).toISOString().slice(0,10);
  const safeUrl = s => { try { const u=new URL(s); return ['http:','https:'].includes(u.protocol) ? u.href : ''; } catch(e) { return ''; } };
  const weight = {end_user_speakers:20,audience_breakdown:30,advisory_board:10,prior_attendees:15,sponsors:5,public_attendance:20,company_event_page:20,organizer_claim:10};
  function qualify(r,today) {
    const b=r.booking || {}, seen=new Set();
    const evidence=(b.evidence || []).filter(e => weight[e.kind] && safeUrl(e.url) && e.note && day(e.checked) && e.checked<=today && e.checked>=plus(today,-365));
    let score=0;
    evidence.forEach(e=>{if(!seen.has(e.kind)){score+=weight[e.kind];seen.add(e.kind);}});
    score=Math.min(score,100);
    const excluded=!!b.exclusion || /african internet governance|afigf|chief ai officer summit boston/i.test(r.name || '');
    return {score: evidence.length ? score : null, evidence, excluded, strong: score>=40 && b.buyer_fit==='strong', label: !evidence.length ? 'Buyer evidence unknown' : score>=60 ? 'Strong buyer evidence' : score>=30 ? 'Some buyer evidence' : 'Limited buyer evidence'};
  }
  function normalize(r,op,today) {
    const b=r.booking || {}, q=qualify(r,today), tags=r.status_tags || [];
    const submitted=day(r.submitted_at) || day(b.submitted_at) || (tags.includes('Submitted') ? 'recorded' : '');
    const booked=tags.includes('Booked') || !!b.speaking_booked_at;
    const attending=tags.includes('Attending');
    const completed=!!b.completed_at;
    const past=!!(day(r.end_date || r.start_date) && (r.end_date || r.start_date)<today);
    let action=STATES.includes(b.action) ? b.action : '';
    if(!action && (tags.includes('Rejected') || r.decision==='Reject')) action='Pass';
    const owner=b.owner || (op && op.owner_person) || r.speaker || (r.outreach_assignees || [])[0] || '';
    const due=day(b.due) || day(r.deadline) || day(op && op.next_action_due);
    const sleeping=!!b.recheck_on && b.recheck_on>today;
    const wake=!!day(b.recheck_on) && b.recheck_on<=today;
    const priorFollowups=(r.follow_ups || []).map(f=>day(f.date || f.sent_at || f.at)).filter(Boolean).sort();
    const lastFollowup=priorFollowups[priorFollowups.length-1];
    const followup=day(b.follow_up_due) || (submitted && submitted!=='recorded' && !b.organizer_reply_at && !booked && !attending ? plus(lastFollowup || submitted,7) : '');
    let recommendation=action;
    if(!recommendation) {
      if(booked || attending) recommendation='Attend';
      else if(submitted) recommendation='Outreach';
      else if(q.excluded) recommendation='Pass';
      else if(q.strong && b.speaking_quality==='earned' && safeUrl(r.apply_url)) recommendation='Apply';
      else if(q.strong) recommendation=r.poc_name || r.contact_info ? 'Outreach' : 'Book Meetings';
      else if(op && op.queue_stage==='apply_now') recommendation='Apply';
      else if(op && op.queue_stage==='reach_out') recommendation='Outreach';
    }
    const active=!!action && action!=='Pass' && !!owner && !!b.next_action && !!due && !!b.reason && !sleeping && !past && !r.hidden && !completed;
    const working=!r.hidden && !past && !sleeping && action!=='Pass' && !completed;
    const needsDecision=working && !active && (wake || !!action || !!submitted || !!booked || !!attending || q.strong || !!(op && ['apply_now','reach_out','conflicts'].includes(op.queue_stage)));
    return {...r,suggestedNextAction:op?.next_action||'',suggestedReason:op?.rationale||'',b,q,owner,due,action,recommendation,submitted,booked,attending,followup,past,active,needsDecision,sleeping,wake,completed};
  }
  function groups(rows,today) {
    const active=rows.filter(r=>r.active), soon=plus(today,7);
    return {
      applications:active.filter(r=>r.action==='Apply' && !r.submitted && r.due<=soon),
      contacts:active.filter(r=>r.action==='Outreach' && !(r.followup && r.followup<=today)),
      meetings:active.filter(r=>r.action==='Book Meetings'),
      followups:rows.filter(r=>!r.hidden && !r.past && !r.sleeping && !r.completed && r.action!=='Pass' && r.followup && r.followup<=today && !r.booked && !r.attending),
      decisions:rows.filter(r=>r.needsDecision)
    };
  }
  function metrics(rows) {
    return {applications:rows.filter(r=>r.submitted).length,replies:rows.filter(r=>r.b.organizer_reply_at).length,
      slots:rows.filter(r=>r.booked).length,meetings:rows.reduce((n,r)=>n+(Number(r.b.meetings_booked)||0),0),
      attended:rows.filter(r=>r.b.attended_at).length,opportunities:rows.reduce((n,r)=>n+(Number(r.b.qualified_opportunities)||0),0),
      trips:new Set(rows.filter(r=>r.b.trip_id && r.b.trip_confirmed).map(r=>r.b.trip_id)).size};
  }
  function sameCity(a,b) {
    const norm=s=>fold(s).replace(/\bnyc\b|\bnew york city\b/g,'new york').replace(/\bmünchen\b|\bmunchen\b/g,'munich');
    a=norm(a);b=norm(b);
    if(!a || !b || /^(unknown|tbd|online|remote)$/.test(a) || /^(unknown|tbd|online|remote)$/.test(b)) return false;
    return a===b || a.split(/[,;]/).map(s=>s.trim()).includes(b) || b.split(/[,;]/).map(s=>s.trim()).includes(a);
  }
  function tripPack(trip,rows,accounts) {
    const lo=plus(trip.start_date,-4),hi=plus(trip.end_date,4);
    const nearby=rows.filter(r=>!r.hidden && r.action!=='Pass' && !r.q.excluded && day(r.start_date) && r.start_date<=hi && (r.end_date||r.start_date)>=lo && sameCity(r.city||r.location,trip.city));
    const targets=accounts.filter(a=>sameCity(a.city,trip.city));
    return {trip,nearby,targets,lo,hi};
  }
  const api={STATES,fold,day,plus,safeUrl,qualify,normalize,groups,metrics,sameCity,tripPack};
  if(typeof module!=='undefined') module.exports=api;
  else root.BookingCore=api;
})(typeof window!=='undefined'?window:this);
