(function() {
  'use strict';
  const C=window.BookingCore, esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let raw=[], rows=[], context={opportunities:[],travel_windows:[],target_accounts:[]}, cal=null, error='', loading=true, ready=false, owner='',mode='today',query='', expanded=new Set(), dialog=null;
  const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const title=s=>String(s||'').replace(/\b\w/g,c=>c.toUpperCase());
  const link=(url,label)=>C.safeUrl(url)?'<a class="ac-link" target="_blank" rel="noopener noreferrer" href="'+esc(C.safeUrl(url))+'">'+esc(label)+'</a>':'';
  const host=()=>document.getElementById('ops-action');
  async function request(path,body) {
    const s=await window._ab.auth.getSession(), token=s.data?.session?.access_token;
    const r=await fetch(path,{method:body?'POST':'GET',headers:{...(body?{'Content-Type':'application/json'}:{}),...(token?{Authorization:'Bearer '+token}:{})},...(body?{body:JSON.stringify(body)}:{})});
    const j=await r.json(); if(!r.ok || j.error)throw Error(j.error || 'Request failed'); return j;
  }
  async function load() {
    loading=true;error='';render();
    const results=await Promise.allSettled([request('/api/opportunities'),request('/api/calendars')]);
    if(results[0].status==='fulfilled')context=results[0].value;else error='Qualification and recorded travel could not load. '+results[0].reason.message;
    if(results[1].status==='fulfilled')cal=results[1].value;else cal={configured:false,unavailable:true};
    loading=false;recompute();render();
  }
  function recompute() {
    const by=new Map((context.opportunities||[]).map(o=>[o.source_table+':'+o.source_key,o]));
    rows=raw.map(r=>C.normalize(r,by.get(r._table+':'+r._key),today())).sort((a,b)=>(a.due||'9999').localeCompare(b.due||'9999') || String(a.name||'').localeCompare(String(b.name||'')));
  }
  function filtered() {return rows.filter(r=>(!owner || C.fold(r.owner).includes(owner)) && (!query || C.fold([r.name,r.location,r.owner,r.b.next_action,r.poc_name].join(' ')).includes(C.fold(query))));}
  function eventRow(r) {
    const action=r.b.next_action || (r.submitted?'Set the next organizer follow-up':r.wake?'Review: '+(r.b.recheck_trigger||'scheduled recheck'):'Choose an action, owner and deadline');
    return '<article class="ac-row"><div><h4>'+esc(r.name)+'</h4><p><span class="ac-badge">'+esc(r.action||'Decision needed')+'</span>'+esc(title(r.owner)||'Owner needed')+' · '+esc(r.location||'Location unknown')+'</p><p>'+esc(action)+'</p><p class="ac-note">'+esc(r.q.label)+' · '+(r.due?'<span class="'+(r.due<today()?'ac-overdue':'')+'">'+(r.due<today()?'Overdue · ':'Due ')+esc(r.due)+'</span>':'Due date needed')+'</p></div><div class="ac-row-actions"><button data-detail="'+esc(r._id)+'">Event details</button><button class="ac-primary" data-manage="'+esc(r._id)+'">'+(r.action?'Update action':'Decide')+'</button></div></article>';
  }
  function section(key,label,list) {
    const show=expanded.has(key)?list:list.slice(0,4);
    return '<section class="ac-section" id="ac-'+key+'"><div class="ac-section-head"><h3>'+esc(label)+' <span class="ac-badge">'+list.length+'</span></h3>'+(list.length>4?'<button data-expand="'+key+'">'+(expanded.has(key)?'Show fewer':'Show all '+list.length)+'</button>':'')+'</div>'+(show.length?show.map(eventRow).join(''):'<p class="ac-empty">Nothing due here.</p>')+'</section>';
  }
  function render() {
    const h=host();if(!h)return;
    const rs=filtered(),g=C.groups(rs,today()),m=C.metrics(rs);
    const tripMatches=(context.travel_windows||[]).filter(t=>t.end_date>=today()&&(!owner||C.fold(t.person_key).includes(owner))).map(t=>C.tripPack(t,rs,context.target_accounts||[])).filter(p=>p.nearby.length);
    const buttons=[['today','Today'],['pipeline','Applications'],['trips','Trips'],['targets','Target accounts'],['background','Background']];
    let html='<div class="ac-head"><div><h2>Action Center</h2><p class="ac-note">'+esc(today())+' · Get the next application, conversation and meeting booked.</p></div><button class="ab-btn" data-refresh>Refresh</button></div>';
    html+='<div class="ac-toolbar">'+buttons.map(([k,v])=>'<button data-mode="'+k+'" aria-pressed="'+(mode===k)+'">'+v+'</button>').join('')+'<select aria-label="Action owner" id="ac-owner"><option value="">All owners</option>'+['thor','verma','jerome','carlos'].map(p=>'<option '+(owner===p?'selected':'')+' value="'+p+'">'+title(p)+'</option>').join('')+'</select><input type="search" id="ac-search" placeholder="Find an event or owner" aria-label="Search action center" value="'+esc(query)+'"></div>';
    if(loading)html+='<p class="ac-note" role="status">Refreshing qualification and travel…</p>';
    if(error)html+='<p class="ac-health">'+esc(error)+'</p>';
    if(!ready)html+='<p class="ac-empty">Loading live event records…</p>';
    else if(mode==='today') {
      html+='<div class="ac-stats">'+[['applications','Applications due in 7 days'],['contacts','Organizers to contact'],['meetings','Meetings to book'],['followups','Follow-ups due'],['decisions','Decisions needed']].map(([k,l])=>'<button class="ac-stat" data-jump="'+k+'"><strong>'+g[k].length+'</strong><span>'+l+'</span></button>').join('')+'</div>';
      html+='<p class="ac-note">'+(tripMatches.length?tripMatches.length+' recorded trips have nearby event opportunities. Open Trips to review.':(!cal?.configured?'Live calendar feeds are not connected. Open Trips to add or review recorded travel.':'No nearby event matches for recorded travel.'))+'</p>';
      html+=section('applications','Applications due soon',g.applications)+section('contacts','Organizer outreach',g.contacts)+section('meetings','Meetings to book',g.meetings)+section('followups','Follow-ups due',g.followups)+section('decisions','Decisions required',g.decisions);
      const later=rs.filter(r=>r.active && !Object.values(g).flat().includes(r));
      html+=section('later','Planned actions',later);
    } else if(mode==='pipeline') {
      html+='<p class="ac-note">Applications and speaking bookings from the original event records. Submission history remains visible after a pass or completed event.</p>';
      html+=section('prepare','Prepare application',rs.filter(r=>!r.past&&!r.hidden&&(r.action==='Apply'||r.recommendation==='Apply')&&!r.submitted&&!r.booked&&!r.sleeping&&r.action!=='Pass'));
      html+=section('submitted','Submitted · awaiting outcome',rs.filter(r=>r.submitted&&!r.booked&&!r.b.organizer_reply_at&&r.action!=='Pass'&&!r.past));
      html+=section('reply','Organizer replied',rs.filter(r=>r.b.organizer_reply_at&&!r.booked&&!r.past));
      html+=section('booked','Speaking slots booked',rs.filter(r=>r.booked));
      html+=section('history','Application history',rs.filter(r=>r.submitted&&(r.past||r.action==='Pass')));
    } else if(mode==='background') {
      html+='<p class="ac-note">Unqualified events, future rechecks and passes stay here until there is a concrete next action. Search this list to bring an event into the working queue.</p>';
      html+=section('background','Background universe',rs.filter(r=>!r.active&&!r.needsDecision&&!r.hidden&&!r.past));
    } else if(mode==='trips') html+=renderTrips(rs);
    else html+=renderTargets();
    if(ready)html+='<section class="ac-section"><h3>Booking outcomes</h3><p class="ac-note">All recorded history'+(owner?' · '+esc(title(owner)):'')+'. Applications, replies and speaking slots count events; meetings and qualified opportunities count recorded totals. Unknown outcomes are not counted.</p><div class="ac-metrics">'+[['applications','Applications sent'],['replies','Organizer replies'],['slots','Speaking slots'],['meetings','Meetings booked'],['attended','Events attended'],['opportunities','Qualified opportunities'],['trips','Trips stacked']].map(([k,l])=>'<div><strong>'+m[k]+'</strong><span>'+l+'</span></div>').join('')+'</div></section>';
    h.innerHTML=html;
  }
  function renderTrips(rs) {
    let html='<p class="ac-note">Match event dates within four days of recorded travel in the same city. Check transport and calendar availability before confirming.</p>';
    if(!cal || !cal.configured)html+='<p class="ac-health">'+(cal?.unavailable?'Calendar connection could not be checked.':'Live calendar feeds are not connected.')+' Recorded trips can still be used. Open time slots cannot be confirmed.</p>';
    else html+='<p class="ac-note">Calendar feeds connected · '+(cal.detail_visible?'private details visible to your editor session.':'sign in as an editor to use private travel locations.')+' Recurring entries are not expanded; verify availability in Calendar.</p>';
    html+='<div class="ac-toolbar"><button data-trip-add>Add recorded trip</button><button data-signin>Editor sign-in</button><button data-calendar>Open event calendar</button></div>';
    let trips=(context.travel_windows||[]).slice();
    (cal?.events||[]).filter(e=>e.kind==='person'&&e.location&&e.all_day&&C.day(e.start)&&C.day(e.end)).forEach(e=>{if(!trips.some(t=>C.fold(t.person_key)===C.fold(e.owner)&&t.start_date===e.start))trips.push({id:'calendar:'+e.owner+':'+e.start,person_key:e.owner,start_date:e.start,end_date:e.end,city:e.location,source:'Live calendar location'});});
    trips=trips.filter(t=>t.end_date>=today()&&(!owner||C.fold(t.person_key).includes(owner)));
    if(!trips.length)html+='<p class="ac-empty">'+(context.editor?'No upcoming travel recorded.':'Sign in to load protected recorded travel.')+'</p>';
    trips.forEach(t=>{const p=C.tripPack(t,rs,context.target_accounts||[]);html+='<article class="ac-trip"><h3>'+esc(title(t.person_key))+' · '+esc(t.city)+'</h3><p class="ac-note">'+esc(t.start_date)+' – '+esc(t.end_date)+' · '+esc(t.source||'Recorded travel')+'</p><h4>Nearby event opportunities</h4>'+(p.nearby.length?p.nearby.map(eventRow).join(''):'<p class="ac-note">No matching events in the current tracker.</p>')+'<h4>Target accounts in this city</h4>'+(p.targets.length?'<ul>'+p.targets.map(a=>'<li>'+esc(a.name)+(a.executive_roles?' · '+esc(a.executive_roles):'')+'</li>').join('')+'</ul>':'<p class="ac-note">No target accounts with a confirmed office city recorded.</p>')+'<p class="ac-note">Plan: request buyer meetings; consider a small dinner, roundtable or podcast with confirmed contacts. Relationship data and open slots are not yet connected.</p><button class="ab-btn" data-trip-search="'+esc(t.id)+'">Find events around this trip</button></article>';});
    window._acTrips=trips;return html;
  }
  function renderTargets() {
    const accounts=context.target_accounts||[];
    return '<p class="ac-note">Discover where target-company CIOs, CAIOs, CTOs, COOs, CDOs and product or innovation leaders speak. Public evidence indicates a likely buyer room; it does not prove attendance.</p><div class="ac-toolbar"><button data-account-add>Add target account</button><button data-discover>Find events for targets</button><button data-signin>Editor sign-in</button></div>'+(!context.editor?'<p class="ac-health">Sign in to manage and search the team’s private target-account list.</p>':'')+(accounts.length?accounts.map(a=>'<article class="ac-row"><div><h4>'+esc(a.name)+'</h4><p>'+esc(a.industry||'Industry not recorded')+' · '+esc(a.city||'Office city not recorded')+' · '+esc(title(a.owner_person))+'</p><p class="ac-note">'+esc(a.executive_roles||'CIO, CAIO, CTO, COO, CDO, CPO, digital transformation, innovation')+'</p></div><button data-account="'+a.id+'">Edit</button></article>').join(''):'<p class="ac-empty">No target accounts loaded. Add the companies the team actually wants to sell to.</p>')+'<div id="ac-discovery-results"></div>';
  }
  function openDialog(name,body) {
    if(dialog)dialog.remove();
    dialog=document.createElement('dialog');dialog.className='ac-dialog';dialog.innerHTML='<h2 id="ac-dialog-title">'+esc(name)+'</h2>'+body;dialog.setAttribute('aria-labelledby','ac-dialog-title');document.body.appendChild(dialog);dialog.showModal();
    dialog.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>dialog.close());
    dialog.addEventListener('close',()=>{dialog.remove();dialog=null;});return dialog;
  }
  const input=(label,name,value,type='text',wide=false)=>'<label class="'+(wide?'ac-wide':'')+'">'+esc(label)+'<input name="'+name+'" type="'+type+'" value="'+esc(value||'')+'" '+(type==='number'?'min="0" max="10000" step="1"':'')+'></label>';
  const area=(label,name,value)=>'<label class="ac-wide">'+esc(label)+'<textarea name="'+name+'">'+esc(value||'')+'</textarea></label>';
  const select=(label,name,value,opts)=>'<label>'+esc(label)+'<select name="'+name+'">'+opts.map(o=>'<option value="'+esc(o)+'" '+(o===value?'selected':'')+'>'+esc(o||'Not set')+'</option>').join('')+'</select></label>';
  const footer=()=>'<p class="ac-error" role="alert"></p><footer><button type="button" data-close>Cancel</button><button class="ac-primary" type="submit">Save</button></footer>';
  function manage(r) {
    const b=r.b;
    let body='<p class="ac-note">'+esc(r.name)+'</p><p class="ac-note">Suggested: '+esc(r.recommendation||'Keep in background until qualified')+'. Public evidence score: '+(r.q.score===null?'Unknown':r.q.score+'/100')+'; this is not an attendee count or probability.</p><form id="ac-edit"><div class="ac-form">';
    body+=select('Decision','action',b.action||'', ['',...C.STATES])+input('Owner','owner',b.owner||r.owner)+input('Next action due','due',b.due||r.due,'date')+input('Application deadline','deadline',C.day(r.deadline),'date')+area('Next action','next_action',b.next_action||r.suggestedNextAction)+area('Reason for this decision','reason',b.reason||r.suggestedReason);
    body+=input('Application link','apply_url',r.apply_url,'url',true)+select('Draft status','draft_status',b.draft_status||'Not started',['Not started','Drafting','Ready','Submitted'])+input('Follow-up due','follow_up_due',b.follow_up_due||r.followup,'date')+area('Application draft / pitch','draft',b.draft);
    body+=input('Recheck on (keeps event in background until then)','recheck_on',b.recheck_on,'date')+input('Recheck trigger','recheck_trigger',b.recheck_trigger)+select('Buyer fit','buyer_fit',b.buyer_fit||'unknown',['unknown','strong','mixed','weak'])+select('Speaking route quality','speaking_quality',b.speaking_quality||'unknown',['unknown','earned','invited','paid','closed'])+input('Exclusion reason','exclusion',b.exclusion,'text',true);
    body+='</div><details><summary>Public buyer-room evidence</summary><p class="ac-note">Keep likely buyers, publicly confirmed speakers/attendees and verified portal attendees separate. Record public sources here. Private attendee lists stay in the authorized portal.</p>'+(b.evidence||[]).map((e,i)=>'<div class="ac-evidence">'+esc(e.kind)+' · '+esc(e.checked)+'<br>'+esc(e.note)+' '+link(e.url,'Source')+' <label><input type="checkbox" name="remove_evidence" value="'+i+'"> Remove</label></div>').join('')+'<div class="ac-form">'+select('New evidence type','evidence_kind','',['','end_user_speakers','audience_breakdown','advisory_board','prior_attendees','sponsors','public_attendance','company_event_page','organizer_claim'])+input('Checked on','evidence_checked',today(),'date')+input('Public source URL','evidence_url','','url',true)+area('What this source confirms','evidence_note','')+'</div></details>';
    body+='<details><summary>Record booking outcomes</summary><p class="ac-note">Only record completed actions and confirmed results.</p><div class="ac-form">'+input('Application submitted','submitted_at',C.day(r.submitted),'date')+input('Organizer replied','organizer_reply_at',b.organizer_reply_at,'date')+input('Speaking slot booked','speaking_booked_at',b.speaking_booked_at,'date')+input('Meetings booked','meetings_booked',b.meetings_booked||0,'number')+input('Attended on','attended_at',b.attended_at,'date')+input('Qualified opportunities','qualified_opportunities',b.qualified_opportunities||0,'number')+input('Associated recorded trip ID','trip_id',b.trip_id)+select('Trip stacking confirmed','trip_confirmed',b.trip_confirmed?'Yes':'No',['No','Yes'])+input('Action completed on','completed_at',b.completed_at,'date')+'</div></details>'+footer()+'</form>';
    const d=openDialog('Manage booking',body), form=d.querySelector('form');
    form.onsubmit=async e=>{
      e.preventDefault();const f=new FormData(form),v=k=>String(f.get(k)||'').trim(),next={...b};
      ['action','owner','due','next_action','reason','draft_status','follow_up_due','draft','recheck_on','recheck_trigger','buyer_fit','speaking_quality','exclusion','organizer_reply_at','speaking_booked_at','attended_at','trip_id','completed_at'].forEach(k=>next[k]=v(k));
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
        const saved=await sb.from(r._table).update(patch).eq(col,r._key).eq('booking',JSON.stringify(b)).select(col);
        if(saved.error)throw saved.error;if(!saved.data?.length)throw Error('This booking changed in another session. Close, refresh and retry.');
        d.close();await window.opsRefresh();
      } catch(ex){err.textContent='Save failed: '+ex.message;btn.disabled=false;}
    };
  }
  function accountForm(account={}) {
    if(!context.editor)return signIn();
    const d=openDialog(account.id?'Edit target account':'Add target account','<form><div class="ac-form">'+input('Company','name',account.name)+input('Industry','industry',account.industry)+input('Confirmed office city','city',account.city)+input('Owner','owner_person',account.owner_person)+input('Executive roles to track','executive_roles',account.executive_roles||'CIO, CAIO, CTO, COO, CDO, CPO, digital transformation, innovation','text',true)+'</div>'+footer()+'</form>');
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.target));await formRequest(d,{action:'save_target_account',...f,...(account.id?{id:account.id}:{})});};
  }
  async function formRequest(d,body) {
    const btn=d.querySelector('[type=submit]');btn.disabled=true;
    try{await request('/api/opportunities',body);d.close();await load();}catch(e){d.querySelector('.ac-error').textContent=e.message;btn.disabled=false;}
  }
  function tripForm() {
    if(!context.editor)return signIn();
    const d=openDialog('Record a confirmed trip','<p class="ac-note">Use travel already in a calendar or confirmed plan.</p><form><div class="ac-form">'+select('Person','person_key',owner||'thor',['thor','verma','jerome','carlos'])+input('City','city','')+input('Starts','start_date','','date')+input('Ends','end_date','','date')+input('Source (calendar or confirmed plan)','source','','text',true)+'</div>'+footer()+'</form>');
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();await formRequest(d,{action:'add_travel_window',...Object.fromEntries(new FormData(e.target))});};
  }
  function signIn() {
    const d=openDialog('Editor sign-in','<p class="ac-note">Target accounts and private travel use the tracker’s existing approved-editor access.</p><form><div class="ac-form">'+input('Work email','email','','email',true)+'</div><p class="ac-error" role="status"></p><footer><button type="button" data-close>Close</button><button type="submit" class="ac-primary">Send sign-in link</button></footer></form>');
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();const btn=d.querySelector('[type=submit]');btn.disabled=true;const res=await window._ab.auth.signInWithOtp({email:new FormData(e.target).get('email'),options:{emailRedirectTo:location.origin+'/events'}});d.querySelector('.ac-error').textContent=res.error?res.error.message:'Check your inbox for the sign-in link.';btn.disabled=false;};
  }
  async function discover(trip) {
    const accounts=context.target_accounts||[];
    if(!trip&&!accounts.length){if(!context.editor)return signIn();return accountForm();}
    const d=openDialog('Discover qualified events','<p class="ac-note">Searching public sources for buyer evidence and actionable booking routes…</p><div id="ac-found"></div><footer><button data-close>Close</button></footer>');
    try {
      const result=await request('/api/search',{count:5,target_accounts:accounts.map(a=>({name:a.name,roles:a.executive_roles})),...(trip?{location:trip.city,date_from:trip.start_date,date_to:trip.end_date}:{})});
      if(!d.isConnected)return;
      d.querySelector('.ac-note').textContent='Review public evidence before adding. New discoveries enter the background universe until a booking decision is made.';
      d.querySelector('#ac-found').innerHTML=(result.events||[]).map((ev,i)=>'<div class="ac-evidence"><h3>'+esc(ev.name)+'</h3><p>'+esc(ev.date_str)+' · '+esc(ev.location)+'</p><p>'+esc(ev.reasoning||ev.why)+'</p>'+link(ev.url,'Event source')+' <button data-add-result="'+i+'">Add to background</button></div>').join('')||'<p>No new matches found.</p>';
      d.querySelectorAll('[data-add-result]').forEach(btn=>btn.onclick=async()=>{btn.disabled=true;try{const ev=result.events[Number(btn.dataset.addResult)],res=await window.opsCreateManual({name:ev.name,date_str:ev.date_str,...(window.opsDeriveDates?window.opsDeriveDates(ev.date_str):{}),location:ev.location,region:ev.region,type:ev.type,why:ev.why,url:C.safeUrl(ev.url)||null,priority:'Low',booking:{discovery_source:'Target-account/trip search',reason:ev.reasoning||ev.why||''}});if(res?.error)throw res.error;btn.textContent='Added';}catch(e){btn.disabled=false;btn.textContent='Retry: '+e.message;}});
    }catch(e){if(d.isConnected)d.querySelector('.ac-note').textContent='Search failed: '+e.message;}
  }
  document.addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b || !b.closest('#ops-action'))return;
    if(b.dataset.mode){mode=b.dataset.mode;render();}
    else if(b.hasAttribute('data-refresh')){window.opsRefresh();load();}
    else if(b.dataset.expand){expanded.has(b.dataset.expand)?expanded.delete(b.dataset.expand):expanded.add(b.dataset.expand);render();}
    else if(b.dataset.jump)document.getElementById('ac-'+b.dataset.jump)?.scrollIntoView({behavior:'smooth'});
    else if(b.dataset.manage){const r=rows.find(r=>r._id===b.dataset.manage);if(r)manage(r);}
    else if(b.dataset.detail){const r=rows.find(r=>r._id===b.dataset.detail);if(r)window.abOpenRef(r._table==='manual_events'?'manual':'catalog',r._key);}
    else if(b.hasAttribute('data-signin'))signIn();
    else if(b.hasAttribute('data-account-add'))accountForm();
    else if(b.dataset.account)accountForm(context.target_accounts.find(a=>String(a.id)===b.dataset.account));
    else if(b.hasAttribute('data-trip-add'))tripForm();
    else if(b.hasAttribute('data-calendar'))window.abBookingView('calendar');
    else if(b.hasAttribute('data-discover'))discover();
    else if(b.dataset.tripSearch)discover(window._acTrips.find(t=>String(t.id)===b.dataset.tripSearch));
  });
  document.addEventListener('change',e=>{if(e.target.id==='ac-owner'){owner=e.target.value;render();}});
  document.addEventListener('input',e=>{if(e.target.id==='ac-search'){const pos=e.target.selectionStart;query=e.target.value;render();const i=document.getElementById('ac-search');i.focus();i.setSelectionRange(pos,pos);}});
  window.ActionCenter={update(records){raw=records;ready=true;recompute();render();},show(){render();if(!this.started){this.started=true;load();window._ab.auth.onAuthStateChange(()=>setTimeout(load,0));}},manage};
})();
