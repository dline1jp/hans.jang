/* TLT · EDV vs TNX 주봉 20년 차트 (클릭 없이 바로 표시)
 * - window.BOND_SERIES: { asof, TLT:{dates,closes}, EDV:{...}, TNX:{...} }
 * - 메인 패널: ETF 주봉 종가 + 20/50/200주선, TNX는 오른쪽 축
 * - 아래 패널: RSI(14), MACD(12,26,9)
 * - TNX 20년 백분위로 TLT·EDV의 매수/매도 확률을 판정합니다.
 */
(function () {
  var C = {
    close: "#e6e6e6",
    ma20: "#7dcea0",
    ma50: "#d8c0ff",
    ma200: "#E53935",
    tnx: "#6cb6ff",
    rsi: "#dddddd",
    macd: "#ffd76a",
    signal: "#ff9b8a",
    grid: "#262626",
    sep: "#3a3a3a",
    axis: "#9a9a9a"
  };

  function average(values, length, index) {
    if (index + 1 < length) return null;
    var sum = 0;
    for (var i = index - length + 1; i <= index; i++) sum += values[i];
    return sum / length;
  }

  function ema(values, length) {
    var out = [];
    var k = 2 / (length + 1);
    var prev = null;
    for (var i = 0; i < values.length; i++) {
      prev = prev === null ? values[i] : values[i] * k + prev * (1 - k);
      out.push(prev);
    }
    return out;
  }

  function rsi(values, length) {
    var out = [];
    var gain = 0;
    var loss = 0;
    for (var i = 0; i < values.length; i++) {
      if (i === 0) {
        out.push(null);
        continue;
      }
      var diff = values[i] - values[i - 1];
      var up = diff > 0 ? diff : 0;
      var down = diff < 0 ? -diff : 0;
      if (i <= length) {
        gain += up;
        loss += down;
        if (i < length) {
          out.push(null);
          continue;
        }
        gain /= length;
        loss /= length;
      } else {
        gain = (gain * (length - 1) + up) / length;
        loss = (loss * (length - 1) + down) / length;
      }
      out.push(loss === 0 ? 100 : 100 - 100 / (1 + gain / loss));
    }
    return out;
  }

  function macd(values) {
    var fast = ema(values, 12);
    var slow = ema(values, 26);
    var line = [];
    var i;
    for (i = 0; i < values.length; i++) line.push(fast[i] - slow[i]);
    var signal = ema(line, 9);
    var hist = [];
    for (i = 0; i < line.length; i++) hist.push(line[i] - signal[i]);
    return { macd: line, signal: signal, hist: hist };
  }

  function dayOf(text) {
    return Date.parse(text + "T00:00:00Z");
  }

  function alignTo(etf, other) {
    var etfDays = etf.dates.map(dayOf);
    var otherDays = other.dates.map(dayOf);
    var out = [];
    var j = 0;
    for (var i = 0; i < etfDays.length; i++) {
      while (j + 1 < otherDays.length && Math.abs(otherDays[j + 1] - etfDays[i]) <= Math.abs(otherDays[j] - etfDays[i])) {
        j += 1;
      }
      out.push(other.closes[j]);
    }
    return out;
  }

  function percentile(values, value) {
    var count = 0;
    for (var i = 0; i < values.length; i++) if (values[i] <= value) count += 1;
    return values.length ? (count / values.length) * 100 : 0;
  }

  function percentileValue(values, percent) {
    var sorted = values.slice().sort(function (a, b) { return a - b; });
    var index = Math.round((percent / 100) * (sorted.length - 1));
    return sorted[Math.min(sorted.length - 1, Math.max(0, index))];
  }

  function lastNumber(values) {
    for (var i = values.length - 1; i >= 0; i--) {
      if (typeof values[i] === "number" && isFinite(values[i])) return values[i];
    }
    return null;
  }

  function num(value, digits) {
    if (typeof value !== "number" || !isFinite(value)) return "-";
    return Number(value).toFixed(typeof digits === "number" ? digits : 2);
  }

  function comma(value) {
    var text = num(value, 2);
    if (text === "-") return text;
    var parts = text.split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return parts.join(".");
  }

  function drawPair(canvas) {
    var key = canvas.getAttribute("data-symbol");
    var data = window.BOND_SERIES || {};
    var etf = data[key];
    var tnx = data.TNX;
    if (!etf || !tnx || !etf.closes || !etf.dates || etf.closes.length < 60) return;

    var closes = etf.closes;
    var dates = etf.dates;
    var n = closes.length;
    var tnxAt = alignTo(etf, tnx);
    var ma20 = [];
    var ma50 = [];
    var ma200 = [];
    var rsiLine = rsi(closes, 14);
    var rsiNow = lastNumber(rsiLine);
    var macdData = macd(closes);
    var i;

    for (i = 0; i < n; i++) {
      ma20.push(average(closes, 20, i));
      ma50.push(average(closes, 50, i));
      ma200.push(average(closes, 200, i));
    }

    var width = Math.max(320, Math.round(canvas.clientWidth || canvas.parentNode.clientWidth || 1100));
    var height = Math.max(380, Math.round(canvas.clientHeight || 560));
    var dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#0c0c0c";
    ctx.fillRect(0, 0, width, height);

    var padLeft = width < 640 ? 44 : 54;
    var padRight = width < 640 ? 52 : 62;
    var padTop = 14;
    var padBottom = 24;
    var plotW = width - padLeft - padRight;
    var innerH = height - padTop - padBottom;
    var gap = Math.max(14, Math.round(innerH * 0.03));
    var mainH = Math.round(innerH * 0.6);
    var restH = innerH - mainH - gap * 2;
    var rsiH = Math.round(restH * 0.5);
    var macdH = restH - rsiH;
    var mainTop = padTop;
    var rsiTop = mainTop + mainH + gap;
    var macdTop = rsiTop + rsiH + gap;

    var lo = Infinity;
    var hi = -Infinity;
    var sources = [closes, ma20, ma50, ma200];
    for (i = 0; i < n; i++) {
      for (var s = 0; s < sources.length; s++) {
        var drawPrice = sources[s][i];
        if (typeof drawPrice === "number" && isFinite(drawPrice)) {
          if (drawPrice < lo) lo = drawPrice;
          if (drawPrice > hi) hi = drawPrice;
        }
      }
    }
    if (!isFinite(lo) || !isFinite(hi)) return;
    var pricePad = (hi - lo) * 0.06 || 1;
    lo -= pricePad;
    hi += pricePad;

    var tLo = Infinity;
    var tHi = -Infinity;
    for (i = 0; i < tnxAt.length; i++) {
      var yieldValue = tnxAt[i];
      if (typeof yieldValue === "number" && isFinite(yieldValue)) {
        if (yieldValue < tLo) tLo = yieldValue;
        if (yieldValue > tHi) tHi = yieldValue;
      }
    }
    var yieldPad = (tHi - tLo) * 0.08 || 0.1;
    tLo -= yieldPad;
    tHi += yieldPad;

    function x(index) {
      return padLeft + (n <= 1 ? 0 : (index / (n - 1)) * plotW);
    }
    function yPrice(value) {
      return mainTop + mainH * (1 - (value - lo) / (hi - lo));
    }
    function yTnx(value) {
      return mainTop + mainH * (1 - (value - tLo) / (tHi - tLo));
    }

    function stroke(values, yOf, color, lineWidth, alpha) {
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = lineWidth;
      ctx.globalAlpha = typeof alpha === "number" ? alpha : 1;
      var started = false;
      for (var k = 0; k < values.length; k++) {
        var value = values[k];
        if (typeof value !== "number" || !isFinite(value)) {
          started = false;
          continue;
        }
        if (!started) {
          ctx.moveTo(x(k), yOf(value));
          started = true;
        } else {
          ctx.lineTo(x(k), yOf(value));
        }
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    ctx.font = "12px Arial";
    var g;
    for (g = 0; g <= 4; g++) {
      var gy = mainTop + (mainH * g) / 4;
      ctx.strokeStyle = C.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padLeft, gy);
      ctx.lineTo(width - padRight, gy);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.fillStyle = C.axis;
      ctx.fillText(num(hi - ((hi - lo) * g) / 4, 0), padLeft - 6, gy + 4);
      ctx.textAlign = "left";
      ctx.fillStyle = C.tnx;
      ctx.fillText(num(tHi - ((tHi - tLo) * g) / 4, 2) + "%", width - padRight + 6, gy + 4);
    }

    var lastYear = 0;
    for (i = 0; i < n; i++) {
      var year = new Date(dayOf(dates[i])).getUTCFullYear();
      if (year === lastYear) continue;
      lastYear = year;
      if (year % 5 !== 0) continue;
      var gx = x(i);
      ctx.strokeStyle = "#1f1f1f";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(gx, mainTop);
      ctx.lineTo(gx, macdTop + macdH);
      ctx.stroke();
      ctx.fillStyle = C.axis;
      ctx.textAlign = "center";
      ctx.fillText(String(year), gx, height - 8);
    }

    ctx.strokeStyle = C.sep;
    ctx.beginPath();
    ctx.moveTo(padLeft, mainTop + mainH);
    ctx.lineTo(width - padRight, mainTop + mainH);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(padLeft, rsiTop + rsiH);
    ctx.lineTo(width - padRight, rsiTop + rsiH);
    ctx.stroke();

    ctx.fillStyle = C.axis;
    ctx.textAlign = "left";
    ctx.fillText("RSI(14)" + (rsiNow === null ? "" : " " + num(rsiNow, 1)), padLeft, rsiTop - 5);
    ctx.fillText("MACD(12,26,9)", padLeft, macdTop - 5);

    stroke(tnxAt, yTnx, C.tnx, 1.1, 0.95);
    stroke(ma200, yPrice, C.ma200, 2.2);
    stroke(ma50, yPrice, C.ma50, 1.4);
    stroke(ma20, yPrice, C.ma20, 1.2);
    stroke(closes, yPrice, C.close, 1.3);

    function yRsi(value) {
      return rsiTop + rsiH * (1 - value / 100);
    }
    [70, 30].forEach(function (level) {
      var levelY = yRsi(level);
      ctx.strokeStyle = "#333";
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(padLeft, levelY);
      ctx.lineTo(width - padRight, levelY);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = C.axis;
      ctx.textAlign = "left";
      ctx.fillText(String(level), width - padRight + 6, levelY + 4);
    });
    stroke(rsiLine, yRsi, C.rsi, 1.1);

    var mValues = macdData.macd.concat(macdData.signal).concat(macdData.hist);
    var mLo = 0;
    var mHi = 0;
    for (i = 0; i < mValues.length; i++) {
      var mv = mValues[i];
      if (typeof mv === "number" && isFinite(mv)) {
        if (mv < mLo) mLo = mv;
        if (mv > mHi) mHi = mv;
      }
    }
    var mPad = (mHi - mLo) * 0.12 || 0.1;
    mLo -= mPad;
    mHi += mPad;
    function yMacd(value) {
      return macdTop + macdH * (1 - (value - mLo) / (mHi - mLo));
    }
    var zeroY = yMacd(0);
    ctx.strokeStyle = "#333";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padLeft, zeroY);
    ctx.lineTo(width - padRight, zeroY);
    ctx.stroke();
    var barW = Math.max(1, (plotW / n) * 0.7);
    for (i = 0; i < n; i++) {
      var histValue = macdData.hist[i];
      if (typeof histValue !== "number" || !isFinite(histValue)) continue;
      var histY = yMacd(histValue);
      ctx.fillStyle = histValue >= 0 ? "rgba(125,206,160,0.55)" : "rgba(229,57,53,0.55)";
      ctx.fillRect(x(i) - barW / 2, Math.min(zeroY, histY), barW, Math.max(1, Math.abs(histY - zeroY)));
    }
    stroke(macdData.macd, yMacd, C.macd, 1.2);
    stroke(macdData.signal, yMacd, C.signal, 1.1);
  }

  function renderJudge() {
    var data = window.BOND_SERIES || {};
    var tnx = data.TNX;
    if (!tnx || !tnx.closes || !tnx.closes.length) return;
    var closes = tnx.closes;
    var last = closes[closes.length - 1];
    var percent = percentile(closes, last);
    var p30 = percentileValue(closes, 30);
    var p70 = percentileValue(closes, 70);
    var min = Math.min.apply(null, closes);
    var max = Math.max.apply(null, closes);
    var asof = data.asof || (tnx.dates ? tnx.dates[tnx.dates.length - 1] : "");

    var cls;
    var band;
    var message;
    if (percent >= 70) {
      cls = "buy";
      band = "매수 확률 높음";
      message = "TNX 20년 백분위 " + Math.round(percent) + "%로 장기 고점 부근입니다. 금리가 고점에서 꺾이면 TLT·EDV 가격이 올라 매수 확률이 높아집니다. 금리 고점이 확인된 뒤 분할 매수를 검토합니다.";
    } else if (percent <= 30) {
      cls = "sell";
      band = "매도 확률 높음";
      message = "TNX 20년 백분위 " + Math.round(percent) + "%로 장기 저점 부근입니다. 금리가 저점에서 반등하면 TLT·EDV 가격이 내려 매도 확률이 높아집니다. 금리 저점이 확인된 뒤 분할 매도(이익 실현)를 검토합니다.";
    } else {
      cls = "wait";
      band = "중립";
      message = "TNX가 20년 범위의 중간 구간(백분위 " + Math.round(percent) + "%)이라 매수·매도 확률이 모두 낮습니다. 인플레이션·연준·유가 이벤트의 결과가 나오고 방향이 확인된 뒤 판단합니다.";
    }

    var meta = "TNX " + num(last, 2) + "% · 20년 백분위 " + Math.round(percent) + "% · 20년 범위 " + num(min, 2) + "%~" + num(max, 2) + "%";

    ["TLT", "EDV"].forEach(function (key) {
      var card = document.getElementById("judge-" + key);
      if (!card) return;
      card.className = "judge-card " + cls;
      var badge = card.querySelector(".badge");
      if (badge) badge.textContent = band;
      var etf = data[key];
      var metaEl = card.querySelector(".judge-meta");
      if (metaEl) {
        metaEl.textContent = (etf ? key + " " + comma(lastNumber(etf.closes)) + " · " : "") + meta;
      }
      var descEl = card.querySelector(".judge-desc");
      if (descEl) {
        descEl.textContent = message + (key === "EDV" ? " EDV는 듀레이션이 더 길어 TLT보다 금리 변화에 더 민감합니다." : "");
      }
      var chartMeta = document.getElementById("meta-" + key);
      if (chartMeta && etf) {
        chartMeta.textContent = "기준일 " + asof + " · " + key + " " + comma(lastNumber(etf.closes)) + " · TNX " + num(last, 2) + "% · 20년 백분위 " + Math.round(percent) + "%";
      }
    });

    var sellLine = document.getElementById("tnx-sell-line");
    if (sellLine) sellLine.textContent = num(p30, 2) + "%";
    var buyLine = document.getElementById("tnx-buy-line");
    if (buyLine) buyLine.textContent = num(p70, 2) + "%";
  }

  function drawAll() {
    var canvases = document.querySelectorAll("canvas.bond-canvas");
    for (var i = 0; i < canvases.length; i++) drawPair(canvases[i]);
  }

  function init() {
    renderJudge();
    drawAll();
    var timer = null;
    window.addEventListener("resize", function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(drawAll, 150);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();