/* 사용자 동작: 실행·중지·삭제·설정 편집·다운로드·연결 예제. 여러 화면에서 함께 쓴다. */
import { t } from './i18n.js';
import { $, api, colorOf, confirmDialog, copy, esc, fmtBytes, fmtNum, gib, modal, toast } from './ui.js';
import { refresh, store } from './store.js';
import { showJob } from './sheet.js';
import { endpointOf } from './parts.js';

export async function up(model, gpus) {
  try {
    const j = await api(`/api/models/${encodeURIComponent(model)}/up`, { method: 'POST', body: { gpus: gpus || '' } });
    refresh();
    showJob(j.id);
  } catch (e) { toast(e.message, 'bad'); }
}

export async function stop(name) {
  const c = store.S?.containers.find((x) => x.name === name);
  const yes = await confirmDialog({
    title: t('stop.title'),
    html: `<p>${esc(t('stop.body', { model: c?.model || name }))}</p><p class="dim small mono">${esc(name)}</p>`,
    ok: t('common.stop'),
  });
  if (!yes) return;
  try { await api(`/api/containers/${encodeURIComponent(name)}/down`, { method: 'POST' }); toast(t('stop.sent', { name: c?.model || name })); refresh(); }
  catch (e) { toast(e.message, 'bad'); }
}

/* ------------------------------------------------------------ 모델 삭제 */
export function deleteModel(alias) {
  const find = () => store.S.models.find((x) => x.alias === alias);
  const m = find();
  if (!m) return;
  const running = store.S.containers.filter((c) => c.model === alias);
  const canFiles = m.files_bytes > 0 && !m.files_shared.length;
  const note = m.files_shared.length ? t('del.shared', { list: m.files_shared.join(', ') })
    : !m.files_bytes ? t('del.noFiles') : t('del.keepNote');
  return modal({
    html: `<h3>${esc(t('del.title'))}</h3>
      <div class="modal-body">
        <div class="rc-head"><span class="swatch" style="background:${colorOf(alias)}"></span><div class="rc-title"><h3>${esc(alias)}</h3><div class="served">${esc(m.served)}</div></div></div>
        ${running.length ? `<div class="fit-box no">${esc(t('del.running', { where: running.map((c) => 'GPU ' + c.gpus).join(', ') }))}</div>` : ''}
        <label class="check ${canFiles ? '' : 'disabled'}"><input type="checkbox" id="delFiles" ${canFiles ? '' : 'disabled'}>
          <span><b>${esc(t('del.files'))}</b> ${m.files_bytes ? `<span class="mono dim">· ${fmtBytes(m.files_bytes)}</span>` : ''}<br><span class="mono faint small">${esc(m.files_dir || '')}</span></span></label>
        <p class="faint small">${esc(note)}</p>
        <label class="field" style="margin-top:14px"><span>${t('del.confirm', { alias: `<b class="mono">${esc(alias)}</b>` })}</span>
          <input class="input mono" id="delConfirm" autocomplete="off" autocapitalize="off" spellcheck="false" autofocus></label>
      </div>
      <div class="modal-actions"><button class="btn ghost" data-close>${esc(t('common.cancel'))}</button><button class="btn danger solid" id="delOk" disabled>${esc(t('del.okConfig'))}</button></div>`,
    setup: (el, close) => {
      const sync = () => {
        $('#delOk', el).disabled = running.length > 0 || $('#delConfirm', el).value.trim() !== alias;
        $('#delOk', el).textContent = $('#delFiles', el).checked ? t('del.okFiles') : t('del.okConfig');
      };
      $('#delConfirm', el).addEventListener('input', sync);
      $('#delFiles', el).addEventListener('change', sync);
      $('#delConfirm', el).addEventListener('keydown', (e) => { if (e.key === 'Enter' && !$('#delOk', el).disabled) $('#delOk', el).click(); });
      $('#delOk', el).onclick = async () => {
        $('#delOk', el).disabled = true;
        try {
          const j = await api(`/api/models/${encodeURIComponent(alias)}?files=${$('#delFiles', el).checked}`, { method: 'DELETE' });
          close(true); refresh(); showJob(j.id);
        } catch (e) { toast(e.message, 'bad'); sync(); }
      };
    },
  });
}

/* ------------------------------------------------------------ 설정 파일 편집 */
export async function editConfig(alias) {
  let text;
  try { text = (await api(`/api/models/${encodeURIComponent(alias)}/config`)).text; }
  catch (e) { toast(e.message, 'bad'); return; }
  const running = store.S.containers.some((c) => c.model === alias);
  return modal({
    wide: true,
    html: `<h3>${esc(t('cfg.title', { alias }))}</h3>
      <p class="modal-sub mono">models/${esc(alias)}.yaml</p>
      <textarea class="input editor" id="cfgText" spellcheck="false" autocapitalize="off" autocomplete="off" autofocus></textarea>
      <p class="hint">${t('cfg.hint')}</p>
      ${running ? `<div class="notice warn">${esc(t('cfg.running'))}</div>` : ''}
      <div class="modal-actions"><button class="btn ghost" data-close>${esc(t('common.cancel'))}</button><button class="btn primary" id="cfgSave">${esc(t('common.save'))}</button></div>`,
    setup: (el, close) => {
      const ta = $('#cfgText', el);
      ta.value = text;
      ta.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') { e.preventDefault(); ta.setRangeText('  ', ta.selectionStart, ta.selectionEnd, 'end'); }
        if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); $('#cfgSave', el).click(); }
      });
      $('#cfgSave', el).onclick = async () => {
        $('#cfgSave', el).disabled = true;
        try {
          await api(`/api/models/${encodeURIComponent(alias)}/config`, { method: 'PUT', body: { text: ta.value } });
          toast(t('cfg.saved'), 'ok'); close(true); refresh();
        } catch (e) { toast(e.message, 'bad'); $('#cfgSave', el).disabled = false; }
      };
    },
  });
}

/* ------------------------------------------------------------ 모델 추가 (검색 → 용량 확인 → 다운로드) */
export function addModel(initial = '') {
  return modal({
    html: `<h3>${esc(t('add.title'))}</h3>
      <p class="modal-sub">${esc(t('add.sub', { dir: store.S?.models_dir || '' }))}</p>
      <label class="field"><span>${esc(t('add.repo'))}</span>
        <input class="input mono" id="addRepo" placeholder="Qwen/Qwen3-8B" autocomplete="off" autocapitalize="off" spellcheck="false" autofocus></label>
      <div class="suggest" id="addSuggest"></div>
      <label class="field"><span>${esc(t('add.alias'))}</span>
        <input class="input mono" id="addAlias" placeholder="${esc(t('add.aliasHint'))}" autocomplete="off" autocapitalize="off" spellcheck="false"></label>
      <div id="addFit"></div>
      <p class="hint">${esc(t('add.resume'))}</p>
      <div class="modal-actions"><button class="btn ghost" data-close>${esc(t('common.cancel'))}</button>
        <button class="btn" id="addCheck">${esc(t('add.check'))}</button>
        <button class="btn primary" id="addGo"><span data-icon="download" data-size="15"></span>${esc(t('add.download'))}</button></div>`,
    setup: (el, close) => {
      const repoEl = $('#addRepo', el), sug = $('#addSuggest', el), fitEl = $('#addFit', el);
      let timer = null, checked = null, seq = 0;
      const clean = () => repoEl.value.trim().replace(/^https:\/\/huggingface\.co\//, '').replace(/\/+$/, '');
      const valid = () => /^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/.test(clean());
      repoEl.value = initial;
      const search = async () => {
        const q = clean(), mine = ++seq;
        if (q.length < 2) { sug.innerHTML = ''; return; }
        try {
          const r = await api('/api/hf/search?q=' + encodeURIComponent(q));
          if (mine !== seq) return;
          sug.innerHTML = r.results.filter((x) => x.id !== q).map((x) => `<button type="button" data-id="${esc(x.id)}">
            <span class="id">${esc(x.id)}${x.gated ? `<span class="tag">${esc(t('add.gated'))}</span>` : ''}</span><span class="meta">↓ ${fmtNum(x.downloads)} · ♥ ${fmtNum(x.likes)}</span>
            <span class="meta">${esc(x.task)}</span></button>`).join('');
        } catch (e) { sug.innerHTML = ''; }
      };
      repoEl.addEventListener('input', () => { checked = null; fitEl.innerHTML = ''; clearTimeout(timer); timer = setTimeout(search, 280); });
      sug.addEventListener('click', (e) => {
        const b = e.target.closest('[data-id]');
        if (!b) return;
        repoEl.value = b.dataset.id; sug.innerHTML = ''; checked = null; check();
      });
      const check = async () => {
        if (!valid()) { toast(t('add.invalid'), 'bad'); return null; }
        const btn = $('#addCheck', el);
        btn.disabled = true; btn.textContent = t('add.checking');
        try {
          const r = await api('/api/pull/check?repo=' + encodeURIComponent(clean()));
          checked = r;
          const G = store.G;
          const body = r.fit === 'ok'
            ? (r.need1_mib != null && r.need1_mib <= r.cap_mib ? t('fit.one', { v: gib(r.need1_mib) }) : r.need_all_mib != null ? t('fit.many', { n: r.gpus, v: gib(r.need_all_mib) }) : r.message)
            : r.fit === 'no' ? t('fit.no', { n: r.gpus || G.length, need: gib(r.need_all_mib), cap: gib(r.cap_mib) })
            : r.engine === 'vllm-omni' ? t('fit.omni', { n: r.gpus }) : t('fit.unknown');
          fitEl.innerHTML = `<div class="fit-box ${r.fit === 'ok' ? 'ok' : r.fit === 'no' ? 'no' : 'unknown'}">${esc(body)}</div>`;
          $('#addGo', el).lastChild.textContent = r.fit === 'ok' ? t('add.download') : t('add.downloadAnyway');
          return r;
        } catch (e) { toast(e.message, 'bad'); return null; }
        finally { btn.disabled = false; btn.textContent = t('add.check'); }
      };
      $('#addCheck', el).onclick = check;
      $('#addGo', el).onclick = async () => {
        // 확인하지 않은 저장소는 먼저 용량을 계산해 보여주고, 한 번 더 눌러야 받는다
        if (!checked || checked.repo !== clean()) {
          const r = await check();
          if (!r || r.fit !== 'ok') return;
        }
        const btn = $('#addGo', el);
        btn.disabled = true;
        try {
          const j = await api('/api/pull', { method: 'POST', body: { repo: clean(), alias: $('#addAlias', el).value.trim(), force: checked.fit !== 'ok' } });
          close(true); refresh(); showJob(j.id);
        } catch (e) { toast(e.message, 'bad'); btn.disabled = false; }
      };
      repoEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); check(); } });
      if (initial) check();
    },
  });
}

/* ------------------------------------------------------------ 연결 예제 */
export function snippets(c, lang) {
  const url = endpointOf(c), key = store.S?.api_key;
  const auth = key ? ` \\\n  -H "Authorization: Bearer $VLLM_API_KEY"` : '';
  if (lang === 'curl') return `curl ${url}/chat/completions \\\n  -H "Content-Type: application/json"${auth} \\\n  -d '{\n    "model": "${c.served}",\n    "messages": [{"role": "user", "content": "Hello"}]\n  }'`;
  if (lang === 'python') return `from openai import OpenAI\n\nclient = OpenAI(\n    base_url="${url}",\n    api_key=${key ? 'os.environ["VLLM_API_KEY"]' : '"none"'},\n)\n\nresponse = client.chat.completions.create(\n    model="${c.served}",\n    messages=[{"role": "user", "content": "Hello"}],\n)\nprint(response.choices[0].message.content)`.replace(/^/, key ? 'import os\n' : '');
  return `import OpenAI from "openai";\n\nconst client = new OpenAI({\n  baseURL: "${url}",\n  apiKey: ${key ? 'process.env.VLLM_API_KEY' : '"none"'},\n});\n\nconst response = await client.chat.completions.create({\n  model: "${c.served}",\n  messages: [{ role: "user", content: "Hello" }],\n});\nconsole.log(response.choices[0].message.content);`;
}
export function snippetBlock(c) {
  return `<div class="seg" data-snip><button class="on" data-lang="curl">curl</button><button data-lang="python">Python</button><button data-lang="js">JavaScript</button></div>
    <pre class="snippet" data-snip-out>${esc(snippets(c, 'curl'))}</pre>
    <div class="actions" style="margin-top:10px"><button class="btn sm" data-snip-copy><span data-icon="copy" data-size="14"></span>${esc(t('common.copy'))}</button>
    ${store.S?.api_key ? `<button class="btn sm" data-copy-key><span data-icon="key" data-size="14"></span>${esc(t('key.copy'))}</button>` : ''}</div>`;
}
export function wireSnippet(root, c) {
  let lang = 'curl';
  root.addEventListener('click', (e) => {
    const b = e.target.closest('[data-lang]');
    if (b) {
      lang = b.dataset.lang;
      root.querySelectorAll('[data-lang]').forEach((x) => x.classList.toggle('on', x === b));
      root.querySelector('[data-snip-out]').textContent = snippets(c, lang);
    }
    if (e.target.closest('[data-snip-copy]')) copy(snippets(c, lang));
    if (e.target.closest('[data-copy-key]')) copyKey();
  });
}
export function connectInfo(name) {
  const c = store.S?.containers.find((x) => x.name === name);
  if (!c) return;
  return modal({
    wide: true,
    html: `<h3>${esc(t('conn.title', { model: c.model }))}</h3>
      <div class="modal-body"><dl class="kv"><dt>${esc(t('conn.base'))}</dt><dd class="mono">${esc(endpointOf(c))}</dd>
        <dt>${esc(t('conn.model'))}</dt><dd class="mono">${esc(c.served)}</dd>
        <dt>${esc(t('conn.auth'))}</dt><dd>${esc(store.S.api_key ? t('conn.authOn') : t('conn.authOff'))}</dd></dl>
        <div style="margin-top:16px" id="connSnip">${snippetBlock(c)}</div></div>
      <div class="modal-actions"><button class="btn" data-close>${esc(t('common.close'))}</button></div>`,
    setup: (el) => wireSnippet($('#connSnip', el), c),
  });
}
export async function copyKey() {
  try { copy(await api('/api/key'), t('key.copied')); } catch (e) { toast(e.message, 'bad'); }
}
