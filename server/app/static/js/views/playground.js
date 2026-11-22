/* 플레이그라운드: 실행 중인 모델에 대화를 보내 응답과 속도를 확인한다. 요청은 관리 서버가 대신 보낸다(API 키 노출 없음). */
import { t } from '../i18n.js';
import { $, esc, hydrateIcons } from '../ui.js';
import { on, store } from '../store.js';
import { snippetBlock, wireSnippet } from '../actions.js';

let root, offs = [], messages = [], busy = null, selected = '', lastOptions = '';
const params = { system: '', temperature: 0.7, max_tokens: 1024 };

const candidates = () => (store.S?.containers || []).filter((c) => c.health && !(store.S.models.find((m) => m.alias === c.model)?.embed));

function renderModels() {
  const list = candidates();
  if (!list.some((c) => c.name === selected)) selected = list[0]?.name || '';
  const html = list.map((c) => `<option value="${esc(c.name)}" ${c.name === selected ? 'selected' : ''}>${esc(c.model)} · GPU ${esc(c.gpus)}</option>`).join('');
  if (html === lastOptions) return;
  lastOptions = html;
  $('#pgModel', root).innerHTML = html || `<option value="">${esc(t('pg.noModel'))}</option>`;
  $('#pgModel', root).disabled = !list.length;
  $('#pgSend', root).disabled = !list.length && !busy;
  renderSnippet();
  if (!messages.length) renderLog();
}
function renderSnippet() {
  const c = candidates().find((x) => x.name === selected);
  const el = $('#pgSnippet', root);
  el.innerHTML = c ? snippetBlock(c) : `<p class="faint small">${esc(t('pg.noModel'))}</p>`;
  hydrateIcons(el);
}

function bubble(m) {
  const who = m.role === 'user' ? t('pg.you') : m.role === 'error' ? t('pg.error') : (m.model || t('pg.assistant'));
  const stats = m.stats ? `<div class="stats">${esc(m.stats)}</div>` : '';
  const reasoning = m.reasoning ? `<details ${m.streaming && !m.content ? 'open' : ''}><summary>${esc(t('pg.reasoning'))}</summary><pre>${esc(m.reasoning)}</pre></details>` : '';
  return `<div class="msg ${m.role}"><div class="who">${esc(who)}</div>${reasoning}
    ${m.content || !m.reasoning ? `<div class="body ${m.streaming ? 'cursor' : ''}">${esc(m.content)}</div>` : ''}${stats}</div>`;
}
function renderLog() {
  const log = $('#pgLog', root);
  const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  log.innerHTML = messages.length ? messages.map(bubble).join('')
    : `<div class="pg-empty">${esc(candidates().length ? t('pg.empty') : t('pg.emptyNoModel'))}${candidates().length ? '' : `<br><a class="btn" style="margin-top:12px" href="#/models">${esc(t('run.goModels'))}</a>`}</div>`;
  if (stick) log.scrollTop = log.scrollHeight;
}

async function send() {
  if (busy) { busy.abort(); return; }
  const input = $('#pgInput', root);
  const text = input.value.trim();
  const c = candidates().find((x) => x.name === selected);
  if (!text || !c) return;
  input.value = ''; input.style.height = '';
  messages.push({ role: 'user', content: text });
  const reply = { role: 'assistant', content: '', reasoning: '', model: c.model, streaming: true };
  messages.push(reply);
  renderLog();
  const history = messages.filter((m) => m !== reply && (m.role === 'user' || m.role === 'assistant')).map((m) => ({ role: m.role, content: m.content }));
  if (params.system.trim()) history.unshift({ role: 'system', content: params.system.trim() });
  busy = new AbortController();
  $('#pgSend', root).innerHTML = `<span data-icon="stop" data-size="14"></span>`; hydrateIcons($('#pgSend', root));
  const started = performance.now();
  let first = null, usage = null, chunks = 0;
  try {
    const res = await fetch('/api/chat', { method: 'POST', credentials: 'same-origin', signal: busy.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ container: c.name, messages: history, temperature: Number(params.temperature), max_tokens: Number(params.max_tokens) || null }) });
    if (res.status === 401) { location.href = '/login'; return; }
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = '', event = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop();
      for (const raw of lines) {
        const line = raw.trimEnd();
        if (!line) { event = ''; continue; }
        if (line.startsWith('event:')) { event = line.slice(6).trim(); continue; }
        if (!line.startsWith('data:')) continue;
        const data = line.slice(5).trim();
        if (data === '[DONE]') continue;
        let obj; try { obj = JSON.parse(data); } catch (e) { continue; }
        if (event === 'error') throw new Error(obj.message || 'error');
        if (obj.usage) usage = obj.usage;
        const d = obj.choices?.[0]?.delta;
        if (!d) continue;
        const r = d.reasoning_content ?? d.reasoning;
        if (r) reply.reasoning += r;
        if (d.content) reply.content += d.content;
        if ((r || d.content) && first == null) first = performance.now();
        if (r || d.content) chunks++;
      }
      renderLog();
    }
  } catch (e) {
    if (e.name !== 'AbortError') {
      if (!reply.content && !reply.reasoning) messages.pop();
      messages.push({ role: 'error', content: e.message });
    }
  } finally {
    reply.streaming = false;
    const total = (performance.now() - started) / 1000;
    if (first != null) {
      const gen = usage?.completion_tokens ?? chunks, span = Math.max((performance.now() - first) / 1000, 0.001);
      reply.stats = [t('pg.ttft', { v: Math.round(first - started) }), t('pg.speed', { v: (gen / span).toFixed(1) }),
        usage ? t('pg.tokens', { p: usage.prompt_tokens, c: usage.completion_tokens }) : '', t('pg.total', { v: total.toFixed(1) })].filter(Boolean).join(' · ');
    }
    busy = null;
    if (root.isConnected) {
      $('#pgSend', root).innerHTML = `<span data-icon="send" data-size="15"></span>`; hydrateIcons($('#pgSend', root));
      renderLog();
    }
  }
}

export function mount(el, query) {
  root = el; lastOptions = '';
  if (query.get('m')) selected = query.get('m');
  el.innerHTML = `<div class="pg">
    <div class="card pg-chat"><div class="pg-log" id="pgLog"></div>
      <div class="pg-input"><textarea class="input" id="pgInput" rows="1" placeholder="${esc(t('pg.placeholder'))}"></textarea>
        <button class="btn primary icon" id="pgSend" aria-label="${esc(t('pg.send'))}"><span data-icon="send" data-size="15"></span></button></div></div>
    <div class="pg-side">
      <div class="card"><label class="field"><span>${esc(t('pg.model'))}</span><select class="input" id="pgModel"></select></label>
        <label class="field"><span>${esc(t('pg.system'))}</span><textarea class="input" id="pgSystem" rows="3" placeholder="${esc(t('pg.systemHint'))}">${esc(params.system)}</textarea></label>
        <label class="field"><span>${esc(t('pg.temperature'))}</span><div class="range-row"><input type="range" id="pgTemp" min="0" max="2" step="0.1" value="${params.temperature}"><span class="mono" id="pgTempV">${params.temperature}</span></div></label>
        <label class="field"><span>${esc(t('pg.maxTokens'))}</span><input class="input mono" id="pgMax" type="number" min="1" max="131072" value="${params.max_tokens}"></label>
        <button class="btn block" id="pgClear" style="margin-top:14px">${esc(t('pg.clear'))}</button></div>
      <div class="card"><div class="card-h"><span class="ic"><span data-icon="code" data-size="16"></span></span><h3>${esc(t('pg.api'))}</h3></div><div id="pgSnippet"></div></div>
    </div></div>`;
  hydrateIcons(el);
  const input = $('#pgInput', el);
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 180) + 'px'; });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
  $('#pgSend', el).onclick = send;
  $('#pgModel', el).onchange = (e) => { selected = e.target.value; renderSnippet(); };
  $('#pgSystem', el).oninput = (e) => { params.system = e.target.value; };
  $('#pgTemp', el).oninput = (e) => { params.temperature = e.target.value; $('#pgTempV', el).textContent = e.target.value; };
  $('#pgMax', el).oninput = (e) => { params.max_tokens = e.target.value; };
  $('#pgClear', el).onclick = () => { if (busy) busy.abort(); messages = []; renderLog(); };
  wireSnippet($('#pgSnippet', el), { get served() { return candidates().find((x) => x.name === selected)?.served; }, get port() { return candidates().find((x) => x.name === selected)?.port; }, get public_url() { return candidates().find((x) => x.name === selected)?.public_url; } });
  offs = [on('state', renderModels)];
  renderModels(); renderLog();
}
export function unmount() { offs.forEach((f) => f()); offs = []; if (busy) busy.abort(); }
