/* 주가 방향 날씨 페이지 하단 '서머리 요점' 렌더러
 * - window.MUHAN_SUMMARY (muhan/muhan-summary.js) : TQQQ 무한매수 매수/매도 상태
 * - window.FEARGREED_SUMMARY (feargreed/feargreed-summary.js) : CNN 공포지수 신호 + 겹친 차트
 * 두 요약 데이터 파일은 각 페이지의 update 스크립트가 매일 갱신합니다.
 */
(function () {
  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function num(value, digits) {
    if (typeof value !== "number" || !isFinite(value)) return "-";
    return Number(value).toFixed(typeof digits === "number" ? digits : 2);
  }
  function money(value) {
    if (typeof value !== "number" || !isFinite(value)) return "-";
    return "$" + value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function sgn(value) {
    if (typeof value !== "number" || !isFinite(value)) return "-";
    return (value > 0 ? "+" : "") + value.toFixed(1) + "%";
  }
  function head(title, href) {
    return '<h3><a href="' + href + '">' + title + "</a></h3>";
  }

  function renderMuhan() {
    var el = document.getElementById("ws-muhan");
    if (!el) return;
    var d = window.MUHAN_SUMMARY;
    if (!d || !d.asof) {
      el.innerHTML = head("1. TQQQ 무한매수법", "muhan/index.html") +
        '<p class="ws-sub">데이터를 불러오지 못했습니다.</p>';
      return;
    }
    var buyCls = d.buyNow ? "on-buy" : "off";
    var sellCls = d.sellNow ? "on-sell" : "off";
    var actCls = d.actionCls === "sell" || d.actionCls === "both" ? "on-sell"
      : d.actionCls === "buy" ? "on-buy" : "off";
    var html = head("1. TQQQ 무한매수법", "muhan/index.html");
    html += '<p class="ws-sub">중단타(사이클마다 다름) · 기준일 ' + esc(d.asof) + " · TQQQ " + money(d.lastClose) + "</p>";
    html += '<div class="ws-badges">' +
      '<span class="ws-badge ' + buyCls + '">' + (d.buyNow ? "오늘 매수 ✅" : "오늘 매수 ✖") + "</span>" +
      '<span class="ws-badge ' + sellCls + '">' + (d.sellNow ? "오늘 매도 ✅" : "오늘 매도 ✖") + "</span>" +
      '<span class="ws-badge ' + actCls + '">→ ' + esc(d.action || "-") + "</span></div>";
    html += '<div class="ws-lines">' +
      "<div>T값 <strong>" + num(d.T, 1) + "</strong> · " + esc(d.phase) + " · 평단 <strong>" + money(d.avg) + "</strong></div>" +
      "<div>매수 지정가 " + money(d.buyLimit) + " 이하 · 매도 지정가 " + money(d.sellLimit) + " 이상</div>" +
      "<div>지정가 매도 " + money(d.targetPrice) + (typeof d.toTargetPct === "number" ? " (현재가에서 " + sgn(d.toTargetPct) + ")" : "") + "</div>" +
      "<div>" + esc(d.actionText || "") + "</div></div>";
    el.innerHTML = html;
  }

  function renderFeargreed() {
    var el = document.getElementById("ws-feargreed");
    if (!el) return;
    var d = window.FEARGREED_SUMMARY;
    if (!d || !d.asof) {
      el.innerHTML = head("2. CNN 공포지수 매수", "feargreed/index.html") +
        '<p class="ws-sub">데이터를 불러오지 못했습니다.</p>';
      return;
    }
    var on = !!d.signalOn;
    var cls = on ? "signal-on" : "off";
    var html = head("2. CNN 공포지수 매수", "feargreed/index.html");
    html += '<p class="ws-sub">중단타(몇달이내) · 기준일 ' + esc(d.asof) + " · 공포지수 " +
      num(d.score, 2) + " (" + esc(d.ratingKo) + ")</p>";
    html += '<div class="ws-badges">' +
      '<span class="ws-badge ' + cls + '">' + (on ? "매수 시그널 ON" : "매수 시그널 대기") + "</span>" +
      '<span class="ws-badge ' + cls + '">대상 QQQ·SPY·VOO</span>' +
      '<span class="ws-badge ' + cls + '">' + (on ? "확률 100%" : "지수 " + num(d.threshold, 0) + " 이하에서 100%") + "</span></div>";
    html += '<div class="ws-lines">' + (on
      ? "지수 " + num(d.score, 2) + " ≤ " + num(d.threshold, 0) + " → QQQ·SPY·VOO 분할 매수 시그널 도착. 장타 아님(중타)."
      : "지수 " + num(d.score, 2) + " > " + num(d.threshold, 0) + " → 대기 중. 남은 하락폭 " + num(Math.max(0, d.score - d.threshold), 2) + "p.") + "</div>";
    html += '<div class="ws-chart"><canvas id="ws-fg-canvas"></canvas></div>';
    if (d.targets && d.targets.length) {
      html += '<div class="ws-targets">' + d.targets.map(function (t) {
        return esc(t.symbol) + " " + money(t.price);
      }).join(" · ") + " (분할 " + (d.splits || 5) + "회 예시)</div>";
    }
    el.innerHTML = html;
    drawChart();
  }

  function drawChart() {
    var d = window.FEARGREED_SUMMARY;
    if (!d || !d.chart) return;
    var dates = d.chart.dates || [], fng = d.chart.fng || [], qqq = d.chart.qqq || [];
    var n = dates.length;
    var canvas = document.getElementById("ws-fg-canvas");
    if (!canvas || n < 2) return;
    var wrap = canvas.parentNode;
    var w = wrap.clientWidth || 460, h = wrap.clientHeight || 250;
    var dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    var padL = 30, padR = 46, padT = 12, padB = 22;
    var pw = w - padL - padR, ph = h - padT - padB;
    var thr = typeof d.threshold === "number" ? d.threshold : 10;
    var qv = [], i;
    for (i = 0; i < n; i++) if (typeof qqq[i] === "number") qv.push(qqq[i]);
    var qmin = qv.length ? Math.min.apply(null, qv) : 0;
    var qmax = qv.length ? Math.max.apply(null, qv) : 1;
    var pad = (qmax - qmin) * 0.08 || 1;
    qmin -= pad; qmax += pad;
    function X(idx) { return padL + (idx / (n - 1)) * pw; }
    function FY(v) { return padT + ph - (v / 100) * ph; }
    function QY(v) { return padT + ph - ((v - qmin) / (qmax - qmin)) * ph; }
    var zt = FY(thr);
    ctx.fillStyle = "rgba(255,107,107,0.16)";
    ctx.fillRect(padL, zt, pw, padT + ph - zt);
    ctx.strokeStyle = "rgba(255,107,107,0.55)";
    ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(padL, zt); ctx.lineTo(padL + pw, zt); ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = "#4da3ff"; ctx.lineWidth = 1.2; ctx.beginPath();
    var st = false;
    for (i = 0; i < n; i++) {
      if (typeof qqq[i] !== "number") continue;
      var qx = X(i), qy = QY(qqq[i]);
      if (!st) { ctx.moveTo(qx, qy); st = true; } else ctx.lineTo(qx, qy);
    }
    ctx.stroke();
    ctx.strokeStyle = "#ff9b6b"; ctx.lineWidth = 1.6; ctx.beginPath();
    for (i = 0; i < n; i++) {
      var v = typeof fng[i] === "number" ? fng[i] : 0;
      if (i === 0) ctx.moveTo(X(i), FY(v)); else ctx.lineTo(X(i), FY(v));
    }
    ctx.stroke();
    ctx.fillStyle = "rgba(255,107,107,0.95)";
    for (i = 0; i < n; i++) {
      if (typeof fng[i] === "number" && fng[i] <= thr) {
        ctx.beginPath(); ctx.arc(X(i), FY(fng[i]), 2, 0, Math.PI * 2); ctx.fill();
      }
    }
    ctx.font = "11px Arial";
    ctx.fillStyle = "#ff9b6b"; ctx.textAlign = "right";
    [0, 50, 100].forEach(function (lv) { ctx.fillText(String(lv), padL - 4, FY(lv) + 3); });
    ctx.fillStyle = "#4da3ff"; ctx.textAlign = "left";
    ctx.fillText("$" + qmax.toFixed(0), padL + pw + 5, padT + 8);
    ctx.fillText("$" + qmin.toFixed(0), padL + pw + 5, padT + ph);
    if (typeof fng[n - 1] === "number") {
      ctx.fillStyle = "#0c0c0c";
      ctx.fillRect(X(n - 1) - 40, FY(fng[n - 1]) - 20, 38, 16);
      ctx.fillStyle = "#ff9b6b"; ctx.textAlign = "right";
      ctx.fillText(num(fng[n - 1], 2), X(n - 1) - 4, FY(fng[n - 1]) - 8);
    }
    ctx.fillStyle = "#9a9a9a"; ctx.textAlign = "center";
    for (var t = 0; t <= 3; t++) {
      var idx = Math.round((t / 3) * (n - 1));
      ctx.fillText((dates[idx] || "").slice(2, 7).replace("-", "."), X(idx), h - 6);
    }
  }

  function render() {
    renderMuhan();
    renderFeargreed();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }

  var timer = null;
  window.addEventListener("resize", function () {
    if (timer) clearTimeout(timer);
    timer = setTimeout(drawChart, 150);
  });
})();
