/* 환경설정: 이 브라우저의 화면 설정과 관리자 계정. */
import { setLang, t } from '../i18n.js';
import { $, api, confirmDialog, defaultPrefs, esc, fmtAgo, getPrefs, hydrateIcons, modal, setPrefs, toast } from '../ui.js';
import * as passkey from '../passkey.js';
import { store } from '../store.js';

let root;
const row = (id, title, help, control) => `<label class="setting-row" for="${id}"><span><b>${esc(title)}</b><small>${esc(help)}</small></span>${control}</label>`;
const select = (id, options, value) => `<select class="input" id="${id}">${options.map(([v, label]) => `<option value="${v}" ${String(v) === String(value) ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select>`;
const toggle = (id, on) => `<input type="checkbox" class="switch" id="${id}" ${on ? 'checked' : ''}>`;
const sec = (n) => t('pref.seconds', { n });

function render() {
  const p = getPrefs();
  root.innerHTML = `<div class="grid two">
    <div class="card"><div class="card-h"><span class="ic"><span data-icon="sun" data-size="16"></span></span><h3>${esc(t('pref.display'))}</h3></div>
      ${row('pTheme', t('pref.theme'), t('pref.themeHelp'), select('pTheme', [['system', t('pref.system')], ['light', t('pref.light')], ['dark', t('pref.dark')]], p.theme))}
      ${row('pLang', t('pref.lang'), t('pref.langHelp'), select('pLang', [['ko', '한국어'], ['en', 'English']], document.documentElement.lang))}
      ${row('pView', t('pref.view'), t('pref.viewHelp'), select('pView', [['cards', t('lib.cards')], ['list', t('lib.list')]], p.viewMode))}
      ${row('pCompact', t('pref.compact'), t('pref.compactHelp'), toggle('pCompact', p.compact))}
      ${row('pMotion', t('pref.motion'), t('pref.motionHelp'), toggle('pMotion', p.reduceMotion))}</div>
    <div class="card"><div class="card-h"><span class="ic"><span data-icon="gpu" data-size="16"></span></span><h3>${esc(t('pref.live'))}</h3></div>
      ${row('pGpuOn', t('pref.gpuOn'), t('pref.gpuOnHelp'), toggle('pGpuOn', p.gpuEnabled))}
      ${row('pGpuInt', t('pref.gpuInt'), t('pref.gpuIntHelp'), select('pGpuInt', [1, 2, 5, 10, 30].map((n) => [n, sec(n)]), p.gpuInterval))}
      ${row('pStateInt', t('pref.stateInt'), t('pref.stateIntHelp'), select('pStateInt', [2, 5, 10, 30].map((n) => [n, sec(n)]), p.stateInterval))}
      ${row('pSensors', t('pref.sensors'), t('pref.sensorsHelp'), toggle('pSensors', p.sensors))}</div>
    <div class="card"><div class="card-h"><span class="ic"><span data-icon="user" data-size="16"></span></span><h3>${esc(t('acct.title'))}</h3><span class="chip">${esc(store.S?.user || '')}</span></div>
      <form id="pwForm" autocomplete="off">
        <label class="field"><span>${esc(t('acct.current'))}</span><input class="input" type="password" id="pwCur" autocomplete="current-password" required></label>
        <label class="field"><span>${esc(t('acct.new'))}</span><input class="input" type="password" id="pwNew" autocomplete="new-password" required></label>
        <label class="field"><span>${esc(t('acct.again'))}</span><input class="input" type="password" id="pwNew2" autocomplete="new-password" required></label>
        <div class="actions" style="margin-top:14px"><button class="btn primary" type="submit">${esc(t('acct.change'))}</button><span class="grow"></span>
          <button class="btn" type="button" id="signOut"><span data-icon="logout" data-size="15"></span>${esc(t('acct.signOut'))}</button></div>
        <p class="hint">${esc(t('acct.hint'))}</p></form></div>
    <div class="card"><div class="card-h"><span class="ic"><span data-icon="key" data-size="16"></span></span><h3>${esc(t('pk.title'))}</h3></div>
      <p class="dim" style="font-size:13px;margin-bottom:12px">${esc(t('pk.sub'))}</p>
      <div id="pkList"></div>
      <button class="btn" id="pkAdd" ${passkey.supported() ? '' : 'disabled'}><span data-icon="plus" data-size="15"></span>${esc(t('pk.add'))}</button>
      ${passkey.supported() ? '' : `<p class="hint">${esc(t('pk.unsupported'))}</p>`}</div>
    <div class="card"><div class="card-h"><span class="ic"><span data-icon="info" data-size="16"></span></span><h3>${esc(t('pref.about'))}</h3></div>
      <p class="dim" style="font-size:13px">${esc(t('pref.aboutBody'))}</p>
      <div class="actions" style="margin-top:14px"><button class="btn" id="pReset">${esc(t('pref.reset'))}</button><a class="btn" href="#/system">${esc(t('pref.server'))} →</a></div>
      <p class="hint" id="pStatus">${esc(t('pref.local'))}</p></div>
  </div>`;
  hydrateIcons(root);
  $('#pGpuInt', root).disabled = !p.gpuEnabled;
  loadPasskeys();
}

async function loadPasskeys() {
  let list = [];
  try { list = (await api('/api/auth/passkeys')).passkeys; } catch (e) { return; }
  const el = $('#pkList', root);
  if (!el) return;
  el.innerHTML = list.length ? `<ul class="pk-list">${list.map((k) => `<li><div class="pk-info"><b>${esc(k.name)}</b>
      <small>${esc(t('pk.created', { v: fmtAgo(k.created) }))} · ${esc(k.last_used ? t('pk.used', { v: fmtAgo(k.last_used) }) : t('pk.never'))}${k.synced ? ` · ${esc(t('pk.synced'))}` : ''}${k.here ? '' : ` · ${esc(t('pk.elsewhere'))}`}</small></div>
      <button class="btn sm ghost" data-pk-rename="${esc(k.id)}" data-name="${esc(k.name)}">${esc(t('pk.rename'))}</button>
      <button class="btn sm danger" data-pk-remove="${esc(k.id)}" data-name="${esc(k.name)}">${esc(t('pk.remove'))}</button></li>`).join('')}</ul>`
    : `<p class="faint" style="font-size:13px;margin-bottom:12px">${esc(t('pk.none'))}</p>`;
}

function addPasskey() {
  return modal({
    html: `<h3>${esc(t('pk.addTitle'))}</h3><p class="modal-sub">${esc(t('pk.addBody'))}</p>
      <form id="pkForm"><label class="field"><span>${esc(t('pk.name'))}</span><input class="input" id="pkName" maxlength="40" autocomplete="off" autofocus></label>
      <label class="field"><span>${esc(t('pk.password'))}</span><input class="input" type="password" id="pkPass" autocomplete="current-password" required></label>
      <div class="modal-actions"><button class="btn ghost" type="button" data-close>${esc(t('common.cancel'))}</button><button class="btn primary" type="submit" id="pkGo">${esc(t('pk.add'))}</button></div></form>`,
    setup: (el, close) => {
      $('#pkForm', el).onsubmit = async (e) => {
        e.preventDefault();
        $('#pkGo', el).disabled = true;
        try { await passkey.register($('#pkPass', el).value, $('#pkName', el).value.trim()); toast(t('pk.added'), 'ok'); close(true); loadPasskeys(); }
        catch (err) { toast(err.message, 'bad'); $('#pkGo', el).disabled = false; }
      };
    },
  });
}

function renamePasskey(id, name) {
  return modal({
    html: `<h3>${esc(t('pk.renameTitle'))}</h3><form id="pkForm" class="modal-body"><input class="input" id="pkName" maxlength="40" value="${esc(name)}" autofocus required>
      <div class="modal-actions"><button class="btn ghost" type="button" data-close>${esc(t('common.cancel'))}</button><button class="btn primary" type="submit">${esc(t('common.save'))}</button></div></form>`,
    setup: (el, close) => {
      $('#pkForm', el).onsubmit = async (e) => {
        e.preventDefault();
        try { await api('/api/auth/passkeys/' + encodeURIComponent(id), { method: 'PATCH', body: { name: $('#pkName', el).value } }); close(true); loadPasskeys(); }
        catch (err) { toast(err.message, 'bad'); }
      };
    },
  });
}

async function removePasskey(id, name) {
  if (!await confirmDialog({ title: t('pk.removeTitle'), html: `<p>${esc(t('pk.removeBody', { name }))}</p>`, ok: t('pk.remove') })) return;
  try { await api('/api/auth/passkeys/' + encodeURIComponent(id), { method: 'DELETE' }); toast(t('pk.removed'), 'ok'); loadPasskeys(); }
  catch (err) { toast(err.message, 'bad'); }
}

export function mount(el) {
  root = el;
  render();
  const map = { pTheme: 'theme', pView: 'viewMode', pCompact: 'compact', pMotion: 'reduceMotion', pGpuOn: 'gpuEnabled', pGpuInt: 'gpuInterval', pStateInt: 'stateInterval', pSensors: 'sensors' };
  el.onchange = (e) => {
    const id = e.target.id;
    if (id === 'pLang') { setLang(e.target.value); return; }
    if (!map[id]) return;
    const value = e.target.type === 'checkbox' ? e.target.checked : (/Int$/.test(id) ? Number(e.target.value) : e.target.value);
    const stored = setPrefs({ [map[id]]: value });
    $('#pGpuInt', root).disabled = !getPrefs().gpuEnabled;
    $('#pStatus', root).textContent = stored ? t('pref.saved') : t('pref.notStored');
  };
  el.onclick = async (e) => {
    const pk = e.target.closest('[data-pk-rename],[data-pk-remove]');
    if (e.target.closest('#pkAdd')) addPasskey();
    else if (pk?.dataset.pkRename) renamePasskey(pk.dataset.pkRename, pk.dataset.name);
    else if (pk?.dataset.pkRemove) removePasskey(pk.dataset.pkRemove, pk.dataset.name);
    if (e.target.closest('#pReset')) { setPrefs(defaultPrefs()); render(); toast(t('pref.resetDone'), 'ok'); }
    if (e.target.closest('#signOut')) { await fetch('/api/logout', { method: 'POST' }); location.href = '/login'; }
  };
  el.onsubmit = async (e) => {
    if (e.target.id !== 'pwForm') return;
    e.preventDefault();
    const cur = $('#pwCur', root).value, a = $('#pwNew', root).value, b = $('#pwNew2', root).value;
    if (a !== b) { toast(t('acct.mismatch'), 'bad'); return; }
    try { await api('/api/account/password', { method: 'POST', body: { current: cur, new: a } }); toast(t('acct.changed'), 'ok'); e.target.reset(); }
    catch (err) { toast(err.message, 'bad'); }
  };
}
export function unmount() {}
