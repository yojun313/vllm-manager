/* 시스템: 버전·업데이트, 호스트, 저장 공간, 이미지, 설치 점검, API 키, 서버 설정(웹에서 편집). */
import { t } from '../i18n.js';
import { $, $$, api, confirmDialog, copy, esc, fmtAgo, fmtBytes, fmtDuration, hydrateIcons, toast } from '../ui.js';
import { refresh, store } from '../store.js';
import { copyKey } from '../actions.js';

let root, info = null, settings = null, timer = null;

const head = (ic, title, extra = '') => `<div class="card-h"><span class="ic"><span data-icon="${ic}" data-size="16"></span></span><h3>${esc(title)}</h3>${extra}</div>`;

function checksHtml() {
  const c = info.checks;
  const row = (ok, title, help, warnOnly) => `<li><span class="${ok ? 'ok-text' : warnOnly ? 'warn-text' : 'bad-text'}"><span data-icon="${ok ? 'check' : 'alert'}" data-size="17"></span></span><span>${esc(title)}${ok || !help ? '' : `<small>${help}</small>`}</span></li>`;
  return `<ul class="check-list">
    ${row(c.docker, t('chk.docker'), t('chk.dockerHelp'))}
    ${row(c.images, t('chk.images'), t('chk.imagesHelp'), true)}
    ${row(c.hf_cli, t('chk.hf'), t('chk.hfHelp'))}
    ${row(c.hf_token, t('chk.token'), t('chk.tokenHelp'), true)}
    ${row(c.api_key, t('chk.key'), t('chk.keyHelp'), true)}
    ${row(info.server.cookie_secure || location.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(location.hostname), t('chk.https'), t('chk.httpsHelp'), true)}
  </ul>`;
}

const GROUPS = [
  ['storage', ['MODELS_DIR', 'HF_CACHE_DIR', 'VLLM_CACHE_DIR']],
  ['gpu', ['GPU_IDS', 'GPU_COUNT']],
  ['network', ['PORT_BASE', 'BIND_ADDR']],
  ['memory', ['KV_CONCURRENCY', 'AUTO_KV_GIB', 'SAFETY_MIB']],
  ['images', ['VLLM_IMAGE', 'VLLM_AUDIO_IMAGE', 'VLLM_OMNI_IMAGE']],
  ['console', ['HOST', 'PORT', 'COOKIE_SECURE', 'SESSION_DAYS']],
];
function field(key) {
  const spec = settings.schema[key], v = settings.values[key] ?? '';
  const control = spec.type === 'bool'
    ? `<input type="checkbox" class="switch" data-key="${key}" ${v === 'true' ? 'checked' : ''}>`
    : `<input class="input mono" style="width:min(340px,100%)" data-key="${key}" value="${esc(v)}" ${spec.type === 'int' ? 'inputmode="numeric"' : ''} spellcheck="false" autocapitalize="off" autocomplete="off">`;
  return `<label class="setting-row"><span><b>${esc(t('set.' + key))}</b><small>${esc(t('set.' + key + '.help'))}${spec.restart ? ` · ${esc(t('set.needsRestart'))}` : ''}</small></span>${control}</label>`;
}
function urlRows() {
  const ports = new Set(Object.keys(settings.public_urls));
  (store.S?.containers || []).forEach((c) => ports.add(String(c.port)));
  const base = store.S?.port_base || 8000;
  store.G.forEach((g) => ports.add(String(base + Number(g.idx))));
  return [...ports].sort((a, b) => a - b).map((p) => `<label class="setting-row"><span><b class="mono">:${esc(p)}</b></span>
    <input class="input mono" style="width:min(340px,100%)" data-url="${esc(p)}" value="${esc(settings.public_urls[p] || '')}" placeholder="llm.example.com/v1" spellcheck="false" autocapitalize="off"></label>`).join('');
}
function settingsHtml() {
  return GROUPS.map(([g, keys]) => `<div class="card"><div class="card-h"><h3>${esc(t('set.group.' + g))}</h3></div>${keys.map(field).join('')}</div>`).join('')
    + `<div class="card"><div class="card-h"><h3>${esc(t('set.group.urls'))}</h3></div><p class="hint" style="margin:-6px 0 10px">${esc(t('set.urlsHelp'))}</p>${urlRows()}</div>`;
}

function render() {
  if (!info || !settings) return;
  const a = info.app, h = info.host, u = info.update;
  const memUsed = h.mem_total - h.mem_available;
  const updateLine = u.behind == null ? (u.error ? `<span class="warn-text">${esc(t('sys.updateFail'))}</span>` : esc(t('sys.updateChecking')))
    : u.behind > 0 ? `<span class="warn-text">${esc(t('sys.updateBehind', { n: u.behind }))}</span>` : `<span class="ok-text">${esc(t('sys.updateLatest'))}</span>`;
  root.innerHTML = `
    <div class="grid two">
      <div class="card">${head('box', 'vLLM Manager')}
        <dl class="kv"><dt>${esc(t('sys.version'))}</dt><dd class="mono">v${esc(a.version)}${a.commit ? ` · ${esc(a.commit)}` : ''}</dd>
          <dt>${esc(t('sys.update'))}</dt><dd>${updateLine} ${u.checked ? `<span class="faint small">· ${esc(fmtAgo(u.checked))}</span>` : ''}</dd>
          <dt>${esc(t('sys.path'))}</dt><dd class="mono">${esc(a.root)}</dd></dl>
        ${u.behind > 0 ? `<div class="code-row" style="margin-top:14px"><code>cd ${esc(a.root)} && ./vllm update</code><button class="btn sm ghost icon" data-copy="cd ${esc(a.root)} && ./vllm update"><span data-icon="copy" data-size="14"></span></button></div>` : ''}
        <div class="actions" style="margin-top:14px"><button class="btn sm" id="updCheck"><span data-icon="refresh" data-size="14"></span>${esc(t('sys.checkNow'))}</button>
          <button class="btn sm" id="restartBtn">${esc(t('sys.restart'))}</button></div></div>
      <div class="card">${head('system', t('sys.host'))}
        <dl class="kv"><dt>${esc(t('sys.hostname'))}</dt><dd class="mono">${esc(h.name)}</dd><dt>OS</dt><dd>${esc(h.os)}</dd>
          <dt>CPU</dt><dd>${esc(t('sys.cpu', { n: h.cpus, load: h.load.join(' / ') }))}</dd>
          <dt>${esc(t('sys.memory'))}</dt><dd>${fmtBytes(memUsed)} / ${fmtBytes(h.mem_total)}</dd>
          <dt>${esc(t('sys.uptime'))}</dt><dd>${esc(fmtDuration(h.uptime))}</dd>
          <dt>${esc(t('sys.driver'))}</dt><dd class="mono">${esc(info.nvidia.driver || '-')} · CUDA ${esc(info.nvidia.cuda || '-')}</dd>
          <dt>Docker</dt><dd class="mono">${info.docker.ok ? esc(info.docker.version || '-') : `<span class="bad-text">${esc(t('sys.dockerNo'))}</span>`}</dd></dl></div>
      <div class="card">${head('disk', t('sys.storage'))}
        ${info.disks.map((d) => { const pct = d.used / d.total * 100; return `<div class="disk"><div class="disk-top"><span>${esc(t('sys.diskFree', { v: fmtBytes(d.free) }))}</span><span class="dim mono">${fmtBytes(d.used)} / ${fmtBytes(d.total)}</span></div>
          <div class="meter"><i class="${pct > 92 ? 'bad' : pct > 80 ? 'warn' : ''}" style="width:${pct}%"></i></div>
          <div class="paths">${d.paths.map((p) => `<span>${esc(p.path)}</span>`).join('')}</div></div>`; }).join('') || `<p class="faint">${esc(t('sys.noDisk'))}</p>`}</div>
      <div class="card">${head('check', t('sys.checks'))}${checksHtml()}</div>
      <div class="card">${head('key', t('key.title'), `<span class="pill ${info.checks.api_key ? 'ok' : 'warn'}">${esc(info.checks.api_key ? t('key.on') : t('key.off'))}</span>`)}
        <p class="dim" style="font-size:13px">${esc(info.checks.api_key ? t('key.onHelp') : t('key.offHelp'))}</p>
        <div class="actions" style="margin-top:14px">${info.checks.api_key ? `<button class="btn sm" id="keyCopy"><span data-icon="copy" data-size="14"></span>${esc(t('key.copy'))}</button>` : ''}
          <button class="btn sm" id="keyNew">${esc(info.checks.api_key ? t('key.rotate') : t('key.create'))}</button>
          ${info.checks.api_key ? `<button class="btn sm danger" id="keyOff">${esc(t('key.disable'))}</button>` : ''}</div></div>
      <div class="card">${head('box', t('sys.images'))}
        ${info.images.length ? `<div class="table-wrap"><table class="table"><tbody>${info.images.map((i) => `<tr><td class="dim nowrap" style="padding-left:0">${esc(t('sys.image.' + i.role))}</td><td class="mono small" style="overflow-wrap:anywhere">${esc(i.image)}</td><td class="num nowrap" style="padding-right:0">${i.present ? fmtBytes(i.bytes) : `<span class="warn-text">${esc(t('sys.imageMissing'))}</span>`}</td></tr>`).join('')}</tbody></table></div>` : `<p class="faint">${esc(t('sys.noImages'))}</p>`}</div>
    </div>
    <section class="section"><div class="sh"><h2>${esc(t('set.title'))}</h2><span class="count">${esc(t('set.sub'))}</span></div>
      <div class="grid two" id="setForm">${settingsHtml()}</div>
      <div class="actions" style="margin-top:14px;justify-content:flex-end"><span class="faint small" id="setStatus"></span><button class="btn primary" id="setSave">${esc(t('set.save'))}</button></div></section>`;
  hydrateIcons(root);
}

async function load() {
  try { [info, settings] = await Promise.all([api('/api/system'), api('/api/settings')]); render(); }
  catch (e) { toast(e.message, 'bad'); }
}

async function restart(ask = true) {
  if (ask && !await confirmDialog({ title: t('sys.restart'), html: `<p>${esc(t('sys.restartBody'))}</p>`, ok: t('sys.restart'), danger: false })) return;
  try { await api('/api/system/restart', { method: 'POST' }); toast(t('sys.restarting')); }
  catch (e) { toast(e.message, 'bad'); return; }
  // 새 포트로 바뀌었으면 그 주소로, 아니면 서버가 돌아올 때까지 기다렸다가 새로 고친다
  const port = settings.values.PORT;
  const target = port && port !== location.port && location.port ? `${location.protocol}//${location.hostname}:${port}/` : null;
  let tries = 0;
  const wait = setInterval(async () => {
    tries++;
    try { await fetch((target || '/') + 'login', { mode: 'no-cors', cache: 'no-store' }); clearInterval(wait); location.href = target || location.href; }
    catch (e) { if (tries > 60) clearInterval(wait); }
  }, 1500);
}

async function save() {
  const values = {};
  $$('[data-key]', root).forEach((el) => { values[el.dataset.key] = el.type === 'checkbox' ? String(el.checked) : el.value.trim(); });
  const public_urls = {};
  $$('[data-url]', root).forEach((el) => { public_urls[el.dataset.url] = el.value.trim(); });
  const btn = $('#setSave', root);
  btn.disabled = true;
  try {
    const r = await api('/api/settings', { method: 'PUT', body: { values, public_urls } });
    settings = await api('/api/settings');
    if (!r.changed.length) toast(t('set.unchanged'));
    else if (r.restart) {
      if (await confirmDialog({ title: t('set.restartTitle'), html: `<p>${esc(t('set.restartBody'))}</p>`, ok: t('sys.restart'), danger: false })) restart(false);
      else toast(t('set.savedRestart'), 'ok');
    } else toast(t('set.saved'), 'ok');
    refresh(); load();
  } catch (e) { toast(e.message, 'bad'); }
  finally { btn.disabled = false; }
}

async function keyAction(action) {
  const title = action === 'off' ? t('key.disable') : info.checks.api_key ? t('key.rotate') : t('key.create');
  const body = action === 'off' ? t('key.offConfirm') : info.checks.api_key ? t('key.rotateConfirm') : t('key.createConfirm');
  if (!await confirmDialog({ title, html: `<p>${esc(body)}</p>`, ok: title, danger: action === 'off' || info.checks.api_key })) return;
  try { await api('/api/key', { method: 'POST', body: { action } }); toast(t('key.changed'), 'ok'); refresh(); load(); }
  catch (e) { toast(e.message, 'bad'); }
}

export function mount(el) {
  root = el; info = null; settings = null;
  el.innerHTML = '<div class="grid two"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>';
  el.onclick = async (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.copy) copy(b.dataset.copy);
    else if (b.id === 'updCheck') { b.disabled = true; try { await api('/api/system/update-check', { method: 'POST' }); } catch (err) { toast(err.message, 'bad'); } load(); }
    else if (b.id === 'restartBtn') restart();
    else if (b.id === 'keyCopy') copyKey();
    else if (b.id === 'keyNew') keyAction('new');
    else if (b.id === 'keyOff') keyAction('off');
    else if (b.id === 'setSave') save();
  };
  load();
  timer = setInterval(() => { if (!document.activeElement?.closest?.('#setForm')) api('/api/system').then((s) => { if (JSON.stringify(s.update) !== JSON.stringify(info?.update)) { info = s; render(); } }).catch(() => {}); }, 15000);
}
export function unmount() { clearInterval(timer); }
