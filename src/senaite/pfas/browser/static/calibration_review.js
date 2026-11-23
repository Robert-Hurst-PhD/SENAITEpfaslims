/* The calibration curve cards, shared by the Calibrations archive and Data
   Review's Calibration tab. The page sets:
     CAL_RUNS      the runs (calibrations view, calibration_runs_json)
     CAL_URL       where fit overrides are saved (@@pfas-calibrations)
     IS_MGR        whether the fit controls are shown
     CAL_APPROVE   null (archive, read-only) or {url, can, state}: the
                   approve / reject bar posting to Data Review
     limFor(uid)   the analyte's limits (page script) */
// charts draw in the page's face, not Chart.js's Helvetica default
if (window.Chart) Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  /* Curve maths: static/calibration_fit.js (least squares by ml-matrix QR,
     closed-form inverse, R² with the fit's own weights;.
     computeFn returns a callable curve carrying its model, so the plotting
     code below draws it as before. */
  function computeFn(pts, fitType, wtype, origin) {
    var m = PFASCalFit.fit(pts, {type: fitType, weight: wtype, origin: origin});
    if (!m) return null;
    var f = function (x) { return m.f(x); };
    f.model = m;
    return f;
  }

  function computeR2(pts, fn) {
    return fn ? PFASCalFit.r2(pts, fn.model) : null;
  }

  /* an R² is a plain number; coral only when it is judged and fails, "—"
     when there is none (the list, the card head and its live update) */
  function r2Class(r2, failed) {
    if (r2 == null) return 'r2-na';
    return failed ? 'r2-badge r2-fail' : 'r2-num';
  }
  /* a run's R² count: how many pass, and how many the method does not
     judge (an unjudged curve is not a failure) */
  function r2Count(run) {
    var n = run.analytes.length;
    var np = run.analytes.filter(function(a){ return a.r2_ok; }).length;
    var nu = run.analytes.filter(function(a){ return a.r2_ok == null; }).length;
    var nr = run.analytes.filter(function(a){ return a.rule_fail; }).length;
    var rule = nr ? '; '+nr+' fail'+(nr === 1 ? 's' : '')+' on calibrators dropped by hand' : '';
    if (nu === n && !nr) return 'R\u00B2 not judged';
    return np+' of '+n+' pass R\u00B2'+(nu ? '; '+nu+' unjudged' : '')+rule;
  }
  /* the curve's own rule: the worker's sentence, and the calibrators taken
     off by hand with the reason each was */
  function ruleHTML(cal) {
    if (!cal.rule_fail) return '';
    return '<div class="card-rule" role="alert"><p>'+esc(cal.rule_fail)+'</p>'
      +((cal.dropped||[]).length
        ? '<ul class="card-dropped">'+cal.dropped.map(function(d){
            return '<li>'+(d.level != null ? 'Level '+esc(d.level)+', ' : '')+esc(d.injection)+': '+esc(d.reason)+'</li>';
          }).join('')+'</ul>'
        : '')
      +'</div>';
  }
  /* a failing point is a triangle as well as coral */
  function passMark(passed) { return passed ? 'circle' : 'triangle'; }

  function backCalc(fn, y) {
    if (!fn || y == null) return null;
    var x = fn.model.inverse(y);
    return (x != null && x >= 0) ? x : null;
  }

  // ── Chart colours — derived from site CSS tokens so they track the theme ───
  var _css = getComputedStyle(document.documentElement);
  function _tok(n){ return (_css.getPropertyValue(n)||'').trim(); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function _rgba(cssVar, a){
    var h = _tok(cssVar).replace('#','');
    if (!h||h.length<6) return 'rgba(128,128,128,'+a+')';
    return 'rgba('+parseInt(h.substr(0,2),16)+','+parseInt(h.substr(2,2),16)+','+parseInt(h.substr(4,2),16)+','+a+')';
  }
  var cOK   = _rgba('--s-success',   0.85);
  var cFail = _rgba('--s-danger',    0.85);
  var cLine = _rgba('--s-primary',   0.85);
  var cIdeal= _rgba('--s-secondary', 0.40);

  // ── Chart registry ────────────────────────────────────────────────────────
  var _ch = {};
  function destroyCard(uid) {
    ['c1','c2','c3'].forEach(function(k){
      var key=uid+k; if(_ch[key]){_ch[key].destroy();delete _ch[key];}
    });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function _fmtCoeff(v, first) {
    var s = v.toExponential(4);
    if (first) return s;
    return v < 0 ? ' − '+Math.abs(v).toExponential(4) : ' + '+s;
  }
  function formatEquation(fn, fitType) {
    if (!fn) return '';
    var ft = (fitType||'').toLowerCase().replace(/\s/g,'');
    if (ft==='averagerf'||ft==='avg_rf') {
      return 'y = '+fn(1).toExponential(4)+' × x  (Avg RF)';
    }
    var co = fn.model.coef;
    if (ft==='quadratic') {
      return 'y = '+co.c2.toExponential(3)+'x\u00B2'+_fmtCoeff(co.c1,false)+'x'+_fmtCoeff(co.c0,false);
    }
    var slope = co.c1, intercept = co.c0;
    return 'y = '+slope.toExponential(4)+'x'+_fmtCoeff(intercept,false);
  }

  /* The fitted curve as the shared equation draws it, the inline size
     (pfas-components.js, PFAS.equation): the response from the
     concentration, then the concentration read back, each coefficient in
     its colour and named under the line. Without the component, the line's
     plain text. Always shown, to the right of the curve's title. */
  function eqCoef(v) {
    var a = Math.abs(v);
    if (a !== 0 && (a >= 1e6 || a < 1e-3)) return a.toExponential(3);
    var s = String(Number(a.toPrecision(5))), parts = s.split('.');
    if (a >= 10000) parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, '\u2009');
    return parts.join('.');
  }
  function curveEquation(fn, fitType, useResp) {
    var E = window.PFAS && window.PFAS.equation;
    if (!E) return calEsc('Fit: ' + formatEquation(fn, fitType));
    var ft = (fitType||'').toLowerCase().replace(/\s/g,''), y = useResp ? 'RR' : 'y', f, t;
    if (ft === 'averagerf' || ft === 'avg_rf') {
      var rf = eqCoef(fn(1));
      t = [{symbol: rf, label: 'mean response factor'}];
      f = [y + ' = ' + rf + ' \u00d7 C', 'C = ' + y + ' \u00f7 ' + rf];
    } else if (ft === 'quadratic') {
      var q = fn.model.coef, a = eqCoef(q.c2), b = eqCoef(q.c1), c = eqCoef(q.c0);
      t = [{symbol: a, label: 'a'}, {symbol: b, label: 'b'}, {symbol: c, label: 'c'}];
      f = [y + ' = ' + (q.c2 < 0 ? '\u2212' : '') + a + ' \u00d7 C\u00b2 ' + (q.c1 < 0 ? '\u2212 ' : '+ ') + b +
           ' \u00d7 C ' + (q.c0 < 0 ? '\u2212 ' : '+ ') + c];
    } else {
      var co = fn.model.coef, m = eqCoef(co.c1), k = eqCoef(co.c0), neg = co.c0 < 0;
      t = [{symbol: m, label: 'slope'}, {symbol: k, label: 'intercept'}];
      f = [y + ' = ' + (co.c1 < 0 ? '\u2212' : '') + m + ' \u00d7 C ' + (neg ? '\u2212 ' : '+ ') + k,
           'C = (' + y + (neg ? ' + ' : ' \u2212 ') + k + ') \u00f7 ' + (co.c1 < 0 ? '\u2212' : '') + m];
    }
    return E.lines(f, t) + E.key(t, 'from this fit');
  }

  // a concentration with the method's calibration unit (ppt: in the sample;
  // or in the extract), as the method profile states it
  function conc(cal, v) {
    var u = (cal && cal.level_unit) || '';
    return v + (u ? ' ' + u : '');
  }

  /* A point's readout and the curve's calculation open in the shared centred
     dialog (R5-82, R5-85): a calibrator against the fit drawn on this card
     (calibration_fit.js readout), the calibrator's own record (its imported
     line) when the page can open records, and "Open the calculation". */
  /* a pass or a fail as the drawn mark (icons.py through PFAS.components.icon):
   a tick, or the failure diamond; its words are its name. Without the page's
   icon drawings, the words alone. */
function calMark(ok, words) {
  var I = window.PFAS && window.PFAS.components && window.PFAS.components.icon;
  var s = I ? I.svg(ok ? 'pass' : 'fail', {label: words}) : '';
  return s || calEsc(words);
}
function calEsc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }
  function calNum(v, d) { return v == null || !isFinite(v) ? '—' : (Math.abs(v) >= 1000 || (Math.abs(v) < 0.01 && v !== 0) ? v.toExponential(3) : v.toFixed(d == null ? 3 : d)); }
  function calDialog(title, html, foot) {
    var d = window.PFAS && window.PFAS.components && window.PFAS.components.drawer;
    if (!d) return;
    d.open(title, html, { cls: "is-dialog", footer: foot || null });
  }
  function calRows(rows) {
    return '<table class="pfas-table cal-readout"><tbody>' + rows.map(function (r) {
      return '<tr><th scope="row">' + calEsc(r[0]) + '</th><td>' + r[1] + '</td></tr>';
    }).join('') + '</tbody></table>';
  }
  function showPointDetail(cal, point, ptType) {
    var title = (ptType === 'CAL' ? 'Calibration point' : (point.qc_type || 'QC')) + ' — ' + cal.analyte;
    if (ptType !== 'CAL') {
      calDialog(title, calRows([
        ['Expected', calEsc(conc(cal, point.expected_value != null ? point.expected_value : '?'))],
        ['Measured', calEsc(conc(cal, point.value != null ? parseFloat(point.value).toFixed(3) : '?'))],
        ['Response ratio', calEsc(point.response_ratio != null ? point.response_ratio.toExponential(4) : 'not recorded')],
        ['Deviation', calEsc(point.pct_dev != null ? (point.pct_dev > 0 ? '+' : '') + point.pct_dev.toFixed(2) + ' %' : '—')],
        ['Result', calMark(point.passed, point.passed ? 'Pass' : 'Fail') + ' ' + (point.passed ? 'Pass' : 'Fail')],
        ['Run', calEsc((cal.run_date || '') + (cal.batch_id ? ' · ' + cal.batch_id : ''))]]));
      return;
    }
    var m = cal._fn ? cal._fn.model : null, win = calWindow(cal._uid, point);
    var y = cal._useResp ? point.response_ratio : point.calculated;
    var r = PFASCalFit.readout(m, {x: point.expected, y: y}, win ? win.hi : null);
    var src = (point.prov_key && window.PFAS && window.PFAS.provenance)
      ? ' <button type="button" class="btn-sm btn-secondary" data-prov="' + calEsc(point.prov_key) + '">Open the record</button>' : '';
    var rows = [
      ['x, expected (L' + (point.level || '?') + ')', calEsc(conc(cal, point.expected))],
      ['y, ' + (cal._useResp ? 'response ratio' : 'calculated'), calEsc(calNum(y, 4)) + src],
      ['The fit at x', calEsc(calNum(r.fit_y, 4))],
      ['Read back off the fit from y', calEsc(conc(cal, calNum(r.back)))],
      ['Deviation from the fit', calEsc(r.dev == null ? '—' : (r.dev > 0 ? '+' : '') + r.dev.toFixed(1) + ' %') +
        (win ? ' against ±' + calEsc(win.hi) + ' % ' + calMark(r.within, r.within ? 'Within the window' : 'Outside the window') : ' (no window set)')]];
    if (cal._useResp && point.calculated != null) {
      rows.push(['The instrument read back', calEsc(conc(cal, point.calculated.toFixed(3))) +
        (point.pct_deviation != null ? ' (' + (point.pct_deviation > 0 ? '+' : '') + point.pct_deviation.toFixed(1) + ' %)' : '')]);
    }
    var foot = document.createElement('div');
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'btn-sm btn-secondary'; b.textContent = 'Open the calculation';
    b.addEventListener('click', function () { showCalculation(cal); });
    foot.appendChild(b);
    calDialog(title, calRows(rows), foot);
  }
  /* The curve's calculation: its equation, fit, weighting, origin and
     R² as this card draws them, and every calibrator read the same way. */
  function showCalculation(cal) {
    var m = cal._fn ? cal._fn.model : null;
    if (!m) return;
    var pts = (cal._pts || []).map(function (p) { return {x: p.x, y: p.y}; });
    var c = PFASCalFit.calculation(pts, m);
    var h = calRows([
      ['Equation', calEsc(formatEquation(cal._fn, cal._ft))],
      ['Fit', calEsc(cal._ft || '')],
      ['Weighting', calEsc(cal._wt || 'unweighted')],
      ['Origin', calEsc(cal._ori || 'exclude')],
      ['R², with the fit’s own weights', calEsc(c.r2 == null ? '—' : c.r2.toFixed(5))],
      ['The instrument’s R²', calEsc(cal.r2 != null ? cal.r2.toFixed(5) : 'not reported')]]);
    h += '<table class="pfas-table cal-readout" data-col-resize="cal-levels"><thead><tr><th>Level</th><th>x</th><th>y</th><th>Fit at x</th>' +
         '<th>Read back</th><th>Deviation</th></tr></thead><tbody>';
    c.points.forEach(function (r, i) {
      var lv = (cal._pts[i] || {})._lv || {};
      h += '<tr><td>L' + calEsc(lv.level || i + 1) + '</td><td>' + calEsc(calNum(r.x)) + '</td><td>' + calEsc(calNum(r.y, 4)) +
           '</td><td>' + calEsc(calNum(r.fit_y, 4)) + '</td><td>' + calEsc(calNum(r.back)) + '</td><td>' +
           calEsc(r.dev == null ? '—' : (r.dev > 0 ? '+' : '') + r.dev.toFixed(1) + ' %') + '</td></tr>';
    });
    calDialog('The calculation — ' + cal.analyte, h + '</tbody></table>');
  }

  // ── Judged windows ──────────────────────────────────────────────────────
  /* Each point is drawn against the window the worker judged it by: stored
     per calibrator (limit_pct, ±%) and per ICV / CCV (limit_low / limit_high,
     recovery %). A run stored before the windows were recorded falls back to
     the method profile's keys, read by the same rules (calibrations.py
     method_limits). No window: nothing is drawn -- never a default. */
  function calWindow(uid, lv) {
    var lim = lv.limit_pct;
    if (lim == null) {
      var L = limFor(uid).CAL || {};
      lim = (String(lv.level) === '1' && L.low_max != null) ? L.low_max : L.max;
    }
    return lim == null ? null : {lo: -lim, hi: lim};
  }
  function qcWindow(uid, r) {
    if (r.limit_low != null && r.limit_high != null)
      return {lo: r.limit_low - 100, hi: r.limit_high - 100};
    var L = limFor(uid), C = L.CCV || {}, I = L.ICV || {};
    var ccv = (C.min != null && C.max != null) ? {lo: C.min - 100, hi: C.max - 100} : null;
    if (r.qc_type === 'ICV') {
      if (I.same_as_ccv) return ccv;
      return I.max == null ? null : {lo: -I.max, hi: I.max};
    }
    return ccv;
  }
  /* one pass band per point (its own window) on a category axis */
  function windowBoxes(wins) {
    var out = {};
    wins.forEach(function (w, i) {
      if (!w) return;
      out['w' + i] = {type: 'box', drawTime: 'beforeDatasetsDraw', borderWidth: 1,
                      borderColor: _rgba('--s-success', 0.45),
                      backgroundColor: _rgba('--s-success', 0.10),
                      xMin: i - 0.32, xMax: i + 0.32, yMin: w.lo, yMax: w.hi};
    });
    return out;
  }
  function devRange(devs, wins) {
    var m = 1;
    devs.forEach(function (v) { if (v != null) m = Math.max(m, Math.abs(v) * 1.25); });
    wins.forEach(function (w) { if (w) m = Math.max(m, Math.abs(w.lo) * 1.15, Math.abs(w.hi) * 1.15); });
    return Math.ceil(m / 10) * 10;     // a round axis end
  }
  /* Where a curve's Fit, Weighting and Origin start: the curve's own change,
     else the method profile (QC criteria, Calibration), else what the run's
     row records, else Linear. "none" stores a per-curve None; "" in the
     select is None. */
  function startFit(cal) {
    return cal.fit_type_override || cal.profile_fit || cal.fit_type || 'Linear';
  }
  function startWt(cal) {
    if (cal.weight_override) return cal.weight_override === 'none' ? '' : cal.weight_override;
    if (cal.profile_weight != null) return cal.profile_weight;
    return cal.weight_type || '';
  }
  /* an Average RF passes through the origin by definition: its origin is
     Force, and cannot be changed */
  var AVG_RF = 'Average RF', AVG_RF_ORIGIN = 'An average RF passes through the origin';
  function startOri(cal) {
    if (startFit(cal) === AVG_RF) return 'force';
    return cal.origin_override || cal.profile_origin || 'exclude';
  }
  function markChanged(uid, cal, wt, ori, ft) {
    var el = document.getElementById(uid + '_chg');
    if (!el) return;
    var pw = cal.profile_weight != null ? cal.profile_weight : (cal.weight_type || '');
    var pf = cal.profile_fit || cal.fit_type || 'Linear';
    // the origin is not compared for an Average RF: it has only Force
    var sameOri = ft === AVG_RF || ori === (cal.profile_origin || 'exclude');
    el.hidden = (wt === pw) && sameOri && (ft === pf);
  }
  /* the Origin list for a fit: Force and unavailable for an Average RF */
  function lockOrigin(uid, cal, ft) {
    var oriEl = document.getElementById(uid + '_ori');
    if (!oriEl) return;
    var avg = ft === AVG_RF;
    if (avg) oriEl.value = 'force';
    // leaving an Average RF, the curve's own origin comes back
    else if (oriEl.disabled) oriEl.value = cal.origin_override || cal.profile_origin || 'exclude';
    oriEl.disabled = avg;
    oriEl.title = avg ? AVG_RF_ORIGIN : '';
  }
  function refusedText(analyte) {
    return 'The quadratic for ' + analyte + ' turns within its calibration range. '
      + 'Choose Linear, or narrow the range at its ends.';
  }
  function relog(uid) {
    var cal = CAL_BY_UID[uid];
    if (!cal) return;
    cal._log = !!(document.getElementById(uid + '_log') || {}).checked;
    drawPlot1(uid, cal, cal._ft || startFit(cal),
              cal._wt != null ? cal._wt : startWt(cal),
              cal._ori || startOri(cal));
  }
  window.relog = relog;

  // ── Plot 1: the calibrators and the fitted curve ──────────────────────────
  function drawPlot1(uid, cal, fitType, wtype, origin) {
    var canvas = document.getElementById(uid+'_p1');
    if (!canvas) return;
    cal._ft = fitType; cal._wt = wtype; cal._ori = origin;
    var lvs = cal.levels || [];
    var useResp = lvs.some(function(l){ return l.response_ratio != null; });
    var pts = lvs.filter(function(l){
      return l.expected != null && (useResp ? l.response_ratio != null : l.calculated != null);
    }).map(function(l){
      return {x:l.expected, y:useResp?l.response_ratio:l.calculated, passed:l.passed, _lv:l};
    });
    if (pts.length === 0) {
      canvas.parentNode.classList.add('is-empty'); canvas.parentNode.innerHTML = '<div class="plot-empty">No calibration level data</div>';
      return;
    }
    var xy = pts.map(function(p){return{x:p.x,y:p.y};});
    var fn = computeFn(xy, fitType, wtype, origin);
    /* a quadratic that turns within its calibration range is not drawn:
       the card says so, as the worker refuses the run */
    var refused = document.getElementById(uid+'_refused');
    var why = fn ? null : PFASCalFit.refusal(xy, {type: fitType, weight: wtype, origin: origin});
    if (refused) {
      refused.hidden = !why;
      refused.textContent = why ? refusedText(cal.analyte) : '';
    }
    if (!fn) {
      if (_ch[uid+'c1']) { _ch[uid+'c1'].destroy(); delete _ch[uid+'c1']; }
      cal._fn = null;
      return;
    }
    // what the point readout and the calculation read (showPointDetail, showCalculation)
    cal._uid = uid; cal._fn = fn; cal._useResp = useResp; cal._pts = pts;
    var r2c = computeR2(xy, fn);
    var r2el = document.getElementById(uid+'_r2');
    if (r2el && r2c !== null) {
      r2el.textContent = 'R² ' + r2c.toFixed(4);
      var r2min = limFor(uid).r2;
      r2el.className = r2Class(r2c, r2min != null && r2c < r2min);
    }
    /* the curve's title line: the analyte, the fit and its R² (the fit's
       description lives here, not in the legend) */
    var titleEl = document.getElementById(uid+'_p1t');
    if (titleEl) titleEl.textContent = cal.analyte + ' \u00B7 ' + fitType + ', '
      + (wtype ? wtype.replace('x2', 'x\u00B2') : 'unweighted')
      + ' \u00B7 R\u00B2 ' + (r2c !== null ? r2c.toFixed(4) : '\u2014');
    var eqEl = document.getElementById(uid+'_eq');
    var keyEl = document.getElementById(uid+'_eqkey');
    if (eqEl) {
      eqEl.innerHTML = curveEquation(fn, fitType, useResp);
      /* the colour key (slope, intercept: what each coloured value is) moves
         out of the equation to the title row's top right */
      var kn = eqEl.querySelector('.pv-formula-key');
      if (keyEl) { keyEl.innerHTML = ''; if (kn) keyEl.appendChild(kn); }
    }
    // the R² and the equation open the calculation behind them
    [r2el, eqEl].forEach(function (el) {
      if (!el || el.__calc) return;
      el.__calc = true;
      el.setAttribute('role', 'button'); el.setAttribute('tabindex', '0');
      el.addEventListener('click', function () { showCalculation(cal); });
      el.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); showCalculation(cal); } });
    });

    var log = !!cal._log;
    var xs = pts.map(function(p){return p.x;}).filter(function(x){return x > 0;});
    var xmax = Math.max.apply(null, pts.map(function(p){return p.x;}));
    var xmin = xs.length ? Math.min.apply(null, xs) : xmax / 100;
    // the fit, sampled smoothly across the calibrated range (geometric on a
    // log axis, so the low levels get as many samples as the high ones)
    var linePts = [], n = 80, lo = log ? xmin / 1.5 : 0, hi = xmax * 1.04;
    for (var i = 0; i <= n; i++) {
      var xv = log ? lo * Math.pow(hi / lo, i / n) : lo + (hi - lo) * i / n;
      var yv = fn(xv);
      if (yv != null && isFinite(yv) && (!log || yv > 0)) linePts.push({x: xv, y: yv});
    }
    var datasets = [
      {label:'Calibrators', data:xy, type:'scatter', order:1,
       pointStyle:pts.map(function(p){ return passMark(p.passed); }), pointRadius:3, pointHoverRadius:5,
       pointBackgroundColor:pts.map(function(p){ return p.passed ? cOK : cFail; }),
       pointBorderColor:pts.map(function(p){ return p.passed ? _rgba('--s-success',1) : _rgba('--s-danger',1); }),
       pointBorderWidth:1},
      {label:'Fitted curve', isFit:true, data:linePts, type:'line', order:2, borderColor:cLine, borderWidth:1.5,
       borderDash:[6,4], pointRadius:0, pointStyle:'line', tension:0, fill:false}
    ];
    if (!useResp) datasets.push(
      {label:'y = x', data:[{x:log?lo:0,y:log?lo:0},{x:hi,y:hi}], type:'line', order:3,
       borderColor:cIdeal, borderWidth:1, borderDash:[2,3], pointRadius:0, pointStyle:'line', fill:false});

    var _lvs = pts.map(function(p){return p._lv;}), _cal = cal, key = uid+'c1';
    var yLabel = useResp ? 'Response ratio (analyte / IS area)' : 'Calculated (' + (cal.level_unit || '') + ')';
    if (_ch[key]) _ch[key].destroy();
    _ch[key] = new Chart(canvas, {
      type:'scatter',
      data:{datasets:datasets},
      options:{
        responsive:true, maintainAspectRatio:false, animation:false,
        onClick: function(evt, elems) {
          if (elems && elems.length > 0 && elems[0].datasetIndex===0)
            showPointDetail(_cal, _lvs[elems[0].index], 'CAL');
        },
        plugins:{
          /* the legend keeps the calibrators and y = x; the fit is named
             in the title line */
          legend:{display:true, position:'top',
                  labels:{boxWidth:18, font:{size:10}, usePointStyle:true,
                          filter:function(item, data){ return !data.datasets[item.datasetIndex].isFit; },
                          generateLabels:function(chart){
                            return Chart.defaults.plugins.legend.labels.generateLabels(chart).map(function(it){
                              if (it.datasetIndex === 0) it.pointStyle = 'circle';
                              return it;
                            });
                          }}},
          tooltip:{filter:function(ctx){ return ctx.datasetIndex === 0; },
                   callbacks:{label:function(ctx){
            var lv = _lvs[ctx.dataIndex] || {};
            var lines = [conc(_cal, lv.expected)];
            if (lv.response_ratio != null) lines.push('Response ratio: '+lv.response_ratio.toExponential(3));
            else if (lv.calculated != null) lines.push('Calculated: '+conc(_cal, lv.calculated.toFixed(3)));
            if (lv.pct_deviation != null)
              lines.push('Deviation: '+(lv.pct_deviation>0?'+':'')+lv.pct_deviation.toFixed(1)+'%'
                         +(lv.limit_pct != null ? ' (limit ±'+lv.limit_pct+'%)' : ''));
            lines.push(lv.passed ? 'Pass' : 'Fail (click for detail)');
            return lines;
          }}}
        },
        scales:{
          x:{type: log ? 'logarithmic' : 'linear',
             title:{display:true, text:'Expected concentration (' + (cal.level_unit || '') + ')', font:{size:10}},
             ticks:{font:{size:10}}, min: log ? undefined : 0, grace:'2%'},
          y:{type: log ? 'logarithmic' : 'linear',
             title:{display:true, text:yLabel, font:{size:10}},
             ticks:{font:{size:10}}, min: log ? undefined : 0, grace:'5%'}
        }
      }
    });
  }

  // ── Plot 2: each calibrator's deviation against its own window ────────────
  function drawPlot2(uid, cal) {
    var canvas = document.getElementById(uid+'_p2');
    if (!canvas) return;
    var lvs = (cal.levels||[]).filter(function(l){ return l.pct_deviation != null; });
    if (lvs.length === 0) {
      canvas.parentNode.classList.add('is-empty'); canvas.parentNode.innerHTML = '<div class="plot-empty">No % deviation data</div>';
      return;
    }
    /* each calibrator by its concentration, so it ties to the curve's x
       axis; the unit is said once, in the axis title, and the labels stay
       level: where they do not fit side by side, some are left out rather
       than any two overlapping */
    var labels = lvs.map(function(l){ return l.expected != null ? String(l.expected) : '?'; });
    var devs   = lvs.map(function(l){ return l.pct_deviation; });
    var wins   = lvs.map(function(l){ return calWindow(uid, l); });
    var yMax   = devRange(devs, wins);
    var _lvs2 = lvs, _cal2 = cal, key = uid+'c2';
    if (_ch[key]) _ch[key].destroy();
    _ch[key] = new Chart(canvas, {
      type:'line',
      data:{labels:labels, datasets:[
        {label:'Deviation', data:devs, showLine:false, pointRadius:3, pointHoverRadius:5,
         pointStyle:lvs.map(function(l){ return passMark(l.passed); }),
         pointBackgroundColor:lvs.map(function(l){ return l.passed ? cOK : cFail; }),
         pointBorderColor:lvs.map(function(l){ return l.passed ? cOK : cFail; })}
      ]},
      options:{
        responsive:true, maintainAspectRatio:false, animation:false,
        onClick: function(evt, elems) {
          if (elems && elems.length > 0) showPointDetail(_cal2, _lvs2[elems[0].index], 'CAL');
        },
        plugins:{
          annotation:{ annotations: windowBoxes(wins) },
          legend:{display:false},
          tooltip:{callbacks:{label:function(ctx){
            var lv = _lvs2[ctx.dataIndex]||{}, w = wins[ctx.dataIndex], dev = ctx.parsed.y;
            return [conc(_cal2, lv.expected||'?'),
                    'Deviation: '+(dev>0?'+':'')+dev.toFixed(2)+'%',
                    w ? 'Window: ±'+w.hi+'%' : 'No window set',
                    lv.passed ? 'Pass' : 'Fail (click for detail)'];
          }}}
        },
        scales:{
          x:{title:{display:true, font:{size:10},
                    text:'Expected concentration' + (cal.level_unit ? ' (' + cal.level_unit + ')' : '')},
             ticks:{font:{size:10}, maxRotation:0, autoSkip:true, autoSkipPadding:8},
             grid:{display:false}, offset:true},
          y:{title:{display:true, text:'% deviation', font:{size:10}},
             ticks:{font:{size:10}}, min:-yMax, max:yMax}
        }
      }
    });
  }

  // ── Plot 3: ICV / CCV recovery against each one's window; CCB as chips ────
  function drawPlot3(uid, cal) {
    var canvas = document.getElementById(uid+'_p3');
    if (!canvas) return;
    var ccbRows = (cal.qc||[]).filter(function(r){ return r.qc_type==='CCB'; });
    var chipWrap = document.getElementById(uid+'_ccb');
    window['_calRef_'+uid]  = cal;
    window['_ccbRef_'+uid]  = ccbRows;
    if (chipWrap) {
      if (ccbRows.length > 0) {
        chipWrap.innerHTML = ccbRows.map(function(r, i) {
          var cls = r.passed ? 'ccb-chip pass' : 'ccb-chip fail';
          var val = r.value!=null ? parseFloat(r.value).toFixed(4) : '—';
          return '<button type="button" class="'+cls+'" title="Click for detail" '
            +"onclick=\"showPointDetail(window['_calRef_"+uid+"'],window['_ccbRef_"+uid+"']["+i+"],'QC')\">"
            +'CCB'+(i>0?' '+(i+1):'')+': '+conc(cal, val)+' '+calMark(r.passed, r.passed ? 'Pass' : 'Fail')
            +'</button>';
        }).join('');
        chipWrap.classList.add('shown');
      } else {
        chipWrap.classList.remove('shown');
      }
    }
    var qcRows = (cal.qc||[]).filter(function(r){ return r.qc_type==='ICV'||r.qc_type==='CCV'; });
    if (qcRows.length === 0) {
      var p3w = document.getElementById(uid+'_p3w');
      if (p3w) { p3w.classList.add('is-empty'); } if (p3w) p3w.innerHTML = '<div class="plot-empty">No ICV/CCV data for this run</div>';
      return;
    }
    var counts = {}, labels = [], devs = [];
    qcRows.forEach(function(r){
      var qt = r.qc_type||'?';
      counts[qt] = (counts[qt]||0)+1;
      // two lines: the check, then its concentration (no bracketed level)
      labels.push([qt+(counts[qt]>1?' '+counts[qt]:''),
                   r.expected_value!=null ? conc(cal, parseFloat(r.expected_value)) : '']);
      devs.push(r.pct_dev!=null ? r.pct_dev : null);
    });
    var wins = qcRows.map(function(r){ return qcWindow(uid, r); });
    var yMax = devRange(devs, wins);
    var ann = windowBoxes(wins);
    var _cal3 = cal, _qcRows = qcRows, key = uid+'c3';
    if (_ch[key]) _ch[key].destroy();
    _ch[key] = new Chart(canvas, {
      type:'line',
      data:{labels:labels, datasets:[
        {label:'Check standard', data:devs, showLine:false, pointRadius:3, pointHoverRadius:5,
         pointStyle:qcRows.map(function(r){ return passMark(r.passed); }),
         pointBackgroundColor:qcRows.map(function(r){ return r.passed ? cOK : cFail; }),
         pointBorderColor:qcRows.map(function(r){ return r.passed ? cOK : cFail; })}
      ]},
      options:{
        responsive:true, maintainAspectRatio:false, animation:false,
        onClick: function(evt, elems) {
          if (elems && elems.length > 0) showPointDetail(_cal3, _qcRows[elems[0].index], 'QC');
        },
        plugins:{
          annotation:{ annotations: ann },
          legend:{display:false},
          tooltip:{callbacks:{label:function(ctx){
            var r = _qcRows[ctx.dataIndex]||{}, w = wins[ctx.dataIndex], dev = ctx.parsed.y;
            var lines = [r.qc_type+': '+conc(_cal3, r.expected_value!=null?r.expected_value:'?'),
                         'Deviation: '+(dev>0?'+':'')+dev.toFixed(2)+'%',
                         w ? 'Window: '+(100+w.lo)+'–'+(100+w.hi)+'% recovery' : 'No window set'];
            if (r.response_ratio!=null) lines.push('Response ratio: '+r.response_ratio.toExponential(3));
            lines.push(r.passed ? 'Pass' : 'Fail (click for detail)');
            return lines;
          }}}
        },
        scales:{
          x:{ticks:{font:{size:10}}, grid:{display:false}, offset:true},
          y:{title:{display:true, text:'% deviation', font:{size:10}},
             ticks:{font:{size:10}}, min:-yMax, max:yMax}
        }
      }
    });
  }

  function renderCard(cal) {
    drawPlot1(cal._uid, cal,
              startFit(cal),
              startWt(cal),
              startOri(cal));
    markChanged(cal._uid, cal, startWt(cal), startOri(cal), startFit(cal));
    drawPlot2(cal._uid, cal);
    drawPlot3(cal._uid, cal);
  }

  function cardHTML(cal) {
    var uid = 'c'+cal.id;
    cal._uid = uid;
    var r2disp = cal.r2 != null ? 'R\u00B2 '+cal.r2.toFixed(4) : 'R\u00B2 —';
    CAL_BY_UID[uid] = cal;
    var r2cls  = r2Class(cal.r2, cal.r2_ok === false);
    /* the instrument's equation until the card's own fit is drawn over it */
    var eqText = calEsc(cal.equation || '');

    var approvedBadge = cal.rule_fail
      ? '<span class="pfas-tag is-flag">Failed</span>'
      : (cal.approved_by
         ? '<span>Approved</span>'
         : '<span class="pfas-tag">Not approved</span>');     // a state, not a fault: grey

    var ctrlHtml = '';
    if (IS_MGR) {
      var fitOpts = ['Linear','Quadratic','Average RF'].map(function(f){
        var s=startFit(cal)===f?' selected':'';
        return '<option value="'+f+'"'+s+'>'+f+'</option>';
      }).join('');
      var wtOpts = ['','1/x','1/x2'].map(function(w){
        var l=w ? w.replace('x2', 'x\u00b2') : 'None'; var s=startWt(cal)===w?' selected':'';
        return '<option value="'+w+'"'+s+'>'+l+'</option>';
      }).join('');
      var origOpts = ['exclude','include','force'].map(function(o){
        var s=startOri(cal)===o?' selected':'';
        return '<option value="'+o+'"'+s+'>'+o.charAt(0).toUpperCase()+o.slice(1)+'</option>';
      }).join('');
      ctrlHtml = '<div class="card-controls">'
        +'<label>Fit <select id="'+uid+'_ft" onchange="refit(\''+uid+'\')">'+fitOpts+'</select></label>'
        +'<label>Weighting <select id="'+uid+'_wt" onchange="refit(\''+uid+'\')">'+wtOpts+'</select></label>'
        +'<label>Origin <select id="'+uid+'_ori" onchange="refit(\''+uid+'\')"'
        +(startFit(cal) === AVG_RF ? ' disabled="disabled" title="'+AVG_RF_ORIGIN+'"' : '')+'>'+origOpts+'</select></label>'
        +'<span class="badge badge-warn" id="'+uid+'_chg" hidden>Changed from profile</span>'
        +'<span class="card-controls-gap"></span>'
        +'<button type="button" class="btn btn-secondary" onclick="resetToProfile('+cal.id+',\''+uid+'\')">Reset to method profile</button>'
        +'<button type="button" class="btn btn-primary save-ovr" onclick="saveOverride('+cal.id+',\''+uid+'\')">Save</button>'
        +'</div>';
    }

    return [
      '<div class="analyte-card" id="'+uid+'">',
      '  <div class="card-head">',
      '    <span class="analyte-name">'+esc(cal.analyte)+'</span>',
      '    <span class="'+r2cls+'" id="'+uid+'_r2">'+r2disp+'</span>',
      '    '+approvedBadge,
      '  </div>',
      ruleHTML(cal),
      ctrlHtml,
      '  <div class="card-refused" id="'+uid+'_refused" role="alert" hidden></div>',
      '  <div class="card-plots">',
      '    <div class="plot-section">',
      '      <div class="plot-label">',
      '        Calibration curve',
      '        <button type="button" class="btn-help" data-help-entry="calibration-curve" aria-label="Help: Calibration curve" aria-haspopup="dialog">?</button>',
      '        <label class="plot-opt pfas-switch"><input type="checkbox" id="'+uid+'_log" onchange="relog(\''+uid+'\')"><span class="pfas-switch-track"></span> Log scale</label>',
      '      </div>',
      '      <div class="plot-title-row">',
      '        <div class="plot-title" id="'+uid+'_p1t"></div>',
      '        <div class="pv-formula is-inline cal-eq" id="'+uid+'_eq" title="Computed equation">'+eqText+'</div>',
      '        <div class="cal-eq-key" id="'+uid+'_eqkey"></div>',
      '      </div>',
      '      <div class="plot-canvas-wrap"><canvas id="'+uid+'_p1"></canvas></div>',
      '    </div>',
      '    <div class="plot-section">',
      '      <div class="plot-label">Calibrators: % deviation in the judged window</div>',
      '      <div class="plot-canvas-wrap plot-sm" id="'+uid+'_p2w"><canvas id="'+uid+'_p2"></canvas></div>',
      '    </div>',
      '    <div class="plot-section">',
      '      <div class="plot-label">ICV / CCV: % deviation in the judged window</div>',
      '      <div class="plot-canvas-wrap plot-sm" id="'+uid+'_p3w"><canvas id="'+uid+'_p3"></canvas></div>',
      '      <div class="ccb-chips" id="'+uid+'_ccb"></div>',
      '    </div>',
      '  </div>',
      '</div>',
    ].join('\n');
  }

  function renderRun(run) {
    var n  = run.analytes.length;
    var allApproved = run.analytes.every(function(a){return a.approved_by;});
    var anyApproved = run.analytes.some(function(a){return a.approved_by;});
    /* the method by its one name (method_name); its id is never printed */
    var meta = [esc(run.instrument_id), esc(run.analyst), esc(run.method_name)].filter(Boolean).join(' • ');
    /* the run's R² count: coral only when a curve fails; plain otherwise */
    var nFail = run.analytes.filter(function(a){return a.r2_ok === false || a.rule_fail;}).length;
    var passBadge = '<span class="'+(nFail ? 'pass-badge pass-fail' : 'run-meta')+'">'+r2Count(run)+'</span>';

    /* approval: Data Review's Calibration tab only (CAL_APPROVE); the
       archive shows the state */
    var approveBar = '';
    var A = (typeof CAL_APPROVE !== 'undefined') ? CAL_APPROVE : null;
    var st = A && A.state ? A.state : null;
    /* a curve re-used from an earlier worksheet is approved once: shown
       here as approved, read-only */
    var from = (A && A.from) ? ' (run on '+A.from+')' : '';
    if (allApproved) {
      approveBar = '<div class="approve-bar"><span class="approve-label">Run '+esc(run.run_date)+esc(from)+'</span>'
                  /* approved is a state, not a verdict: plain text */
                  +'<span>Approved'
                  +(run.analytes[0].approved_by ? ' by '+esc(run.analytes[0].approved_by) : '')+'</span></div>';
    } else if (A && A.url && A.can) {
      /* a curve failing its rule holds Approve with the rule's sentence;
         the server refuses the post with the same one */
      var hold = A.hold || '';
      approveBar = (hold
        ? '<div class="approve-bar"><span class="approve-label">Calibration of this run'+from+'</span>'
          +'<span class="approve-hold" role="status">'+esc(hold)+'</span>'
          +'<button type="button" class="btn btn-success btn-approve-run" disabled="disabled" title="'+esc(hold)+'">Approve ('+n+' analytes)</button>'
          +'</div>'
        : '<form class="approve-bar" method="POST" action="'+A.url+'">'
          +'<input type="hidden" name="action" value="approve_calibration">'
          +'<input type="hidden" name="tab" value="calibration">'
          +'<span class="approve-label">Calibration of this run'+from+'</span>'
          +'<input type="text" name="initials" required placeholder="Initials" maxlength="6">'
          +'<button type="submit" class="btn btn-success btn-approve-run">Approve ('+n+' analytes)</button>'
          +'</form>')
                  +'<form class="approve-bar" method="POST" action="'+A.url+'">'
                  +'<input type="hidden" name="action" value="reject_calibration">'
                  +'<input type="hidden" name="tab" value="calibration">'
                  +'<input type="text" name="note" required placeholder="Why the curve is rejected">'
                  +'<button type="submit" class="btn btn-danger">Reject</button>'
                  +'</form>';
    } else {
      /* the archive: a run waiting for approval names where it is given,
         its worksheet's Data Review, and offers the button there */
      var next = (st !== 'rejected' && run.review_url)
        ? '<span>Approved in Data Review, on the worksheet\u2019s Calibration tab.</span>'
          +'<a class="btn-sm btn-secondary" href="'+esc(run.review_url)+'">Approve in Data Review</a>'
        : '';
      approveBar = '<div class="approve-bar"><span class="approve-label">Run '+esc(run.run_date)+'</span>'
                  /* coral for a rejected curve only; waiting for approval is a state */
                  +'<span class="'+(st === 'rejected' ? 'pass-badge pass-fail' : 'pfas-tag')+'">'
                  +(st === 'rejected' ? 'Rejected' : (anyApproved ? 'Partly approved' : 'Not approved'))
                  +'</span>'+next+'</div>';
    }

    var runsHTML = [
      '<div class="run-section" id="run-'+esc(run.run_date).replace(/-/g,'')+'">',
      '<div class="run-header">',
      '  <h3>'+esc(run.run_date)+(run.run_time ? ' <span class="run-time">'+esc(run.run_time)+'</span>' : '')
          +(run.batch_id ? ' \u00B7 '+run.batch_id : '')+'</h3>',
      (meta ? '<span class="run-meta">'+meta+'</span>' : ''),
      /* every worksheet that used this curve set (stored once) */
      ((run.used_by||[]).length > 1 ? '<span class="run-meta">Used by '+run.used_by.join(', ')+'</span>' : ''),
      passBadge,
      '</div>',
      '<div class="cal-split">',
      '<nav class="cal-list" aria-label="Analytes">',
      '<p class="run-meta cal-list-count">'+n+' curve'+(n===1?'':'s')+' \u00B7 '+r2Count(run)+'</p>',
      run.analytes.map(function(a){
        return '<button type="button" data-cal="'+a.id+'" onclick="showCal('+a.id+')"><span>'+esc(a.analyte)+'</span>'
              +'<span class="'+r2Class(a.r2, a.r2_ok === false)+'">'+(a.r2 != null ? a.r2.toFixed(4) : '\u2014')+'</span></button>';
      }).join(''),
      '</nav>',
      '<div class="cal-detail">',
      run.analytes.map(cardHTML).join('\n'),
      '</div>',
      '</div>',
      approveBar,
      '</div>',
    ].join('\n');
    return runsHTML;
  }

  function renderAll(runs) {
    var area = document.getElementById('cal-runs-area');
    if (!runs||runs.length===0) {
      area.innerHTML = '<div class="empty-state"><p style="font-size:var(--fs-2xl)">▶</p>'
                      +'<p>No calibration records found.</p>'
                      +'<p style="font-size:var(--fs-xs)">Import instrument data to populate calibrations.</p></div>';
      return;
    }
    area.innerHTML = runs.map(renderRun).join('\n');
    // one analyte shown at a time: a failing one first, else the first
    runs.forEach(function(run){
      var first = run.analytes.filter(function(a){ return a.r2_ok === false; })[0] || run.analytes[0];
      if (first) showCal(first.id);
    });
  }

  // show one analyte's card (drawn the first time it is shown: a chart drawn
  // while hidden has no size)
  var CAL_DRAWN = {};
  function showCal(id) {
    var card = document.getElementById('c' + id);
    if (!card) return;
    var detail = card.parentNode;
    Array.prototype.forEach.call(detail.children, function(c){ c.hidden = (c !== card); });
    var list = detail.parentNode.querySelector('.cal-list');
    Array.prototype.forEach.call(list.children, function(b){
      b.classList.toggle('active', b.getAttribute('data-cal') === String(id));
    });
    if (!CAL_DRAWN[id]) {
      CAL_DRAWN[id] = true;
      for (var ri = 0; ri < CAL_RUNS.length; ri++)
        for (var ci = 0; ci < CAL_RUNS[ri].analytes.length; ci++)
          if (CAL_RUNS[ri].analytes[ci].id === id) renderCard(CAL_RUNS[ri].analytes[ci]);
    }
  }

  function filterRun(ws, rd) {
    var url = new URL(window.location.href);
    url.searchParams.set('run', ws || '');
    url.searchParams.set('run_date', rd || '');
    window.location.href = url.toString();
  }

  function refit(uid) {
    var calId = parseInt(uid.replace('c',''), 10);
    var cal = null;
    for (var ri=0; ri<CAL_RUNS.length&&!cal; ri++)
      for (var ci=0; ci<CAL_RUNS[ri].analytes.length&&!cal; ci++)
        if (CAL_RUNS[ri].analytes[ci].id===calId) cal=CAL_RUNS[ri].analytes[ci];
    if (!cal) return;
    var ftEl  = document.getElementById(uid+'_ft');
    var wtEl  = document.getElementById(uid+'_wt');
    var oriEl = document.getElementById(uid+'_ori');
    var ft  = ftEl  ? ftEl.value  : startFit(cal);
    lockOrigin(uid, cal, ft);
    var wtp = wtEl  ? wtEl.value  : startWt(cal);
    var ori = oriEl ? oriEl.value : startOri(cal);
    markChanged(uid, cal, wtp, ori, ft);
    // Redraw Plot 1 with new fit
    drawPlot1(uid, cal, ft, wtp, ori);

    // Recompute Plot 2 % deviations using back-calculation from the new fit
    // (only if response_ratio data is available; otherwise show stored values)
    var lvs = cal.levels || [];
    var useResp = lvs.some(function(l){ return l.response_ratio != null; });
    // pts2 defined here so it's also accessible for the Plot 3 QC refit below
    var pts2 = lvs.filter(function(l){
      return l.expected != null && l.response_ratio != null;
    }).map(function(l){ return {x:l.expected, y:l.response_ratio}; });
    if (useResp) {
      var fn2 = computeFn(pts2.slice(), ft, wtp, ori);
      var updLvs = lvs.map(function(l) {
        if (l.response_ratio == null || l.expected == null || l.expected === 0) return l;
        var xBack = backCalc(fn2, l.response_ratio);
        var pctDev = xBack != null
          ? Math.round((xBack - l.expected) / l.expected * 10000) / 100
          : l.pct_deviation;
        // re-judged in the point's own window (a preview of the refit; the
        // stored verdict is the worker's)
        var w = calWindow(uid, l);
        return {level:l.level, expected:l.expected, calculated:l.calculated,
                response_ratio:l.response_ratio, limit_pct:l.limit_pct,
                pct_deviation:pctDev,
                passed: (pctDev != null && w) ? (pctDev >= w.lo && pctDev <= w.hi) : l.passed};
      });
      drawPlot2(uid, {levels: updLvs});
    } else {
      drawPlot2(uid, cal);
    }

    // Recompute Plot 3 (ICV/CCV) deviations from response_ratio using new fit
    var icvccvWithRR = (cal.qc||[]).filter(function(r){
      return (r.qc_type==='ICV'||r.qc_type==='CCV') && r.response_ratio != null && r.expected_value;
    });
    if (icvccvWithRR.length > 0 && useResp) {
      var fn3 = computeFn(pts2.slice(), ft, wtp, ori);
      var updQC = (cal.qc||[]).map(function(r) {
        if ((r.qc_type!=='ICV'&&r.qc_type!=='CCV') || r.response_ratio==null || !r.expected_value) return r;
        var xBack = backCalc(fn3, r.response_ratio);
        var pctDev = xBack != null
          ? Math.round((xBack - r.expected_value) / r.expected_value * 10000) / 100
          : r.pct_dev;
        var w3 = qcWindow(uid, r);
        return {qc_type:r.qc_type, qc_level:r.qc_level, value:r.value,
                expected_value:r.expected_value, pct_dev:pctDev,
                response_ratio:r.response_ratio, flag:r.flag,
                limit_low:r.limit_low, limit_high:r.limit_high,
                passed: (pctDev != null && w3) ? (pctDev >= w3.lo && pctDev <= w3.hi) : r.passed};
      });
      drawPlot3(uid, {qc: updQC});
    } else {
      drawPlot3(uid, cal);
    }
  }

  /* Back to the method profile: the curve's own fit, weighting and origin
     are cleared. */
  function resetToProfile(calId, uid) {
    var cal = CAL_BY_UID[uid];
    if (!cal) return;
    cal.fit_type_override = ''; cal.weight_override = ''; cal.origin_override = '';
    cal._ft = null; cal._wt = null; cal._ori = null;
    var ftEl = document.getElementById(uid+'_ft');
    var wtEl = document.getElementById(uid+'_wt'), oriEl = document.getElementById(uid+'_ori');
    if (ftEl) ftEl.value = startFit(cal);
    if (wtEl) wtEl.value = startWt(cal);
    if (oriEl) { oriEl.disabled = false; oriEl.value = startOri(cal); }
    refit(uid);
    var fd = new FormData();
    fd.append('action','override');
    fd.append('calibration_id',calId);
    fd.append('fit_type_override','');
    fd.append('weight_override','');
    fd.append('origin_override','');
    fetch(CAL_URL,{method:'POST',body:fd}).catch(function(e){console.error('resetToProfile:',e);});
  }
  window.resetToProfile = resetToProfile;

  function saveOverride(calId, uid) {
    var ft  = (document.getElementById(uid+'_ft') ||{}).value||'';
    var wtp = (document.getElementById(uid+'_wt') ||{}).value||'';
    var ori = (document.getElementById(uid+'_ori')||{}).value||'';
    var fd = new FormData();
    fd.append('action','override');
    fd.append('calibration_id',calId);
    fd.append('fit_type_override',ft);
    fd.append('weight_override',wtp === '' ? 'none' : wtp);
    // an Average RF has no origin of its own to keep: it is Force
    fd.append('origin_override',ft === AVG_RF ? '' : ori);
    fetch(CAL_URL,{method:'POST',body:fd})
      .then(function(r){return r.json();})
      .then(function(d){
        if (d.ok) {
          var el=document.getElementById(uid);
          if(el){el.style.outline='2px solid var(--s-success)';
                 setTimeout(function(){el.style.outline='';},1200);}
        }
      }).catch(function(e){console.error('saveOverride:',e);});
  }
