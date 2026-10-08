(function () {
  'use strict';
  const form = document.getElementById('loginForm');
  const err = document.getElementById('loginErr');
  const btn = document.getElementById('loginBtn');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.textContent = '';
    btn.disabled = true;
    btn.textContent = '확인 중…';
    try {
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: document.getElementById('username').value,
          password: document.getElementById('password').value,
        }),
      });
      if (res.ok) { location.href = '/'; return; }
      let msg = '로그인에 실패했습니다';
      try { msg = (await res.json()).detail || msg; } catch (e2) { /* noop */ }
      err.textContent = msg;
      document.getElementById('password').select();
    } catch (e3) {
      err.textContent = '서버에 연결할 수 없습니다';
    } finally {
      btn.disabled = false;
      btn.textContent = '로그인';
    }
  });
})();
