/* 방문자 카운터 (오늘 몇 명 들어왔는지)
   공개 서비스 hitscounter.dev 의 API 를 사용합니다. (로그인/키 필요 없음)
   - 조회수 올리기: /api/hit?...  (하루에 한 번만, 브라우저 기준 localStorage 로 중복 방지)
   - 실제 숫자 읽기: /api/history?...  (읽기 전용 JSON, 항상 최신)
   - "오늘" 기준 시간대는 한국 시간(Asia/Seoul)입니다. */
(function () {
  var KEY = "https://hansjang.com/";
  var TZ = "Asia/Seoul";
  var HIT =
    "https://hitscounter.dev/api/hit?url=" +
    encodeURIComponent(KEY) +
    "&label=visits&tz=" +
    encodeURIComponent(TZ);
  var HISTORY = "https://hitscounter.dev/api/history?url=" + encodeURIComponent(KEY);
  var SENT = "hansjang_visit_sent";

  var CSS =
    ".visit-counter{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:999px;" +
    'font-size:14px;font-weight:700;line-height:1;white-space:nowrap;letter-spacing:.2px;' +
    'font-family:"Malgun Gothic","Apple SD Gothic Neo",Arial,sans-serif;' +
    "background:#fffdf8;color:#2c2824;border:2px solid #c9c1b4;box-shadow:0 2px 8px rgba(0,0,0,.14);}" +
    ".visit-counter b{color:#008C95;font-weight:800;}" +
    ".visit-counter--inline{margin-left:auto;}" +
    ".visit-counter--fixed{position:fixed;right:12px;bottom:12px;z-index:9000;}" +
    ".visit-counter--dark{background:#1b1b1b;color:#e8e8e8;border-color:#4a4a4a;box-shadow:0 2px 10px rgba(0,0,0,.5);}" +
    ".visit-counter--dark b{color:#7dd3c0;}" +
    "@media (max-width:700px){.visit-counter{font-size:13px;padding:6px 11px;}}";

  function injectCss() {
    if (document.getElementById("visit-counter-css")) return;
    var style = document.createElement("style");
    style.id = "visit-counter-css";
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  /* 오늘 날짜(한국 시간)를 YYYY-MM-DD 로 */
  function kstToday() {
    var d = new Date(Date.now() + 9 * 60 * 60 * 1000);
    var m = d.getUTCMonth() + 1;
    var day = d.getUTCDate();
    return d.getUTCFullYear() + "-" + (m < 10 ? "0" : "") + m + "-" + (day < 10 ? "0" : "") + day;
  }

  function comma(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function nodes() {
    return document.querySelectorAll("[data-visit-counter]");
  }

  function paint(today, total) {
    Array.prototype.forEach.call(nodes(), function (el) {
      el.innerHTML = "오늘 방문 <b>" + comma(today) + "</b>명 · 전체 <b>" + comma(total) + "</b>명";
    });
  }

  function alreadySent() {
    try {
      return localStorage.getItem(SENT) === kstToday();
    } catch (e) {
      return false;
    }
  }

  function markSent() {
    try {
      localStorage.setItem(SENT, kstToday());
    } catch (e) {}
  }

  function read() {
    return fetch(HISTORY, { cache: "no-store" })
      .then(function (res) {
        return res.json();
      })
      .then(function (json) {
        var today = kstToday();
        var count = 0;
        var rows = json.history || [];
        for (var i = 0; i < rows.length; i++) {
          if (rows[i] && rows[i].hit_date === today) count = rows[i].hit_count;
        }
        paint(count, json.total_hits || 0);
      });
  }

  function run() {
    if (!nodes().length) return;
    injectCss();
    Array.prototype.forEach.call(nodes(), function (el) {
      el.innerHTML = "오늘 방문 <b>–</b>명 · 전체 <b>–</b>명";
    });
    if (alreadySent()) {
      read().catch(function () {});
      return;
    }
    /* 오늘 처음 방문한 브라우저만 조회수를 1 올리고, 그 다음 숫자를 읽는다. */
    fetch(HIT, { cache: "no-store" })
      .then(function () {
        markSent();
      })
      .catch(function () {})
      .then(function () {
        return read().catch(function () {});
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
