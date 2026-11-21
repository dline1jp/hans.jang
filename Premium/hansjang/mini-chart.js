/* 주봉 종가 + 200주 단순이동평균 미니 차트 (한스장 200주 페이지 공용)
 * - window.MA_SERIES 또는 window.MA_SUMMARY 에 있는 종목 데이터를 canvas.mini-canvas 에 그립니다.
 * - 페이지에 id="summary" 요소가 있고 window.MA_SUMMARY 가 있으면 서머리 카드를 먼저 그립니다.
 */
(function () {
  function average(values, length, index) {
    var sum = 0;
    for (var i = index - length + 1; i <= index; i++) sum += values[i];
    return sum / length;
  }

  function seriesFor(symbol) {
    var series = window.MA_SERIES || window.MA_SUMMARY || {};
    return series[symbol];
  }

  function fixed(value) {
    return Number(value).toFixed(2);
  }

  function comma(value) {
    var text = fixed(value);
    var parts = text.split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return parts.join(".");
  }

  function draw(canvas) {
    var row = seriesFor(canvas.getAttribute("data-symbol"));
    if (!row || !row.closes || row.closes.length < 200) return;
    var closes = row.closes;
    var width = Math.max(320, canvas.clientWidth || canvas.parentNode.clientWidth || 520);
    var height = 220;
    var dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.height = height + "px";
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    var points = [];
    var lo = Infinity;
    var hi = -Infinity;
    for (var i = 199; i < closes.length; i++) {
      var ma = average(closes, 200, i);
      points.push([closes[i], ma]);
      if (closes[i] < lo) lo = closes[i];
      if (closes[i] > hi) hi = closes[i];
      if (ma < lo) lo = ma;
      if (ma > hi) hi = ma;
    }
    if (!points.length || !isFinite(lo) || !isFinite(hi)) return;
    var pad = (hi - lo) * 0.06;
    lo -= pad;
    hi += pad;
    function x(index) {
      return 6 + (index / Math.max(1, points.length - 1)) * (width - 12);
    }
    function y(value) {
      return 12 + (hi - value) / (hi - lo) * (height - 28);
    }
    function stroke(column, color, lineWidth) {
      ctx.beginPath();
      for (var j = 0; j < points.length; j++) {
        var px = x(j);
        var py = y(points[j][column]);
        if (j === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = lineWidth;
      ctx.lineJoin = "round";
      ctx.stroke();
    }
    stroke(1, "#E53935", 2.2);
    stroke(0, "#bbbbbb", 1.2);
    ctx.fillStyle = "#888";
    ctx.font = "12px Arial";
    ctx.fillText(String(Math.round(hi)), 6, 14);
    ctx.fillText(String(Math.round(lo)), 6, height - 6);
  }

  function cardHtml(row) {
    var symbol = row.symbol;
    var gap = Number(row.gap);
    var sign = gap > 0 ? "+" : "";
    var desc = gap > 0
      ? "시세가 200주선보다 " + fixed(Math.abs(gap)) + "% 위에 있어 아직 매수 구간이 아닙니다. 200주선에 가까워질수록 확률이 높아지고, 200주선 아래로 내려오면 100%가 됩니다. 아래 그래프는 클릭 없이 바로 보이는 주봉 종가(회색)와 200주선(빨강)입니다."
      : "시세가 200주선 아래로 내려와 확률 100%인 종목입니다. 다만 버블기 종목은 예외로 봅니다. 아래 그래프는 클릭 없이 바로 보이는 주봉 종가(회색)와 200주선(빨강)입니다.";
    return "" +
      '<div class="stock-card ' + (row.cls || "miss") + '">' +
        "<h2>" + row.label + " · " + row.name + " · 확률 " + row.prob + "%</h2>" +
        '<p class="stock-meta">종가 ' + comma(row.close) + " · 200주선 " + comma(row.ma) + " · 200주선 대비 " + sign + fixed(gap) + "%</p>" +
        '<p class="stock-desc">' + desc + "</p>" +
        '<p class="ma-legend"><i class="ma200"></i>200주선 <i class="mapx"></i>주봉 종가</p>' +
        '<canvas class="mini-canvas" data-symbol="' + symbol + '" width="1100" height="220"></canvas>' +
      "</div>";
  }

  function renderSummary() {
    var host = document.getElementById("summary");
    var data = window.MA_SUMMARY;
    if (!host || !data) return;
    var order = window.MA_SUMMARY_ORDER || Object.keys(data);
    var html = "";
    for (var i = 0; i < order.length; i++) {
      var row = data[order[i]];
      if (row) html += cardHtml(row);
    }
    host.innerHTML = html;
  }

  function drawAll() {
    var minis = document.querySelectorAll("canvas.mini-canvas");
    for (var i = 0; i < minis.length; i++) draw(minis[i]);
  }

  renderSummary();
  drawAll();
  var timer = null;
  window.addEventListener("resize", function () {
    if (timer) clearTimeout(timer);
    timer = setTimeout(drawAll, 150);
  });
})();
