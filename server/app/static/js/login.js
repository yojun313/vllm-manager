/* 로그인과 초기 설정 화면. */
import { applyI18n, setLang, t } from './i18n.js';
import * as passkey from './passkey.js';

const $ = (s) => document.querySelector(s);
applyI18n();

function langButton() {
  const b = $('#langToggle');
  b.textContent = document.documentElement.lang === 'ko' ? 'English' : '한국어';
  b.onclick = () => setLang(document.documentElement.lang === 'ko' ? 'en' : 'ko');
}
langButton();
window.addEventListener('vm:lang', () => { applyI18n(); langButton(); });

async function post(path, body) {
  const res = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (res.ok) return;
  let detail = res.statusText;
  try { detail = (await res.json()).detail || detail; } catch (e) { /* 본문 없음 */ }
  throw new Error(typeof detail === 'string' ? detail : t('login.failed'));
}

// 비밀번호 보기 전환, Caps Lock 안내
document.querySelectorAll('[data-reveal]').forEach((b) => {
  b.setAttribute('aria-label', t('login.show'));
  b.addEventListener('click', () => {
    const input = document.getElementById(b.dataset.reveal);
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    b.classList.toggle('on', show);
    input.focus();
  });
});
const caps = $('#capsNote');
if (caps) $('#password').addEventListener('keyup', (e) => { caps.hidden = !(e.getModifierState && e.getModifierState('CapsLock')); });

const login = $('#loginForm');
if (login) {
  login.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('#loginBtn'), err = $('#loginErr');
    btn.disabled = true; err.textContent = '';
    try { await post('/api/login', { username: $('#username').value, password: $('#password').value }); location.href = '/'; }
    catch (ex) { err.textContent = ex.message; $('#password').select(); }
    finally { btn.disabled = false; }
  });
}

const pkButton = $('#passkeyLogin');
if (pkButton) {
  if (!passkey.supported()) $('#passkeyBox').remove();
  else pkButton.addEventListener('click', async () => {
    const err = $('#loginErr');
    pkButton.disabled = true; err.textContent = '';
    try { await passkey.login(); location.href = '/'; }
    catch (ex) { err.textContent = ex.message; pkButton.disabled = false; }
  });
}

const setup = $('#setupForm');
if (setup) {
  // 터미널에 표시된 주소(/setup?token=…)로 들어오면 토큰 입력란을 채우고 숨긴다
  const token = new URLSearchParams(location.search).get('token');
  if (token) { $('#token').value = token; $('#tokenField').hidden = true; history.replaceState(null, '', '/setup'); }
  setup.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('#setupBtn'), err = $('#setupErr');
    err.textContent = '';
    if ($('#password').value !== $('#password2').value) { err.textContent = t('acct.mismatch'); return; }
    btn.disabled = true;
    try {
      await post('/api/setup', { token: $('#token').value, username: $('#username').value, password: $('#password').value });
      location.href = '/#/system';
    } catch (ex) { err.textContent = ex.message; $('#tokenField').hidden = false; }
    finally { btn.disabled = false; }
  });
}
