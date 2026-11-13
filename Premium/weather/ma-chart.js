(function () {
  var params = new URLSearchParams(location.search);
  var symbol = params.get("symbol");
  if (!symbol) return;
  var report = document.getElementById("report");
  var view = document.getElementById("ma-chart");
  var title = document.getElementById("ma-chart-title");
  if (report) report.hidden = true;
  if (view) view.hidden = false;
  var row = (window.MA_SERIES || {})[symbol];
  if (!row) {
    title.textContent = symbol;
    document.title = symbol;
    return;
  }
  title.textContent = row.label + " " + row.name + " · " + symbol;
  document.title = row.label + " " + row.name;

  function average(values, length, index) {
    var sum = 0;
    for (var i = index - length + 1; i <= index; i++) sum += values[i];
    return sum / length;
  }

  var closes = row.closes;
  var points = [];
  for (var i = 199; i < closes.length; i++) {
    points.push({
      c: closes[i],
      m50: average(closes, 50, i),
      m200: average(closes, 200, i)
    });
  }
  var canvas = document.getElementById("ma-canvas");
  var width = Math.min(1100, document.documentElement.clientWidth - 32);
  var height = 520;
  var dpr = window.devicePixelRatio || 1;
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  var ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = "#0c0c0c";
  ctx.fillRect(0, 0, width, height);

  var lo = Infinity;
  var hi = -Infinity;
  points.forEach(function (point) {
    lo = Math.min(lo, point.c, point.m50, point.m200);
    hi = Math.max(hi, point.c, point.m50, point.m200);
  });
  var pad = (hi - lo) * 0.08 || 1;
  lo -= pad;
  hi += pad;
  function xOf(index) {
    return 56 + (width - 72) * (index / Math.max(points.length - 1, 1));
  }
  function yOf(value) {
    return 20 + (height - 44) * (1 - (value - lo) / (hi - lo));
  }
  function stroke(key, color, lineWidth) {
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    points.forEach(function (point, index) {
      var x = xOf(index);
      var y = yOf(point[key]);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }
  stroke("m200", "#E53935", 2.5);
  stroke("m50", "#9C27B0", 2.5);
  stroke("c", "#bbbbbb", 1.25);

  ctx.fillStyle = "#888";
  ctx.font = "13px Arial";
  ctx.fillText(String(Math.round(hi)), 8, 24);
  ctx.fillText(String(Math.round(lo)), 8, height - 28);
})();
