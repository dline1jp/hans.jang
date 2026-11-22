/* CNN 공포지수 매수 시그널 페이지 렌더러
 * - window.FEARGREED_DATA 를 읽어 시그널 배너, 요약 카드, 대상 카드, 겹친 차트를 그립니다.
 * - 차트: CNN 공포·탐욕 지수(왼쪽 0~100) + QQQ 종가(오른쪽 $) 를 한 화면에 겹쳐 그립니다.
 */
(function () {
  var C = {
    fng: "#ff9b6b",
    qqq: "#4da3ff",
    zone: "rgba(255,107,107,0.14)",
    zoneEdge: "rgba(255,107,107,0.55)",
    marker: "rgba(255,107,107,0.95)",
    grid: "#262626",
    axis: "#9a9a9a",
    text: "#dddddd",
    panel: "#0c0c0c"
  };

  function num(value, digits) {
    if (typeof value !== "number" || !isFinite(value)) return "-";
    return Number(value).toFixed(typeof digits === "number" ? digits : 2);
  }

  function money(value) {
    if (typeof value !== "number" || !isFinite(value)) return "-";
    return "$" + value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function percent(value) {
    if (typeof value !== "number" || !isFinite(value)) return "-";
    return (value > 0 ? "+" : "") + value.toFixed(1) + "%";
  }

  function escapeHtml(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setText(id, text, className) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    if (className) el.className = className;
  }

  function renderSignal(data) {
    var box = document.getElementById("signal");
    if (!box) return;
    var on = !!data.signalOn;
    box.className = "signal " + (on ? "on" : "off");
    setText("signal-badge", on ? "매수 시그널 ON" : "매수 시그널 대기");
    if (on) {
      setText(
        "signal-title",
        "QQQ · SPY · VOO 분할 매수 시그널에 왔습니다"
      );
      setText(
        "signal-sub",
        "CNN 공포지수 " + num(data.score, 2) + " (" + data.ratingKo + ") · 지수가 " +
          num(data.threshold, 0) + " 이하입니다. 중타(몇달) 기준, 장타 아님."
      );
      setText("signal-prob", "100%", "signal-prob");
      setText("signal-prob-note", "지수 " + num(data.threshold, 0) + " 이하 = 규칙상 100% 표시");
    } else {
      setText(
        "signal-title",
        "아직 대기 중입니다 · 지수 " + num(data.score, 2)
      );
      setText(
        "signal-sub",
        "공포지수가 " + num(data.threshold, 0) + " 이하로 내려가면 QQQ·SPY·VOO 분할 매수 시그널이 켜집니다. " +
          "남은 하락폭 " + num(Math.max(0, data.score - data.threshold), 2) + "p."
      );
      setText("signal-prob", "-", "signal-prob");
      setText("signal-prob-note", "지수 " + num(data.threshold, 0) + " 이하일 때 100% 표시");
    }
    setText("signal-count", "분할 " + (data.splits || 5) + "회 · 중타(몇달)");
  }

  function renderHero(data) {
    setText("hero-score", num(data.score, 2), "hero-value " + (data.signalOn ? "good" : "bad"));
    setText("hero-rating", data.ratingKo + " (" + (data.rating || "-") + ")");
    setText(
      "hero-threshold",
      "직전 " + num(data.previousClose, 2) + " · 1주 " + num(data.previous1Week, 2) + " · 1달 " + num(data.previous1Month, 2)
    );
    setText("hero-prob", "100%", "hero-value gold");
    setText("hero-horizon", "중타 · 몇달", "hero-value gold");
  }

  function renderTargets(data) {
    var host = document.getElementById("targets");
    if (!host) return;
    var targets = data.targets || [];
    if (!targets.length) {
      host.innerHTML = '<p class="error">대상 데이터가 없습니다.</p>';
      return;
    }
    var splits = data.splits || 5;
    var html = "";
    targets.forEach(function (item) {
      var cls = "target" + (data.signalOn ? " on" : "");
      html +=
        '<div class="' + cls + '">' +
          "<h3>" + escapeHtml(item.symbol) + "</h3>" +
          '<span class="tname">' + escapeHtml(item.name) + "</span>" +
          '<div class="price">' + money(item.price) + "</div>" +
          '<div class="split">분할 매수 예시 ' + splits + "회 · 1회 약 " +
            money(item.price == null ? null : item.price / splits) + "</div>" +
          (data.signalOn
            ? '<div class="split">시그널 ON · 분할 매수 대상</div>'
            : '<div class="split">시그널 대기 · 지수 ' + num(data.threshold, 0) + " 이하에서 대상</div>") +
        "</div>";
    });
    host.innerHTML = html;
  }

  function renderDocStats(data) {
    var stats = data.stats || {};
    var el = document.getElementById("doc-stats");
    if (!el) return;
    var parts = [];
    parts.push(
      "최근 약 1년 동안 공포지수가 " + num(data.threshold, 0) + " 이하로 내려간 구간은 " +
        (stats.episodes == null ? "-" : stats.episodes) + "번이었습니다."
    );
    if (stats.forwardAvg != null) {
      parts.push(
        "그중 " + stats.forwardCount + "번은 약 3개월(" + stats.forwardDays + "거래일) 뒤 QQQ 수익률을 계산할 수 있었고, " +
          "평균 " + percent(stats.forwardAvg) + " (최고 " + percent(stats.forwardBest) + " / 최저 " + percent(stats.forwardWorst) + ")였습니다."
      );
    }
    parts.push("표시되는 100%는 규칙 신뢰도이며, 수익을 보장하지 않습니다.");
    el.textContent = parts.join(" ");
  }

  function drawChart() {
    var data = window.FEARGREED_DATA || {};
    var chart = data.chart || {};
    var dates = chart.dates || [];
    var fng = chart.fng || [];
    var qqq = chart.qqq || [];
    var n = dates.length;

    var canvas = document.getElementById("fg-chart");
    if (!canvas || n < 2) return;
    var wrap = canvas.parentNode;
    var width = wrap.clientWidth || 1000;
    var height = wrap.clientHeight || 420;
    var dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    var padLeft = 52;
    var padRight = 74;
    var padTop = 18;
    var padBottom = 34;
    var plotW = width - padLeft - padRight;
    var plotH = height - padTop - padBottom;

    var threshold = typeof data.threshold === "number" ? data.threshold : 10;

    // 각 축의 범위
    var fngMin = 0;
    var fngMax = 100;
    var qqqVals = [];
    for (var i = 0; i < n; i++) {
      if (typeof qqq[i] === "number") qqqVals.push(qqq[i]);
    }
    var qMin = qqqVals.length ? Math.min.apply(null, qqqVals) : 0;
    var qMax = qqqVals.length ? Math.max.apply(null, qqqVals) : 1;
    var qPad = (qMax - qMin) * 0.08 || 1;
    qMin -= qPad;
    qMax += qPad;

    function x(index) { return padLeft + (n === 1 ? 0 : (index / (n - 1)) * plotW); }
    function fngY(value) { return padTop + plotH - ((value - fngMin) / (fngMax - fngMin)) * plotH; }
    function qqqY(value) { return padTop + plotH - ((value - qMin) / (qMax - qMin)) * plotH; }

    // 공포지수 10 이하 매수 구간(0~10) 음영
    var zoneTop = fngY(threshold);
    ctx.fillStyle = C.zone;
    ctx.fillRect(padLeft, zoneTop, plotW, padTop + plotH - zoneTop);
    ctx.strokeStyle = C.zoneEdge;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(padLeft, zoneTop);
    ctx.lineTo(padLeft + plotW, zoneTop);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(255,179,179,0.9)";
    ctx.font = "12px Arial";
    ctx.textAlign = "left";
    ctx.fillText("매수 구간 " + num(threshold, 0) + " 이하", padLeft + 6, zoneTop - 5);

    // 왼쪽 눈금(공포지수 0/25/50/75/100)
    ctx.font = "12px Arial";
    [0, 25, 50, 75, 100].forEach(function (value) {
      var gy = fngY(value);
      ctx.strokeStyle = C.grid;
      ctx.beginPath();
      ctx.moveTo(padLeft, gy);
      ctx.lineTo(padLeft + plotW, gy);
      ctx.stroke();
      ctx.fillStyle = C.fng;
      ctx.textAlign = "right";
      ctx.fillText(String(value), padLeft - 8, gy + 4);
    });

    // 오른쪽 눈금(QQQ 가격)
    var steps = 4;
    ctx.textAlign = "left";
    for (var s = 0; s <= steps; s++) {
      var value2 = qMin + ((qMax - qMin) * s) / steps;
      var gy2 = qqqY(value2);
      ctx.strokeStyle = C.grid;
      ctx.beginPath();
      ctx.moveTo(padLeft, gy2);
      ctx.lineTo(padLeft + plotW, gy2);
      ctx.stroke();
      ctx.fillStyle = C.qqq;
      ctx.fillText("$" + value2.toFixed(0), padLeft + plotW + 8, gy2 + 4);
    }

    // X축 월 라벨
    var ticks = Math.max(2, Math.min(6, Math.floor(plotW / 130)));
    ctx.fillStyle = C.axis;
    ctx.textAlign = "center";
    for (var t = 0; t <= ticks; t++) {
      var idx = Math.round((t / ticks) * (n - 1));
      var lx = x(idx);
      ctx.strokeStyle = C.grid;
      ctx.beginPath();
      ctx.moveTo(lx, padTop);
      ctx.lineTo(lx, padTop + plotH);
      ctx.stroke();
      var label = (dates[idx] || "").slice(2, 7).replace("-", ".");
      ctx.fillText(label, lx, padTop + plotH + 20);
    }

    // QQQ 종가 라인(오른쪽 축)
    ctx.strokeStyle = C.qqq;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    var started = false;
    for (i = 0; i < n; i++) {
      if (typeof qqq[i] !== "number") continue;
      var qx = x(i);
      var qy = qqqY(qqq[i]);
      if (!started) { ctx.moveTo(qx, qy); started = true; }
      else ctx.lineTo(qx, qy);
    }
    ctx.stroke();

    // CNN 공포지수 라인(왼쪽 축)
    ctx.strokeStyle = C.fng;
    ctx.lineWidth = 1.9;
    ctx.beginPath();
    for (i = 0; i < n; i++) {
      var fv = typeof fng[i] === "number" ? fng[i] : 0;
      if (i === 0) ctx.moveTo(x(i), fngY(fv));
      else ctx.lineTo(x(i), fngY(fv));
    }
    ctx.stroke();

    // 공포지수 10 이하인 날 마커
    ctx.fillStyle = C.marker;
    for (i = 0; i < n; i++) {
      if (typeof fng[i] === "number" && fng[i] <= threshold) {
        ctx.beginPath();
        ctx.arc(x(i), fngY(fng[i]), 2.4, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // 현재값(마지막 점) 강조
    if (typeof fng[n - 1] === "number") {
      var fx = x(n - 1);
      var fy = fngY(fng[n - 1]);
      ctx.beginPath();
      ctx.arc(fx, fy, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = C.fng;
      ctx.fill();
      ctx.fillStyle = C.panel;
      ctx.fillRect(fx - 46, fy - 26, 44, 20);
      ctx.fillStyle = C.fng;
      ctx.textAlign = "right";
      ctx.fillText(num(fng[n - 1], 2), fx - 6, fy - 11);
    }
    for (i = n - 1; i >= 0; i--) {
      if (typeof qqq[i] === "number") {
        ctx.fillStyle = C.qqq;
        ctx.beginPath();
        ctx.arc(x(i), qqqY(qqq[i]), 4, 0, Math.PI * 2);
        ctx.fill();
        break;
      }
    }
  }

  function renderAll() {
    var data = window.FEARGREED_DATA;
    if (!data || !data.chart || !data.chart.dates) {
      setText("signal-title", "데이터를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.");
      return;
    }
    renderSignal(data);
    renderHero(data);
    renderTargets(data);
    renderDocStats(data);
    drawChart();
    setText(
      "chart-help",
      "주황선 = CNN 공포·탐욕 지수(왼쪽 0~100), 파란선 = QQQ 종가(오른쪽 $). " +
        "빨간 점·음영 = 공포지수 " + num(data.threshold, 0) + " 이하(매수 구간). " +
        "신호는 장타가 아니라 중타(몇달) 기준입니다."
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderAll);
  } else {
    renderAll();
  }

  var timer = null;
  window.addEventListener("resize", function () {
    if (timer) clearTimeout(timer);
    timer = setTimeout(drawChart, 150);
  });
})();

