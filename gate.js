var PASS = '3142';
function safeNext(raw) {
  if (!raw || raw.indexOf('\\') !== -1) return '';
  try {
    var u = new URL(raw, location.origin);
    if (u.origin !== location.origin) return '';
    if (u.pathname.indexOf('/Premium/') !== 0) return '';
    if (u.pathname === '/Premium/' || u.pathname === '/Premium/index.html') return '';
    return u.pathname + u.search;
  } catch (e) {
    return '';
  }
}
function showMenu() {
  var gate = document.getElementById('gate');
  var menu = document.getElementById('menu');
  if (gate) gate.style.display = 'none';
  if (menu) menu.style.display = 'block';
}
function unlockPremium() {
  var input = document.getElementById('pw');
  if (!input || input.value !== PASS) {
    alert('비밀번호가 틀립니다');
    return;
  }
  localStorage.setItem('hans-premium', PASS);
  var next = safeNext(new URLSearchParams(location.search).get('next'));
  location.href = next || '/Premium/';
}
(function () {
  var path = location.pathname;
  var gate = path === '/Premium' || path === '/Premium/' || path === '/Premium/index.html';
  if (!gate) {
    if (path.indexOf('/Premium/') === 0 && localStorage.getItem('hans-premium') !== PASS) {
      location.replace('/Premium/?next=' + encodeURIComponent(path + location.search));
    }
    return;
  }
  document.addEventListener('DOMContentLoaded', function () {
    var input = document.getElementById('pw');
    if (input) {
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') unlockPremium();
      });
    }
    if (localStorage.getItem('hans-premium') === PASS) showMenu();
  });
})();
