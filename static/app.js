const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const req=async(path,options={})=>{const r=await fetch('/api'+path,options);const text=await r.text();let data;try{data=JSON.parse(text)}catch{data={detail:text}}if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:`Request failed: ${r.status}`);return data};
const json=(method,body)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
let newsRows=[],newsError=false;
let filings=[],marketRows=[],hasMarket=false;function toast(msg){const t=$('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3700)}
function switchTab(tab){document.querySelectorAll('.view').forEach(e=>e.classList.toggle('active',e.id===tab));document.querySelectorAll('[data-tab]').forEach(e=>e.classList.toggle('active',e.dataset.tab===tab));$('crumb').textContent=({overview:'Overview',feed:'Intelligence feed',research:'AI research',portfolio:'Portfolio'})[tab];window.scrollTo({top:0,behavior:'smooth'});if(tab==='research')loadDocs()}
function dateLabel(s){const d=new Date(s);return isNaN(d)?'Date unavailable':d.toLocaleString('en-IN',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}
function badge(f){return f.source==='synthetic_demo'?'<span class="tag synthetic">SYNTHETIC DEMO</span>':'<span class="tag">'+esc(f.source||'MANUAL')+'</span>'}
function filingHTML(f,feed=false){const high=f.score>=75;return `<div class="${feed?'feed-item':'event'}">${feed?`<div class="score">${f.score}<small>PRIORITY</small></div>`:`<span class="event-icon">${high?'✳':'◈'}</span>`}<div><div class="event-title">${esc(f.ticker)} <span style="color:#677e85">/</span> ${esc(f.title)}</div><div class="event-meta"><span>${esc(f.category.replaceAll('_',' '))}</span><span>${dateLabel(f.published)}</span>${badge(f)}${f.url?`<a href="${esc(f.url)}" target="_blank" rel="noopener noreferrer">Original filing ↗</a>`:''}</div>${f.excerpt?`<p>${esc(f.excerpt)}</p>`:''}</div></div>`}
function groupedHTML(g){const main=g.filings[0];return `<article class="feed-item grouped-event"><div class="score">${g.score}<small>PRIORITY</small></div><div><div class="event-title">${esc(g.ticker)} <span style="color:#677e85">/</span> ${esc(g.title)}</div><div class="event-meta"><span>${esc(g.category.replaceAll('_',' '))}</span><span>${dateLabel(g.published)}</span>${badge(main)}<span>${g.count} source${g.count===1?'':'s'}</span></div><p class="priority-note"><b>Why it matters:</b> ${esc(g.priority_reason)}</p>${main.excerpt?`<p>${esc(main.excerpt)}</p>`:''}<details class="filing-sources"><summary>View ${g.count} original filing${g.count===1?'':'s'} &amp; sources</summary>${g.filings.map((f,i)=>`<div class="filing-source"><span>${i+1}. ${esc(f.title)} · ${dateLabel(f.published)}</span>${f.url?`<a target="_blank" rel="noopener noreferrer" href="${esc(f.url)}">Original PDF ↗</a>`:'<small>Original URL not supplied</small>'}</div>`).join('')}</details>${relatedNews(g.ticker)}</div></article>`}
async function loadFeed(){try{
 const hours=$('window').value,min=$('priority').value;
 const query=`?hours=${hours}&min_priority=${min}`;
 const results=await Promise.all([req('/filings'+query),req('/filings/grouped'+query),loadNews(hours)]);
 filings=results[0];
 const ticker=$('feedTicker').value,cat=$('feedCategory').value,showDemo=$('showSynthetic').checked;
 const groups=results[1].filter(g=>(!ticker||g.ticker===ticker)&&(!cat||g.category===cat)&&(showDemo||g.filings.every(f=>f.source!=='synthetic_demo')));
 $('feedList').innerHTML=groups.length?groups.map(groupedHTML).join(''):'<div class="empty">No matching filings. Try a wider window or import an official BSE snapshot.</div>';
 $('feedSummary').textContent=`${groups.length} distinct event(s) · ${groups.filter(g=>g.score>=75).length} high priority · ${groups.reduce((a,g)=>a+g.count,0)} underlying filing(s). ${showDemo?'Synthetic included.':'Synthetic excluded.'}`;
 const overviewGroups=results[1].filter(g=>g.filings.every(f=>f.source!=='synthetic_demo'));
 $('overviewFilings').innerHTML=overviewGroups.slice(0,5).map(groupedHTML).join('')||'<div class="empty">No official announcements loaded. Upload a BSE snapshot.</div>';
 $('metricImportant').textContent=overviewGroups.filter(g=>g.score>=75).length;
 await loadDigest(false);
 }catch(e){toast(e.message)}}
async function loadMarket(){const b=$('refreshBtn');b.disabled=true;b.textContent='Fetching EOD data…';try{marketRows=await req('/markets?limit=20');hasMarket=true;const triggered=marketRows.filter(x=>x.alerts.length);$('metricMarket').textContent=triggered.length;$('overviewMarket').innerHTML=triggered.length?triggered.slice(0,6).map(x=>`<div class="event"><span class="event-icon">↗</span><div><div class="event-title">${esc(x.ticker)} ${x.price_change_pct>=0?'+':''}${x.price_change_pct}%</div><div class="event-meta">${x.date} · Volume ${x.volume_multiple??'—'}× usual · ${esc(x.alerts.join(' + '))} alert</div></div></div>`).join(''):'<div class="empty">'+(marketRows.some(x=>x.status==='live_eod')?'No unusual movements crossed your current thresholds.':'Live market data unavailable. Check internet access and yfinance installation.')+'</div>';await loadAlerts();toast('Market refresh finished.')}catch(e){toast(e.message)}finally{b.disabled=false;b.textContent='↻ Refresh market data'}}
async function loadStatus(){try{const x=await req('/demo/status');$('metricDocs').textContent=x.documents}catch{}}
async function loadPortfolio(){const rows=await req('/portfolio');$('portfolioList').innerHTML=rows.map(x=>`<div class="company" data-company="${esc(x.ticker)}"><span class="company-icon">${esc(x.ticker.slice(0,2))}</span><div><b>${esc(x.name)}</b><small>${esc(x.ticker)} · ${esc(x.sector)}</small></div></div>`).join('');document.querySelectorAll('[data-company]').forEach(el=>el.addEventListener('click',()=>{$('ticker').value=el.dataset.company;switchTab('research')}))}
let currentTicker='';async function loadDocs(){const t=$('ticker').value.trim().toUpperCase();if(!t||!/^[A-Z0-9&_\-]{1,25}$/.test(t))return;currentTicker=t;const links=await req('/research/links/'+encodeURIComponent(t));$('sourceLinks').innerHTML=`<a target="_blank" rel="noopener noreferrer" href="${esc(links.screener)}">Find reports ↗</a><a target="_blank" rel="noopener noreferrer" href="${esc(links.nse)}">NSE disclosures ↗</a>`;const docs=await req('/documents/'+encodeURIComponent(t));$('docList').innerHTML=docs.length?docs.map(d=>`<div class="doc">▤ ${esc(d.name)}<small>${esc(d.kind.replaceAll('_',' '))} · ${d.pages} pages${d.source_url?` · <a href="${esc(d.source_url)}">Source</a>`:''}</small></div>`).join(''):'<div class="empty">No indexed documents for '+esc(t)+'.<br>Upload an original report to begin.</div>';loadStatus()}
function addMessage(role,text,citations=[]){const c=$('conversation');if(c.querySelector('.welcome-mark'))c.innerHTML='';const div=document.createElement('div');div.className='message '+role;div.textContent=text;c.appendChild(div);if(citations.length){const panel=document.createElement('div');panel.className='citations';panel.innerHTML='<b>SUPPORTING PASSAGES</b>'+citations.map((s,i)=>`<details><summary>[${i+1}] ${esc(s.document)} · page ${s.page} · relevance ${s.score}</summary><p>${esc(s.text)}</p>${s.source_url?`<a target="_blank" rel="noopener noreferrer" href="${esc(s.source_url)}">Original document ↗</a>`:''}</details>`).join('');c.appendChild(panel)}c.scrollTop=c.scrollHeight}
async function askQuestion(question){const ticker=$('ticker').value.trim().toUpperCase();if(!ticker){toast('Enter a ticker');return}addMessage('user',question);$('question').value='';const b=$('askForm').querySelector('button');b.disabled=true;try{const result=await req('/research/ask',json('POST',{ticker,question}));addMessage('ai',result.answer,result.citations);if(result.mode==='extractive')toast('Extractive research mode: configure an LLM key for synthesized answers.')}catch(e){addMessage('ai','Research failed: '+e.message)}finally{b.disabled=false}}
document.querySelectorAll('[data-tab]').forEach(x=>x.addEventListener('click',()=>switchTab(x.dataset.tab)));document.querySelectorAll('[data-goto]').forEach(x=>x.addEventListener('click',()=>switchTab(x.dataset.goto)));document.querySelectorAll('[data-question]').forEach(x=>x.addEventListener('click',()=>askQuestion(x.dataset.question)));$('refreshBtn').addEventListener('click',loadMarket);$('window').addEventListener('change',loadFeed);$('priority').addEventListener('change',loadFeed);['feedTicker','feedCategory','showSynthetic'].forEach(x=>$(x).addEventListener('change',loadFeed));$('seedBtn').addEventListener('click',async()=>{try{const r=await req('/demo/seed',{method:'POST'});await Promise.all([loadFeed(),loadStatus()]);toast('Synthetic demo loaded. Research example: FINNDEMO.')}catch(e){toast(e.message)}});$('ticker').addEventListener('change',loadDocs);$('ticker').addEventListener('blur',loadDocs);$('file').addEventListener('change',()=>{$('fileName').textContent=$('file').files[0]?.name||'No document selected'});$('uploadForm').addEventListener('submit',async e=>{e.preventDefault();const f=$('file').files[0];if(!f)return;const b=e.currentTarget.querySelector('[type=submit]');b.disabled=true;try{const fd=new FormData();fd.append('ticker',$('ticker').value);fd.append('kind',$('docKind').value);fd.append('source_url',$('docSource').value.trim());fd.append('file',f);const r=await req('/documents/upload',{method:'POST',body:fd});toast(`Indexed ${r.chunks} source passages`);$('uploadForm').reset();$('fileName').textContent='No document selected';await loadDocs()}catch(e){toast(e.message)}finally{b.disabled=false}});$('askForm').addEventListener('submit',e=>{e.preventDefault();const q=$('question').value.trim();if(q)askQuestion(q)});$('guidanceBtn').addEventListener('click',async()=>{try{const r=await req('/research/guidance/'+encodeURIComponent($('ticker').value.trim()));$('guidanceList').innerHTML=r.items.length?r.items.map(x=>`<div class="doc"><b>${esc(x.document)}, p. ${x.page}</b><p>${esc(x.statement)}</p><small>${esc(x.review_status)}</small></div>`).join(''):'<div class="empty">No candidate guidance found in indexed transcripts.</div>';toast('Candidate guidance, not validated actual-vs-target analysis.')}catch(e){toast(e.message)}});$('settingsBtn').addEventListener('click',async()=>{try{const s=await req('/settings');$('priceThreshold').value=s.price_threshold;$('volumeThreshold').value=s.volume_threshold;$('settingsDialog').showModal()}catch(e){toast(e.message)}});document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>$(b.dataset.close).close()));$('settingsForm').addEventListener('submit',async e=>{e.preventDefault();try{await req('/settings',json('PUT',{price_threshold:Number($('priceThreshold').value),volume_threshold:Number($('volumeThreshold').value),min_priority:40}));$('settingsDialog').close();toast('Saved. Refresh market data to apply thresholds.')}catch(e){toast(e.message)}});$('addFilingBtn').addEventListener('click',()=>{const input=$('filingForm').elements.published;const d=new Date();input.value=new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);$('filingDialog').showModal()});$('filingForm').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.currentTarget);const item=Object.fromEntries(f);item.published=new Date(item.published).toISOString();try{const r=await req('/filings',json('POST',item));$('filingDialog').close();$('filingForm').reset();await loadFeed();toast(`Filing classified: ${r.category} / ${r.score}`)}catch(err){toast(err.message)}});
Promise.all([loadFeed(),loadPortfolio(),loadStatus(),loadAlerts()]).catch(e=>toast(e.message));

// BSE official RSS snapshot import (explicit user upload, never claimed live).
$('bseFile').addEventListener('change',()=>{$('bseFileName').textContent=$('bseFile').files[0]?.name||'No feed selected'});
$('bseForm').addEventListener('submit',async e=>{
 e.preventDefault();const file=$('bseFile').files[0];if(!file)return;
 const btn=$('bseImportBtn');btn.disabled=true;btn.textContent='Importing…';
 try{const form=new FormData();form.append('file',file);
 const result=await req('/bse/import?scope='+encodeURIComponent($('bseScope').value),{method:'POST',body:form});
 $('bseResult').textContent=`Imported ${result.added} official filing(s); ${result.duplicates} duplicate(s), ${result.out_of_scope} outside scope. ${result.note}`;
 await loadFeed();toast(`BSE import finished: ${result.added} added`);
 }catch(error){$('bseResult').textContent='Import failed: '+error.message;toast(error.message)}
 finally{btn.disabled=false;btn.textContent='Import BSE snapshot'}
});

// User-entered, source-linked quarterly financial analysis. No fabricated numbers.
const currentSymbol=()=> $('ticker').value.trim().toUpperCase();
$('quarterForm').addEventListener('submit',async e=>{e.preventDefault();const obj={ticker:currentSymbol(),period:$('quarterPeriod').value,source_url:$('qSource').value,basis:$('qBasis').value,evidence_page:$('qPage').value?Number($('qPage').value):null};for(const [key,id] of Object.entries({revenue:'qRevenue',ebitda:'qEbitda',pbt:'qPbt',pat:'qPat'})){obj[key]=$(id).value===''?null:Number($(id).value)}try{await req('/financials/quarter',json('POST',obj));toast('Quarter saved; open comparisons to review.')}catch(err){toast(err.message)}});
$('targetForm').addEventListener('submit',async e=>{e.preventDefault();try{await req('/financials/target',json('POST',{ticker:currentSymbol(),period:$('targetPeriod').value,metric:$('targetMetric').value,target:Number($('targetValue').value),target_kind:$('targetKind').value,unit:$('targetKind').value==='absolute'?'INR crore':'percent',statement:$('targetStatement').value,source_url:$('targetSource').value}));toast('Management target saved.')}catch(err){toast(err.message)}});
$('compareBtn').addEventListener('click',async()=>{try{const t=encodeURIComponent(currentSymbol());const [quarters,targets]=await Promise.all([req('/financials/'+t),req('/financials/targets/'+t)]);const change=x=>x==null?'—':(x>0?'+':'')+x+'%';$('financialOutput').innerHTML='<h3>Quarterly financials</h3>'+(quarters.length?quarters.map(r=>`<div class="financial-result"><b>${esc(r.period)} · ${esc(r.basis||'unknown basis')}</b><small>INR crore · <a target="_blank" rel="noopener noreferrer" href="${esc(r.source_url)}">Original filing ↗</a></small>${['revenue','ebitda','pbt','pat'].map(m=>`<div>${m.toUpperCase()}: ${r[m]??'—'} <small>QoQ ${change(r.comparison[m].qoq_pct)} · YoY ${change(r.comparison[m].yoy_pct)}</small></div>`).join('')}</div>`).join(''):'<p>No quarterly data entered for this ticker.</p>')+'<h3>Guidance vs actual</h3>'+(targets.length?targets.map(r=>`<div class="financial-result"><b>${esc(r.period)} · ${esc(r.metric.toUpperCase())}</b><div>${esc(r.target_kind==='yoy_growth_pct'?'YoY growth %':'INR crore')} · Target ${r.target}, actual ${r.actual??'—'} (${esc(r.result)})</div><small><a target="_blank" rel="noopener noreferrer" href="${esc(r.source_url)}">Guidance source ↗</a>${r.actual_source?` · <a target="_blank" rel="noopener noreferrer" href="${esc(r.actual_source)}">Actual source ↗</a>`:''}</small><p>${esc(r.statement)}</p></div>`).join(''):'<p>No management targets entered.</p>');renderFinancialChart(quarters); }catch(e){toast(e.message)}});


// Release 4: review-first table extraction with explicit column, unit and basis.
$('extractFile').addEventListener('change',()=>{$('extractFileName').textContent=$('extractFile').files[0]?.name||'No PDF selected'});
$('extractForm').addEventListener('submit',async e=>{
 e.preventDefault();const file=$('extractFile').files[0];if(!file)return;
 const button=e.currentTarget.querySelector('button[type=submit]');button.disabled=true;
 $('extractStatus').textContent='Locating financial-statement tables, period columns and units…';$('extractCandidates').innerHTML='';
 try{
  const fd=new FormData();fd.append('file',file);
  const result=await req('/financials/extract-pdf',{method:'POST',body:fd});
  $('extractStatus').textContent=`${result.candidates.length} candidate accounting rows on ${result.pages_with_text} readable pages · ${result.tables_detected} table(s) detected. All require verification.`;
  $('extractCandidates').innerHTML=result.candidates.length?`<p class="caution">Financial data is NEVER auto-saved. Verify the source table, exact quarter, reporting basis and units before copying.</p>`+result.candidates.map(c=>`<div class="candidate-row"><div class="candidate-title"><b>${esc(c.metric.toUpperCase())} · page ${c.page}</b><small>${esc(c.method.replaceAll('_',' '))} · ${esc(c.basis)}</small></div><p class="evidence">${esc(c.evidence)}</p><small>${c.unit_detected?'Unit: '+esc(c.unit_detected)+' · normalized values in INR crore':'Unit: unknown — NO automatic copying'} · ${c.table?'Table '+c.table+', row '+c.row:'strict text row'}</small><div class="candidate-data">${c.values.map(v=>`<div class="candidate-value"><small>${esc(v.period_header)} · column ${v.column}</small><strong>${esc(v.raw)} ${c.unit_detected?esc(c.unit_detected):'unit unknown'}</strong>${v.crore!==null?`<small>Converted: ${esc(v.crore)} INR crore</small><button type="button" class="text-btn candidate-copy" data-metric="${esc(c.metric)}" data-value="${v.crore}" data-page="${c.page}" data-basis="${esc(c.basis)}">Use confirmed column ↗</button>`:'<small class="caution">Cannot convert without a verified unit. Enter manually after checking.</small>'}</div>`).join('')}</div></div>`).join(''):'<p>No sufficiently structured accounting rows were found. This is a safe abstention, not a PDF error. Try another machine-readable results PDF or enter reviewed figures manually.</p>';
  $('extractCandidates').querySelectorAll('.candidate-copy').forEach(btn=>btn.addEventListener('click',()=>{
    const map={revenue:'qRevenue',ebitda:'qEbitda',pbt:'qPbt',pat:'qPat'};
    $(map[btn.dataset.metric]).value=btn.dataset.value;$('qPage').value=btn.dataset.page;
    if(['standalone','consolidated'].includes(btn.dataset.basis))$('qBasis').value=btn.dataset.basis;
    toast('Figure copied in INR crore. Confirm year, quarter, scope and original source before saving.');
  }));
 }catch(err){$('extractStatus').textContent='Extraction failed: '+err.message;toast(err.message)}
 finally{button.disabled=false}
});

// A light-weight, dependency-free chart for verified revenue values only.
function renderFinancialChart(records){
 const list=[...records].filter(x=>x.revenue!=null).sort((a,b)=>a.period.localeCompare(b.period)).slice(-8);
 if(list.length<2){$('financialChart').innerHTML='<p class="short-status">Add at least two comparable revenue quarters to show a trend.</p>';return}
 const max=Math.max(...list.map(x=>x.revenue),1),min=Math.min(0,...list.map(x=>x.revenue));
 const w=620,h=220,px=45,py=25,x=i=>px+i*(w-2*px)/Math.max(1,list.length-1),y=v=>h-py-(v-min)/(max-min||1)*(h-py*2);
 const segments=[];let active=[];
 list.forEach((r,i)=>{if(active.length&&r.basis!==list[i-1].basis){segments.push(active);active=[]}active.push([x(i),y(r.revenue)])});if(active.length)segments.push(active);
 $('financialChart').innerHTML=`<h3>Verified revenue trend (INR crore)</h3><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Revenue chart of manually verified quarterly figures"><path d="M${px} ${py} V${h-py} H${w-px}" stroke="#46636b" fill="none"/>${segments.map(a=>`<polyline fill="none" stroke="#bdf59c" stroke-width="3" points="${a.map(pt=>pt.join(',')).join(' ')}"/>`).join('')}${list.map((r,i)=>`<circle cx="${x(i)}" cy="${y(r.revenue)}" r="4" fill="#bdf59c"><title>${esc(r.period)} · ${esc(r.basis)} · ${r.revenue} crore</title></circle><text x="${x(i)}" y="${h-7}" text-anchor="middle" font-size="10" fill="#a8c0c0">${esc(r.period.slice(2))}</text>`).join('')}</svg><p class="short-status">Lines disconnect when reporting basis changes. Figures are user-confirmed, not independently audited by FINN.</p>`;
}

// DIL-free web UI, no background polling or hidden external requests.
async function loadDigest(showToast=true){
 try{const hours=$('window').value;const d=await req(`/digest?hours=${hours}&portfolio_only=true`);
   $('digestDownload').href=`/api/digest/export?hours=${hours}&portfolio_only=true`;
   $('digestSummary').textContent=`${d.high_priority_events} high-priority · ${d.events_total} events · ${d.coverage.portfolio_with_filings}/${d.coverage.portfolio_companies} companies with filings · ${d.market_alerts.length} cached EOD alerts`;
   $('digestTop').innerHTML=d.events.slice(0,3).map(g=>`<div class="brief-item"><small>${esc(g.ticker)} · PRIORITY ${g.score}</small><b>${esc(g.title)}</b><small>${esc(g.priority_reason)}</small></div>`).join('')||'<p class="short-status">No source-linked portfolio filings in this window. Import the BSE snapshot to populate the brief.</p>';
   if(showToast)toast('Daily brief updated from source-linked records.');
 }catch(e){if(showToast)toast(e.message)}
}
$('digestRefreshBtn').addEventListener('click',()=>loadDigest(true));
$('feedExportBtn').addEventListener('click',()=>window.open('/api/digest/export?hours='+encodeURIComponent($('window').value),'_blank'));
// Generate filter choices from the portfolio and source-defined categories.
req('/portfolio').then(rows=>{
 const sel=$('feedTicker');rows.forEach(r=>{const opt=document.createElement('option');opt.value=r.ticker;opt.textContent=r.ticker;sel.appendChild(opt)})
}).catch(()=>{});
['results','M&A','management_change','litigation','fund_raise','credit_rating','dividend','capex','earnings_call','press_release','unclassified'].forEach(x=>{
 const opt=document.createElement('option');opt.value=x;opt.textContent=x.replaceAll('_',' ');$('feedCategory').appendChild(opt)
});

$('loadBundledBtn').addEventListener('click',async()=>{try{const r=await req('/bse/import-bundled',{method:'POST'});$('bseResult').textContent=`Historical BSE snapshot: ${r.added} added, ${r.duplicates} already present. Original links retained.`;$('window').value='168';$('feedTicker').value='';await loadFeed();toast('Official BSE sample loaded (historical snapshot, not live).')}catch(e){toast(e.message)}});

async function loadAlerts(){
 try{const items=await req('/alerts?limit=12');$('alertHistory').innerHTML=items.length?items.map(a=>`<div class="event"><span class="event-icon">!</span><div><div class="event-title">${esc(a.ticker)} · ${esc(a.alert_type.toUpperCase())}</div><div class="event-meta">EOD ${esc(a.market_date)} · Price ${a.price_change_pct??'—'}% · Volume ${a.volume_multiple??'—'}×</div></div></div>`).join(''):'<p class="short-status">No recorded alerts yet. Refresh EOD prices to evaluate your chosen thresholds.</p>'}catch(e){$('alertHistory').textContent='Stored alert history unavailable.'}
}

// Read persisted collection status; repaint age without changing its timestamp.
let feedFreshness = null;
function paintFreshness(){
 const el=$('feedFreshness');
 if(!feedFreshness){el.textContent='Update status unavailable';return}
 const stamp=Date.parse(feedFreshness.last_updated);
 const age=Number.isFinite(stamp)?Math.max(0,Math.floor((Date.now()-stamp)/60000)):null;
 el.textContent=(age===null?'Update time unknown':`Last updated ${age} min ago`)+` · ${feedFreshness.source}`;
}
async function refreshFreshness(){
 try{feedFreshness=await req('/ingest/status')}catch{feedFreshness=null}
 paintFreshness();
}
refreshFreshness();
setInterval(refreshFreshness,60000);

function newsHTML(n){
 const safeLink=String(n.link||'').startsWith('https://')?n.link:'#';
 return `<div class="news-item"><a href="${esc(safeLink)}" target="_blank" rel="noopener noreferrer">${esc(n.title)} ↗</a><small>${esc(n.ticker)} · ${esc(n.source)} · ${dateLabel(n.published)}</small></div>`;
}
function relatedNews(ticker){
 const matches=newsRows.filter(n=>n.ticker===ticker).slice(0,3);
 return matches.length?`<details class="related-news"><summary>Market context · ${esc(ticker)} · secondary sources</summary>${matches.map(newsHTML).join('')}</details>`:'';
}
async function loadNews(hours){
 try{newsRows=await req('/news?hours='+encodeURIComponent(hours));newsError=false}
 catch{newsRows=[];newsError=true}
 const company=$('feedTicker').value;
 const selected=newsRows.filter(n=>!company||n.ticker===company).slice(0,20);
 $('marketContext').innerHTML=selected.length?selected.map(newsHTML).join(''):
 `<p class="short-status">${newsError?'Market context is temporarily unavailable.':'No company headlines available in this time window.'}</p>`;
}
