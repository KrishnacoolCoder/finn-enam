const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
} [c]));

const req = async (path, options = {}) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), /^\/(research|markets)/.test(path) ? 90000 : 25000);
    try {
        const r = await fetch('/api' + path, {
            ...options,
            signal: controller.signal
        });
        const text = await r.text();
        let data;
        try {
            data = JSON.parse(text)
        } catch {
            data = {
                detail: text
            }
        }
        if (!r.ok) throw Error(typeof data.detail === 'string' ? data.detail : `Request failed: ${r.status}`);
        return data;
    } catch (error) {
        if (error.name === 'AbortError') throw Error('Request timed out. Please try again.');
        throw error
    } finally {
        clearTimeout(timer)
    }
};
const json = (method, body) => ({
    method,
    headers: {
        'Content-Type': 'application/json'
    },
    body: JSON.stringify(body)
});
let newsRows = [],
    newsError = false;

const EVENT_TYPES = ['results', 'management_change', 'M&A', 'litigation', 'credit_rating', 'fund_raise', 'pledging', 'capex', 'dividend', 'bonus_split', 'earnings_call', 'insider_trading', 'investor_meetings', 'press_release', 'postal_ballot', 'agm_egm', 'unclassified'];
const EVENT_LABELS = {
    results: 'Financial results',
    management_change: 'Management change',
    'M&A': 'Mergers & acquisitions',
    agm_egm: 'General meetings',
    unclassified: 'Needs review'
};
const labelEvent = value => EVENT_LABELS[value] || value.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
const storage = {
    get: (key, fallback) => {
        try {
            return localStorage.getItem(key) || fallback
        } catch {
            return fallback
        }
    },
    set: (key, value) => {
        try {
            localStorage.setItem(key, String(value))
        } catch {}
    }
};
let filings = [],
    marketRows = [],
    hasMarket = false,
    feedRequest = 0,
    overviewRequest = 0,
    alertRequest = 0,
    digestRequest = 0;
let lastFeedGroups = [],
    lastOverviewGroups = [],
    lastAlertGroups = [];
let digestHours = Number(storage.get('finn.digest.hours', '24'));
if (![24, 72, 168].includes(digestHours)) digestHours = 24;
let savedSettings = {
        price_threshold: 5,
        volume_threshold: 2,
        min_priority: 40,
        event_types: [...EVENT_TYPES]
    },
    settingsPromise = null;
const companyNames = new Map();
let toastTimer;

function toast(msg) {
    const t = $('toast');
    clearTimeout(toastTimer);
    t.textContent = msg;
    t.classList.add('show');
    toastTimer = setTimeout(() => t.classList.remove('show'), 4500)
}

function skeletons(count = 2) {
    return '<span class="sr-only" role="status">Loading…</span>' + Array.from({
        length: count
    }, () => '<div class="skeleton-card" aria-hidden="true"><span class="skeleton skeleton-line short"></span><span class="skeleton skeleton-line"></span><span class="skeleton skeleton-line medium"></span></div>').join('')
}

function showSkeleton(id, count = 2) {
    const el = $(id);
    if (el) {
        el.setAttribute('aria-busy', 'true');
        el.innerHTML = skeletons(count)
    }
}

function finishLoading(id) {
    $(id)?.setAttribute('aria-busy', 'false')
}

function errorHTML(message, retry) {
    return `<div class="error-panel" role="alert">${esc(message)}<button type="button" class="button ghost" data-retry="${esc(retry)}">Try again</button></div>`
}

function safeHref(url) {
    try {
        const u = new URL(url);
        return ['https:', 'http:'].includes(u.protocol) ? u.href : ''
    } catch {
        return ''
    }
}

function switchTab(tab, updateURL = true) {
    const names = {
        overview: 'Brief',
        feed: 'Feed',
        research: 'Research',
        portfolio: 'Portfolio',
        alerts: 'Alerts'
    };
    if (!names[tab]) tab = 'overview';
    document.querySelectorAll('.view').forEach(e => {
        const active = e.id === tab;
        e.classList.toggle('active', active);
        e.hidden = !active
    });
    document.querySelectorAll('[data-tab]').forEach(e => {
        const active = e.dataset.tab === tab;
        e.classList.toggle('active', active);
        if (active) e.setAttribute('aria-current', 'page');
        else e.removeAttribute('aria-current')
    });
    $('crumb').textContent = names[tab];
    if (updateURL && location.hash !== '#' + tab) history.pushState(null, '', '#' + tab);
    window.scrollTo({
        top: 0,
        behavior: 'instant'
    });
    $(tab).querySelector('h1')?.focus({
        preventScroll: true
    });
    if (tab === 'research') loadDocs();
    if (tab === 'alerts') {
        loadSettings();
        loadFilingAlerts();
        loadAlerts()
    }
}

function dateLabel(s) {
    const d = new Date(s);
    return isNaN(d) ? 'Date unavailable' : d.toLocaleString('en-IN', {
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit'
    })
}

function badge(f) {
    return f.source === 'synthetic_demo' ? '<span class="tag synthetic">SYNTHETIC DEMO</span>' : '<span class="tag">' + esc(f.source || 'MANUAL') + '</span>'
}

function managementHTML(f) {
    const m = f.management_change;
    if (f.category !== 'management_change' || !m) return '';
    const heading = [m.role, m.action].filter(Boolean).join(' ') || 'Management change';
    return `<section class="management-card" aria-label="Management change"><h3>${esc(heading)}${m.person_name?': '+esc(m.person_name):''}${m.effective_date?', effective '+esc(m.effective_date):''}</h3><dl><div><dt>Person</dt><dd>${esc(m.person_name)}</dd></div><div><dt>Role</dt><dd>${esc(m.role)}</dd></div><div><dt>Change</dt><dd>${esc(m.action)}</dd></div><div><dt>Effective date</dt><dd>${esc(m.effective_date)}</dd></div></dl>${f.url?`<a href="${esc(f.url)}" target="_blank" rel="noopener noreferrer">Source filing ↗</a>`:''}<small>Rule-based extraction · missing fields are blank</small></section>`;
}

function isRoutine(g) {
    return /routine notice/i.test(g.priority_reason || '') || ['investor_meetings', 'agm_egm', 'postal_ballot'].includes(g.category)
}

function ranked(groups) {
    return [...groups].sort((a, b) => (b.score - a.score) || (Date.parse(b.published) - Date.parse(a.published)))
}

function filingHTML(f) {
    return groupedHTML({
        ticker: f.ticker,
        title: f.title,
        category: f.category,
        score: f.score,
        published: f.published,
        priority_reason: f.priority_reason || 'Review the original filing for context.',
        count: 1,
        filings: [f]
    })
}

function groupedHTML(g) {
    const main = g.filings[0],
        url = safeHref(main.url),
        why = g.priority_reason || 'Review the original filing for context.';
    return `<article class="feed-item grouped-event" data-priority="${Number(g.score)}">
  <div class="card-top"><div><span class="company-title">${esc(companyNames.get(g.ticker)||g.ticker)}</span><span class="ticker-label">${esc(g.ticker)}</span></div><span class="priority-pill ${g.score<75?'low':''}" aria-label="Priority ${Number(g.score)} out of 100">${Number(g.score)}<small>PRIORITY</small></span></div>
  <h3 class="event-title">${esc(g.title)}</h3>
  <div class="event-meta"><span class="event-chip">${esc(labelEvent(g.category))}</span><time datetime="${esc(g.published)}">${dateLabel(g.published)}</time>${badge(main)}</div>
  <p class="why-line" title="${esc(why)}"><b>Why it matters:</b> ${esc(why)}</p>
  ${g.filings.map(managementHTML).join('')}
  <div class="card-actions">${url?`<a class="source-button" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Original filing ↗</a>`:''}<span class="short-status">${Number(g.count)} source${g.count===1?'':'s'}</span></div>
  <details class="filing-sources"><summary>Evidence &amp; sources</summary><p class="priority-note">${esc(why)}</p>${main.excerpt?`<p class="source-note">${esc(main.excerpt)}</p>`:''}${g.filings.map((f,i)=>`<div class="filing-source"><span>${i+1}. ${esc(f.title)} · ${dateLabel(f.published)}</span>${safeHref(f.url)?`<a href="${esc(safeHref(f.url))}" target="_blank" rel="noopener noreferrer">Source ${i+1} · original PDF ↗</a>`:'<small>No original URL supplied</small>'}</div>`).join('')}</details>${relatedNews(g.ticker)}
 </article>`;
}

function renderGroupedList(id, groups, limit = Infinity) {
    const el = $(id),
        wasOpen = !!el.querySelector('.routine-group[open]');
    const sorted = ranked(groups),
        important = sorted.filter(g => !isRoutine(g)),
        routine = sorted.filter(isRoutine);
    const count = routine.reduce((sum, g) => sum + Number(g.count || g.filings.length), 0);
    el.innerHTML = (important.length ? important.slice(0, limit).map(groupedHTML).join('') : '<div class="empty">No priority events in this window.</div>') +
        (routine.length ? `<details class="routine-group" ${wasOpen?'open':''}><summary>${count} routine filing${count===1?'':'s'}</summary><div class="stack">${routine.map(groupedHTML).join('')}</div></details>` : '');
    if (!groups.length) el.innerHTML = '<div class="empty">No matching filings in this window. Try a wider window or different filters.</div>';
    finishLoading(id);
}
async function loadFeed() {
    const generation = ++feedRequest;
    showSkeleton('feedList', 3);
    $('feedSummary').textContent = 'Loading filings…';
    const hours = $('window').value,
        min = $('priority').value;
    const ticker = $('feedTicker').value,
        cat = $('feedCategory').value,
        showDemo = $('showSynthetic').checked;
    try {
        const query = `?hours=${hours}&min_priority=${min}`;
        const results = await Promise.all([req('/filings' + query), req('/filings/grouped' + query), loadNews(hours)]);
        if (generation !== feedRequest) return;
        filings = results[0];
        const groups = results[1].filter(g => (!ticker || g.ticker === ticker) && (!cat || g.category === cat) && (showDemo || g.filings.every(f => f.source !== 'synthetic_demo')));
        lastFeedGroups = groups;
        renderGroupedList('feedList', groups);
        $('feedSummary').textContent = `${groups.length} events · ${new Set(groups.map(g=>g.ticker)).size}/20 companies · ${groups.filter(g=>g.score>=75).length} high priority · ${groups.reduce((n,g)=>n+Number(g.count),0)} filings. ${showDemo?'Demos included.':'Demos excluded.'}`;
        if (feedFreshness) paintFreshness();
    } catch (error) {
        if (generation === feedRequest) {
            $('feedList').innerHTML = errorHTML(error.message, 'feed');
            $('feedSummary').textContent = 'Feed unavailable. Saved filings have not been removed.'
        }
    } finally {
        if (generation === feedRequest) finishLoading('feedList')
    }
}

function paintDigestWindow() {
    document.querySelectorAll('[data-digest-hours]').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.digestHours) === digestHours)));
    $('digestWindowText').textContent = ({
        24: 'Last 24 hours',
        72: 'Last 3 days',
        168: 'Last 7 days'
    })[digestHours];
}
async function loadOverview() {
    const generation = ++overviewRequest;
    showSkeleton('overviewFilings', 2);
    $('metricImportant').textContent = '—';
    try {
        const groups = await req(`/filings/grouped?hours=${digestHours}&min_priority=0`);
        if (generation !== overviewRequest) return;
        lastOverviewGroups = groups.filter(g => g.filings.every(f => f.source !== 'synthetic_demo'));
        renderGroupedList('overviewFilings', lastOverviewGroups, 5);
        $('metricImportant').textContent = lastOverviewGroups.filter(g => g.score >= 75).length;
    } catch (error) {
        if (generation === overviewRequest) $('overviewFilings').innerHTML = errorHTML(error.message, 'overview')
    } finally {
        if (generation === overviewRequest) finishLoading('overviewFilings')
    }
}

async function loadMarket() {
    const b = $('refreshBtn');
    b.disabled = true;
    b.textContent = 'Fetching EOD data…';
    showSkeleton('overviewMarket', 2);
    try {
        marketRows = await req('/markets?limit=20');
        hasMarket = true;
        const triggered = marketRows.filter(x => x.alerts.length);
        $('metricMarket').textContent = triggered.length;
        $('overviewMarket').innerHTML = triggered.length ? triggered.slice(0, 6).map(x => `<div class="event"><span class="event-icon">↗</span><div><div class="event-title">${esc(x.ticker)} ${x.price_change_pct>=0?'+':''}${x.price_change_pct}%</div><div class="event-meta">${x.date} · Volume ${x.volume_multiple??'—'}× usual · ${esc(x.alerts.join(' + '))} alert</div></div></div>`).join('') : '<div class="empty">' + (marketRows.some(x => x.status === 'live_eod') ? 'No unusual movements crossed your current thresholds.' : 'Live market data unavailable. Check internet access and yfinance installation.') + '</div>';
        await loadAlerts();
        toast('Market refresh finished.')
    } catch (e) {
        $('overviewMarket').innerHTML = errorHTML(e.message, 'market');
        toast(e.message)
    } finally {
        finishLoading('overviewMarket');
        b.disabled = false;
        b.textContent = '↻ Refresh market data'
    }
}
async function loadStatus() {
    try {
        const x = await req('/demo/status');
        $('metricDocs').textContent = x.documents
    } catch {}
}

async function loadPortfolio() {
    const rows = await req('/portfolio');
    rows.forEach(x => companyNames.set(x.ticker, x.name));
    $('portfolioTickers').innerHTML = rows.map(x => `<option value="${esc(x.ticker)}">${esc(x.name)}</option>`).join('');
    $('feedTicker').innerHTML = '<option value="">All companies</option>' + rows.map(x => `<option value="${esc(x.ticker)}">${esc(x.name)}</option>`).join('');
    $('portfolioList').innerHTML = rows.map(x => `<button type="button" class="company" data-company="${esc(x.ticker)}"><span class="company-icon" aria-hidden="true">${esc(x.ticker.slice(0,2))}</span><div><b>${esc(x.name)}</b><small>${esc(x.ticker)} · ${esc(x.sector)}</small></div></button>`).join('');
    if (lastFeedGroups.length) renderGroupedList('feedList', lastFeedGroups);
    if (lastOverviewGroups.length) renderGroupedList('overviewFilings', lastOverviewGroups, 5);
    if (lastAlertGroups.length) renderGroupedList('filingAlerts', lastAlertGroups);
}

let currentTicker = '',
    reportGeneration = 0;
const reportLoads = new Map();

function prepareReports(ticker) {
    if (!reportLoads.has(ticker)) {
        const promise = req('/reports/' + encodeURIComponent(ticker) + '/ensure', {
            method: 'POST'
        }).catch(() => ({
            status: 'unavailable',
            note: 'Automatic loading failed; existing indexed documents remain available.'
        }));
        reportLoads.set(ticker, promise);
        promise.then(result => {
            if (['unavailable', 'partial'].includes(result.status)) reportLoads.delete(ticker)
        });
    }
    return reportLoads.get(ticker);
}
async function loadDocs() {
    const t = $('ticker').value.trim().toUpperCase();
    if (!t || !/^[A-Z0-9&_\-]{1,25}$/.test(t)) return;
    const generation = ++reportGeneration;
    currentTicker = t;
    void loadCompanyContext(t);
    $('reportStatus').textContent = 'Loading primary reports for ' + t + '…';
    showSkeleton('docList', 2);
    try {
        const prepared = await prepareReports(t);
        if (generation !== reportGeneration) return;
        const [links, docs] = await Promise.all([req('/research/links/' + encodeURIComponent(t)), req('/documents/' + encodeURIComponent(t))]);
        if (generation !== reportGeneration) return;
        $('sourceLinks').innerHTML = `<a target="_blank" rel="noopener noreferrer" href="${esc(links.nse)}">NSE disclosures ↗</a>`;
        $('reportStatus').textContent = (prepared.status === 'ready' ? `${prepared.indexed} primary report(s) ready for ${t}. ` : prepared.status === 'partial' ? 'Some primary reports are ready. ' : prepared.status === 'manual' ? 'Upload a primary report for this ticker. ' : 'Automatic report loading is unavailable. ') + (prepared.note || '');
        $('docList').innerHTML = docs.length ? docs.map(d => `<div class="doc">▤ ${esc(d.name)}<small>${d.auto_loaded?'AUTO-LOADED PRIMARY SOURCE · ':''}${esc(d.kind.replaceAll('_',' '))} · ${d.pages} original PDF pages${d.source_url?` · <a target="_blank" rel="noopener noreferrer" href="${esc(d.source_url)}">Source ↗</a>`:''}</small></div>`).join('') : '<div class="empty">No indexed primary documents for ' + esc(t) + '. Upload an original report if automatic loading is unavailable.</div>';
        finishLoading('docList');
        loadStatus();
    } catch (error) {
        if (generation === reportGeneration) {
            $('reportStatus').textContent = 'Could not load reports: ' + error.message;
            $('docList').innerHTML = errorHTML('Reports could not be loaded.', 'research');
            finishLoading('docList')
        }
    }
}

function addMessage(role, text, citations = []) {
    const c = $('conversation');
    if (c.querySelector('.welcome-mark')) c.innerHTML = '';
    const div = document.createElement('div');
    div.className = 'message ' + role;
    div.textContent = text;
    c.appendChild(div);
    if (citations.length) {
        const panel = document.createElement('div');
        panel.className = 'citations';
        panel.innerHTML = '<b>SUPPORTING PASSAGES</b>' + citations.map((s, i) => `<details><summary>[${esc(s.document)}, ${s.page}] · relevance ${s.score}</summary><p>${esc(s.text)}</p>${s.source_url?`<a target="_blank" rel="noopener noreferrer" href="${esc(s.source_url)}">Original document ↗</a>`:''}</details>`).join('');
        c.appendChild(panel)
    }
    c.scrollTop = c.scrollHeight
}
async function askQuestion(question) {
    if ($('askForm').querySelector('button').disabled) return;
    const ticker = $('ticker').value.trim().toUpperCase();
    if (!ticker) {
        toast('Enter a ticker');
        return
    }
    addMessage('user', question);
    $('question').value = '';
    const b = $('askForm').querySelector('button');
    b.disabled = true;
    document.querySelectorAll('[data-question]').forEach(x => x.disabled = true);
    const pending = document.createElement('div');
    pending.className = 'pending-answer';
    pending.innerHTML = '<span class="sr-only" role="status">Reading primary-source evidence…</span>' + skeletons(1);
    $('conversation').appendChild(pending);
    $('conversation').setAttribute('aria-busy', 'true');
    $('conversation').scrollTop = $('conversation').scrollHeight;
    try {
        await prepareReports(ticker);
        const result = await req('/research/ask', json('POST', {
            ticker,
            question
        }));
        pending.remove();
        addMessage('ai', result.answer, result.citations);
        document.querySelector('.under-ask').textContent = (result.mode === 'gemini_grounded' ? 'Gemini' : result.mode === 'groq_grounded' ? 'Groq' : result.mode === 'extractive' ? 'Extractive' : 'Insufficient evidence') + (result.cached ? ' · cached answer' : '') + ' · indexed primary documents only' + (result.provider_failures?.length ? ' · ' + result.provider_failures.map(x => x.provider + ': ' + x.reason.replaceAll('_', ' ')).join('; ') : '');
        if (result.mode === 'extractive') toast('Showing primary-source excerpts; AI providers are unavailable.')
    } catch (e) {
        pending.remove();
        addMessage('ai', 'Research failed: ' + e.message)
    } finally {
        pending.remove();
        $('conversation').setAttribute('aria-busy', 'false');
        b.disabled = false;
        document.querySelectorAll('[data-question]').forEach(x => x.disabled = false)
    }
}
document.querySelectorAll('[data-tab]').forEach(x => x.addEventListener('click', () => switchTab(x.dataset.tab)));
document.querySelectorAll('[data-goto]').forEach(x => x.addEventListener('click', () => switchTab(x.dataset.goto)));
document.querySelectorAll('[data-question]').forEach(x => x.addEventListener('click', () => askQuestion(x.dataset.question)));
$('refreshBtn').addEventListener('click', loadMarket);
$('window').addEventListener('change', loadFeed);
$('priority').addEventListener('change', loadFeed);
['feedTicker', 'feedCategory', 'showSynthetic'].forEach(x => $(x).addEventListener('change', loadFeed));
$('seedBtn').addEventListener('click', async () => {
    try {
        const r = await req('/demo/seed', {
            method: 'POST'
        });
        await Promise.all([loadFeed(), loadStatus()]);
        toast('Synthetic demo loaded. Research example: FINNDEMO.')
    } catch (e) {
        toast(e.message)
    }
});
$('ticker').addEventListener('change', loadDocs);
$('ticker').addEventListener('blur', loadDocs);
$('file').addEventListener('change', () => {
    $('fileName').textContent = $('file').files[0]?.name || 'No document selected'
});
$('uploadForm').addEventListener('submit', async e => {
    e.preventDefault();
    const f = $('file').files[0];
    if (!f) return;
    const b = e.currentTarget.querySelector('[type=submit]');
    b.disabled = true;
    try {
        const fd = new FormData();
        fd.append('ticker', $('ticker').value);
        fd.append('kind', $('docKind').value);
        fd.append('source_url', $('docSource').value.trim());
        fd.append('file', f);
        const r = await req('/documents/upload', {
            method: 'POST',
            body: fd
        });
        toast(`Indexed ${r.chunks} source passages`);
        $('uploadForm').reset();
        $('fileName').textContent = 'No document selected';
        await loadDocs()
    } catch (e) {
        toast(e.message)
    } finally {
        b.disabled = false
    }
});
$('askForm').addEventListener('submit', e => {
    e.preventDefault();
    const q = $('question').value.trim();
    if (q) askQuestion(q)
});
$('guidanceBtn').addEventListener('click', async () => {
    try {
        const r = await req('/research/guidance/' + encodeURIComponent($('ticker').value.trim()));
        $('guidanceList').innerHTML = r.items.length ? r.items.map(x => `<div class="doc"><b>${esc(x.document)}, p. ${x.page}</b><p>${esc(x.statement)}</p><small>${esc(x.review_status)}</small></div>`).join('') : '<div class="empty">No candidate guidance found in indexed transcripts.</div>';
        toast('Candidate guidance, not validated actual-vs-target analysis.')
    } catch (e) {
        toast(e.message)
    }
});
$('settingsBtn').addEventListener('click', () => switchTab('alerts'));
document.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => $(b.dataset.close).close()));
$('addFilingBtn').addEventListener('click', () => {
    const input = $('filingForm').elements.published;
    const d = new Date();
    input.value = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    $('filingDialog').showModal()
});
$('filingForm').addEventListener('submit', async e => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const item = Object.fromEntries(f);
    item.published = new Date(item.published).toISOString();
    try {
        const r = await req('/filings', json('POST', item));
        $('filingDialog').close();
        $('filingForm').reset();
        await loadFeed();
        toast(`Filing classified: ${r.category} / ${r.score}`)
    } catch (err) {
        toast(err.message)
    }
});


// BSE official RSS snapshot import (explicit user upload, never claimed live).
$('bseFile').addEventListener('change', () => {
    $('bseFileName').textContent = $('bseFile').files[0]?.name || 'No feed selected'
});
$('bseForm').addEventListener('submit', async e => {
    e.preventDefault();
    const file = $('bseFile').files[0];
    if (!file) return;
    const btn = $('bseImportBtn');
    btn.disabled = true;
    btn.textContent = 'Importing…';
    try {
        const form = new FormData();
        form.append('file', file);
        const result = await req('/bse/import?scope=' + encodeURIComponent($('bseScope').value), {
            method: 'POST',
            body: form
        });
        $('bseResult').textContent = `Imported ${result.added} official filing(s); ${result.duplicates} duplicate(s), ${result.out_of_scope} outside scope. ${result.note}`;
        await loadFeed();
        toast(`BSE import finished: ${result.added} added`);
    } catch (error) {
        $('bseResult').textContent = 'Import failed: ' + error.message;
        toast(error.message)
    } finally {
        btn.disabled = false;
        btn.textContent = 'Import BSE snapshot'
    }
});

// User-entered, source-linked quarterly financial analysis. No fabricated numbers.
const currentSymbol = () => $('ticker').value.trim().toUpperCase();
$('quarterForm').addEventListener('submit', async e => {
    e.preventDefault();
    const obj = {
        ticker: currentSymbol(),
        period: $('quarterPeriod').value,
        source_url: $('qSource').value,
        basis: $('qBasis').value,
        verified: $('qVerified').checked,
        evidence_note: $('qNotes').value,
        evidence_page: $('qPage').value ? Number($('qPage').value) : null
    };
    for (const [key, id] of Object.entries({
            revenue: 'qRevenue',
            ebitda: 'qEbitda',
            pbt: 'qPbt',
            pat: 'qPat'
        })) {
        obj[key] = $(id).value === '' ? null : Number($(id).value)
    }
    try {
        await req('/financials/quarter', json('POST', obj));
        toast('Quarter saved; open comparisons to review.')
    } catch (err) {
        toast(err.message)
    }
});
$('targetForm').addEventListener('submit', async e => {
    e.preventDefault();
    try {
        await req('/financials/target', json('POST', {
            ticker: currentSymbol(),
            period: $('targetPeriod').value,
            metric: $('targetMetric').value,
            target: Number($('targetValue').value),
            target_kind: $('targetKind').value,
            unit: $('targetKind').value === 'absolute' ? 'INR crore' : 'percent',
            statement: $('targetStatement').value,
            quote: $('targetQuote').value,
            basis: $('targetBasis').value,
            tolerance: Number($('targetTolerance').value),
            source_url: $('targetSource').value
        }));
        toast('Management target saved.')
    } catch (err) {
        toast(err.message)
    }
});
$('compareBtn').addEventListener('click', loadFinancialComparisons);
async function loadFinancialComparisons() {
    try {
        const t = encodeURIComponent(currentSymbol());
        const [quarters, targets] = await Promise.all([req('/financials/' + t), req('/financials/targets/' + t)]);
        const fmt = x => x == null ? '—' : Number(x).toLocaleString('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
        const change = (c, k) => c[k + '_pct'] == null ? esc(c[k + '_note']) : (c[k + '_pct'] > 0 ? '+' : '') + fmt(c[k + '_pct']) + '%' + (c[k + '_note'] === 'Profit to loss' ? ' · profit to loss' : '');
        const badge = verified => `<span class="tag ${verified?'review-verified':'review-unverified'}">${verified?'Verified by user':'Unverified'}</span>`;
        $('financialOutput').innerHTML = '<h3>Quarterly financials · Rs crore</h3>' + (quarters.length ? quarters.map(r => `<div class="financial-result"><b>${esc(r.period)} · ${esc(r.period_label)} · ${esc(r.basis)}</b> ${badge(r.verified)}<small>Rs crore · <a target="_blank" rel="noopener noreferrer" href="${esc(r.source_url)}">Original filing ↗</a> · PDF page ${r.evidence_page??'unknown'}</small>${['revenue','ebitda','pbt','pat'].map(m=>{const c=r.comparison[m];return `<div class="metric-comparison"><b>${m.toUpperCase()}${m==='ebitda'&&/derived/i.test(r.evidence_note)?' (derived)':''}: ${fmt(r[m])} Rs crore</b>${['qoq','yoy'].map(k=>`<small>${k.toUpperCase()} vs ${esc(c[k+'_period'])} (${esc(c[k+'_label'])}): ${change(c,k)} · Δ ${fmt(c[k+'_delta'])} Rs crore ${badge(c[k+'_verified'])}</small>`).join('')}</div>`}).join('')}<p class="evidence">${esc(r.evidence_note)}</p><button class="text-btn review-quarter" data-period="${esc(r.period)}">Load for source review →</button></div>`).join('') : '<p>No quarterly data recorded.</p>') + '<h3>Guidance vs actual</h3>' + (targets.length ? targets.map(r => `<div class="financial-result"><b>${esc(r.period_label)} · ${esc(r.basis)} · ${esc(r.metric.toUpperCase())}</b><div>Target ${fmt(r.target)}, actual ${fmt(r.actual)} ${r.target_kind==='yoy_growth_pct'?'%':'Rs crore'} · <strong>${esc(r.result)}</strong></div><small>In-line tolerance: ±${fmt(r.tolerance)} ${r.target_kind==='yoy_growth_pct'?'percentage points':'Rs crore'}. Actuals: ${badge(r.actual_verified)}</small><small><a target="_blank" rel="noopener noreferrer" href="${esc(r.source_url)}">Guidance source ↗</a>${r.actual_source?` · <a target="_blank" rel="noopener noreferrer" href="${esc(r.actual_source)}">Actual source ↗</a>`:''}</small><p>${esc(r.statement)}</p><blockquote>${esc(r.quote||'Legacy target: source quote missing')}</blockquote><small>${esc(r.note)}</small></div>`).join('') : '<p>No source-quoted guidance recorded.</p>');
        $('financialOutput').querySelectorAll('.review-quarter').forEach(button => button.addEventListener('click', () => {
            const r = quarters.find(x => x.period === button.dataset.period);
            $('quarterPeriod').value = r.period;
            $('qBasis').value = r.basis;
            $('qSource').value = r.source_url;
            $('qPage').value = r.evidence_page ?? '';
            $('qNotes').value = r.evidence_note || '';
            $('qVerified').checked = false;
            for (const [m, id] of Object.entries({
                    revenue: 'qRevenue',
                    ebitda: 'qEbitda',
                    pbt: 'qPbt',
                    pat: 'qPat'
                })) $(id).value = r[m] ?? '';
            $('quarterForm').scrollIntoView({
                behavior: 'smooth'
            });
            toast('Check all figures against the PDF before marking verified.');
        }));
        renderFinancialChart(quarters);
    } catch (e) {
        toast(e.message)
    }
}


// Release 4: review-first table extraction with explicit column, unit and basis.
$('extractFile').addEventListener('change', () => {
    $('extractFileName').textContent = $('extractFile').files[0]?.name || 'No PDF selected'
});
$('extractForm').addEventListener('submit', async e => {
    e.preventDefault();
    const file = $('extractFile').files[0];
    if (!file) return;
    const button = e.currentTarget.querySelector('button[type=submit]');
    button.disabled = true;
    $('extractStatus').textContent = 'Locating financial-statement tables, period columns and units…';
    $('extractCandidates').innerHTML = '';
    try {
        const fd = new FormData();
        fd.append('file', file);
        const result = await req('/financials/extract-pdf', {
            method: 'POST',
            body: fd
        });
        $('extractStatus').textContent = `${result.candidates.length} candidate accounting rows on ${result.pages_with_text} readable pages · ${result.tables_detected} table(s) detected. All require verification.`;
        $('extractCandidates').innerHTML = result.candidates.length ? `<p class="caution">Financial data is NEVER auto-saved. Verify the source table, exact quarter, reporting basis and units before copying.</p>` + result.candidates.map(c => `<div class="candidate-row"><div class="candidate-title"><b>${esc(c.metric.toUpperCase())} · page ${c.page}</b><small>${esc(c.method.replaceAll('_',' '))} · ${esc(c.basis)}</small></div><p class="evidence">${esc(c.evidence)}</p><small>${c.unit_detected?'Unit: '+esc(c.unit_detected)+' · normalized values in INR crore':'Unit: unknown — NO automatic copying'} · ${c.table?'Table '+c.table+', row '+c.row:'strict text row'}</small><div class="candidate-data">${c.values.map(v=>`<div class="candidate-value"><small>${esc(v.period_header)} · column ${v.column}</small><strong>${esc(v.raw)} ${c.unit_detected?esc(c.unit_detected):'unit unknown'}</strong>${v.crore!==null?`<small>Converted: ${esc(v.crore)} INR crore</small><button type="button" class="text-btn candidate-copy" data-metric="${esc(c.metric)}" data-value="${v.crore}" data-page="${c.page}" data-basis="${esc(c.basis)}">Use confirmed column ↗</button>`:'<small class="caution">Cannot convert without a verified unit. Enter manually after checking.</small>'}</div>`).join('')}</div></div>`).join('') : '<p>No sufficiently structured accounting rows were found. This is a safe abstention, not a PDF error. Try another machine-readable results PDF or enter reviewed figures manually.</p>';
        $('extractCandidates').querySelectorAll('.candidate-copy').forEach(btn => btn.addEventListener('click', () => {
            const map = {
                revenue: 'qRevenue',
                ebitda: 'qEbitda',
                pbt: 'qPbt',
                pat: 'qPat'
            };
            $('qVerified').checked = false;
            $(map[btn.dataset.metric]).value = btn.dataset.value;
            $('qPage').value = btn.dataset.page;
            if (['standalone', 'consolidated'].includes(btn.dataset.basis)) $('qBasis').value = btn.dataset.basis;
            toast('Figure copied in INR crore. Confirm year, quarter, scope and original source before saving.');
        }));
    } catch (err) {
        $('extractStatus').textContent = 'Extraction failed: ' + err.message;
        toast(err.message)
    } finally {
        button.disabled = false
    }
});

// A light-weight, dependency-free chart for verified revenue values only.
function renderFinancialChart(records) {
    const list = [...records].filter(x => x.revenue != null && x.verified).sort((a, b) => a.period.localeCompare(b.period)).slice(-8);
    if (list.length < 2) {
        $('financialChart').innerHTML = '<p class="short-status">Add at least two user-verified comparable revenue quarters to show a trend.</p>';
        return
    }
    const max = Math.max(...list.map(x => x.revenue), 1),
        min = Math.min(0, ...list.map(x => x.revenue));
    const w = Math.max(240, Math.min(620, $('financialChart').clientWidth || 320)),
        h = 220,
        px = 45,
        py = 25,
        x = i => px + i * (w - 2 * px) / Math.max(1, list.length - 1),
        y = v => h - py - (v - min) / (max - min || 1) * (h - py * 2);
    const segments = [];
    let active = [];
    list.forEach((r, i) => {
        if (active.length && r.basis !== list[i - 1].basis) {
            segments.push(active);
            active = []
        }
        active.push([x(i), y(r.revenue)])
    });
    if (active.length) segments.push(active);
    $('financialChart').innerHTML = `<h3>Verified revenue trend (INR crore)</h3><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Revenue chart of manually verified quarterly figures"><path d="M${px} ${py} V${h-py} H${w-px}" stroke="#46636b" fill="none"/>${segments.map(a=>`<polyline fill="none" stroke="#bdf59c" stroke-width="3" points="${a.map(pt=>pt.join(',')).join(' ')}"/>`).join('')}${list.map((r,i)=>`<circle cx="${x(i)}" cy="${y(r.revenue)}" r="4" fill="#bdf59c"><title>${esc(r.period)} · ${esc(r.basis)} · ${r.revenue} crore</title></circle><text x="${x(i)}" y="${h-7}" text-anchor="middle" font-size="10" fill="#a8c0c0">${esc(r.period.slice(2))}</text>`).join('')}</svg><p class="short-status">Lines disconnect when reporting basis changes. Figures are user-confirmed, not independently audited by FINN.</p>`;
}

// DIL-free web UI, no background polling or hidden external requests.

async function loadDigest(showToast = false) {
    const generation = ++digestRequest;
    showSkeleton('digestTop', 3);
    $('digestSummary').textContent = 'Loading selected window…';
    $('digestDownload').href = `/api/digest/export?hours=${digestHours}&portfolio_only=true`;
    try {
        const hours = digestHours,
            d = await req(`/digest?hours=${hours}&portfolio_only=true`);
        if (generation !== digestRequest) return;
        $('digestDownload').href = `/api/digest/export?hours=${hours}&portfolio_only=true`;
        $('digestSummary').textContent = `${d.high_priority_events} high priority · ${d.events_total} events · ${d.coverage.portfolio_with_filings}/${d.coverage.portfolio_companies} companies · ${d.market_alerts.length} recorded EOD alerts`;
        $('digestTop').innerHTML = d.events.slice(0, 3).map(g => `<div class="brief-item"><small>${esc(g.ticker)} · PRIORITY ${Number(g.score)}</small><b>${esc(g.title)}</b><small>${esc(g.priority_reason)}</small></div>`).join('') || '<p class="short-status">No source-linked portfolio filings in this window. Try 3d or 7d.</p>';
        if (showToast) toast('Investor brief updated.');
    } catch (error) {
        if (generation === digestRequest) {
            $('digestTop').innerHTML = errorHTML(error.message, 'digest');
            $('digestSummary').textContent = 'Brief unavailable. Please try again.'
        }
    } finally {
        if (generation === digestRequest) finishLoading('digestTop')
    }
}

$('digestRefreshBtn').addEventListener('click', () => loadDigest(true));
$('feedExportBtn').addEventListener('click', () => window.open('/api/digest/export?hours=' + encodeURIComponent($('window').value), '_blank'));

$('loadBundledBtn').addEventListener('click', async () => {
    try {
        const r = await req('/bse/import-bundled', {
            method: 'POST'
        });
        $('bseResult').textContent = `Historical BSE snapshot: ${r.added} added, ${r.duplicates} already present. Original links retained.`;
        $('window').value = '168';
        $('feedTicker').value = '';
        await loadFeed();
        toast('Official BSE sample loaded (historical snapshot, not live).')
    } catch (e) {
        toast(e.message)
    }
});


async function loadAlerts() {
    try {
        const items = await req('/alerts?limit=12');
        const html = items.length ? items.map(a => `<div class="event"><span class="event-icon" aria-hidden="true">!</span><div><div class="event-title">${esc(a.ticker)} · ${esc(a.alert_type.toUpperCase())}</div><div class="event-meta">EOD ${esc(a.market_date)} · Price ${a.price_change_pct??'—'}% · Volume ${a.volume_multiple??'—'}×</div></div></div>`).join('') : '<p class="short-status">No recorded market alerts yet. Refresh EOD prices to evaluate your thresholds.</p>';
        $('alertHistory').innerHTML = html;
        $('alertsEodHistory').innerHTML = html;
    } catch (error) {
        $('alertHistory').innerHTML = errorHTML(error.message, 'alerts');
        $('alertsEodHistory').innerHTML = $('alertHistory').innerHTML
    } finally {
        finishLoading('alertHistory');
        finishLoading('alertsEodHistory')
    }
}

// Poll saved collection state; only reload filings when the dataset changes.
let feedFreshness = null,
    lastFeedChange = null,
    feedStatusSeen = false;

function paintFreshness() {
    const el = $('feedFreshness');
    if (!feedFreshness) {
        el.textContent = 'Update status unavailable';
        return
    }
    const stamp = Date.parse(feedFreshness.last_success),
        age = Number.isFinite(stamp) ? Math.max(0, Math.floor((Date.now() - stamp) / 60000)) : null;
    el.textContent = (age === null ? 'Automatic check pending' : `Checked ${age} min ago`) + ` · ${feedFreshness.source}`;
    $('autoFeedStatus').textContent = (feedFreshness.running ? 'Collecting announcements… ' : age === null ? 'Waiting for the next collection. ' : `Last successful check ${age} min ago. `) + `${feedFreshness.filings_total} filings from ${feedFreshness.companies_with_filings}/20 companies stored. Checks every 15 minutes.` + (feedFreshness.errors?.length ? ` ${feedFreshness.errors.length} company/source checks failed; saved filings remain available.` : '');
    $('widenFeedBtn').hidden = Number($('window').value) >= 168 || filings.length > 0;
}
async function refreshFreshness() {
    try {
        const value = await req('/feed/status');
        feedFreshness = value;
        paintFreshness();
        if (feedStatusSeen && (value.last_added_at || null) !== lastFeedChange) await Promise.allSettled([loadFeed(), loadOverview(), loadDigest(), loadFilingAlerts()]);
        lastFeedChange = value.last_added_at || null;
        feedStatusSeen = true;
    } catch {
        feedFreshness = null;
        paintFreshness()
    }
}
$('checkFeedBtn').addEventListener('click', async () => {
    const button = $('checkFeedBtn');
    button.disabled = true;
    try {
        feedFreshness = await req('/feed/refresh', {
            method: 'POST'
        });
        paintFreshness();
        await loadFeed();
        toast(feedFreshness.running ? 'Automatic collection is running. New filings appear when it finishes.' : 'Collection is scheduled every 15 minutes; showing saved filings.')
    } catch (e) {
        toast(e.message)
    } finally {
        button.disabled = false
    }
});
$('widenFeedBtn').addEventListener('click', () => {
    $('window').value = '168';
    loadFeed()
});
setInterval(refreshFreshness, 60000);

function newsHTML(n) {
    const safeLink = String(n.link || '').startsWith('https://') ? n.link : '#';
    return `<div class="news-item"><a href="${esc(safeLink)}" target="_blank" rel="noopener noreferrer">${esc(n.title)} ↗</a><small>${esc(n.ticker)} · ${esc(n.source)} · ${dateLabel(n.published)}</small></div>`;
}

function relatedNews(ticker) {
    const matches = newsRows.filter(n => n.ticker === ticker).slice(0, 3);
    return matches.length ? `<details class="related-news"><summary>Market context · ${esc(ticker)} · secondary sources</summary>${matches.map(newsHTML).join('')}</details>` : '';
}
async function loadNews(hours) {
    try {
        newsRows = await req('/news?hours=' + encodeURIComponent(hours));
        newsError = false
    } catch {
        newsRows = [];
        newsError = true
    }
    const company = $('feedTicker').value;
    const selected = newsRows.filter(n => !company || n.ticker === company).slice(0, 20);
    $('marketContext').innerHTML = selected.length ? selected.map(newsHTML).join('') :
        `<p class="short-status">${newsError?'Market context is temporarily unavailable.':'No company headlines available in this time window.'}</p>`;
    finishLoading('marketContext');
}

let contextRequest = 0;
async function loadCompanyContext(ticker) {
    const generation = ++contextRequest,
        box = $('companyContext');
    box.innerHTML = skeletons(2);
    try {
        const data = await req('/company-context/' + encodeURIComponent(ticker) + '?basis=' + encodeURIComponent($('contextBasis').value));
        if (generation !== contextRequest) return;
        if (data.status === 'unavailable') {
            box.textContent = data.error;
            return
        }
        box.innerHTML = `<p><b>${esc(data.company)} · ${esc(data.basis)}</b></p><span class="tag review-unverified">${esc(data.verification)}</span><p class="short-status">${data.stale?'Stale saved snapshot':'Fetched '+dateLabel(data.fetched_at)} · ${esc(data.source)} · Cache up to 6 hours</p>${data.stale?`<p class="caution">${esc(data.error)} · Last fetched ${dateLabel(data.fetched_at)}</p>`:''}<div class="context-ratios">${data.ratios.map(r=>`<div><small>${esc(r.name)}</small><b>${esc(r.value)}</b></div>`).join('')}</div><h3>Recent quarterly results</h3><p class="short-status">${esc(data.unit_note)}</p><div class="context-table-wrap"><table class="context-table"><thead><tr><th>Metric</th>${data.periods.map(p=>`<th>${esc(p)}</th>`).join('')}</tr></thead><tbody>${data.quarterly_rows.map(r=>`<tr><th>${esc(r.metric)}</th>${r.values.map(v=>`<td>${esc(v||'—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="short-status">${esc(data.note)}</p><a target="_blank" rel="noopener noreferrer" href="${esc(data.source_url)}">Source: Screener.in ↗</a>`;
    } catch (error) {
        if (generation === contextRequest) box.textContent = 'Screener snapshot unavailable. Primary-document research remains available.'
    }
}
$('contextBasis').addEventListener('change', () => loadCompanyContext(currentSymbol()));


async function loadSettings() {
    if (settingsPromise) return settingsPromise;
    $('saveSettingsBtn').disabled = true;
    settingsPromise = (async () => {
        try {
            let value = await req('/settings');
            let restored = false;
            let backup = null;
            try {
                backup = JSON.parse(storage.get('finn.alert-settings', 'null'));
            } catch {}
            if (!value.revision && backup?.revision && validSettingsBackup(backup)) {
                value = await req('/settings', json('PUT', settingsBody(backup)));
                restored = true;
            }
            savedSettings = {
                ...value,
                event_types: value.event_types || [...EVENT_TYPES]
            };
            $('priceThreshold').value = value.price_threshold;
            $('volumeThreshold').value = value.volume_threshold;
            if (![...$('alertMinPriority').options].some(o => Number(o.value) === value.min_priority)) $('alertMinPriority').add(new Option(String(value.min_priority), String(value.min_priority)));
            $('alertMinPriority').value = value.min_priority;
            $('eventTypeChoices').innerHTML = EVENT_TYPES.map(type => `<label class="event-choice"><input type="checkbox" name="event_types" value="${esc(type)}" ${savedSettings.event_types.includes(type)?'checked':''}/><span>${esc(labelEvent(type))}</span></label>`).join('');
            finishLoading('eventTypeChoices');
            if (value.revision) storage.set('finn.alert-settings', JSON.stringify(value));
            $('settingsStatus').textContent = restored ? 'Your saved settings were restored after the server reset.' : 'Saved settings loaded.';
            $('saveSettingsBtn').disabled = false;
        } catch (error) {
            $('settingsStatus').textContent = 'Could not load saved settings. ' + error.message;
            $('eventTypeChoices').innerHTML = errorHTML('Settings unavailable.', 'settings');
            finishLoading('eventTypeChoices')
        } finally {
            settingsPromise = null
        }
    })();
    return settingsPromise;
}

function settingsBody(value) {
    return {
        price_threshold: value.price_threshold,
        volume_threshold: value.volume_threshold,
        min_priority: value.min_priority,
        event_types: value.event_types
    };
}

function validSettingsBackup(value) {
    return Number.isFinite(value.price_threshold) && value.price_threshold >= .1 && value.price_threshold <= 99 &&
        Number.isFinite(value.volume_threshold) && value.volume_threshold >= 1.01 && value.volume_threshold <= 100 &&
        Number.isInteger(value.min_priority) && value.min_priority >= 0 && value.min_priority <= 100 &&
        Array.isArray(value.event_types) && value.event_types.every(x => EVENT_TYPES.includes(x));
}
async function loadFilingAlerts() {
    const generation = ++alertRequest;
    showSkeleton('filingAlerts', 2);
    try {
        const groups = await req('/alerts/filings?hours=168');
        if (generation !== alertRequest) return;
        lastAlertGroups = groups;
        renderGroupedList('filingAlerts', groups);
        if (!groups.length) $('filingAlerts').innerHTML = '<div class="empty">No matching filing alerts in the last 7 days. Adjust your saved event types or minimum priority.</div>';
    } catch (error) {
        if (generation === alertRequest) $('filingAlerts').innerHTML = errorHTML(error.message, 'filing-alerts')
    } finally {
        if (generation === alertRequest) finishLoading('filingAlerts')
    }
}
$('settingsForm').addEventListener('submit', async event => {
    event.preventDefault();
    const button = $('saveSettingsBtn');
    button.disabled = true;
    button.textContent = 'Saving…';
    $('settingsStatus').textContent = 'Saving alert settings…';
    try {
        savedSettings = await req('/settings', json('PUT', {
            price_threshold: Number($('priceThreshold').value),
            volume_threshold: Number($('volumeThreshold').value),
            min_priority: Number($('alertMinPriority').value),
            event_types: [...document.querySelectorAll('#eventTypeChoices input:checked')].map(x => x.value)
        }));
        storage.set('finn.alert-settings', JSON.stringify(savedSettings));
        $('settingsStatus').textContent = 'Saved. Your settings will be here after reload. Refresh EOD data to apply market thresholds.';
        toast('Alert settings saved.');
        await loadFilingAlerts();
    } catch (error) {
        $('settingsStatus').textContent = 'Not saved. ' + error.message
    } finally {
        button.disabled = false;
        button.textContent = 'Save alert settings'
    }
});
$('eventsAll').addEventListener('click', () => document.querySelectorAll('#eventTypeChoices input').forEach(x => x.checked = true));
$('eventsNone').addEventListener('click', () => document.querySelectorAll('#eventTypeChoices input').forEach(x => x.checked = false));
$('alertsRefreshBtn').addEventListener('click', () => Promise.allSettled([loadFilingAlerts(), loadAlerts()]));
document.querySelectorAll('[data-digest-hours]').forEach(button => button.addEventListener('click', () => {
    digestHours = Number(button.dataset.digestHours);
    storage.set('finn.digest.hours', digestHours);
    paintDigestWindow();
    Promise.allSettled([loadOverview(), loadDigest()]);
}));
document.addEventListener('click', event => {
    const company = event.target.closest('[data-company]');
    if (company) {
        $('ticker').value = company.dataset.company;
        switchTab('research')
    }
    const retry = event.target.closest('[data-retry]');
    if (retry)({
        feed: loadFeed,
        overview: loadOverview,
        digest: loadDigest,
        alerts: loadAlerts,
        'filing-alerts': loadFilingAlerts,
        settings: loadSettings,
        research: loadDocs,
        market: loadMarket,
        portfolio: () => loadPortfolio().catch(() => toast('Company list unavailable. Please try again.'))
    })[retry.dataset.retry]?.();
});
window.addEventListener('popstate', () => switchTab(location.hash.slice(1) || 'overview', false));

function decorateTables() {
    document.querySelectorAll('table').forEach(table => {
        const headers = [...table.querySelectorAll('thead tr:first-child th')].map(x => x.textContent.trim());
        table.querySelectorAll('tbody tr').forEach(row => [...row.children].forEach((cell, index) => {
            if (cell.tagName === 'TD' && !cell.dataset.label) cell.dataset.label = headers[index] || 'Value';
        }));
    });
}
new MutationObserver(decorateTables).observe(document.querySelector('.content'), {
    childList: true,
    subtree: true
});
document.querySelectorAll('.upload-target').forEach(label => {
    label.tabIndex = 0;
    label.setAttribute('role', 'button');
    label.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            label.querySelector('input[type=file]')?.click()
        }
    });
});
async function boot() {
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
    $('feedCategory').innerHTML = '<option value="">All event types</option>' + EVENT_TYPES.map(x => `<option value="${esc(x)}">${esc(labelEvent(x))}</option>`).join('');
    paintDigestWindow();
    if (matchMedia('(max-width:800px)').matches) document.querySelector('.research-left').removeAttribute('open');
    const tab = location.hash.slice(1) || 'overview';
    switchTab(tab, false);
    const results = await Promise.allSettled([loadFeed(), loadOverview(), loadDigest(), loadPortfolio(), loadStatus(), loadAlerts(), loadSettings(), loadFilingAlerts(), refreshFreshness()]);
    if (results[3].status === 'rejected') $('portfolioList').innerHTML = errorHTML('Company list unavailable.', 'portfolio');
    decorateTables();
}
boot();
