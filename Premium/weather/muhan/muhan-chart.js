/* TQQQ 무한매수법(라오어 v2.2) 페이지 렌더러
 * - window.MUHAN_DATA 를 읽어 요약 카드, T 진행바, 주문 카드, 차트를 그립니다.
 * - 차트: TQQQ 종가 + 평단가 + 매수/매도 지정가 + 현재 사이클 체결 마커
 */
(function () {
  var C = {
    price: "#e6e6e6",
    avg: "#7dcea0",
    buy: "#6cb6ff",
    sell1: "#f5a623",
    sell2: "#ff6b6b",
    grid: "#262626",
    axis: "#9a9a9a",
    text: "#dddddd"
  };

  function num(value, digits) {
    if (typeof value !== "number" || !isFinite(value)) return "-";
    return Number(value).toFixed(typeof digits === "number" ? digits : 2);
  }

  function money(value) {
    if (typeof value !== "number" || !isFinite(value)) return "-";
    var text = Math.abs(value).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return (value < 0 ? "-$" : "$") + text;
  }

  function percent(value) {
    if (typeof value !== "number" || !isFinite(value)) return "-";
    return (value > 0 ? "+" : "") + value.toFixed(2) + "%";
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

  function renderHero(data) {
    var t = typeof data.T === "number" ? data.T : 0;
    var total = typeof data.total === "number" ? data.total : null;
    setText("hero-T", num(t, 1), "hero-value gold");
    setText("hero-phase", data.phase + " · 별% " + num(data.star, 1) + "%");
    setText("hero-avg", money(data.avg), "hero-value");
    setText("hero-shares", "보유 " + num(data.shares, 2) + "주 · 사이클 시작 " + (data.cycleStart || "-"));
    setText("hero-invested", money(data.invested), "hero-value");
    setText("hero-cash", "잔여 " + money(data.cashLeft) + " · 1회 매수금 " + money(data.unit));
    var cls = "hero-value " + (total >= 0 ? "good" : "bad");
    setText("hero-total", money(total), cls);
    setText(
      "hero-return",
      "수익률 " + percent(data.returnPct) + " · 실현 " + money(data.realized) + " / 평가 " + money(data.unrealized)
    );
  }

  function renderTbar(data) {
    var t = typeof data.T === "number" ? data.T : 0;
    var ratio = Math.max(0, Math.min(1, t / 40));
    var fill = document.getElementById("tbar-fill");
    var dot = document.getElementById("tbar-dot");
    if (fill) fill.style.width = ratio * 100 + "%";
    if (dot) dot.style.left = ratio * 100 + "%";
    setText(
      "tbar-text",
      "T " + num(t, 1) + " / 40 · " + data.phase + " · 별% " + num(data.star, 1) + "% · 투입 " + money(data.invested)
    );
    setText(
      "tbar-cycle",
      "사이클 " + data.cycleNo + " · 매수 " + data.buyCount + "회 / 매도 " + data.sellCount + "회"
    );
  }

  function renderOrders(data) {
    var host = document.getElementById("orders");
    if (!host) return;
    var orders = data.orders || [];
    if (!orders.length) {
      host.innerHTML = '<p class="error">주문 데이터가 없습니다.</p>';
      return;
    }
    var html = "";
    orders.forEach(function (order) {
      var qty;
      if (order.type === "buy") {
        qty = money(order.amount) + " (약 " + num(order.shares, 2) + "주)";
      } else {
        qty = num(order.shares, 2) + "주";
      }
      html +=
        '<div class="order ' + order.type + '">' +
          "<h3>" + escapeHtml(order.label) + "</h3>" +
          '<div class="price">' + money(order.price) + "</div>" +
          '<div class="qty">' + qty + "</div>" +
          '<div class="desc">' + escapeHtml(order.note) + "</div>" +
        "</div>";
    });
    host.innerHTML = html;

    var note = document.getElementById("orders-note");
    if (note) {
      var text =
        "기준일 " + data.asof + " 종가 " + money(data.lastClose) +
        " 기준 · 현재 T " + num(data.T, 1) + " (" + data.phase + ") · 매수 여력 " + money(data.cashLeft) +
        ". 아래는 다음 거래일에 걸 주문입니다.";
      if (data.cashLeft <= 0.01) {
        text += " 원금이 모두 투입되어 추가 매수는 없습니다.";
      }
      note.textContent = text;
    }
  }

  function cycleItem(label, value, cls) {
    return '<div class="cycle-item"><span>' + label + "</span><strong" +
      (cls ? ' style="color:' + cls + '"' : "") + ">" + value + "</strong></div>";
  }

  function renderCycle(data) {
    var host = document.getElementById("cycle");
    if (!host) return;
    var plColor = function (value) {
      return typeof value === "number" && value < 0 ? "#ff8a8a" : "#7dcea0";
    };
    host.innerHTML =
      cycleItem("사이클", data.cycleNo + "번") +
      cycleItem("사이클 시작", data.cycleStart || "-") +
      cycleItem("보유 수량", num(data.shares, 2) + "주") +
      cycleItem("평단 / 현재가", money(data.avg) + " / " + money(data.lastClose)) +
      cycleItem("투입 / 잔여", money(data.invested) + " / " + money(data.cashLeft)) +
      cycleItem("실현 손익", money(data.realized), plColor(data.realized)) +
      cycleItem("평가 손익", money(data.unrealized), plColor(data.unrealized)) +
      cycleItem("총 손익", money(data.total) + " (" + percent(data.returnPct) + ")", plColor(data.total)) +
      cycleItem("최고 T", num(data.maxT, 1) + " / 40") +
      cycleItem("매수 / 매도", data.buyCount + " / " + data.sellCount + "회") +
      cycleItem("평단 +10% 목표", money(data.targetPrice)) +
      cycleItem("1회 매수금", money(data.unit));
  }

  function drawChart() {
    var data = window.MUHAN_DATA || {};
    var canvas = document.getElementById("muhan-chart");
    if (!canvas) return;
    var chart = data.chart || {};
    var closes = chart.closes || [];
    var dates = chart.dates || [];
    var avg = chart.avg || [];
    var width = Math.max(320, Math.round(canvas.clientWidth || canvas.parentNode.clientWidth || 1100));
    var height = Math.max(300, Math.round(canvas.clientHeight || 480));
    var dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#0c0c0c";
    ctx.fillRect(0, 0, width, height);
    ctx.font = "12px Arial";

    if (closes.length < 2) {
      ctx.fillStyle = "#f1948a";
      ctx.textAlign = "center";
      ctx.fillText("차트 데이터가 없습니다.", width / 2, height / 2);
      return;
    }

    var padLeft = 56;
    var padRight = 74;
    var padTop = 18;
    var padBottom = 28;
    var plotW = width - padLeft - padRight;
    var plotH = height - padTop - padBottom;
    var n = closes.length;

    var levels = {};
    (data.orders || []).forEach(function (order) {
      var price = Number(order.price);
      if (!isFinite(price)) return;
      var key = price.toFixed(2);
      if (!levels[key]) levels[key] = { price: price, kinds: [] };
      if (order.type === "buy") levels[key].kinds.push("매수");
      else if (String(order.label).indexOf("1/4") >= 0) levels[key].kinds.push("1/4 매도");
      else levels[key].kinds.push("3/4 매도");
    });

    var values = [];
    var i;
    for (i = 0; i < n; i++) {
      if (isFinite(closes[i])) values.push(closes[i]);
      if (typeof avg[i] === "number" && isFinite(avg[i])) values.push(avg[i]);
    }
    Object.keys(levels).forEach(function (key) {
      values.push(levels[key].price);
    });
    if (!values.length) return;
    var lo = Math.min.apply(null, values);
    var hi = Math.max.apply(null, values);
    var pad = (hi - lo) * 0.08 || 1;
    lo -= pad;
    hi += pad;

    function x(index) {
      return padLeft + (index / (n - 1)) * plotW;
    }
    function y(value) {
      return padTop + plotH * (1 - (value - lo) / (hi - lo));
    }

    var g;
    for (g = 0; g <= 4; g++) {
      var gy = padTop + (plotH * g) / 4;
      ctx.strokeStyle = C.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padLeft, gy);
      ctx.lineTo(width - padRight, gy);
      ctx.stroke();
      var label = hi - ((hi - lo) * g) / 4;
      ctx.fillStyle = C.axis;
      ctx.textAlign = "right";
      ctx.fillText(label >= 100 ? label.toFixed(0) : label.toFixed(1), padLeft - 8, gy + 4);
    }

    var lastYear = "";
    for (i = 0; i < n; i++) {
      var year = String(dates[i] || "").slice(0, 4);
      if (!year || year === lastYear) continue;
      lastYear = year;
      var gx = x(i);
      ctx.strokeStyle = "#1f1f1f";
      ctx.beginPath();
      ctx.moveTo(gx, padTop);
      ctx.lineTo(gx, padTop + plotH);
      ctx.stroke();
      ctx.fillStyle = C.axis;
      ctx.textAlign = "center";
      ctx.fillText(year, gx, height - 8);
    }

    ctx.beginPath();
    ctx.strokeStyle = C.avg;
    ctx.lineWidth = 2;
    var started = false;
    for (i = 0; i < n; i++) {
      var avgValue = avg[i];
      if (typeof avgValue !== "number" || !isFinite(avgValue)) {
        started = false;
        continue;
      }
      if (!started) {
        ctx.moveTo(x(i), y(avgValue));
        started = true;
      } else {
        ctx.lineTo(x(i), y(avgValue));
      }
    }
    ctx.stroke();

    var levelKeys = Object.keys(levels).sort(function (a, b) {
      return levels[a].price - levels[b].price;
    });
    var labelY = -100;
    levelKeys.forEach(function (key) {
      var level = levels[key];
      var ly = y(level.price);
      var color = C.buy;
      if (level.kinds.indexOf("3/4 매도") >= 0) color = C.sell2;
      else if (level.kinds.indexOf("1/4 매도") >= 0) color = C.sell1;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.2;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(padLeft, ly);
      ctx.lineTo(width - padRight, ly);
      ctx.stroke();
      ctx.setLineDash([]);
      var levelText = level.kinds.join("·") + " " + money(level.price);
      if (Math.abs(ly - labelY) < 14) ly = labelY + 14;
      labelY = ly;
      var textWidth = ctx.measureText(levelText).width;
      ctx.fillStyle = "#0c0c0c";
      ctx.fillRect(width - padRight - textWidth - 12, ly - 15, textWidth + 10, 15);
      ctx.fillStyle = color;
      ctx.textAlign = "right";
      ctx.fillText(levelText, width - padRight - 4, ly - 4);
      level.color = color;
      level.text = levelText;
      level.labelY = ly;
    });

    ctx.beginPath();
    ctx.strokeStyle = C.price;
    ctx.lineWidth = 1.3;
    for (i = 0; i < n; i++) {
      if (i === 0) ctx.moveTo(x(i), y(closes[i]));
      else ctx.lineTo(x(i), y(closes[i]));
    }
    ctx.stroke();

    var lastX = x(n - 1);
    var lastY = y(closes[n - 1]);
    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#ffffff";
    ctx.fill();
    ctx.fillStyle = "#0c0c0c";
    ctx.fillRect(width - padRight + 4, lastY - 10, padRight - 8, 20);
    ctx.fillStyle = C.price;
    ctx.textAlign = "left";
    ctx.fillText(money(closes[n - 1]), width - padRight + 8, lastY + 4);

    var dateIndex = {};
    for (i = 0; i < n; i++) dateIndex[dates[i]] = i;
    (data.trades || []).forEach(function (trade) {
      var index = dateIndex[trade.date];
      if (index === undefined) return;
      var px = x(index);
      var py = y(trade.price);
      ctx.beginPath();
      if (trade.type === "buy") {
        ctx.moveTo(px, py - 8);
        ctx.lineTo(px - 5, py + 1);
        ctx.lineTo(px + 5, py + 1);
        ctx.fillStyle = "rgba(125,206,160,0.95)";
      } else {
        ctx.moveTo(px, py + 8);
        ctx.lineTo(px - 5, py - 1);
        ctx.lineTo(px + 5, py - 1);
        ctx.fillStyle = "rgba(255,107,107,0.95)";
      }
      ctx.closePath();
      ctx.fill();
    });

    if (data.cycleStart && dateIndex[data.cycleStart] !== undefined) {
      var csx = x(dateIndex[data.cycleStart]);
      ctx.strokeStyle = "rgba(255,215,106,0.45)";
      ctx.setLineDash([3, 5]);
      ctx.beginPath();
      ctx.moveTo(csx, padTop);
      ctx.lineTo(csx, padTop + plotH);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // 라벨은 마커/가격선 위에 다시 그려 가독성을 유지합니다.
    levelKeys.forEach(function (key) {
      var level = levels[key];
      var labelWidth = ctx.measureText(level.text).width;
      ctx.fillStyle = "#0c0c0c";
      ctx.fillRect(width - padRight - labelWidth - 12, level.labelY - 15, labelWidth + 10, 15);
      ctx.fillStyle = level.color;
      ctx.textAlign = "right";
      ctx.fillText(level.text, width - padRight - 4, level.labelY - 4);
    });
  }

  function renderToday(data) {
    var trade = data.trade || {};
    var box = document.getElementById("today");
    if (box) box.className = "today " + (trade.actionCls || "hold");

    var buyChip = document.getElementById("today-buy");
    if (buyChip) {
      buyChip.textContent = trade.buyNow ? "오늘 매수 ✅" : "오늘 매수 ✖";
      buyChip.className = "trade-chip " + (trade.buyNow ? "on-buy" : "off");
    }
    var sellChip = document.getElementById("today-sell");
    if (sellChip) {
      sellChip.textContent = trade.sellNow ? "오늘 매도 ✅" : "오늘 매도 ✖";
      sellChip.className = "trade-chip " + (trade.sellNow ? "on-sell" : "off");
    }
    var actChip = document.getElementById("today-action");
    if (actChip) {
      var cls = trade.actionCls === "sell" || trade.actionCls === "both" ? "on-sell"
        : trade.actionCls === "buy" ? "on-buy" : "off";
      actChip.textContent = "→ " + (trade.action || "-");
      actChip.className = "trade-chip " + cls;
    }

    var line = document.getElementById("today-line");
    if (line) {
      var parts = [];
      if (trade.actionText) parts.push(escapeHtml(trade.actionText));
      parts.push(
        "현재가 " + money(trade.lastClose) + " · 평단 " + money(trade.avg) +
        " · 매수 지정가 " + money(trade.buyLimit) + " 이하 · 매도 지정가 " + money(trade.sellLimit) + " 이상"
      );
      if (typeof trade.toTargetPct === "number") {
        parts.push(
          "지정가 매도(" + money(trade.targetPrice) + ")까지 " +
          (trade.toTargetPct > 0 ? "+" : "") + trade.toTargetPct + "%"
        );
      }
      line.innerHTML = parts.join(" ");
    }
  }

  function renderAll() {
    var data = window.MUHAN_DATA || {};
    if (!data || !data.asof) {
      setText("orders-note", "데이터를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.");
      return;
    }
    renderToday(data);
    renderHero(data);
    renderTbar(data);
    renderOrders(data);
    renderCycle(data);
    drawChart();
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