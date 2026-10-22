/* =====================================================================
   共享纯函数 —— 与 web/report.html 的 PURE_START..PURE_END 逐字一致

   只被 web/garmin.html 引用；report.html 保留自己的内联副本，两者必须保持一致。
   tests/test_garmin_page.py 会逐行比对这两段，出现分歧即测试失败（防漂移）。
   ===================================================================== */
/* PURE_START */
var STOP_MPS = 0.14;
var SPEED_STOPS = ['#3d7bd9', '#46b97a', '#d8cf4a', '#f0a33c', '#e2513c'];
var STOP_COLOR = '#9aa7b4';

function haversine(a, b) {
  var R = 6371000;
  var p1 = a.lat * Math.PI / 180, p2 = b.lat * Math.PI / 180;
  var dp = (b.lat - a.lat) * Math.PI / 180;
  var dl = (b.lng - a.lng) * Math.PI / 180;
  var h = Math.sin(dp / 2) * Math.sin(dp / 2) +
          Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) * Math.sin(dl / 2);
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

function percentile(sorted, p) {
  if (!sorted.length) return 0;
  var i = (sorted.length - 1) * p;
  var lo = Math.floor(i), hi = Math.ceil(i);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
}

// 按累计里程在相邻两点之间线性插值取点
function interpSample(cum, pts, dist) {
  var n = pts.length;
  if (dist <= 0) {
    return { lat: pts[0].lat, lng: pts[0].lng, ele: pts[0].ele, time: pts[0].time };
  }
  if (dist >= cum[n - 1]) {
    var last = pts[n - 1];
    return { lat: last.lat, lng: last.lng, ele: last.ele, time: last.time };
  }
  var lo = 0, hi = n - 1;
  while (hi - lo > 1) {
    var mid = (lo + hi) >> 1;
    if (cum[mid] <= dist) lo = mid; else hi = mid;
  }
  var span = cum[hi] - cum[lo];
  var f = span > 0 ? (dist - cum[lo]) / span : 0;
  var a = pts[lo], b = pts[hi];
  return {
    lat: a.lat + (b.lat - a.lat) * f,
    lng: a.lng + (b.lng - a.lng) * f,
    ele: (a.ele !== null && b.ele !== null) ? a.ele + (b.ele - a.ele) * f
         : (f < 0.5 ? a.ele : b.ele),
    time: (a.time !== null && b.time !== null) ? a.time + (b.time - a.time) * f
          : (f < 0.5 ? a.time : b.time)
  };
}

// 速度 → 颜色：档位之间线性插值，得到连续渐变（不再是 5 段跳变）。
// 返回 null 表示该点没有可用速度，调用方沿用上一个颜色。
function speedColor(value, domain) {
  if (value === null || value === undefined || !isFinite(value)) return null;
  if (value < STOP_MPS) return STOP_COLOR;
  if (!domain || !(domain.hi - domain.lo > 0.01)) return SPEED_STOPS[2];
  var t = (value - domain.lo) / (domain.hi - domain.lo);
  t = Math.max(0, Math.min(1, t));
  t = Math.round(t * 32) / 32;            // 细分 33 级：够平滑，又能合并同色段
  return gradientColor(t);
}

function gradientColor(t) {
  var last = SPEED_STOPS.length - 1;
  var f = Math.max(0, Math.min(1, t)) * last;
  var i = Math.min(last - 1, Math.floor(f));
  return mixHex(SPEED_STOPS[i], SPEED_STOPS[i + 1], f - i);
}

function hex2(n) {
  var s = Math.round(n).toString(16);
  return s.length < 2 ? '0' + s : s;
}

function mixHex(a, b, k) {
  var ar = parseInt(a.slice(1, 3), 16), ag = parseInt(a.slice(3, 5), 16);
  var ab = parseInt(a.slice(5, 7), 16);
  var br = parseInt(b.slice(1, 3), 16), bg = parseInt(b.slice(3, 5), 16);
  var bb = parseInt(b.slice(5, 7), 16);
  return '#' + hex2(ar + (br - ar) * k) + hex2(ag + (bg - ag) * k) +
         hex2(ab + (bb - ab) * k);
}

// 运动时间：按移动速度阈值累计（静止 = 总耗时 - 运动时间）
function movingSeconds(pts, cum) {
  var n = pts.length, sum = 0;
  for (var i = 1; i < n; i++) {
    var a = pts[i - 1], b = pts[i];
    if (a.time === null || a.time === undefined) continue;
    if (b.time === null || b.time === undefined) continue;
    var dt = (b.time - a.time) / 1000;
    if (dt <= 0) continue;
    if ((cum[i] - cum[i - 1]) / dt >= STOP_MPS) sum += dt;
  }
  return sum;
}

var SLOPE_PCT = 0.05;

// 坡度构成：±50m 窗口算坡度，>3% 爬升、<-3% 下降、其余平路
function slopeShares(pts, cum) {
  var n = pts.length, up = 0, flat = 0, down = 0, WIN = 50;
  var g1 = 0, g2 = 0;
  for (var i = 1; i < n; i++) {
    while (g1 < n - 1 && cum[i] - cum[g1] > WIN) g1++;
    if (g2 < i) g2 = i;
    while (g2 < n - 1 && cum[g2] - cum[i] < WIN) g2++;
    var e1 = pts[g1].ele, e2 = pts[g2].ele;
    var span = cum[g2] - cum[g1];
    if (e1 === null || e1 === undefined) continue;
    if (e2 === null || e2 === undefined) continue;
    if (span <= 0) continue;
    var grade = (e2 - e1) / span;
    var step = cum[i] - cum[i - 1];
    if (grade > SLOPE_PCT) up += step;
    else if (grade < -SLOPE_PCT) down += step;
    else flat += step;
  }
  var total = up + flat + down;
  return total > 0 ? { up: up, flat: flat, down: down, total: total } : null;
}

// 分段步长：从 1km 起按整数倍递增，保证总段数不超过 10
function pickSplitStep(totalM) {
  var steps = [1000, 2000, 3000, 5000, 10000, 15000, 20000, 25000, 50000];
  for (var i = 0; i < steps.length; i++) {
    if (Math.ceil(totalM / steps[i]) <= 10) return steps[i];
  }
  return steps[steps.length - 1];
}

// 分段：model 需要 points / cum / hasEle，可选 stepM（默认 1km）
function buildSplits(model) {
  var pts = model.points, cum = model.cum, n = pts.length;
  var step = model.stepM && model.stepM > 0 ? model.stepM : 1000;
  var total = cum[n - 1];
  if (!(total > 0.5)) return [];
  var starts = [];
  for (var d = 0; d < total - 0.5; d += step) starts.push(d);
  if (!starts.length) starts.push(0);

  var rows = [];
  var cursor = 0;
  for (var s = 0; s < starts.length; s++) {
    var a0 = starts[s];
    var a1 = Math.min(total, a0 + step);
    var pA = interpSample(cum, pts, a0);
    var pB = interpSample(cum, pts, a1);

    var gain = null, loss = null, hrSum = 0, hrCnt = 0, cadSum = 0, cadCnt = 0;
    if (model.hasEle) { gain = 0; loss = 0; }
    var prevEle = pA.ele;
    while (cursor < n && cum[cursor] <= a0) cursor++;
    for (var k = cursor; k < n && cum[k] <= a1; k++) {
      var e = pts[k].ele;
      if (e !== null && gain !== null) {
        if (prevEle !== null) {
          if (e > prevEle) gain += e - prevEle;
          else if (e < prevEle) loss += prevEle - e;
        }
        prevEle = e;
      }
      if (pts[k].hr !== null && pts[k].hr !== undefined) { hrSum += pts[k].hr; hrCnt++; }
      if (pts[k].cad !== null && pts[k].cad !== undefined) { cadSum += pts[k].cad; cadCnt++; }
    }
    if (gain !== null && pB.ele !== null && prevEle !== null) {
      if (pB.ele > prevEle) gain += pB.ele - prevEle;
      else if (pB.ele < prevEle) loss += prevEle - pB.ele;
    }

    var dist = a1 - a0;
    var sec = (pA.time !== null && pB.time !== null && pB.time > pA.time)
            ? (pB.time - pA.time) / 1000 : null;
    rows.push({
      idx: rows.length + 1,
      dist: dist / 1000,
      time: sec,
      pace: (sec !== null && sec > 0) ? sec / (dist / 1000) : null,
      speed: (sec !== null && sec > 0) ? dist / sec * 3.6 : null,
      gain: gain === null ? null : Math.round(gain),
      loss: loss === null ? null : Math.round(loss),
      hr: hrCnt ? hrSum / hrCnt : null,
      cad: cadCnt ? cadSum / cadCnt : null
    });
  }
  return rows;
}
/* PURE_END */