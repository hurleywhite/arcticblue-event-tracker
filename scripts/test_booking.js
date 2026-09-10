const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
const C=require('../src/booking-core.js');const now='2026-09-10';
const base={name:'Buyer forum',start_date:'2026-10-01',end_date:'2026-10-02',location:'Munich, Germany',booking:{}};
const normalize=r=>C.normalize({...base,...r},null,now);
assert.equal(C.day('2026-02-30'),'');assert.equal(C.day('2028-02-29'),'2028-02-29');
assert.equal(C.safeUrl('javascript:alert(1)'),'');
assert.equal(normalize({}).q.score,null);
assert.equal(normalize({}).active,false);
const b={action:'Apply',owner:'Thor',next_action:'Submit proposal',due:'2026-09-15',reason:'Earned stage for healthcare buyers'};
const active=normalize({booking:b});assert.equal(active.active,true);
assert.equal(C.groups([active],now).applications.length,1);
assert.equal(normalize({booking:{...b,owner:''}}).active,false);
const snooze=normalize({booking:{...b,recheck_on:'2026-09-20',recheck_trigger:'CFP opens'}});
assert.equal(snooze.active,false);assert.equal(C.groups([snooze],now).decisions.length,0);
assert.equal(normalize({booking:{recheck_on:now}}).needsDecision,true);
assert.equal(normalize({booking:{...b,action:'Pass'}}).active,false);
assert.equal(normalize({end_date:'2026-09-09',booking:b}).active,false);
assert.equal(normalize({hidden:true,booking:b}).active,false);
assert.equal(normalize({booking:{...b,completed_at:now}}).active,false);
const submitted=normalize({submitted_at:'2026-09-01'});
assert.equal(C.groups([submitted],now).followups.length,1);
assert.equal(C.groups([normalize({submitted_at:'2026-09-01',booking:{organizer_reply_at:now}})],now).followups.length,0);
const evidence=[{kind:'end_user_speakers',url:'https://example.com/speakers',checked:now,note:'Published end-user speakers'}, {kind:'audience_breakdown',url:'https://example.com/audience',checked:now,note:'Published job titles'}];
const qualified=normalize({booking:{buyer_fit:'strong',evidence}});assert.equal(qualified.q.score,50);assert.equal(qualified.q.strong,true);
assert.equal(normalize({booking:{evidence:[...evidence,...evidence]}}).q.score,50);
assert.equal(normalize({booking:{evidence:[{...evidence[0],checked:'2024-01-01'}]}}).q.score,null);
assert.equal(normalize({booking:{evidence:[{...evidence[0],url:'javascript:bad'}]}}).q.score,null);
assert.equal(normalize({name:'Chief AI Officer Summit Boston 2026'}).q.excluded,true);
const m=C.metrics([submitted,normalize({status_tags:['Booked'],booking:{meetings_booked:3,qualified_opportunities:1}})]);
assert.deepEqual(m,{applications:1,replies:0,slots:1,meetings:3,attended:0,opportunities:1,trips:0});
assert.equal(C.sameCity('Munich, Germany','Munich'),true);assert.equal(C.sameCity('London','Munich'),false);assert.equal(C.sameCity('New York','NYC'),true);assert.equal(C.sameCity('TBD','TBD'),false);
const pack=C.tripPack({start_date:'2026-09-28',end_date:'2026-09-30',city:'Munich'},[qualified,normalize({location:'London, UK'})],[{name:'Buyer',city:'Munich'}]);
assert.equal(pack.nearby.length,1);assert.equal(pack.targets.length,1);
assert.equal(C.tripPack({start_date:'2026-11-01',end_date:'2026-11-03',city:'Munich'},[qualified],[]).nearby.length,0);
// ── Derived actions: the Action Center must be populated from the record itself ──
// A real application (date behind it) becomes an Outreach item with owner+due, marked derived.
const realApp=normalize({speaker:'Thor',status_tags:['Submitted'],submitted_at:'2026-09-01'});
assert.equal(realApp.realApplication,true);assert.equal(realApp.action,'Outreach');assert.equal(realApp.derived,true);
assert.equal(realApp.owner,'thor');assert.equal(realApp.active,true);assert.equal(realApp.due,'2026-09-08');
// A bare "Submitted" tag with nothing behind it is a relic: not an application, not a follow-up, not active.
const relic=normalize({speaker:'Thor',status_tags:['Submitted']});
assert.equal(relic.submitted,'tag-only');assert.equal(relic.realApplication,false);assert.equal(relic.active,false);
assert.equal(C.groups([relic],now).followups.length,0);
// A chase, a contact or a note also count as evidence.
assert.equal(normalize({status_tags:['Submitted'],poc_email:'x@y.z'}).realApplication,true);
assert.equal(normalize({status_tags:['Submitted'],notes:'Applied via CFP portal'}).realApplication,true);
// Booked / attending become Attend with the event date as the due date.
const booked=normalize({speaker:'Verma',status_tags:['Booked']});
assert.equal(booked.action,'Attend');assert.equal(booked.due,'2026-10-01');assert.equal(booked.active,true);
assert.equal(normalize({attendees:['jerome'],status_tags:['Attending']}).owner,'jerome');
// A live deadline inside 45 days with a known owner becomes an Apply decision; outside 45 days it doesn't.
assert.equal(normalize({speaker:'Thor',deadline:'2026-10-01'}).action,'Apply');
assert.equal(normalize({speaker:'Thor',deadline:'2027-01-01'}).action,'');
// A typed decision always beats a derived one.
const typed=normalize({speaker:'Thor',submitted_at:'2026-09-01',booking:{action:'Pass',reason:'Not our audience'}});
assert.equal(typed.action,'Pass');assert.equal(typed.derived,false);
// Rejected -> Pass, never active.
assert.equal(normalize({status_tags:['Rejected','Submitted'],submitted_at:'2026-08-01'}).action,'Pass');
// ── cityOf: venue-first locations resolve to a city; a bare venue does not ──
assert.equal(C.cityOf({location:'Hynes Convention Center, Boston, MA'}),'boston');
assert.equal(C.cityOf({location:'Cape Town International Convention Centre, Cape Town, South Africa'}),'cape town');
assert.equal(C.cityOf({location:'New York City, NY'}),'new york');
assert.equal(C.cityOf({location:'Washington, DC'}),'washington');
assert.equal(C.cityOf({location:'22 Bishopsgate'}),'');
assert.equal(C.cityOf({location:'Online'}),'');
assert.equal(C.cityOf({city:'München'}),'munich');
assert.equal(C.sameCity('Olympia London, London, UK','London'),true);
// ── agenda: commitments only, clashes and stacking ──
const A=normalize({name:'A',speaker:'Thor',status_tags:['Booked'],start_date:'2026-10-01',end_date:'2026-10-02',location:'Munich, Germany'});
const B=normalize({name:'B',attendees:['thor'],status_tags:['Attending'],start_date:'2026-10-02',end_date:'2026-10-03',location:'London, UK'});
const Cc=normalize({name:'C',attendees:['thor'],status_tags:['Attending'],start_date:'2026-10-05',end_date:'2026-10-05',location:'Munich, Germany'});
const W=normalize({name:'W',speaker:'Thor',status_tags:['Submitted'],submitted_at:'2026-09-01',start_date:'2026-10-01',location:'Paris, France'});
const V=normalize({name:'V',attendees:['verma'],status_tags:['Attending'],start_date:'2026-10-03',end_date:'2026-10-03',location:'Munich, Germany'});
const ag=C.agenda([A,B,Cc,W,V],now);
assert.equal(ag.people.thor.list.length,3);            // W is a wish, not a commitment
assert.equal(ag.people.thor.clashes.length,1);          // A overlaps B
assert.equal(ag.people.thor.stacks.length,1);           // A and C both Munich within 4 days
assert.equal(ag.cross.length,2);assert.ok(ag.cross.every(c=>c.city==='munich'));  // Verma's Munich day sits within 4 days of BOTH of Thor's Munich events
// ── health ──
const hl=C.health([realApp,relic,booked,W,normalize({speaker:'Thor',status_tags:['Rejected'],submitted_at:'2026-08-01'})],now);
assert.equal(hl.thor.applications,2);assert.equal(hl.thor.rejected,1);assert.equal(hl.verma.booked,1);
// Parse every executable script emitted by the Python f-string generator.
const html=fs.readFileSync('public/index.html','utf8');let count=0;
for(const match of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)){if(/application\/json|src=/.test(match[1]))continue;new vm.Script(match[2]);count++;}
assert.ok(count>=2);assert.ok(html.includes('id="ops-action"'));assert.ok(html.includes("setView(VIEW_NAMES.indexOf(requested) !== -1 ? requested : 'action')"));
const routes=JSON.parse(fs.readFileSync('vercel.json'));assert.equal(routes.redirects.find(r=>r.source==='/').destination,'/events');assert.equal(routes.rewrites.find(r=>r.source==='/events').destination,'/index.html');
console.log('Booking rules, evidence, outcomes, trip matching, routing and '+count+' generated scripts passed.');
