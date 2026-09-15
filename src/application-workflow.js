(function(root) {
  'use strict';
  function buildDraft(event, d) {
    const recipient=(d.contact_name||'').trim().split(/\s+/)[0]||'there';
    const signature={thor:'Thor',verma:'Verma',jerome:'Jerome',carlos:'Carlos'}[d.owner]||d.owner||'[Your name]';
    const context=d.relationship_context ? d.relationship_context+'\n\n' : '';
    const angle=d.angle ? d.angle+'\n\n' : '';
    let subject,body;
    if(d.route==='Warm introduction') {
      subject='Introduction to the '+event.name+' team';
      body='Hi '+recipient+',\n\n'+context+'I’m exploring a speaking opportunity at '+event.name+' for ArcticBlue.\n\n'+angle+(d.ask||'Would you be comfortable introducing me to the person who shapes the program?')+'\n\nHappy to send a short note you can forward.\n\n'+signature;
    } else if(d.route==='Follow-up') {
      subject='Following up — '+event.name;
      body='Hi '+recipient+',\n\n'+context+'Following up on my earlier note about '+event.name+'.\n\n'+angle+(d.ask||'Is this still worth exploring with your team?')+'\n\n'+signature;
    } else if(d.route==='Meeting request') {
      subject='A conversation around '+event.name;
      body='Hi '+recipient+',\n\n'+context+'I’m looking to connect with people working on product and AI adoption around '+event.name+'.\n\n'+angle+(d.ask||'Would a brief conversation be useful?')+'\n\n'+signature;
    } else {
      subject='Speaker idea for '+event.name;
      body='Hi '+recipient+',\n\n'+context+'I’m reaching out from ArcticBlue about a possible contribution to '+event.name+'.\n\n'+angle+(d.ask||'Would this fit a session you’re planning, and who is the best person to discuss it with?')+'\n\n'+signature;
    }
    return {subject,body};
  }
  if(typeof module!=='undefined')module.exports={buildDraft};
  if(typeof document==='undefined')return;
  const C=root.BookingCore;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  async function open(r,ui) {
    if(!ui.editor)return ui.signIn();
    const {request,input,area,select,openDialog}=ui;
    const popup=openDialog('Application & outreach','<p role="status">Loading the private workspace…</p>');
    let result;
    try {result=await request('/api/workflow?source_table='+r._table+'&source_key='+r._key);}
    catch(e){popup.innerHTML='<h2>Application & outreach</h2><p>'+esc(e.message)+'</p><button data-close>Close</button>';popup.querySelector('button').onclick=()=>popup.close();return;}
    if(!popup.isConnected)return;
    let saved=result.workspace,version=saved?.version||0;
    const d={owner:r.owner||'',contact_name:r.poc_name||'',contact_email:r.poc_email||'',contact_source:r.url||'',route:r.realApplication?'Follow-up':'Speaker pitch',status:'Not started',...(saved?.document||{})};
    popup.classList.add('ac-workspace');
    popup.innerHTML='<h2>Application & outreach</h2><p>'+esc(r.name)+'</p><p class="ac-note">Contacts and drafts are visible to approved editors. Review and send from your email app or Attio.</p><div class="ac-workflow-steps"><span>1 · Check fit</span><span>2 · Find a route in</span><span>3 · Draft</span><span>4 · Follow through</span></div><p class="ac-health">'+esc(r.q.label)+(r.deadline?' · Deadline: '+esc(r.deadline):' · Application deadline unverified')+'</p><div class="ac-toolbar">'+(C.safeUrl(r.apply_url)?'<a class="ac-link" href="'+esc(C.safeUrl(r.apply_url))+'" target="_blank" rel="noopener noreferrer">Open application form</a>':'<span class="ac-note">Add a verified application link in Manage booking.</span>')+'<button type="button" data-fit>Manage booking / fit</button></div><form><div class="ac-form">'+select('Who is this for?','owner',d.owner,['','thor','verma','jerome','carlos'])+select('Outreach route','route',d.route,['Speaker pitch','Warm introduction','Follow-up','Meeting request'])+'</div><section class="ac-section"><h3>Find a route in</h3><p class="ac-note">Search Attio for a known person or email domain. A CRM match does not prove a warm relationship or event attendance.</p><div class="ac-toolbar"><input aria-label="Search Attio" placeholder="Name, company domain or email"><button type="button" data-search-attio '+(!result.attio_configured?'disabled':'')+'>Search Attio</button><button type="button" data-connect-attio>'+(result.attio_configured?'Manage Attio':'Connect Attio')+'</button></div><div data-contact-results></div><div class="ac-form">'+input('Contact name','contact_name',d.contact_name)+input('Contact email','contact_email',d.contact_email,'email')+input('Role','contact_role',d.contact_role)+input('Company / organizer','contact_company',d.contact_company)+input('Contact source','contact_source',d.contact_source,'text',true)+input('Who can make the introduction?','warm_via',d.warm_via,'text',true)+area('Verified relationship context (included in draft)','relationship_context',d.relationship_context)+'</div><p data-attio-link></p></section><section class="ac-section"><h3>Prepare the message</h3><div class="ac-form">'+area('Specific angle and value for this audience','angle',d.angle)+area('What are you asking for?','ask',d.ask)+'</div><div class="ac-toolbar"><button type="button" data-build-draft>Build draft from these details</button></div><div class="ac-form">'+input('Subject','subject',d.subject,'text',true)+area('Email draft','body',d.body)+'</div><div class="ac-toolbar"><button type="button" data-copy>Copy email</button><a class="ac-link" data-compose>Open in email app</a></div><p class="ac-note">Copying or opening a draft does not mark it sent. For Attio, copy the draft and open the selected contact’s record.</p></section><section class="ac-section"><h3>Follow through</h3><div class="ac-form">'+select('Outreach status','status',d.status,['Not started','Drafting','Ready','Sent','Replied','Closed'])+input('Next follow-up','follow_up_due',d.follow_up_due,'date')+input('Actually sent on','sent_at',d.sent_at,'date')+input('Reply received on','reply_at',d.reply_at,'date')+'</div></section><p class="ac-error" role="status"></p><footer><button type="button" data-close>Close</button><button type="submit" class="ac-primary">Save workspace</button></footer></form>';
    const form=popup.querySelector('form'),err=popup.querySelector('.ac-error');
    let attio={attio_record_id:d.attio_record_id||'',attio_url:d.attio_url||''},dirty=false;
    const read=()=>({...Object.fromEntries(new FormData(form)),...attio});
    const status=s=>{err.textContent=s;};
    function updateLinks() {
      const v=read(),a=popup.querySelector('[data-compose]');
      const email=/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(v.contact_email||'')?v.contact_email:'';
      a.removeAttribute('href');a.setAttribute('aria-disabled','true');
      if(email&&v.body){a.href='mailto:'+encodeURIComponent(email)+'?subject='+encodeURIComponent(v.subject||'')+'&body='+encodeURIComponent(v.body);a.setAttribute('aria-disabled','false');}
      const url=C.safeUrl(attio.attio_url);
      popup.querySelector('[data-attio-link]').innerHTML=url&&new URL(url).hostname==='app.attio.com'?'<a class="ac-link" href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">Open contact in Attio</a>':'';
    }
    form.addEventListener('input',()=>{dirty=true;updateLinks();});
    form.addEventListener('change',()=>{dirty=true;updateLinks();});
    popup.querySelector('[data-close]').onclick=()=>popup.close();
    popup.querySelector('[data-fit]').onclick=()=>{if(dirty){status('Save your workspace before opening Manage booking.');return;}popup.close();ui.manage(r);};
    popup.querySelector('[data-connect-attio]').onclick=()=>{if(dirty){status('Save your workspace before managing the connection.');return;}popup.close();connections('attio',ui);};
    popup.querySelector('[data-build-draft]').onclick=()=>{
      const v=read();if(!v.owner||!v.angle){status('Choose an owner and add a specific angle before drafting.');return;}
      if(v.body&&popup.querySelector('[data-build-draft]').textContent!=='Replace the current draft'){
        popup.querySelector('[data-build-draft]').textContent='Replace the current draft';status('Your current text will be replaced. Click again to confirm.');return;
      }
      const draft=buildDraft(r,v);form.elements.subject.value=draft.subject;form.elements.body.value=draft.body;
      form.elements.status.value='Drafting';dirty=true;updateLinks();status('Draft prepared. Review the wording and factual claims, then save.');popup.querySelector('[data-build-draft]').textContent='Build draft from these details';
    };
    popup.querySelector('[data-copy]').onclick=async()=>{const v=read();if(!v.body){status('Prepare a draft first.');return;}try{await navigator.clipboard.writeText('Subject: '+v.subject+'\n\n'+v.body);status('Copied. Outreach status is unchanged.');}catch(e){status('Copy was blocked. Select the draft text and copy it manually.');}};
    popup.querySelector('[data-search-attio]').onclick=async e=>{
      const button=e.currentTarget;button.disabled=true;status('Searching Attio…');
      try {
        const data=await request('/api/workflow',{action:'search_contacts',query:popup.querySelector('[aria-label="Search Attio"]').value});
        const results=popup.querySelector('[data-contact-results]');
        results.innerHTML=data.contacts.length?data.contacts.map(c=>'<button type="button" class="ac-contact-result" data-record="'+esc(c.record_id)+'">'+esc(c.name)+' · Review contact</button>').join(''):'<p>No matching people found. Try an email domain or enter a verified contact below.</p>';
        results.querySelectorAll('[data-record]').forEach(b=>b.onclick=async()=>{
          b.disabled=true;
          try {const {contact:c}=await request('/api/workflow',{action:'get_contact',record_id:b.dataset.record});
            for(const [field,value] of Object.entries({contact_name:c.name,contact_email:c.email,contact_role:c.role,contact_source:c.attio_url||'Attio record'}))form.elements[field].value=value||'';
            attio={attio_record_id:c.record_id,attio_url:c.attio_url};dirty=true;updateLinks();status('Contact selected. Verify the relationship and whether this person can help with the event.');
          }catch(ex){status(ex.message);}finally{b.disabled=false;}
        });status('');
      }catch(ex){status(ex.message);}finally{button.disabled=false;}
    };
    form.onsubmit=async e=>{
      e.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;
      try{const data=await request('/api/workflow',{action:'save_workspace',source_table:r._table,source_key:String(r._key),version,document:read()});version=data.workspace.version;dirty=false;status('Workspace saved.');ui.reload();}
      catch(ex){status(ex.message);}finally{button.disabled=false;}
    };updateLinks();
  }

  function connections(kind,ui) {
    if(!ui.editor)return ui.signIn();
    const {input,select,openDialog,request}=ui,isAttio=kind==='attio';
    const d=openDialog(isAttio?'Connect Attio':'Connect a travel calendar','<p class="ac-note">'+(isAttio?'Use an Attio token with record and object read permissions. This connection searches contacts; it does not send emails or change CRM records.':'Connect a calendar you are authorized to use for team travel planning. In Google Calendar settings, choose the calendar → Integrate calendar → Secret address in iCal format. A travel-only calendar limits what is shared.')+'</p><form><div class="ac-form">'+(isAttio?input('Attio access token','token','','password',true):select('Whose calendar?','person',kind,['thor','verma','jerome'])+input('Secret iCal address','url','','password',true))+'</div><p class="ac-note">Saved on the server and available only to the integration. Secret values are never returned to the browser. Calendar locations and contacts are visible only to approved editors.</p><p class="ac-error" role="status"></p><footer><button type="button" data-disconnect>Disconnect saved connection</button><button type="button" data-close>Close</button><button type="submit" class="ac-primary">Verify & connect</button></footer></form>');
    const f=d.querySelector('form'),err=d.querySelector('.ac-error');
    f.querySelector('input').setAttribute('autocomplete','off');
    f.onsubmit=async e=>{e.preventDefault();const b=f.querySelector('[type=submit]');b.disabled=true;err.textContent='Checking connection…';try{await request('/api/workflow',{action:isAttio?'connect_attio':'connect_calendar',...Object.fromEntries(new FormData(f))});f.querySelector('input').value='';d.close();ui.reload();}catch(ex){err.textContent=ex.message;b.disabled=false;}};
    d.querySelector('[data-disconnect]').onclick=async e=>{const b=e.currentTarget;b.disabled=true;try{await request('/api/workflow',{action:'disconnect',key:isAttio?'attio':'calendar:'+f.elements.person.value});d.close();ui.reload();}catch(ex){err.textContent=ex.message;b.disabled=false;}};
  }

  function importCalendar(ui) {
    if(!ui.editor)return ui.signIn();
    const d=ui.openDialog('Review trips from a calendar export','<p class="ac-note">Upload one person’s .ics calendar export. Only reviewed city/date windows are saved as trips. Calendar contents are not retained.</p><form><div class="ac-form">'+ui.select('Whose calendar?','person','thor',['thor','verma','jerome'])+'<label>Calendar export<input type="file" name="file" accept=".ics,text/calendar" required></label></div><p class="ac-error" role="status"></p><footer><button type="button" data-close>Close</button><button type="submit" class="ac-primary">Find possible trips</button></footer></form><div data-preview></div>');
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();const form=e.target,b=form.querySelector('[type=submit]'),err=d.querySelector('.ac-error');b.disabled=true;try{const file=form.elements.file.files[0];if(!file||file.size>1900000)throw Error('Choose an .ics file smaller than 1.9 MB.');const data=await ui.request('/api/workflow',{action:'preview_calendar',person:form.elements.person.value,ics:await file.text()});ui.previewCandidates=data.candidates;const box=d.querySelector('[data-preview]');box.innerHTML='<p>'+data.candidates.length+' possible trips · '+data.recurring_skipped+' recurring entries skipped. Check these in Calendar.</p>'+data.candidates.map((c,i)=>'<div class="ac-row"><p>'+esc(c.city)+' · '+esc(c.start_date)+' – '+esc(c.end_date)+'</p><button data-preview-trip="'+i+'">Review dates & save</button></div>').join('');box.querySelectorAll('[data-preview-trip]').forEach(b=>b.onclick=()=>reviewTrip(data.candidates[Number(b.dataset.previewTrip)],ui));err.textContent='';}catch(ex){err.textContent=ex.message;}finally{b.disabled=false;}};
  }

  function reviewTrip(t,ui) {
    if(!ui.editor)return ui.signIn();
    const d=ui.openDialog('Review calendar trip','<p class="ac-note">'+esc(t.title||t.source)+'. Confirm the destination and actual travel window. A calendar marker does not establish availability.</p><form><div class="ac-form">'+ui.select('Person','person_key',t.person_key,['thor','verma','jerome'])+ui.input('Destination city','city',t.city)+ui.input('Travel starts','start_date',t.start_date,'date')+ui.input('Travel ends','end_date',t.end_date,'date')+'</div><p class="ac-error" role="status"></p><footer><button type="button" data-close>Close</button><button type="submit" class="ac-primary">Save reviewed trip</button></footer></form>');
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('[type=submit]');b.disabled=true;try{await ui.request('/api/workflow',{action:'save_trip',...Object.fromEntries(new FormData(e.target)),source_event_id:t.source_event_id});d.close();ui.reload();}catch(ex){d.querySelector('.ac-error').textContent=ex.message;b.disabled=false;}};
  }
  root.ApplicationWorkflow={open,connections,importCalendar,reviewTrip,buildDraft};
})(typeof window==='undefined'?this:window);
