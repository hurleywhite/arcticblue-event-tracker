(function() {
  'use strict';
  const C=window.BookingCore, esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let raw=[], rows=[], context={opportunities:[],travel_windows:[],target_accounts:[]}, cal=null, error='', loading=true, ready=false, owner='',mode='today',query='', expanded=new Set(), dialog=null;
  let workflow={workspaces:[],calendars:[]},workflowError='';
  const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const title=s=>String(s||'').replace(/\b\w/g,c=>c.toUpperCase());
  const link=(url,label)=>C.safeUrl(url)?'<a class="ac-link" target="_blank" rel="noopener noreferrer" href="'+esc(C.safeUrl(url))+'">'+esc(label)+'</a>':'';
  const host=()=>document.getElementById('ops-action');
  async function request(path,body) {
    const s=await window._ab.auth.getSession(), token=s.data?.session?.access_token;
    const ctl=new AbortController(), timer=setTimeout(()=>ctl.abort(),15000);
    try {
      const r=await fetch(path,{method:body?'POST':'GET',signal:ctl.signal,headers:{...(body?{'Content-Type':'application/json'}:{}),...(token?{Authorization:'Bearer '+token}:{})},...(body?{body:JSON.stringify(body)}:{})});
      const j=await r.json(); if(!r.ok || j.error)throw Error(j.error || 'Request failed'); return j;
    } catch(e) {
      if(e && e.name==='AbortError') throw Error(path+' timed out after 15 seconds. Check the deployment and Supabase/calendar connections, then retry.');
      throw e;
    } finally { clearTimeout(timer); }
  }
  async function load() {
    loading=true;error='';context={...context,editor:false,travel_windows:[],target_accounts:[]};cal=null;workflow={workspaces:[],calendars:[]};render();
    const results=await Promise.allSettled([request('/api/opportunities'),request('/api/calendars')]);
    if(results[0].status==='fulfilled')context=results[0].value;else error='Qualification and recorded travel could not load. '+results[0].reason.message;
    if(results[1].status==='fulfilled')cal=results[1].value;else cal={configured:false,unavailable:true};
    workflow={workspaces:[],calendars:[]};workflowError='';
    // /api/workflow is the one thing a magic link still changes: it holds the
    // Attio token and proxies CRM reads. Everything else on this board is open
    // (Hurley 2026-09-15), so ask for it only when actually signed in rather
    // than showing everyone a 403 they can do nothing about.
    if(context.signed_in){try{workflow=await request('/api/workflow');}catch(e){workflowError=e.message;}}
    loading=false;recompute();render();
  }
  function recompute() {
    const by=new Map((context.opportunities||[]).map(o=>[o.source_table+':'+o.source_key,o]));
    rows=raw.map(r=>C.normalize(r,by.get(r._table+':'+r._key),today())).sort((a,b)=>(a.due||'9999').localeCompare(b.due||'9999') || String(a.name||'').localeCompare(String(b.name||'')));
  }
  function filtered() {return rows.filter(r=>(!owner || C.fold(r.owner).includes(owner)) && (!query || C.fold([r.name,r.location,r.owner,r.b.next_action,r.poc_name].join(' ')).includes(C.fold(query))));}
  // opts.chase adds the one-click chase button. It is passed ONLY by the
  // follow-ups section: a third button on every row everywhere would cost more
  // attention than it earns.
  function eventRow(r,opts) {
    // No badges. This row used to open with the internal state name ("Apply",
    // "Outreach", "Decision needed"), a "suggested" chip and the words "Owner
    // needed" / "Location unknown" / "Due date needed" -- labels standing in
    // for facts we do not have (Hurley 2026-09-15: stop adding labels just for
    // the sake of them). What is left is the event, who has it, where and when,
    // the next step in a sentence, and the date it is due.
    const next=r.b.next_action || (r.submitted?'Set the next organiser follow-up':r.wake?('Review: '+(r.b.recheck_trigger||'scheduled recheck')):'Decide what happens with this one');
    const meta=[r.owner?title(r.owner):'', r.city?title(r.city):'', r.start?niceRange(r.start,r.end):''].filter(Boolean).join(' · ');
    const due=r.due?(r.due<today()?'<span class="ac-overdue">'+C.diff(r.due,today())+' days late</span>':'Due '+esc(niceDate(r.due))):'';
    return '<article class="ac-row"><div>'+nameLink(r)+(meta?'<p class="ac-meta">'+esc(meta)+'</p>':'')
      +'<p class="ac-next">'+esc(next)+'</p>'+(due?'<p class="ac-note">'+due+'</p>':'')
      +'</div><div class="ac-row-actions">'+(opts&&opts.chase?'<button data-chase="'+esc(r._id)+'">Chased today</button>':'')
      +'<button class="ac-primary" data-manage="'+esc(r._id)+'">Update</button></div></article>';
  }
  // Every event name on this page opens the event. One helper so none is missed.
  function nameLink(r,tag){const t=tag||'h4';return '<'+t+' class="ac-title"><button class="ac-linklike" data-detail="'+esc(r._id)+'">'+esc(r.name)+'</button></'+t+'>';}
  // An empty section used to render a heading, a zero badge and "Nothing due
  // here." -- 270px of furniture on the live board for two lanes that were
  // simply clear. Nothing to show means nothing to draw (Hurley 2026-09-15).
  function section(key,label,list,opts) {
    if(!list.length) return '';
    const show=expanded.has(key)?list:list.slice(0,4);
    return '<section class="ac-section" id="ac-'+key+'"><div class="ac-section-head"><h3>'+esc(label)+' <span class="ac-badge">'+list.length+'</span></h3>'+(list.length>4?'<button data-expand="'+key+'">'+(expanded.has(key)?'Show fewer':'Show all '+list.length)+'</button>':'')+'</div>'+(show.length?show.map(r=>eventRow(r,opts)).join(''):'<p class="ac-empty">Nothing due here.</p>')+'</section>';
  }
  function render() {
    const h=host();if(!h)return;
    const rs=filtered(),g=C.groups(rs,today());
    // ONE page. There were five buttons here (Today / Applications / Trips /
    // Target accounts / Background) plus a separate Lineup tab, so the same
    // events were reachable five ways and nothing was in one place
    // (Hurley 2026-09-15: "less views to switch around to"). Everything that
    // needs doing is now one scroll, in the order you act on it.
    let html='<div class="ac-head"><div><h2>Action Center</h2><p class="ac-note">'+esc(niceDate(today()))+' · What needs doing, who is where, and who we want to meet.</p></div><button class="ab-btn" data-refresh>Refresh</button></div>';
    html+='<div class="ac-toolbar"><select aria-label="Show one person" id="ac-owner"><option value="">Everyone</option>'+C.PEOPLE.map(p=>'<option '+(owner===p?'selected':'')+' value="'+p+'">'+title(p)+'</option>').join('')+'</select><input type="search" id="ac-search" placeholder="Find an event or person" aria-label="Search" value="'+esc(query)+'"></div>';
    if(loading)html+='<p class="ac-note" role="status">Loading…</p>';
    if(error)html+='<p class="ac-health">'+esc(error)+'</p>';
    if(!ready){h.innerHTML=html+'<p class="ac-empty">Loading live event records…</p>';return;}
    html+=renderHealth(rs);
    const later=rs.filter(r=>r.active && !Object.values(g).flat().includes(r));
    const work=section('followups','Follow-ups due',g.followups,{chase:true})
      +section('contacts','Organiser contact',g.contacts)
      +section('applications','Applications due soon',g.applications)
      +section('meetings','Meetings to book',g.meetings)
      +section('decisions','Decisions needed',g.decisions)
      +section('later','Planned',later);
    html+=work||'<p class="ac-empty">Nothing due right now'+(owner?' for '+esc(title(owner)):'')+(query?' matching that search':'')+'.</p>';
    html+=renderCalendar(rs)+renderTargets(rs);
    h.innerHTML=html;
  }
  // Pipeline health per person — applications out, accepted, rejected, deadlines
  // inside 30 days, chases overdue. This is the line Thor asked for and never got.
  // Dates as people read them: "Sep 29–30", "Nov 3–5", "Jan 25–26, 2027".
  // ISO ("2026-09-29–09-30") was precise and hard to scan (Hurley 2026-09-15).
  const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  function niceDate(d){if(!C.day(d))return d||'';const y=+d.slice(0,4);return MON[+d.slice(5,7)-1]+' '+(+d.slice(8,10))+(y!==+today().slice(0,4)?', '+y:'');}
  function niceRange(a,b){
    if(!C.day(a))return a||'';if(!C.day(b)||b===a)return niceDate(a);
    const ya=a.slice(0,4),yb=b.slice(0,4),ma=+a.slice(5,7)-1,mb=+b.slice(5,7)-1,yr=+ya!==+today().slice(0,4)?', '+ya:'';
    if(ya!==yb)return niceDate(a)+' – '+niceDate(b);
    return MON[ma]+' '+(+a.slice(8,10))+'–'+(ma===mb?'':MON[mb]+' ')+(+b.slice(8,10))+yr;
  }
  // One card per person, led by the single number that needs doing something
  // about. It used to be five small grey lines, mostly zeros, including
  // "rejected (all time)" -- a scoreboard stat, not a to-do. Zeros are dropped;
  // clicking a card filters the board to that person (click again to clear).
  function renderHealth(rs) {
    const h=C.health(rs,today());
    const people=(owner?[owner]:C.PEOPLE);
    const card=p=>{const x=h[p]||{};
      const hl=x.overdue?['ac-hl-bad',x.overdue,x.overdue===1?'chase overdue':'chases overdue']
        :x.deadlines?['ac-hl-warn',x.deadlines,x.deadlines===1?'deadline this month':'deadlines this month']
        :['ac-hl-ok','✓','nothing overdue'];
      const sub=[x.applications&&x.applications+' applied',x.booked&&x.booked+' speaking',x.attending&&x.attending+' attending',(x.overdue&&x.deadlines)&&x.deadlines+' deadlines soon'].filter(Boolean);
      return '<button class="ac-pcard" data-pick-owner="'+esc(p)+'" aria-pressed="'+(owner===p)+'" title="'+(owner===p?'Show everyone':'Show only '+esc(title(p)))+'"><span class="ac-pcard-name">'+esc(title(p))+'</span><span class="ac-pcard-hl '+hl[0]+'"><b>'+hl[1]+'</b> '+hl[2]+'</span><span class="ac-pcard-sub">'+(sub.join(' · ')||'Nothing in flight')+'</span></button>';};
    return '<section class="ac-section ac-health-strip"><div class="ac-section-head"><h3>Pipeline health</h3></div><div class="ac-pcards">'+people.map(card).join('')+'</div></section>';
  }
  // What people are ACTUALLY going to (Booked / Attending), with hard clashes,
  // same-city stacking and where two of them coincide. Applications are not
  // commitments; a clash between two wishes is normal and not shown here.
  function renderAgenda(rs) {
    const a=C.agenda(rs,today());
    const people=(owner?[owner]:C.PEOPLE).filter(p=>(a.people[p]||{}).list?.length);
    // "Attending" is the default, so it is no longer printed on every line --
    // only "Speaking" is tagged, because that is the one that needs prep.
    const mini=r=>'<li><span class="ac-when">'+esc(niceRange(r.start,r.end))+'</span><button class="ac-linklike" data-detail="'+esc(r._id)+'">'+esc(r.name)+'</button><span class="ac-where">'+esc(r.city?title(r.city):(r.location||''))+(r.why==='Speaking'?'<span class="ac-tag">Speaking</span>':'')+'</span></li>';
    let html='<section class="ac-section"><div class="ac-section-head"><h3>Commitments & conflicts</h3></div>';
    if(!people.length) html+='<p class="ac-empty">Nobody is booked or attending anything upcoming'+(owner?' for '+esc(title(owner)):'')+'.</p>';
    people.forEach(p=>{const x=a.people[p];
      html+='<div class="ac-agenda"><h4>'+esc(title(p))+' <span class="ac-badge">'+x.list.length+'</span></h4><ul>'+x.list.map(mini).join('')+'</ul>';
      x.clashes.forEach(([e1,e2])=>html+='<p class="ac-overdue">Clash: '+esc(e1.name)+' overlaps '+esc(e2.name)+' ('+esc(niceDate(e1.start))+')</p>');
      x.stacks.forEach(([e1,e2])=>html+='<p class="ac-warn">Same trip: '+esc(e1.name)+' and '+esc(e2.name)+' are both in '+esc(title(e1.city))+' within 4 days.</p>');
      html+='</div>';});
    if(!owner&&a.cross.length) html+='<h4>Where two of them coincide</h4><ul>'+a.cross.map(c=>'<li>'+esc(title(c.a))+' ('+esc(c.ea.name)+') and '+esc(title(c.b))+' ('+esc(c.eb.name)+') are both in '+esc(title(c.city))+' around '+esc(niceDate(c.ea.start))+'</li>').join('')+'</ul>';
    return html+'</section>';
  }
  function workflowUi() {return {request,input,area,select,openDialog,signIn,manage,editor:context.editor,reload:load};}
  // Calendar, conflicts and loop-ins in one place. Replaces the Trips view.
  function renderCalendar(rs) {
    const conflicts=C.conflicts(rs,cal,today());
    const calTrips=C.calendarTrips(cal).filter(t=>t.end_date>=today()&&(!owner||t.person_key===owner));
    const recorded=(context.travel_windows||[]).filter(t=>t.end_date>=today()&&(!owner||C.fold(t.person_key).includes(owner)))
      .map(t=>({...t,city:C.cityOf(t)||t.city,source:t.source||'Recorded'}));
    // A recorded trip and a calendar trip for the same person/city/dates are
    // the same trip; the calendar one wins because it is live.
    const trips=calTrips.concat(recorded.filter(r=>!calTrips.some(c=>c.person_key===C.fold(r.person_key)&&c.city===r.city&&c.start_date===r.start_date)));
    const loop=C.loopIns(rs,trips,today(),3);
    const a=C.agenda(rs,today());
    const people=(owner?[owner]:C.PEOPLE);
    let html='<section class="ac-section" id="ac-calendar"><div class="ac-section-head"><h3>Where everyone is</h3></div>';
    html+='<div class="ac-cal-row">'+people.map(p=>{
      const c=(cal?.connections||[]).find(x=>x.person===p);
      const state=!c?'Calendar not connected':(c.healthy===false?'Calendar needs reconnecting':'Calendar connected');
      return '<span class="ac-cal-chip'+(c?(c.healthy===false?' is-bad':' is-on'):'')+'"><b>'+esc(title(p))+'</b> '+esc(state)+' <button class="ac-linklike" data-connect-cal="'+esc(p)+'">'+(c?'Change':'Connect')+'</button></span>';}).join('')+'</div>';
    if(cal&&cal.errors&&cal.errors.length)html+='<p class="ac-health">'+cal.errors.map(e=>esc(title(e.name))+': '+esc(e.reason)).join(' · ')+'</p>';
    if(conflicts.length)html+='<h4 class="ac-sub">Clashes</h4>'+conflicts.map(c=>'<article class="ac-row"><div>'+nameLink(c.event)+'<p class="ac-meta">'+esc(title(c.person))+' · '+esc(niceRange(c.event.start,c.event.end))+(c.event.city?' · '+esc(title(c.event.city)):'')+'</p><p class="ac-next ac-overdue">'+esc(c.why)+'</p></div><div class="ac-row-actions"><button class="ac-primary" data-manage="'+esc(c.event._id)+'">Update</button></div></article>').join('');
    if(!trips.length)html+='<p class="ac-empty">No upcoming travel. Connect a calendar above, or <button class="ac-linklike" data-trip-add>add a trip</button>.</p>';
    trips.forEach(t=>{
      const l=loop.find(x=>x.trip===t), commit=((a.people[t.person_key]||{}).list||[]).filter(e=>e.start&&e.start<=C.plus(t.end_date,4)&&(e.end||e.start)>=C.plus(t.start_date,-4));
      html+='<article class="ac-trip"><h4>'+esc(title(t.person_key))+' · '+esc(t.city?title(t.city):'Away')+'</h4><p class="ac-meta">'+esc(niceRange(t.start_date,t.end_date))+' · '+esc(t.source)+'</p>';
      if(commit.length)html+='<ul class="ac-mini">'+commit.map(e=>'<li>'+nameLink(e,'span')+' <span class="ac-where">'+esc(e.why)+'</span></li>').join('')+'</ul>';
      if(l&&l.events.length)html+='<p class="ac-sub">Also on while they are there</p><ul class="ac-mini">'+l.events.map(e=>'<li>'+nameLink(e,'span')+' <span class="ac-where">'+esc(niceRange(e.start,e.end))+'</span> <button class="ac-linklike" data-manage="'+esc(e._id)+'">Add</button></li>').join('')+'</ul>';
      else if(t.city)html+='<p class="ac-note">Nothing else on in '+esc(title(t.city))+' that week.</p>';
      html+='</article>';
    });
    return html+'</section>';
  }
  // Where a target account actually shows up. Matches the company name against
  // the text the tracker already stores for each event (who typically attends,
  // who has spoken before, the description). It is a text match on public
  // blurb -- it does not prove anyone will be in the room, and it says so.
  const EVIDENCE_FIELDS=[['typical_attendees','who attends'],['past_speakers','past speakers'],['about','description'],['focus_areas','focus'],['why','why we track it'],['notes','notes']];
  function accountEvidence(rs,account){
    const name=String(account.name||'').trim(); if(name.length<3)return [];
    const re=new RegExp('(?<![A-Za-z])'+name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'(?![A-Za-z])','i');
    const out=[];
    rs.forEach(r=>{ if(r.past||r.hidden)return;
      for(const [f,label] of EVIDENCE_FIELDS){ if(re.test(String(r[f]||''))){out.push({event:r,where:label});break;} }});
    return out.sort((a,b)=>String(a.event.start||'9999').localeCompare(String(b.event.start||'9999')));
  }
  // Structured proof wins. a786c7e records real people against an account and
  // an opportunity (event_people.target_account_id) -- that is someone we know
  // is in the room, not an inference. Only when an account has none of that do
  // we fall back to matching the company name in the event's published text.
  function accountProof(a){
    const oppById=new Map((context.opportunities||[]).map(o=>[String(o.id),o]));
    const seen=new Set(), out=[];
    (context.people||[]).forEach(p=>{
      if(String(p.target_account_id||'')!==String(a.id))return;
      const o=oppById.get(String(p.opportunity_id)); if(!o)return;
      const k=o.id+'|'+p.full_name; if(seen.has(k))return; seen.add(k);
      out.push({opportunity:o,person:p});
    });
    return out;
  }
  function renderTargets(rs) {
    const accounts=(context.target_accounts||[]).filter(a=>!owner||C.fold(a.owner_person||'').includes(owner));
    let html='<section class="ac-section" id="ac-targets"><div class="ac-section-head"><h3>Accounts we want in the room</h3><button data-account-add>Add a company</button></div>';
    if(!accounts.length)return html+'<p class="ac-empty">No companies yet. Add the ones worth flying to meet.</p></section>';
    html+='<p class="ac-note">Matched against what each event publishes about who attends and who has spoken. That is a sign, not a guest list.</p>';
    accounts.forEach(a=>{
      const proof=accountProof(a), ev=proof.length?[]:accountEvidence(rs,a);
      html+='<article class="ac-row"><div><h4 class="ac-title">'+esc(a.name)+'</h4>'
        +'<p class="ac-meta">'+esc([a.owner_person?title(a.owner_person):'',a.city||'',a.industry||''].filter(Boolean).join(' · '))+'</p>'
        +(proof.length?'<p class="ac-sub">Known to be there</p><ul class="ac-mini">'+proof.map(m=>'<li><button class="ac-linklike" data-account-event="'+esc(m.opportunity.id)+'">'+esc(m.opportunity.name||m.opportunity.event_name||'Event')+'</button> <span class="ac-where">'+esc(m.person.full_name||'')+(m.person.title?' · '+esc(m.person.title):'')+'</span></li>').join('')+'</ul>':'')
        +(proof.length?'':ev.length?'<ul class="ac-mini">'+ev.slice(0,3).map(e=>'<li>'+nameLink(e.event,'span')+' <span class="ac-where">'+esc(niceRange(e.event.start,e.event.end))+' · named in '+esc(e.where)+'</span></li>').join('')+'</ul>'+(ev.length>3?'<p class="ac-note">and '+(ev.length-3)+' more</p>':'')
             :'<p class="ac-note">Not named in any upcoming event we track.</p>')
        +'</div><div class="ac-row-actions"><button data-account="'+esc(a.id)+'">Edit</button><button data-account-remove="'+esc(a.id)+'" data-account-name="'+esc(a.name)+'">Remove</button></div></article>';
    });
    return html+'</section>';
  }
  function openDialog(name,body) {
    if(dialog)dialog.remove();
    dialog=document.createElement('dialog');dialog.className='ac-dialog';dialog.innerHTML='<h2 id="ac-dialog-title">'+esc(name)+'</h2>'+body;dialog.setAttribute('aria-labelledby','ac-dialog-title');document.body.appendChild(dialog);dialog.showModal();
    dialog.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>dialog.close());
    const current=dialog;
    current.addEventListener('close',()=>{current.remove();if(dialog===current)dialog=null;});return current;
  }
  const input=(label,name,value,type='text',wide=false)=>'<label class="'+(wide?'ac-wide':'')+'">'+esc(label)+'<input name="'+name+'" type="'+type+'" value="'+esc(value||'')+'" '+(type==='number'?'min="0" max="10000" step="1"':'')+'></label>';
  const area=(label,name,value)=>'<label class="ac-wide">'+esc(label)+'<textarea name="'+name+'">'+esc(value||'')+'</textarea></label>';
  const select=(label,name,value,opts)=>'<label>'+esc(label)+'<select name="'+name+'">'+opts.map(o=>'<option value="'+esc(o)+'" '+(o===value?'selected':'')+'>'+esc(o||'Not set')+'</option>').join('')+'</select></label>';
  const footer=()=>'<p class="ac-error" role="alert"></p><footer><button type="button" data-close>Cancel</button><button class="ac-primary" type="submit">Save</button></footer>';
  function manage(r) {
    const b=r.b;
    let body='<p class="ac-note">'+esc(r.name)+'</p><p class="ac-note">Suggested: '+esc(r.recommendation||'Keep in background until qualified')+'. Public evidence score: '+(r.q.score===null?'Unknown':r.q.score+'/100')+'; this is not an attendee count or probability.</p><form id="ac-edit"><div class="ac-form">';
    body+=select('Decision','action',b.action||'', ['',...C.STATES])+input('Owner','owner',b.owner||r.owner)+input('Next action due','due',b.due||r.due,'date')+input('Application / speaking deadline','deadline',C.day(r.applicationDeadline||r.deadline),'date')+area('Next action','next_action',b.next_action||r.suggestedNextAction)+area('Reason for this decision','reason',b.reason||r.suggestedReason);
    body+=select('Product / innovation fit','topic_fit',b.topic_fit||'review',['review','core','off_focus'])+area('Specific product or innovation relevance','topic_reason',b.topic_reason)+input('Agenda / session source','topic_source',b.topic_source,'url',true);
    body+=input('Application link','apply_url',r.apply_url,'url',true)+select('Draft status','draft_status',b.draft_status||'Not started',['Not started','Drafting','Ready','Submitted'])+input('Follow-up due','follow_up_due',b.follow_up_due||r.followup,'date')+area('Application draft / pitch','draft',b.draft);
    body+=input('Recheck on (keeps event in background until then)','recheck_on',b.recheck_on,'date')+input('Recheck trigger','recheck_trigger',b.recheck_trigger)+select('Buyer fit','buyer_fit',b.buyer_fit||'unknown',['unknown','strong','mixed','weak'])+select('Speaking route quality','speaking_quality',b.speaking_quality||'unknown',['unknown','earned','invited','paid','closed'])+input('Exclusion reason','exclusion',b.exclusion,'text',true);
    body+='</div><details><summary>Public buyer-room evidence</summary><p class="ac-note">Keep likely buyers, publicly confirmed speakers/attendees and verified portal attendees separate. Record public sources here. Private attendee lists stay in the authorized portal.</p>'+(b.evidence||[]).map((e,i)=>'<div class="ac-evidence">'+esc(e.kind)+' · '+esc(e.checked)+'<br>'+esc(e.note)+' '+link(e.url,'Source')+' <label><input type="checkbox" name="remove_evidence" value="'+i+'"> Remove</label></div>').join('')+'<div class="ac-form">'+select('New evidence type','evidence_kind','',['','end_user_speakers','audience_breakdown','advisory_board','prior_attendees','sponsors','public_attendance','company_event_page','organizer_claim'])+input('Checked on','evidence_checked',today(),'date')+input('Public source URL','evidence_url','','url',true)+area('What this source confirms','evidence_note','')+'</div></details>';
    body+='<details><summary>Record booking outcomes</summary><p class="ac-note">Only record completed actions and confirmed results.</p><div class="ac-form">'+input('Application submitted','submitted_at',C.day(r.submitted),'date')+input('Organizer replied','organizer_reply_at',b.organizer_reply_at,'date')+input('Speaking slot booked','speaking_booked_at',b.speaking_booked_at,'date')+input('Meetings booked','meetings_booked',b.meetings_booked||0,'number')+input('Attended on','attended_at',b.attended_at,'date')+input('Qualified opportunities','qualified_opportunities',b.qualified_opportunities||0,'number')+input('Associated recorded trip ID','trip_id',b.trip_id)+select('Trip stacking confirmed','trip_confirmed',b.trip_confirmed?'Yes':'No',['No','Yes'])+input('Action completed on','completed_at',b.completed_at,'date')+'</div></details>'+footer()+'</form>';
    const d=openDialog('Manage booking',body), form=d.querySelector('form');
    form.onsubmit=async e=>{
      e.preventDefault();const f=new FormData(form),v=k=>String(f.get(k)||'').trim(),next={...b};
      ['topic_fit','topic_reason','topic_source','action','owner','due','next_action','reason','draft_status','follow_up_due','draft','recheck_on','recheck_trigger','buyer_fit','speaking_quality','exclusion','organizer_reply_at','speaking_booked_at','attended_at','trip_id','completed_at'].forEach(k=>next[k]=v(k));
      next.meetings_booked=Number(v('meetings_booked'));next.qualified_opportunities=Number(v('qualified_opportunities'));next.trip_confirmed=v('trip_confirmed')==='Yes';
      next.evidence=(b.evidence||[]).filter((_,i)=>!f.getAll('remove_evidence').includes(String(i)));
      const err=d.querySelector('.ac-error'),btn=form.querySelector('[type=submit]');
      if(next.action && next.action!=='Pass' && (!next.owner||!next.due||!next.next_action||!next.reason)){err.textContent='Active decisions need an owner, next action, due date and reason.';return;}
      if(next.action==='Pass'&&!next.reason){err.textContent='Record a reason for passing.';return;}
      if(next.recheck_on&&!next.recheck_trigger){err.textContent='Add a trigger explaining what to recheck.';return;}
      if(v('evidence_kind')||v('evidence_url')||v('evidence_note')){
        if(!v('evidence_kind')||!C.safeUrl(v('evidence_url'))||!v('evidence_note')||!C.day(v('evidence_checked'))||v('evidence_checked')>today()){err.textContent='Evidence needs a type, public URL, observation and valid checked date.';return;}
        next.evidence.push({kind:v('evidence_kind'),url:C.safeUrl(v('evidence_url')),note:v('evidence_note'),checked:v('evidence_checked')});
      }
      if(next.action==='Apply' && (next.topic_fit!=='core'||!next.topic_reason||!C.safeUrl(next.topic_source)||next.exclusion)){err.textContent='Before applying, record core product / innovation fit, its reason and an agenda source. Clear any exclusion only after reviewing it.';return;}
      if(next.action==='Apply'&&next.speaking_quality==='paid'){err.textContent='A paid speaking route is not an earned application. Choose Outreach or another decision.';return;}
      if(next.trip_confirmed&&!next.trip_id){err.textContent='Choose a recorded trip before confirming stacking.';return;}
      for(const k of ['submitted_at','organizer_reply_at','speaking_booked_at','attended_at','completed_at'])if(v(k)>today()){err.textContent='Completed outcomes cannot have future dates.';return;}
      btn.disabled=true;err.textContent='';
      try {
        const patch={booking:next,apply_url:v('apply_url')||null};
        if(v('deadline'))patch.deadline=v('deadline');else if(C.day(r.deadline))patch.deadline=null;
        if(v('submitted_at')){patch.submitted_at=v('submitted_at');patch.status_tags=Array.from(new Set([...(r.status_tags||[]),'Submitted']));next.draft_status='Submitted';}
        if(next.speaking_booked_at)patch.status_tags=Array.from(new Set([...(patch.status_tags||r.status_tags||[]),'Booked']));
        if(!v('submitted_at')&&C.day(r.submitted)){patch.submitted_at=null;patch.status_tags=(patch.status_tags||r.status_tags||[]).filter(t=>t!=='Submitted');}
        if(!next.speaking_booked_at&&b.speaking_booked_at)patch.status_tags=(patch.status_tags||r.status_tags||[]).filter(t=>t!=='Booked');
        const sb=window._ab,col=r._table==='manual_events'?'id':'event_num';
        if(r._table==='event_state') {const init=await sb.from(r._table).upsert({event_num:r._key},{onConflict:'event_num',ignoreDuplicates:true});if(init.error)throw init.error;}
        const saved=await sb.from(r._table).update(patch).eq(col,r._key).eq('booking',JSON.stringify(r.booking||{})).select(col);
        if(saved.error)throw saved.error;if(!saved.data?.length)throw Error('This booking changed in another session. Close, refresh and retry.');
        d.close();await window.opsRefresh();
      } catch(ex){err.textContent='Save failed: '+ex.message;btn.disabled=false;}
    };
  }
  function accountForm(account={}) {
    const d=openDialog(account.id?'Edit target account':'Add target account','<form><div class="ac-form">'+input('Company','name',account.name)+input('Industry','industry',account.industry)+input('Confirmed office city','city',account.city)+input('Owner','owner_person',account.owner_person)+input('Executive roles to track','executive_roles',account.executive_roles||'CIO, CAIO, CTO, COO, CDO, CPO, digital transformation, innovation','text',true)+'</div>'+footer()+'</form>');
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.target));await formRequest(d,{action:'save_target_account',...f,...(account.id?{id:account.id}:{})});};
  }
  async function formRequest(d,body) {
    const btn=d.querySelector('[type=submit]');btn.disabled=true;
    try{await request('/api/opportunities',body);d.close();await load();}catch(e){d.querySelector('.ac-error').textContent=e.message;btn.disabled=false;}
  }
  function tripForm() {
    const d=openDialog('Record a confirmed trip','<p class="ac-note">Use travel already in a calendar or confirmed plan.</p><form><div class="ac-form">'+select('Person','person_key',owner||'thor',C.PEOPLE)+input('City','city','')+input('Starts','start_date','','date')+input('Ends','end_date','','date')+input('Source (calendar or confirmed plan)','source','','text',true)+'</div>'+footer()+'</form>');
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();await formRequest(d,{action:'add_travel_window',...Object.fromEntries(new FormData(e.target))});};
  }
  function signIn() {
    const d=openDialog('Editor sign-in','<p class="ac-note">Target accounts and private travel use the tracker’s existing approved-editor access.</p><form><div class="ac-form">'+input('Work email','email','','email',true)+'</div><p class="ac-error" role="status"></p><footer><button type="button" data-close>Close</button><button type="submit" class="ac-primary">Send sign-in link</button></footer></form>');
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();const btn=d.querySelector('[type=submit]');btn.disabled=true;const res=await window._ab.auth.signInWithOtp({email:new FormData(e.target).get('email'),options:{emailRedirectTo:location.origin+'/events'}});d.querySelector('.ac-error').textContent=res.error?res.error.message:'Check your inbox for the sign-in link.';btn.disabled=false;};
  }
  async function discover(trip) {
    const accounts=context.target_accounts||[];
    if(!trip&&!accounts.length){return accountForm();}
    const d=openDialog('Discover qualified events','<p class="ac-note">Searching public sources for buyer evidence and actionable booking routes…</p><div id="ac-found"></div><footer><button data-close>Close</button></footer>');
    try {
      const result=await request('/api/search',{count:5,target_accounts:accounts.map(a=>({name:a.name,roles:a.executive_roles})),...(trip?{location:trip.city,date_from:trip.start_date,date_to:trip.end_date}:{})});
      if(!d.isConnected)return;
      d.querySelector('.ac-note').textContent='Review public evidence before adding. New discoveries enter the background universe until a booking decision is made.';
      d.querySelector('#ac-found').innerHTML=(result.events||[]).map((ev,i)=>'<div class="ac-evidence"><h3>'+esc(ev.name)+'</h3><p>'+esc(ev.date_str)+' · '+esc(ev.location)+'</p><p>'+esc(ev.reasoning||ev.why)+'</p>'+link(ev.url,'Event source')+' <button data-add-result="'+i+'">Add to background</button></div>').join('')||'<p>No new matches found.</p>';
      d.querySelectorAll('[data-add-result]').forEach(btn=>btn.onclick=async()=>{btn.disabled=true;try{const ev=result.events[Number(btn.dataset.addResult)],res=await window.opsCreateManual({name:ev.name,date_str:ev.date_str,...(window.opsDeriveDates?window.opsDeriveDates(ev.date_str):{}),location:ev.location,region:ev.region,type:ev.type,why:ev.why,url:C.safeUrl(ev.url)||null,priority:'Low',booking:{discovery_source:'Target-account/trip search',reason:ev.reasoning||ev.why||''}});if(res?.error)throw res.error;btn.textContent='Added';}catch(e){btn.disabled=false;btn.textContent='Retry: '+e.message;}});
    }catch(e){if(d.isConnected)d.querySelector('.ac-note').textContent='Search failed: '+e.message;}
  }
  // Connect one person's calendar. No sign-in, like the rest of the board.
  function connectCal(person){
    const d=openDialog('Connect '+title(person)+'\u2019s calendar',
      '<p class="ac-note">In Google Calendar: <b>Settings</b> \u2192 pick the calendar \u2192 <b>Integrate calendar</b> \u2192 copy the <b>Secret address in iCal format</b>. Only the calendar\u2019s owner can get that link. The tracker reads dates and destination cities from it \u2014 meeting titles never leave the server.</p><form><div class="ac-form">'
      +input('Secret iCal address','url','','url',true)+'</div><p class="ac-error" role="status"></p><footer><button type="button" data-close>Close</button><button type="button" data-disconnect>Disconnect</button><button type="submit" class="ac-primary">Connect</button></footer></form>');
    const f=d.querySelector('form'),err=d.querySelector('.ac-error');
    f.onsubmit=async e=>{e.preventDefault();const b=f.querySelector('[type=submit]');b.disabled=true;err.textContent='Checking the calendar\u2026';
      try{await request('/api/calendars',{person,url:f.elements.url.value});d.close();await load();}catch(ex){err.textContent=ex.message;b.disabled=false;}};
    d.querySelector('[data-disconnect]').onclick=async()=>{err.textContent='';
      try{await request('/api/calendars',{person,action:'disconnect'});d.close();await load();}catch(ex){err.textContent=ex.message;}};
  }
  document.addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b || !b.closest('#ops-action'))return;
    if(b.hasAttribute('data-refresh')){window.opsRefresh();load();}
    else if(b.dataset.expand){expanded.has(b.dataset.expand)?expanded.delete(b.dataset.expand):expanded.add(b.dataset.expand);render();}
    else if(b.dataset.pickOwner){owner=owner===b.dataset.pickOwner?'':b.dataset.pickOwner;render();}
    else if(b.dataset.chase)chase(b,rows.find(r=>r._id===b.dataset.chase));
    else if(b.dataset.manage){const r=rows.find(r=>r._id===b.dataset.manage);if(r)manage(r);}
    else if(b.dataset.connectCal)connectCal(b.dataset.connectCal);
    else if(b.dataset.detail){const r=rows.find(r=>r._id===b.dataset.detail);if(r)window.abOpenRef(r._table==='manual_events'?'manual':'catalog',r._key);}
    else if(b.hasAttribute('data-account-add'))accountForm();
    else if(b.dataset.account)accountForm(context.target_accounts.find(a=>String(a.id)===b.dataset.account));
    else if(b.dataset.accountRemove){
      if(!confirm('Remove '+b.dataset.accountName+' from the account list?'))return;
      b.disabled=true;request('/api/opportunities',{action:'archive_target_account',id:b.dataset.accountRemove}).then(load).catch(e=>{b.disabled=false;alert(e.message);});
    }
    else if(b.dataset.accountEvent){const o=(context.opportunities||[]).find(x=>String(x.id)===b.dataset.accountEvent);if(o)window.abOpenRef(o.source_table==='manual_events'?'manual':'catalog',o.source_key);}
    else if(b.hasAttribute('data-trip-add'))tripForm();
    else if(b.hasAttribute('data-discover'))discover();
  });
  document.addEventListener('change',e=>{if(e.target.id==='ac-owner'){owner=e.target.value;render();}});
  document.addEventListener('input',e=>{if(e.target.id==='ac-search'){const pos=e.target.selectionStart;query=e.target.value;render();const i=document.getElementById('ac-search');i.focus();i.setSelectionRange(pos,pos);}});
  // Record a chase without opening the drawer. Appends to follow_ups (which is
  // also what applicationEvidence() reads as 'chased') and pushes the next due
  // date out a week, so the row leaves this list until it is genuinely due
  // again. opsWrite stamps updated_by/updated_at and goes through sbWriteRetry.
  async function chase(btn,r) {
    if(!r||!window.opsWrite)return;
    const label=btn.textContent;btn.disabled=true;btn.textContent='Saving…';
    const t=today();
    try {
      await Promise.resolve(window.opsWrite(r._table,r._key,{
        follow_ups:[...(r.follow_ups||[]),{date:t,note:'Chased the organiser'}],
        booking:{...(r.booking||{}),follow_up_due:C.plus(t,7)}
      }));
      window.opsRefresh&&window.opsRefresh();load();
    } catch(e) { btn.disabled=false;btn.textContent=label==='Chased today'?'Retry':label; }
  }
  window.ActionCenter={update(records){raw=records;ready=true;recompute();render();},show(){render();if(!this.started){this.started=true;load();window._ab.auth.onAuthStateChange((event)=>{if(event==='SIGNED_OUT'&&dialog)dialog.close();setTimeout(load,0);});}},manage};
})();
