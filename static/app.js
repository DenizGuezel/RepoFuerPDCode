"use strict";

const icons = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/>',
  book: '<path d="M12 5v16M3 3h5a4 4 0 0 1 4 2 4 4 0 0 1 4-2h5v16h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3z"/>',
  pen: '<path d="m15 5 4 4M4 20l4-1L20 7a3 3 0 0 0-4-4L4 15z"/>',
  sliders: '<path d="M5 3v5m0 4v9M12 3v10m0 4v4M19 3v2m0 4v12"/><circle cx="5" cy="10" r="2"/><circle cx="12" cy="15" r="2"/><circle cx="19" cy="7" r="2"/>',
  settings: '<path d="m10 3-.5 2-2 .8-1.8-.6-2 3.4L5 10v3l-1.3 1.4 2 3.4 1.8-.6 2 .8.5 2h4l.5-2 2-.8 1.8.6 2-3.4L19 13v-3l1.3-1.4-2-3.4-1.8.6-2-.8L14 3z"/><circle cx="12" cy="11.5" r="3"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 3h.01"/>',
  spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 2v4m-2-2h4"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 11-2l3 3M4 16l3 3a7 7 0 0 0 11-2"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  file: '<path d="M14 2H5v20h14V7zM14 2v6h5M8 12h8M8 16h6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  send: '<path d="m22 2-7 20-4-9-9-4 20-7Z"/><path d="M22 2 11 13"/>',
  copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 8V3H3v13h5"/>',
  external: '<path d="M14 3h7v7M21 3 10 14M10 3H3v18h18v-7"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 3v3m6-3v3M9 18v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3"/>',
  download: '<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
  pause: '<path d="M9 5v14M15 5v14"/>',
  play: '<path d="m7 4 14 8-14 8z"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  building: '<path d="M5 21V3h14v18M9 7h1m4 0h1M9 11h1m4 0h1M9 15h1m4 0h1M10 21v-3h4v3"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/>',
};
const icon = (name, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.mail}</svg>`;
const gmailIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285f4" d="M2 6v13h4V9z"/><path fill="#34a853" d="M18 9v10h4V6z"/><path fill="#fbbc04" d="m18 9 4-3V4a2 2 0 0 0-3-1l-1 1z"/><path fill="#ea4335" d="m2 6 10 7 10-7-4-2-6 5-6-5z"/><path fill="#c5221f" d="M2 6V4a2 2 0 0 1 3-1l1 1v5z"/></svg>';
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const token = document.querySelector('meta[name="local-token"]').content;
const root = document.getElementById('app');
const modal = document.getElementById('modal');
const routes = {overview:'Übersicht', inbox:'Postfach', knowledge:'Unternehmenswissen', style:'Schreibstil', rules:'Regeln', settings:'Einstellungen'};
const statusLabels = {ready:'Entwurf bereit', saved:'In Gmail gespeichert', review:'Braucht dich', new:'Neu eingegangen', queued:'In Warteschlange', generating:'Wird vorbereitet', skipped:'Keine Antwort nötig', error:'Prüfung erforderlich', protected:'Entwurf geschützt', sending:'Wird gesendet', sent:'Gesendet', send_uncertain:'Versand prüfen'};
let state, route = location.hash.slice(1) || 'overview', mode = localStorage.getItem('amr-view') || 'demo', selected = null, previewTab = 'draft', search = '', statusFilter = '', formDirty = false, refreshing = false, lastRenderedSnapshot = '';
const pendingDrafts = new Map();

async function api(path, data) {
  const response = await fetch(path, {method: data === undefined ? 'GET' : 'POST', headers: {'X-Local-Token': token, ...(data !== undefined ? {'Content-Type':'application/json'} : {})}, ...(data !== undefined ? {body:JSON.stringify(data)} : {})});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Die Aktion konnte nicht abgeschlossen werden.');
  return result;
}
let toastTimer;
function toast(message, error = false) {
  const node = document.getElementById('toast');
  node.textContent = message;
  node.className = 'visible' + (error ? ' error' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.className = '', error ? 7500 : 4000);
}
async function refresh(force = false) {
  if (refreshing) return;
  refreshing = true;
  try {
    state = await api('/api/state');
    const editing = document.activeElement?.isContentEditable || ['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName);
    if (!formDirty && !modal.open && (force || (!editing && JSON.stringify(state)!==lastRenderedSnapshot))) render();
  } catch (error) {
    if (!state) root.innerHTML = `<div class="boot"><span class="boot-mark">m</span><p>Die lokale Anwendung ist nicht erreichbar.</p><button class="btn" data-action="reload">Erneut versuchen</button></div>`;
    else if (force) toast(error.message, true);
  } finally { refreshing = false; }
}
function displayTime(timestamp) { return new Date(timestamp*1000).toLocaleTimeString('de-DE', {hour:'2-digit', minute:'2-digit'}); }
function initials(name) { return name.split(/\s+/).slice(0,2).map(x => x[0]).join('').toUpperCase(); }
function statusBadge(status) { return `<span class="status ${esc(status)}">${icon(['ready','saved','sent'].includes(status)?'check':['review','error','protected','send_uncertain'].includes(status)?'alert':['queued','generating','sending'].includes(status)?'clock':'mail', status==='generating'?'spinner':'')}${esc(statusLabels[status] || status)}</span>`; }
function button(action, label, name, primary=false, extra='') { return `<button type="button" class="btn${primary?' primary':''}" data-action="${action}" ${extra}>${name?icon(name):''}${label}</button>`; }

function render() {
  lastRenderedSnapshot=JSON.stringify(state);
  if (!routes[route]) route='overview';
  const s=state.settings;
  const ready=state.threads.filter(t=>t.source==='gmail'&&['ready','saved'].includes(t.status)).length;
  root.innerHTML = `<div class="layout">
    <aside class="sidebar" aria-label="Hauptnavigation"><button class="icon-btn mobile-close" data-action="menu" aria-label="Navigation schließen">${icon('close')}</button>
      <a href="#overview" class="brand"><img src="/icon.svg" alt=""><div class="brand-text"><div class="brand-name">AI Mail Responder</div><div class="brand-sub">Dein lokaler Assistent</div></div></a>
      <div class="workspace"><span class="workspace-icon">${icon('building')}</span><div><strong>${esc(s.company||'Mein Arbeitsbereich')}</strong><small>${state.gmail.connected?'Gmail verbunden':'Persönlicher Arbeitsbereich'}</small></div></div>
      <div class="eyebrow">Arbeitsbereich</div><nav class="nav">${[['overview','grid'],['inbox','mail'],['knowledge','book'],['style','pen'],['rules','sliders']].map(([key,i])=>`<a href="#${key}" class="${route===key?'active':''}" ${route===key?'aria-current="page"':''}>${icon(i)}<span class="nav-label">${routes[key]}</span>${key==='inbox'&&ready?`<span class="nav-count">${ready}</span>`:''}</a>`).join('')}</nav>
      <div class="sidebar-bottom"><nav class="nav"><a href="#settings" class="${route==='settings'?'active':''}" ${route==='settings'?'aria-current="page"':''}>${icon('settings')}<span class="nav-label">Einstellungen</span></a></nav>
      <div class="local-card"><strong><span class="dot ${state.model.selected_ready?'':'amber'}"></span>${state.model.selected_ready?'Lokales Modell bereit':'Lokales Modell einrichten'}</strong><p>${esc(s.model)}</p><div class="local-meta"><span>6 GB VRAM · Zielprofil</span><span>Lokal</span></div></div><div class="sidebar-foot">PERSÖNLICH. LOKAL. IN DEINER HAND.</div></div>
    </aside>
    <div class="page"><header class="topbar"><div class="breadcrumb"><button class="icon-btn mobile-menu" data-action="menu" aria-label="Navigation öffnen">${icon('menu')}</button><span>Arbeitsbereich</span><span>/</span><strong>${routes[route]}</strong></div><div class="top-actions"><span class="local-pill">${icon('shield')}Verarbeitung auf deinem Rechner</span>${state.gmail.connected?`<span class="health-badge"><span class="dot"></span>Gmail verbunden</span>`:`<button class="btn small" data-action="setup-gmail">${gmailIcon}Gmail verbinden</button>`}<span class="avatar" aria-hidden="true">${esc(initials(s.company||'Mein Arbeitsbereich'))}</span></div></header>
    <main id="main" class="main" tabindex="-1">${({overview:dashboard,inbox:dashboard,knowledge:knowledgePage,style:stylePage,rules:rulesPage,settings:settingsPage}[route])()}<footer class="bottom-strip"><span>${icon('lock')}Dein Wissen und deine KI bleiben lokal auf diesem Rechner.</span><span>${icon('mail')}Gmail synchronisiert Nachrichten und Entwürfe.</span></footer></main></div></div>`;
}

function onboardingCard(){
  const o=state.onboarding;
  if(!o)return '';
  if(!state.gmail.connected)return `<section class="onboarding-card"><span class="onboarding-icon">${icon('spark')}</span><div class="onboarding-copy"><h3>Einmal verbinden. Dein Unternehmen kennenlernen lassen.</h3><p>Beim ersten Verbinden wird das gesamte Gmail-Postfach lokal geladen – einschließlich gesendeter E-Mails. Deine KI erkennt daraus Unternehmen und Schreibstil.</p></div><a href="#settings" class="btn small">Gmail einrichten ${icon('arrow')}</a></section>`;
  if(o.stage==='complete')return `<section class="onboarding-card complete"><span class="onboarding-icon">${icon('check')}</span><div class="onboarding-copy"><h3>Dein Postfach ist einmalig eingelesen.</h3><p>${Number(o.imported).toLocaleString('de-DE')} E-Mails geladen · ${Number(o.sent).toLocaleString('de-DE')} gesendete Mails · Unternehmen und Schreibstil lokal analysiert. Die Erstanalyse wird bei späteren Starts nicht wiederholt.</p>${!state.settings.company||!state.settings.description?'<p>Einige Unternehmensangaben waren nicht eindeutig erkennbar. Du kannst sie im Profil ergänzen.</p>':''}</div><a href="#knowledge" class="btn small">Profil ansehen ${icon('arrow')}</a></section>`;
  const title={pending:'Dein Assistent lernt dich kennen.',listing:'Dein gesamtes Postfach wird erfasst.',downloading:'Deine E-Mails werden lokal geladen.',analyzing:'Dein Unternehmen und dein Schreibstil werden erkannt.'}[o.stage]||'Einmalige Einrichtung';
  const detail=o.stage==='listing'?`${o.listed.toLocaleString('de-DE')} Nachrichten erfasst, einschließlich Gesendet und Archiv.`:o.stage==='downloading'?`${o.downloaded.toLocaleString('de-DE')} von ${o.listed.toLocaleString('de-DE')} Nachrichten geladen.`:o.stage==='analyzing'?`${o.parts_done.toLocaleString('de-DE')} von ${o.parts_total.toLocaleString('de-DE')} Textabschnitten lokal ausgewertet.`:'Die Einrichtung startet nach der ersten Gmail-Verbindung automatisch.';
  const percent=o.stage==='downloading'&&o.listed?o.downloaded/o.listed*100:o.stage==='analyzing'&&o.parts_total?o.parts_done/o.parts_total*100:0;
  return `<section class="onboarding-card running"><span class="onboarding-icon">${icon(o.error?'alert':'spark',state.gmail.syncing&&!state.settings.paused?'spinner':'')}</span><div class="onboarding-copy"><h3>${title}${state.settings.paused?' · pausiert':''}</h3><p>${detail}</p><div class="onboarding-progress"><span style="width:${Math.min(100,Math.round(percent))}%"></span></div><p class="tiny">Nur einmal pro Konto. Nach Unterbrechungen geht es am gespeicherten Stand weiter. Alte E-Mails erhalten dadurch keine automatischen Antworten.</p>${o.error?`<p class="onboarding-error">${esc(o.error)}</p>`:''}</div>${button('sync',state.gmail.syncing?'Wird eingerichtet':o.error?'Fortsetzen':'Einrichtung starten','refresh',false,state.gmail.syncing||state.settings.paused?'disabled':'')}</section>`;
}

function dashboard() {
  const rows=state.threads.filter(t=>t.source===(mode==='demo'?'demo':'gmail'));
  let filtered=rows.filter(t=>(!statusFilter||t.status===statusFilter)&&`${t.sender_name} ${t.sender} ${t.subject} ${t.body}`.toLowerCase().includes(search.toLowerCase()));
  if(!filtered.some(t=>t.id===selected)) selected=filtered[0]?.id||null;
  const row=filtered.find(t=>t.id===selected);
  const ready=rows.filter(t=>['ready','saved'].includes(t.status)).length, running=rows.filter(t=>['new','queued','generating'].includes(t.status)).length, review=rows.filter(t=>['review','error','protected','send_uncertain'].includes(t.status)).length;
  const completed=[state.model.selected_ready,state.onboarding.stage==='complete'&&!!state.settings.company&&!!state.settings.description,state.gmail.connected];
  return `<div class="page-heading"><div><h1>${route==='inbox'?'Dein Postfach, gut vorbereitet.':'Weniger tippen. Mehr Zeit.'}</h1><p>Persönliche Antworten, vorbereitet von deiner lokalen KI.</p></div><div class="heading-tools">${button('pause',state.settings.paused?'Fortsetzen':'Pausieren',state.settings.paused?'play':'pause',false)}${button('sync',state.gmail.syncing?'Wird synchronisiert':'Synchronisieren','refresh',false,state.gmail.connected&&!state.gmail.syncing?'':'disabled')}</div></div>
    ${onboardingCard()}${state.settings.paused?'<div class="note">Die Verarbeitung ist pausiert. Ein bereits laufender Entwurf wird lokal fertiggestellt.</div>':''}
    <div class="stats"><div class="stat"><div class="stat-head">Entwürfe bereit<span class="stat-icon">${icon('pen')}</span></div><div class="stat-line"><span class="stat-number">${ready.toString().padStart(2,'0')}</span><small>${mode==='demo'?'Fiktive Vorschau':'Zum Prüfen und Absenden'}</small></div></div><div class="stat"><div class="stat-head">Noch vorzubereiten<span class="stat-icon">${icon('clock')}</span></div><div class="stat-line"><span class="stat-number">${running.toString().padStart(2,'0')}</span><small>${mode==='demo'?'Fiktive Vorschau':'Neue und wartende Nachrichten'}</small></div></div><div class="stat"><div class="stat-head">Brauchen dich<span class="stat-icon">${icon('alert')}</span></div><div class="stat-line"><span class="stat-number">${review.toString().padStart(2,'0')}</span><small>${mode==='demo'?'Fiktive Vorschau':'Deine Entscheidung ist gefragt'}</small></div></div></div>
    ${completed.every(Boolean)?`<div class="setup-banner"><div class="setup-left"><span class="setup-symbol">${icon('check')}</span><div><h3>Dein Assistent ist eingerichtet.</h3><p>${state.settings.automatic?'Automatische Entwürfe sind aktiv.':'Du kannst Entwürfe einzeln erstellen oder die Automatik aktivieren.'}</p></div></div><a href="#rules" class="btn small">Automatik verwalten ${icon('arrow')}</a></div>`:`<div class="setup-banner"><div class="setup-left"><span class="setup-symbol">${icon('spark')}</span><div><h3>Mach deinen Assistenten startklar.</h3><p>Lokales Modell einrichten und Gmail verbinden. Unternehmen und Schreibstil werden einmalig erkannt.</p></div></div><div class="setup-right"><div class="progress-dots" aria-label="${completed.filter(Boolean).length} von 3 Schritten erledigt">${completed.map(c=>`<span class="${c?'done':''}"></span>`).join('')}</div><a href="#settings" class="btn small">Einrichtung öffnen ${icon('arrow')}</a></div></div>`}
    <div class="section-heading"><div><h2>${mode==='demo'?'Ein Blick in deinen neuen Alltag':'Deine Nachrichten'} <span class="section-count">${rows.length}</span></h2><p>${mode==='demo'?'Lerne den Ablauf mit fiktiven Nachrichten kennen.':'Alle Entwürfe bleiben bis zu deinem Versand ungesendet.'}</p></div><div class="segmented" aria-label="Datenansicht"><button data-action="mode" data-mode="gmail" class="${mode==='gmail'?'active':''}" aria-pressed="${mode==='gmail'}">Mein Gmail</button><button data-action="mode" data-mode="demo" class="${mode==='demo'?'active':''}" aria-pressed="${mode==='demo'}">Beispielansicht</button></div></div>
    <div class="mail-workspace"><section class="card" aria-label="Nachrichten"><div class="mail-list-tools"><label class="search">${icon('search')}<input id="mail-search" placeholder="Nachrichten durchsuchen" aria-label="Nachrichten durchsuchen" value="${esc(search)}"></label><select class="filter-select" id="status-filter" aria-label="Nach Status filtern"><option value="">Alle Status</option>${['ready','review','new','saved','skipped','error','protected','queued','generating','sending','sent','send_uncertain'].map(s=>`<option value="${s}" ${statusFilter===s?'selected':''}>${statusLabels[s]}</option>`).join('')}</select></div><div id="mail-rows">${filtered.map((t,i)=>mailRow(t,i)).join('')||`<div class="empty live-empty">${icon(mode==='demo'?'search':'mail')}<h3>${rows.length?'Keine Treffer':state.gmail.connected?'Dein Postfach wartet':'Verbinde dein Gmail-Postfach'}</h3><p>${rows.length?'Passe deine Suche oder den Statusfilter an.':state.gmail.connected?'Synchronisiere deine Nachrichten, um erste Entwürfe vorzubereiten.':'Danach erscheinen deine echten Nachrichten hier.'}</p>${!rows.length?button(state.gmail.connected?'sync':'setup-gmail',state.gmail.connected?'Jetzt synchronisieren':'Gmail einrichten',state.gmail.connected?'refresh':'arrow',true):''}</div>`}</div><div class="list-foot"><span>${filtered.length} ${filtered.length===1?'Nachricht':'Nachrichten'}</span><span>${mode==='demo'?'Beispieldaten':'Letzter Abruf: '+(state.gmail.last_sync?displayTime(state.gmail.last_sync):'–')}</span></div></section>
    <section class="card" id="preview" aria-label="Antwortvorschau">${row?preview(row):`<div class="empty live-empty">${icon('pen')}<h3>Hier entsteht deine Antwort.</h3><p>Wähle links eine Nachricht aus.<br>Dein Entwurf erscheint dann an dieser Stelle.</p></div>`}</section></div>
    ${mode==='demo'?`<p class="demo-note">${icon('alert')}Beispielansicht: Alle Kontakte, Nachrichten und vorbereiteten Antworten sind fiktiv.</p>`:''}`;
}
function mailRow(t,index){return `<button class="mail-row ${selected===t.id?'active':''}" data-action="select" data-id="${esc(t.id)}" aria-pressed="${selected===t.id}"><span class="sender-avatar ${['','sand','rose','mint'][index%4]}">${esc(initials(t.sender_name))}</span><span class="mail-row-content"><span class="row-top"><strong>${esc(t.sender_name)}</strong><time>${displayTime(t.received)}</time></span><span class="mail-subject">${esc(t.subject)}</span><span class="mail-snippet">${esc(t.body.replace(/\n/g,' '))}</span><span class="row-bottom">${statusBadge(t.status)}<span class="source-mark">${t.source==='demo'?'BEISPIEL':'GMAIL'}</span></span></span></button>`;}

function draftFor(thread) {
  return pendingDrafts.get(thread.id) ?? {text:thread.draft, html:thread.draft_html, revision:thread.revision};
}

function preview(t) {
  const draft = draftFor(t);
  const busy = ['queued', 'generating', 'sending'].includes(t.status);
  const locked = ['sending', 'sent', 'send_uncertain'].includes(t.status);
  const changed = pendingDrafts.has(t.id);
  const usable = Boolean(draft.text?.trim()) && !busy && !locked;
  const id = `data-id="${esc(t.id)}" data-revision="${esc(t.revision)}"`;
  let content;

  if (previewTab === 'original') {
    content = t.messages.map(m => `<div class="message-author">${esc(m.from)}</div><div class="original-message">${esc(m.body)}</div>`).join('');
  } else if (previewTab === 'context') {
    content = `<div class="original-message"><h3>Berücksichtigtes Wissen</h3>
      <p>${t.sources.length ? esc(t.sources.join('\n')) : 'Noch keine Wissensquellen verwendet.'}</p><br>
      <h3>Verarbeitung</h3><p>${esc(t.generated_by || 'Noch nicht erstellt')}${t.duration ? ' · '+t.duration+' Sekunden' : ''}</p>
      <p>${state.settings.use_history ? 'Früher importierte Gespräche desselben Kontakts dürfen einbezogen werden.' : 'Zusätzliche frühere Gespräche sind ausgeschaltet.'}</p></div>`;
  } else if (t.status === 'sent') {
    content = '<div class="empty"><h3>Deine Antwort wurde gesendet.</h3><p>Du findest sie in Gmail unter „Gesendet“.</p></div>';
  } else if (draft.text || changed || t.status === 'send_uncertain') {
    const label = t.generated_by === 'Beispielentwurf' ? 'Vorbereiteter Beispieltext' : t.generated_by || 'Lokaler Entwurf';
    content = `<div class="draft-toolbar"><span>${icon('pen')}${esc(label)}${t.duration ? ' · '+t.duration+' s' : ''}</span>
      ${t.user_edited ? '<span>Von dir bearbeitet</span>' : ''}</div>${richEditor(t.id, draft, !busy && !locked)}`;
  } else {
    const skipped = t.status === 'skipped';
    const title = busy ? 'Dein Entwurf wird vorbereitet.' : skipped ? 'Die KI sieht hier keinen Antwortbedarf.' : 'Bereit für einen guten ersten Entwurf?';
    const detail = busy ? 'Die lokale KI verarbeitet diese Nachricht.' : 'Du kannst einen Entwurf erstellen lassen oder deine Antwort selbst schreiben.';
    content = `<div class="empty">${icon(busy ? 'clock' : 'spark', busy ? 'spinner' : '')}<h3>${title}</h3><p>${detail}</p>
      ${!busy ? `<div class="compose-options">${button('generate', skipped ? 'Entwurf trotzdem erstellen' : 'Entwurf erstellen', 'spark', true, id)}
        ${button('compose', 'Selbst schreiben', 'pen', false, id)}</div>` : ''}</div>`;
  }

  const draftButtons = locked ? '' : `<div class="footer-actions">
    ${button('copy', 'Kopieren', 'copy', false, `${id} ${usable ? '' : 'disabled'}`)}
    ${changed ? button('save-draft', 'Lokal speichern', 'check', false, `${id} ${usable ? '' : 'disabled'}`) :
      draft.text && !t.user_edited && t.status !== 'protected' ? button('generate', 'Neu erstellen', 'refresh', false, `${id} ${busy ? 'disabled' : ''}`) : ''}</div>
    ${t.source === 'gmail' ? `<div class="footer-actions">
      ${button('publish', t.draft_id ? 'In Gmail aktualisieren' : 'In Gmail speichern', 'external', false, `${id} ${usable ? '' : 'disabled'}`)}
      ${button('prepare-send', 'Senden…', 'send', true, `${id} ${usable ? '' : 'disabled'}`)}</div>` : '<span class="preview-note">Beispiel bleibt lokal.</span>'}`;
  return `<div class="preview-head"><h3>${icon('pen')}Antwortvorschau</h3>${statusBadge(t.status)}</div>
    <div class="preview-body"><h2 class="preview-subject">${esc(t.subject)}</h2>
    <div class="recipient">An <strong>${esc(t.sender_name)}</strong><span>&lt;${esc(t.reply_recipient || t.sender)}&gt;</span></div>
    <div class="preview-tabs" role="tablist" aria-label="Nachrichtenansicht">
    ${[['draft','Antwortentwurf'],['original','Originalnachricht'],['context','Kontext']].map(([key,label]) =>
      `<button role="tab" aria-selected="${previewTab===key}" class="${previewTab===key?'active':''}" data-action="preview-tab" data-tab="${key}">${label}</button>`).join('')}</div>
    ${t.error ? `<div class="note error-note">${esc(t.error)}</div>` : ''}
    ${t.notes.length ? `<div class="note"><strong>${t.status==='skipped'?'Hinweis':'Ein Punkt für dich'}</strong><ul>${t.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul></div>` : ''}
    ${content}${t.sources.length ? `<div class="source-tags">${t.sources.map(s=>`<span class="source-tag">${icon('book')}${esc(s)}</span>`).join('')}</div>` : ''}</div>
    ${draftButtons ? `<div class="preview-footer">${draftButtons}</div>` : ''}`;
}

function rememberDraft(editor) {
  const id = editor.dataset.id;
  const row = state.threads.find(thread => thread.id === id);
  if (!row) return;
  const draft = {text:editor.innerText, html:cleanEditorHTML(editor.innerHTML), revision:pendingDrafts.get(id)?.revision ?? Number(editor.dataset.revision)};
  pendingDrafts.set(id, draft);
  const footer = document.querySelector('.preview-footer');
  if (!footer) return;
  footer.querySelector('[data-action="generate"]')?.remove();
  if (!footer.querySelector('[data-action="save-draft"]')) {
    footer.querySelector('.footer-actions').insertAdjacentHTML('beforeend',
      button('save-draft', 'Lokal speichern', 'check', false, `data-id="${esc(id)}"`));
  }
  for (const action of footer.querySelectorAll('[data-action="save-draft"], [data-action="copy"], [data-action="publish"], [data-action="prepare-send"]')) {
    action.disabled = !draft.text.trim();
  }
}

async function savePendingDraft(id, displayedRevision) {
  const row = state.threads.find(thread => thread.id === id);
  const pending = pendingDrafts.get(id);
  if (!pending) return displayedRevision ?? row.revision;
  const saved = await api('/api/thread/edit', {id, ...pending});
  row.revision = saved.revision;
  row.draft = pending.text;
  row.draft_html = pending.html;
  row.user_edited = 1;
  const editor = document.getElementById('draft-editor');
  if (editor?.dataset.id === id) editor.dataset.revision = saved.revision;
  if (pendingDrafts.get(id) !== pending) {
    pendingDrafts.get(id).revision = saved.revision;
    throw new Error('Der Entwurf wurde während des Speicherns weiter bearbeitet. Bitte wiederhole die Aktion.');
  }
  pendingDrafts.delete(id);
  return saved.revision;
}

function openSendDialog(id, confirmation) {
  modal.innerHTML = `<form data-form="send"><div class="modal-head"><h2 id="modal-title">Antwort senden?</h2></div>
    <p>Gmail verschickt diese Antwort sofort.</p>
    <dl class="send-details"><dt>An</dt><dd>${esc(confirmation.recipient)}</dd><dt>Betreff</dt><dd>${esc(confirmation.subject)}</dd></dl>
    <input type="hidden" name="id" value="${esc(id)}">
    <input type="hidden" name="confirmation" value="${esc(confirmation.confirmation)}">
    <div class="modal-actions"><button type="button" class="btn" data-action="close-modal" autofocus>Abbrechen</button>
    <button class="btn primary" type="submit">${icon('send')}Jetzt senden</button></div></form>`;
  modal.showModal();
}

function heading(title,description){return `<div class="page-heading"><div><h1>${title}</h1><p>${description}</p></div></div>`;}
function input(name,label,value,help='',type='text'){return `<label class="field"><span>${label}</span><input name="${name}" type="${type}" value="${esc(value)}" ${name==='company'?'maxlength="180"':''}>${help?`<small>${help}</small>`:''}</label>`;}
function textarea(name,label,value,help='',rows=4){return `<label class="field"><span>${label}</span><textarea name="${name}" rows="${rows}">${esc(value)}</textarea>${help?`<small>${help}</small>`:''}</label>`;}
function select(name,label,value,options,help=''){return `<label class="field"><span>${label}</span><select name="${name}">${options.map(o=>`<option value="${esc(o[0])}" ${String(value)===String(o[0])?'selected':''}>${esc(o[1])}</option>`).join('')}</select>${help?`<small>${help}</small>`:''}</label>`;}
function saveActions(){return '<div class="form-actions"><small class="muted">Wird auf diesem Rechner gespeichert.</small><button class="btn primary" type="submit">'+icon('check')+'Änderungen speichern</button></div>';}
function knowledgePage(){const s=state.settings;return `${heading('Dein Wissen. Die Grundlage.','Gute Antworten beginnen mit den richtigen Informationen.')}${onboardingCard()}<div class="form-layout"><div><form class="card form-card" data-form="settings"><h2>Dein Unternehmensprofil</h2><p>Beim ersten Verbinden aus deinen E-Mails erkannt. Du kannst alle Angaben ergänzen und korrigieren.</p>${input('company','Unternehmensname',s.company)}${textarea('description','Was sollte dein Assistent über dein Unternehmen wissen?',s.description,'Beschreibe Leistungen, Zielgruppe, Abläufe und bestätigte Konditionen.',6)}${saveActions()}</form><section class="card form-card"><div class="section-heading"><div><h2>Deine Wissenssammlung</h2><p>Leistungen, Abläufe, Preise und häufige Fragen.</p></div>${button('add-document','Wissen ergänzen','plus')}</div><input class="file-input" id="knowledge-file" type="file" accept=".txt,.md,.csv"><div class="document-list">${state.documents.map(d=>`<div class="doc-row"><span class="doc-icon">${icon('file')}</span><div class="doc-text"><strong>${esc(d.title)}</strong><small>${d.content.length.toLocaleString('de-DE')} Zeichen · Lokal gespeichert</small></div><div class="doc-actions"><button class="icon-btn" data-action="edit-document" data-id="${esc(d.id)}" aria-label="${esc(d.title)} bearbeiten">${icon('pen')}</button><button class="icon-btn" data-action="delete-document" data-id="${esc(d.id)}" aria-label="${esc(d.title)} löschen">${icon('trash')}</button></div></div>`).join('')||`<div class="empty">${icon('book')}<h3>Hier bekommt dein Assistent Hintergrundwissen.</h3><p>Füge einen Text hinzu oder importiere eine Textdatei.</p>${button('import-document','Datei importieren','download')}</div>`}</div>${state.documents.length?`<div style="margin-top:16px">${button('import-document','Textdatei importieren','download')}</div>`:''}</section></div><aside class="card info-card"><div class="info-icon">${icon('book')}</div><h3>Ein gemeinsamer Wissensstand</h3><p>Die lokale Suche findet für jede Anfrage passende Textstellen. So muss dein Modell nur die Informationen lesen, die für die Antwort relevant sind.</p><br><p>Du kannst Texte aus deiner Website hier einfügen. Unterstützte Dateien: TXT, Markdown und CSV.</p><br><p>Gespeicherte Daten werden nicht an einen KI-Anbieter übertragen.</p></aside></div>`;}
function stylePage(){const s=state.settings;return `${heading('Antworten, die nach dir klingen.','Dein Schreibstil wird beim ersten Verbinden aus eigenen gesendeten E-Mails erkannt.')}${onboardingCard()}<div class="form-layout"><form class="card form-card" data-form="settings"><h2>Dein Schreibstil</h2><p>Diese Vorgaben gelten für neu erstellte Entwürfe.</p><div class="form-grid">${select('salutation','Anrede',s.salutation,[['Sie','Sie'],['Du','Du'],['Wie im Gespräch','Wie im bisherigen Gespräch']])}${select('length','Antwortlänge',s.length,[['Kompakt','Kompakt'],['Mittel','Mittel'],['Ausführlich','Ausführlich']])}</div>${textarea('style_analysis','Erkannter Schreibstil',s.style_analysis,'Einmalig lokal analysierte Sprachmuster. Deine Korrekturen bleiben bei weiteren Starts erhalten.',4)}${input('tone','Tonalität',s.tone,'Zum Beispiel: freundlich, direkt und ohne Floskeln.')}${textarea('signature','Deine Signatur',s.signature,'Wird dem Modell als verbindlicher Signaturtext vorgegeben.',3)}${textarea('style_examples','Eigene Beispielantworten',s.style_examples,'Füge ein bis zwei kurze E-Mails ein, die deinen Schreibstil zeigen.',6)}${saveActions()}</form><aside class="card info-card"><div class="info-icon">${icon('pen')}</div><h3>Persönlich bleibt persönlich.</h3><p>Das erkannte Stilprofil beruht auf deinen eigenen gesendeten Texten. Zitierte Kundenmails werden dafür abgetrennt. Das lokale Modell wird dabei nicht neu trainiert.</p><br><p>Die Antwortsprache richtet sich nach der eingehenden E-Mail. Du kannst jeden Entwurf vor dem Versand bearbeiten.</p></aside></div>`;}
function toggle(action,label,description,on){return `<div class="toggle-row"><div><h3>${label}</h3><p>${description}</p></div><button class="toggle ${on?'on':''}" role="switch" aria-checked="${on}" aria-label="${label}" data-action="${action}"></button></div>`;}
function rulesPage(){const s=state.settings;return `${heading('Dein Assistent. Deine Regeln.','Lege fest, wann und wie Antworten vorbereitet werden.')}<div class="form-layout"><div><section class="card form-card"><h2>Verarbeitung</h2>${toggle('automatic','Entwürfe automatisch vorbereiten','Neue passende Nachrichten werden lokal verarbeitet. Vollständige Entwürfe ohne offene Punkte werden in Gmail gespeichert.',s.automatic)}${toggle('pause','Verarbeitung pausieren','Neue Aufträge und der regelmäßige Gmail-Abruf warten. Ein laufender Entwurf wird lokal fertiggestellt.',s.paused)}${toggle('history','Frühere Gespräche berücksichtigen','Bezieht lokal gespeicherte Nachrichten desselben Kontakts ein. Das Unternehmens- und Stilprofil wird dabei nicht erneut analysiert.',s.use_history)}</section><form class="card form-card" data-form="settings"><h2>Individuelle Vorgaben</h2><p>Formuliere Regeln so, wie du sie einem Kollegen erklären würdest.</p>${textarea('instructions','Antwortregeln',s.instructions,'Beispiel: Für ein Angebot zuerst Umfang und Wunschtermin erfragen. Keine Rabatte zusagen.',5)}${textarea('excluded_senders','Ausgeschlossene Absender',s.excluded_senders,'Eine E-Mail-Adresse oder @domain.de pro Zeile.',3)}${input('gmail_query','Welche Gmail-Nachrichten sollen berücksichtigt werden?',s.gmail_query,'Filter für den laufenden Abruf. Der einmalige Erstimport lädt unabhängig davon das gesamte Postfach.')}${select('sync_seconds','Abrufintervall',s.sync_seconds,[[60,'Jede Minute'],[120,'Alle 2 Minuten'],[300,'Alle 5 Minuten'],[600,'Alle 10 Minuten']])}${saveActions()}</form></div><aside class="card info-card"><div class="info-icon">${icon('shield')}</div><h3>Du behältst das letzte Wort.</h3><p>Die Anwendung erstellt ausschließlich Entwürfe. Du versendest deine Antworten selbst in Gmail.</p><br><p>Newsletter und automatische Absender werden vorab gefiltert. Entwürfe mit offenen Entscheidungen bleiben zur Prüfung in der lokalen Übersicht.</p><br><p>Vorhandene oder in Gmail bearbeitete Entwürfe werden vor einer Änderung geprüft.</p></aside></div>`;}
function settingsPage(){const s=state.settings,m=state.model;const names=m.models.map(x=>x.name);if(!names.includes(s.model))names.unshift(s.model);return `${heading('Alles an seinem Platz.','Verbinde dein Postfach und richte dein lokales Modell ein.')}${onboardingCard()}<div class="form-layout"><div><section class="card form-card" id="model-setup"><div class="section-heading"><div><h2>Lokales KI-Modell</h2><p>Ausgelegt auf eine Zielkonfiguration mit 6 GB VRAM.</p></div><span class="health-badge"><span class="dot ${m.selected_ready?'':'amber'}"></span>${m.selected_ready?'Bereit':m.online?'Modell fehlt':'Nicht verbunden'}</span></div><form data-form="settings">${select('model','Modell in Ollama',s.model,names.map(n=>[n,n]),'Es werden ausschließlich heruntergeladene lokale Modelle verwendet.')}${select('context_size','Kontextfenster',s.context_size,[[2048,'2.048 Tokens · sparsam'],[4096,'4.096 Tokens · Startprofil für 6 GB'],[8192,'8.192 Tokens · höherer Speicherbedarf']])}<div class="form-actions">${button('check-model','Verbindung prüfen','refresh')}<button type="submit" class="btn primary">${icon('check')}Speichern</button></div></form>${!m.selected_ready?`<div class="download-help" style="margin-top:17px">${m.online?'Das ausgewählte Modell ist noch nicht verfügbar.':'Starte Ollama auf diesem Rechner und lade das Startmodell herunter.'}<code>OLLAMA_NO_CLOUD=1 ollama serve</code><code>ollama pull qwen3:4b-instruct</code><small>Einmaliger Modelldownload: ungefähr 2,5 GB. Keine automatischen Downloads durch diese Anwendung.</small></div>`:''}</section>
      <section class="card form-card" id="gmail-setup"><h2>Dein Gmail-Postfach</h2><p>Nachrichten abrufen und Entwürfe in deinem gewohnten Postfach bereitstellen.</p><div class="connection"><div class="connection-logo">${gmailIcon}</div><div><strong>${esc(state.gmail.email||'Gmail')}</strong><p>${state.gmail.connected?'Verbunden · Nachrichten und Entwürfe werden mit Google synchronisiert.':'Noch kein Konto verbunden.'}</p></div></div>${state.gmail.connected?`<div class="form-actions">${button('disconnect','Konto trennen','close',false)}${button('sync','Jetzt synchronisieren','refresh',true,state.gmail.syncing?'disabled':'')}</div><p class="tiny muted" style="margin-top:13px">Beim Trennen werden importierte Gmail-Nachrichten lokal entfernt. Die Freigabe kannst du zusätzlich in deinem Google-Konto widerrufen.</p>`:`<div class="steps"><span class="step-number">1</span><div><h3>Google-Konfiguration importieren</h3><p>Für diesen lokalen Prototyp benötigst du eine OAuth-Datei vom Typ Desktop-App. Die Einrichtung ist unten beschrieben.</p></div></div><input class="file-input" id="google-file" type="file" accept=".json">${button('import-google',state.gmail.configured?'Konfiguration ersetzen':'JSON-Datei auswählen','file')} ${state.gmail.configured?'<span class="health-badge">'+icon('check')+'Konfiguriert</span>':''}<div class="steps"><span class="step-number">2</span><div><h3>Bei Google anmelden</h3><p>Die Anmeldung öffnet sich im Browser. Danach startet der einmalige vollständige Import samt lokaler Unternehmens- und Stilanalyse automatisch.</p></div></div>${button('connect','Mit Google verbinden',null,true,state.gmail.configured?'':'disabled')}`}</section><section class="card form-card"><h2>Letzte Aktivitäten</h2><p>Verarbeitungsschritte ohne E-Mail-Inhalte.</p>${state.events.length?state.events.map(e=>`<div class="event"><span>${esc(e.message)}</span><time>${displayTime(e.created)}</time></div>`).join(''):'<p class="muted">Noch keine Aktivitäten.</p>'}</section></div>
      <aside><section class="card info-card"><div class="info-icon">${icon('cpu')}</div><h3>Auf deinem Rechner zu Hause.</h3><p>KI-Verarbeitung, Unternehmenswissen und Suchindex bleiben lokal. Das Modell läuft über Ollama auf diesem Rechner.</p><br><p>Gmail benötigt Internet für den Abruf und die Synchronisierung der Entwürfe. Die Verarbeitung arbeitet, solange diese Anwendung läuft und der Rechner wach ist.</p><br><a class="btn small" href="#knowledge">Unternehmensprofil ergänzen ${icon('arrow')}</a></section><section class="card form-card" style="margin-top:20px"><h3>Gmail einmalig vorbereiten</h3><div class="steps"><span class="step-number">1</span><div><p>In der Google Cloud Console ein Projekt anlegen und die Gmail API aktivieren.</p></div></div><div class="steps"><span class="step-number">2</span><div><p>Den OAuth-Zustimmungsbildschirm einrichten und dein Konto als Testnutzer hinzufügen.</p></div></div><div class="steps"><span class="step-number">3</span><div><p>Einen OAuth-Client vom Typ <strong>Desktop-App</strong> erstellen und die JSON-Datei herunterladen.</p></div></div><a class="btn small" href="https://developers.google.com/workspace/gmail/api/quickstart/python" target="_blank" rel="noopener noreferrer">Google-Anleitung ${icon('external')}</a></section></aside></div>`;}

function openDocument(doc){modal.innerHTML=`<form data-form="document"><div class="modal-head"><h2 id="modal-title">${doc?.id?'Wissen bearbeiten':'Wissen ergänzen'}</h2><button type="button" class="icon-btn" data-action="close-modal" aria-label="Schließen">${icon('close')}</button></div><input type="hidden" name="id" value="${esc(doc?.id||'')}">${input('title','Titel',doc?.title||'')}${textarea('content','Wissensinhalt',doc?.content||'','Zum Beispiel: Leistungen, Konditionen oder Antworten auf häufige Fragen.',11)}<div class="modal-actions"><button type="button" class="btn" data-action="close-modal">Abbrechen</button><button class="btn primary" type="submit">${icon('check')}Lokal speichern</button></div></form>`;modal.showModal();}

document.addEventListener('click',async event=>{
  if(event.target.closest('a[href="#main"]')){event.preventDefault();document.getElementById('main')?.focus();return;}
  const tool = event.target.closest('[data-format]');
  if (tool) {
    const editor = document.getElementById('draft-editor');
    if (editor?.isContentEditable && applyDraftFormat(editor, tool.dataset.format)) rememberDraft(editor);
    return;
  }
  const buttonNode=event.target.closest('[data-action]');if(!buttonNode||buttonNode.disabled)return;
  const action=buttonNode.dataset.action,id=buttonNode.dataset.id;
  if(action==='menu'){document.querySelector('.sidebar').classList.toggle('open');return;}
  if(action==='reload'){location.reload();return;}
  if(action==='mode'){mode=buttonNode.dataset.mode;localStorage.setItem('amr-view',mode);selected=null;search='';statusFilter='';render();return;}
  if(action==='select'){selected=id;previewTab='draft';render();return;}
  if(action==='compose'){
    const row=state.threads.find(thread=>thread.id===id);
    pendingDrafts.set(id,{text:'',html:'',revision:row.revision});
    previewTab='draft';
    render();
    document.getElementById('draft-editor')?.focus();
    return;
  }
  if(action==='preview-tab'){previewTab=buttonNode.dataset.tab;render();return;}
  if(action==='setup-gmail'){location.hash='settings';setTimeout(()=>document.getElementById('gmail-setup')?.scrollIntoView({behavior:'smooth',block:'center'}),70);return;}
  if(action==='add-document'){openDocument();return;}
  if(action==='edit-document'){openDocument(state.documents.find(d=>d.id===id));return;}
  if(action==='close-modal'){modal.close();return;}
  if(action==='import-document'){document.getElementById('knowledge-file').click();return;}
  if(action==='import-google'){document.getElementById('google-file').click();return;}
  buttonNode.disabled=true;
  try{
    if(action==='check-model'){await api('/api/health');toast('Lokaler Modelldienst geprüft.');}
    else if(action==='sync'){await api('/api/gmail/sync',{});toast(state.onboarding.stage==='complete'?'Gmail-Synchronisierung gestartet.':'Einmalige Einrichtung gestartet oder fortgesetzt.');}
    else if(action==='pause'){await api('/api/settings',{paused:!state.settings.paused});toast(state.settings.paused?'Verarbeitung fortgesetzt.':'Verarbeitung pausiert.');}
    else if(action==='automatic'){await api('/api/settings',{automatic:!state.settings.automatic});toast('Automatische Erstellung '+(state.settings.automatic?'deaktiviert.':'aktiviert.'));}
    else if(action==='history'){await api('/api/settings',{use_history:!state.settings.use_history});toast('Einstellung gespeichert.');}
    else if(action==='generate'){await api('/api/thread/generate',{id});toast('Dein Antwortentwurf wird lokal erstellt.');}
    else if(action==='save-draft'){await savePendingDraft(id);toast('Deine Änderungen sind lokal gespeichert.');}
    else if(action==='copy'){const row=state.threads.find(t=>t.id===id);await navigator.clipboard.writeText(draftFor(row).text);toast('Entwurf kopiert.');}
    else if(action==='publish'){await savePendingDraft(id);await api('/api/thread/publish',{id});toast('Entwurf in Gmail gespeichert.');}
    else if(action==='prepare-send'){
      const revision=await savePendingDraft(id,Number(buttonNode.dataset.revision));
      const confirmation=await api('/api/thread/send/prepare',{id,revision});
      if(selected===id)openSendDialog(id,confirmation);
      return;
    }
    else if(action==='connect'){const result=await api('/api/gmail/connect',{});location.assign(result.url);return;}
    else if(action==='disconnect'){if(!confirm('Gmail trennen und die lokal importierten Gmail-Nachrichten entfernen? Das erkannte Profil und der Abschluss der Ersteinrichtung bleiben gespeichert; die Erstanalyse wird beim erneuten Verbinden nicht wiederholt. Entwürfe in Gmail bleiben erhalten.'))return;await api('/api/gmail/disconnect',{});mode='gmail';toast('Gmail getrennt und lokale Nachrichten entfernt.');}
    else if(action==='delete-document'){if(!confirm('Diesen Wissenseintrag lokal löschen?'))return;await api('/api/knowledge/delete',{id});toast('Wissenseintrag gelöscht.');}
    await refresh(true);
  }catch(error){toast(error.message,true);}finally{if(buttonNode.isConnected)buttonNode.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!form.dataset.form)return;event.preventDefault();
  const data=Object.fromEntries(new FormData(form));
  if(form.dataset.form==='send'){
    if(form.dataset.sending)return;
    form.dataset.sending='true';
    for(const control of form.querySelectorAll('button'))control.disabled=true;
    try{
      await api('/api/thread/send',data);
      toast('Antwort gesendet.');
    }catch(error){
      toast(error.message,true);
    }finally{
      modal.close();
      await refresh(true);
    }
    return;
  }
  const submit=form.querySelector('[type="submit"]');if(submit)submit.disabled=true;
  try{
    if(form.dataset.form==='settings'){
      for(const key of ['context_size','sync_seconds'])if(key in data)data[key]=Number(data[key]);
      await api('/api/settings',data);formDirty=false;toast('Deine Einstellungen sind gespeichert.');
    }else{
      if(!data.id)delete data.id;await api('/api/knowledge',data);modal.close();toast('Dein Wissen ist lokal gespeichert.');
    }
    await refresh(true);
  }catch(error){toast(error.message,true);}finally{if(submit?.isConnected)submit.disabled=false;}
});
document.addEventListener('input',event=>{
  if(event.target.id==='draft-editor'){rememberDraft(event.target);return;}
  if(event.target.id==='mail-search'){
    search=event.target.value;const pos=event.target.selectionStart;render();const input=document.getElementById('mail-search');input.focus();input.setSelectionRange(pos,pos);return;
  }
  if(event.target.closest('[data-form="settings"]'))formDirty=true;
});
document.addEventListener('change',async event=>{
  if(event.target.id==='status-filter'){statusFilter=event.target.value;render();return;}
  if(event.target.closest('[data-form="settings"]'))formDirty=true;
  if(!['knowledge-file','google-file'].includes(event.target.id))return;
  const file=event.target.files[0];if(!file)return;
  if(file.size>1_000_000){toast('Bitte wähle eine Datei unter 1 MB.',true);return;}
  try{
    const text=await file.text();
    if(event.target.id==='google-file'){await api('/api/gmail/configure',JSON.parse(text));toast('Google-Konfiguration wurde lokal gespeichert.');await refresh(true);}
    else{if(!/\.(txt|md|csv)$/i.test(file.name))throw new Error('Bitte wähle eine TXT-, Markdown- oder CSV-Datei.');openDocument({title:file.name.replace(/\.[^.]+$/,''),content:text});}
  }catch(error){toast(error instanceof SyntaxError?'Die ausgewählte Datei enthält kein gültiges JSON.':error.message,true);}
  event.target.value='';
});
window.addEventListener('hashchange',()=>{
  if(formDirty&&!confirm('Du hast noch nicht gespeicherte Änderungen. Möchtest du sie verwerfen?')){history.replaceState(null,'','#'+route);return;}
  formDirty=false;route=location.hash.slice(1)||'overview';if(state)render();window.scrollTo(0,0);
});
modal.addEventListener('cancel',event=>{
  if(modal.querySelector('[data-sending="true"]'))event.preventDefault();
});
window.addEventListener('beforeunload',event=>{if(formDirty||pendingDrafts.size){event.preventDefault();event.returnValue='';}});
refresh(true);
setInterval(()=>refresh(),4000);
