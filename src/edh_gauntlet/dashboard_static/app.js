const $=s=>document.querySelector(s);let timer=null;const state={api:sessionStorage.edhApi||location.origin,key:sessionStorage.edhKey||'',run:sessionStorage.edhRun||''};$('#api').value=state.api;$('#key').value=state.key;
async function call(path,options={}){const response=await fetch(state.api.replace(/\/$/,'')+path,{...options,headers:{Authorization:'Bearer '+state.key,'Content-Type':'application/json',...(options.headers||{})}}),data=await response.json();if(!response.ok)throw Error(data.error||response.statusText);return data}const pretty=v=>JSON.stringify(v||{},null,2),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function runs(){const data=await call('/api/runs'),select=$('#runs');select.innerHTML=data.runs.map(r=>`<option value="${esc(r.id)}">${esc(r.id)} · ${esc(r.state)}</option>`).join('');if(state.run&&data.runs.some(r=>r.id===state.run))select.value=state.run;else state.run=select.value||'';if(state.run)await refresh()}
async function refresh(){if(!state.run)return;const run=state.run,s=await call('/api/runs/'+run);if(state.run!==run)return;sessionStorage.edhRun=run;render(s);if(!$('#cardwise').hidden)await refreshCardwise();$('#connection').textContent='Dashboard connected';$('#connection').style.color='var(--mint)'}
function render(s){
 $('#start').textContent=s.supervisor?.enabled?'Start supervisor':'Start host';
 const st=s.status||{},request=st.request||{},a=s.next_action||{},ps=st.public_state||{};
 $('#headline').textContent=`Game ${String(s.game).padStart(2,'0')} · ${s.pause?.reason?'Paused':s.state.replaceAll('_',' ')}`;$('#subhead').textContent=`Active: ${ps.active||'—'} · Priority/decision: ${request.actor||a.actor||'—'}`;$('#turn').textContent=ps.round!==undefined?`Round ${ps.round} · Turn ${ps.turn_number||0} · ${{precombat_main:'First main phase',postcombat_main:'Second main phase'}[ps.phase]||(ps.phase||'').replaceAll('_',' ')}`:'';
 $('#metrics').innerHTML=[['Decisions',st.decision_count||0],['Game',s.game],['Host',s.host.alive?'online':'stopped'],['Learning',s.config.learning_enabled===false?'off':'on']].map(([k,v])=>`<div class="metric"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('');renderLive(s,request,a,ps);
 $('#next').textContent=pretty(request.actor?request:a);$('#config').textContent=pretty(s.config);$('#host').textContent=pretty({host:s.host,supervisor:s.supervisor})+'\n\n'+s.auth_mode;$('#status').textContent=pretty(st);renderMessages(s.messages||[]);renderDecisions(s);renderResults(s);

 const players=Object.keys(s.operator||{}),seat=$('#seatSelect'),prior=seat.value;seat.innerHTML=players.map(p=>`<option value="${esc(p)}">${esc(p)}</option>`).join('');if(players.includes(prior))seat.value=prior;$('#player').textContent=players.length?s.operator[seat.value||players[0]]:'Operator snapshots appear after the first checkpoint.';seat.onchange=()=>$('#player').textContent=s.operator[seat.value];
}
async function action(fn){try{$('#error').textContent='';await fn()}catch(e){$('#error').textContent=e.message}}
$('#connectButton').onclick=()=>action(async()=>{state.api=$('#api').value.trim();state.key=$('#key').value.trim();sessionStorage.edhApi=state.api;sessionStorage.edhKey=state.key;await runs();$('#connect').hidden=true;$('#app').hidden=false;clearInterval(timer);timer=setInterval(()=>action(refresh),2000)});$('#runs').onchange=()=>action(async()=>{state.run=$('#runs').value;await refresh()});$('#refresh').onclick=()=>action(refresh);$('#start').onclick=()=>action(async()=>{await call(`/api/runs/${state.run}/start`,{method:'POST',body:'{}'});await refresh()});$('#pause').onclick=()=>action(async()=>{await call(`/api/runs/${state.run}/pause`,{method:'POST',body:'{}'});await refresh()});
$('#create').onclick=()=>action(async()=>{const body={id:$('#runId').value.trim()||undefined,games:+$('#games').value,seed_start:+$('#seed').value,max_rounds:+$('#rounds').value,learning:$('#learning').value,async_diplomacy:$('#diplomacy').checked},made=await call('/api/runs',{method:'POST',body:JSON.stringify(body)});state.run=made.id;await runs();document.querySelector('[data-tab="live"]').click()});document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('.tab').forEach(x=>x.hidden=x.id!==b.dataset.tab);if(b.dataset.tab==='cardwise')action(refreshCardwise)});

let lastMessages='',ratingData=null,ratingRun='',ratingRequests=new Set(),lastRatingRows='';
function renderMessages(messages){
 const serialized=JSON.stringify(messages);if(serialized===lastMessages)return;lastMessages=serialized;
 const log=$('#messages'),atBottom=log.scrollHeight-log.scrollTop-log.clientHeight<40,position=log.scrollTop;
 log.innerHTML=messages.length?messages.map(m=>`<div class="chat-row"><strong class="chat-sender">${esc(m.sender)}</strong> <span class="chat-time">T${esc(m.turn)} · ${esc(m.phase.replaceAll('_',' '))}</span> <span class="chat-text">${esc(m.message)}</span></div>`).join(''):'<p class="muted">No public messages have been posted.</p>';
 log.scrollTop=atBottom?log.scrollHeight:position;
}
async function refreshCardwise(){
 if(!state.run)return;
 if(ratingRun!==state.run){ratingData=null;lastRatingRows='';ratingRun=state.run;$('#cardRatings').innerHTML='';$('#cardwiseSummary').textContent='Loading Aminatou’s cards…';$('#cardwisePending').textContent='';$('#cardwiseExcluded').textContent='';}
 if(ratingRequests.has(state.run))return;
 const run=state.run;ratingRequests.add(run);
 try{const data=await call(`/api/runs/${run}/cardwise`);if(state.run!==run)return;ratingData=data;
  $('#cardwiseSummary').textContent=`${data.commander} · ${data.deck_size} cards (${data.rows.length} distinct names) · ${data.completed_games} included games`;
  $('#cardwisePending').textContent=`${data.pending_games} game(s) in progress · ${data.excluded_games.length} completed game(s) excluded pending review or verification. CSV and table use the same included games.`;
  $('#seenDefinition').textContent='Seen: '+data.seen_definition;$('#castDefinition').textContent='ETB/cast: '+data.cast_definition;$('#resultDefinition').textContent=data.result_definition;
  $('#cardwiseExcluded').textContent=data.excluded_games.map(g=>`${g.game}: ${g.reason}`).join(' ');renderCardwiseRows();
 }finally{ratingRequests.delete(run);}
}
function renderCardwiseRows(){
 if(!ratingData)return;const query=$('#cardSearch').value.trim().toLowerCase(),percent=n=>n===null?'':n.toFixed(1)+'%';
 const rows=ratingData.rows.filter(r=>r.card.toLowerCase().includes(query));
 const serialized=JSON.stringify(rows);if(serialized===lastRatingRows)return;lastRatingRows=serialized;
 $('#cardRatings').innerHTML=rows.map(r=>`<tr><th scope="row">${esc(r.card)}${r.quantity>1?` <span class="muted">×${r.quantity}</span>`:''}${r.commander?' <span class="commander-label">Commander</span>':''}</th><td>${r.games_seen}</td><td>${r.games_etb_cast}</td><td>${percent(r.won_if_seen)}</td><td>${percent(r.won_if_cast)}</td></tr>`).join('')||'<tr><td colspan="5">No matching cards.</td></tr>';
}
$('#cardSearch').oninput=renderCardwiseRows;

const human=v=>String(v||'').replaceAll('_',' ');
function decisionRow(d,reason=true){return `<div class="decision-row"><div><strong class="chat-sender">${esc(d.actor)}</strong><span class="chat-time">${esc(d.id)}</span></div><div class="decision-action">${esc(d.action)}</div>${reason&&d.rationale?`<details><summary>Why this choice</summary><p class="prose">${esc(d.rationale)}</p></details>`:''}</div>`}
let lastDecisions='',lastEvents='';
function renderDecisions(s){
 const rows=s.decision_log||[],key=JSON.stringify([s.id,s.game,rows]);if(key===lastDecisions)return;lastDecisions=key;
 const log=$('#decisions'),bottom=log.scrollHeight-log.scrollTop-log.clientHeight<40,position=log.scrollTop;
 log.innerHTML=rows.map(d=>decisionRow(d)).join('')||'<p class="muted">No accepted decisions yet.</p>';
 $('#decisionLogCount').textContent=`${s.decision_log_total||0} accepted choices · showing the latest ${rows.length}. Reasons are private operator information.`;
 log.scrollTop=bottom?log.scrollHeight:position;
}
function renderLive(s,request,action,board){
 const notice=$('#runNotice');const between=s.pending_game?`Game ${s.game} has ended. Game ${s.pending_game} has not started. ${s.supervisor?.alive?'Supervisor online.':'Automatic continuation is offline.'}`:'';notice.hidden=!s.pause?.reason&&!between;notice.textContent=s.pause?.reason==='rules_audit'?'Paused for a rules review. No decisions are being submitted.':s.pause?.reason?'Play is paused.':between;
 const health=s.runtime_health||{};$('#runtimeHealth').innerHTML=`<p class="muted">${esc(health.scope||'No telemetry available.')}</p><p>Largest input: ${esc(health.largest_input||0)} tokens · ${esc(health.inputs_over_64k||0)} samples above 64k</p><p>Duplicate tool request IDs: ${esc(health.duplicate_request_ids||0)} · rejected tool calls: ${esc(health.rejected_tools||0)}</p>`;

 const actor=request.actor||action.actor,live=action.kind==='dispatch_pilot'&&!!request.actor;
 $('#decisionOwner').textContent=live?`${actor} · ${s.host.alive?'Deciding now':'Waiting — host stopped'}`:human(action.kind||s.state);
 $('#decisionPrompt').textContent=live?(request.prompt||human(request.kind)):(s.status?.result?.winner?`${s.status.result.winner} wins`:human(action.reason||s.state));
 const options=live?(request.options||[]):[];
 $('#choiceSummary').textContent=`${options.length} available choices${request.allow_pass?' · passing allowed':''}`;
 $('#decisionOptions').innerHTML=options.map(o=>`<li>${esc(typeof o==='string'?o:'Structured choice — see Run record')}</li>`).join('');
 const stack=board.stack||[];
 $('#stackSummary').textContent=Array.isArray(stack)&&stack.length?`On the stack: ${stack.map(x=>typeof x==='string'?x:x.label||x.name||x.source||'Ability').join(' → ')}`:'Stack empty';
 $('#planTitle').textContent=actor?`${actor} — short-term plan`:'Short-term plan';
 $('#decidingPlan').textContent=live?(s.deciding_plan||'No short-term plan has been published yet.'):'No pending pilot decision.';
 $('#table').innerHTML=Object.entries(board.players||{}).map(([name,p])=>`<div class="seat-card ${name===actor?'deciding-seat':''}"><div class="seat-heading"><strong>${esc(name)}</strong><b>${esc(p.life??'—')} <small>life</small></b></div><p class="muted">${p.eliminated?'Eliminated':name===actor?'Considering this decision':name===board.active?'Active turn':'Waiting'} · ${esc(p.hand_count??p.hand?.length??'?')} cards in hand</p><div class="permanent-list">${(p.battlefield||[]).map(q=>`<span class="permanent ${q.tapped?'tapped':''}">${esc(q.copy_of?`${q.name} (copy of ${q.copy_of})`:q.name)}${q.tapped?' ↷':''}</span>`).join('')||'<span class="muted">No permanents</span>'}</div></div>`).join('')||'<p>No checkpoint yet.</p>';
 const recent=(s.decision_log||[]).slice(-6).reverse(),eventKey=JSON.stringify([s.id,s.game,recent]);
 if(eventKey!==lastEvents){lastEvents=eventKey;$('#events').innerHTML=recent.map(d=>decisionRow(d)).join('')||'<p>No accepted decisions yet.</p>';}
}
$('#downloadDecisions').onclick=()=>action(async()=>{const run=state.run,data=await call(`/api/runs/${run}/decisions`),url=URL.createObjectURL(new Blob([data.markdown],{type:'text/markdown'})),link=document.createElement('a');link.href=url;link.download=`${run}-game-${data.game}-decisions.md`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});

let lastResults='';
function renderResults(s){
 const rows=s.game_results||[],key=JSON.stringify([s.id,rows]);if(key===lastResults)return;lastResults=key;
 $('#gameResults').innerHTML=rows.map(r=>`<section class="decision-row"><h3>Run ${esc(s.id)} · Game ${esc(r.game)}</h3><p><strong>${r.outcome==='in_progress'?'In progress':r.winner?'Winner: '+esc(r.winner):'Draw — no winner'}</strong>${r.losers?.length?' · Losers: '+r.losers.map(esc).join(', '):''}</p>${r.rules_review_pending?'<p class="muted">Rules review pending — recorded result is not yet verified for Cardwise.</p>':''}<p class="prose">${r.narrative?esc(r.narrative):r.outcome==='in_progress'?'Recap will be written after the game ends.':'Supervisor recap pending.'}</p>${r.author?`<small class="muted">${esc(r.author)}</small>`:''}${r.ai_outcome_estimate?`<p><strong>AI estimate: ${esc(r.ai_outcome_estimate.estimated_winner||'Indeterminate')}</strong> · ${esc(r.ai_outcome_estimate.confidence)} confidence</p><p class="prose">${esc(r.ai_outcome_estimate.rationale)}</p><p class="muted">${esc(r.ai_outcome_estimate.uncertainty)} Separate estimate; excluded from verified win rates.</p>`:''}</section>`).join('')||'<p>No game records yet.</p>';
}
$('#downloadCardwise').onclick=()=>action(async()=>{
 const response=await fetch(state.api.replace(/\/$/,'')+`/api/runs/${state.run}/cardwise.csv`,{headers:{Authorization:'Bearer '+state.key}});
 if(!response.ok)throw Error('CSV download failed');const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=state.run+'-cardwise.csv';link.click();URL.revokeObjectURL(url);
});

$('#downloadResults').onclick=()=>action(async()=>{
 const response=await fetch(state.api.replace(/\/$/,'')+`/api/runs/${state.run}/results.csv`,{headers:{Authorization:'Bearer '+state.key}});
 if(!response.ok)throw Error('Results download failed');const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=state.run+'-results.csv';link.click();URL.revokeObjectURL(url);
});
