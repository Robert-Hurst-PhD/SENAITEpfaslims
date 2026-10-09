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

  function backCalc(fn, y) {
    if (!fn || y == null) return null;
    var x = fn.model.inverse(y);
    return (x != null && x >= 0) ? x : null;
  }

  // ── Chart colours — derived from site CSS tokens so they track the theme ───
  var _css = getComputedStyle(document.documentElement);
  function _tok(n){ return (_css.getPropertyValue(n)||'').trim(); }
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

  function showPointDetail(cal, point, ptType) {
    var modal = document.getElementById('pfas-cal-modal');
    var titleEl = document.getElementById('pfas-modal-title');
    var tbody   = document.querySelector('#pfas-modal-table tbody');
    if (!modal||!titleEl||!tbody) return;
    titleEl.childNodes[0].textContent = 'Point Detail — '+cal.analyte+' ';
    var rows;
    if (ptType==='CAL') {
      rows = [
        ['Analyte',      cal.analyte],
        ['Level',        'L'+(point.level||'?')],
        ['Expected',     (point.expected||'?')+' ng/mL'],
        ['Response Ratio', point.response_ratio!=null ? point.response_ratio.toExponential(4) : 'N/A'],
        ['Back-calc',    point.calculated!=null ? point.calculated.toFixed(3)+' ng/mL' : 'N/A'],
        ['% Deviation',  point.pct_deviation!=null ? (point.pct_deviation>0?'+':'')+point.pct_deviation.toFixed(2)+'%' : 'N/A'],
        ['Result',       point.passed ? '✓ Pass' : '✗ Fail'],
        ['Run date',     cal.run_date],
        ['Batch',        cal.batch_id||'—'],
      ];
    } else {
      rows = [
        ['Analyte',      cal.analyte],
        ['QC Type',      point.qc_type],
        ['Expected',     (point.expected_value||'?')+' ng/mL'],
        ['Measured',     (point.value!=null?parseFloat(point.value).toFixed(3):'?')+' ng/mL'],
        ['Response Ratio', point.response_ratio!=null ? point.response_ratio.toExponential(4) : 'N/A'],
        ['% Deviation',  point.pct_dev!=null ? (point.pct_dev>0?'+':'')+point.pct_dev.toFixed(2)+'%' : 'N/A'],
        ['Result',       point.passed ? '✓ Pass' : '✗ Fail'],
        ['Run date',     cal.run_date],
        ['Batch',        cal.batch_id||'—'],
      ];
    }
    tbody.innerHTML = rows.map(function(r){
      return '<tr><td>'+r[0]+'</td><td>'+r[1]+'</td></tr>';
    }).join('');
    modal.classList.add('open');
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
  function warnLines(warn) {
    if (warn == null) return {};
    function ln(y) {
      return {type: 'line', yMin: y, yMax: y, borderWidth: 1, borderDash: [4, 4],
              borderColor: _rgba('--s-warning', 0.8)};
    }
    return {warnHi: ln(warn), warnLo: ln(-warn)};
  }
  function devRange(devs, wins) {
    var m = 1;
    devs.forEach(function (v) { if (v != null) m = Math.max(m, Math.abs(v) * 1.25); });
    wins.forEach(function (w) { if (w) m = Math.max(m, Math.abs(w.lo) * 1.15, Math.abs(w.hi) * 1.15); });
    return Math.ceil(m / 10) * 10;     // a round axis end
  }
  function relog(uid) {
    var cal = CAL_BY_UID[uid];
    if (!cal) return;
    cal._log = !!(document.getElementById(uid + '_log') || {}).checked;
    drawPlot1(uid, cal, cal._ft || cal.fit_type_override || cal.fit_type || 'Linear',
              cal._wt != null ? cal._wt : (cal.weight_override || cal.weight_type || ''),
              cal._ori || cal.origin_override || 'exclude');
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
    if (!fn) return;
    var r2c = computeR2(xy, fn);
    var r2el = document.getElementById(uid+'_r2');
    if (r2el && r2c !== null) {
      r2el.textContent = 'R² ' + r2c.toFixed(4);
      var r2min = limFor(uid).r2;
      r2el.className = 'r2-badge ' + (r2min == null ? 'r2-na' : (r2c >= r2min ? 'r2-ok' : 'r2-fail'));
    }
    var eqEl = document.getElementById(uid+'_eq');
    if (eqEl) eqEl.textContent = 'Fit: ' + formatEquation(fn, fitType);

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
    var fitLabel = 'Fitted curve: ' + fitType + (wtype ? ', ' + wtype : ', unweighted')
                 + (r2c !== null ? ', R² ' + r2c.toFixed(4) : '');
    var datasets = [
      {label:'Calibrators', data:xy, type:'scatter', order:1,
       pointStyle:'circle', pointRadius:3, pointHoverRadius:5,
       pointBackgroundColor:pts.map(function(p){ return p.passed ? cOK : cFail; }),
       pointBorderColor:pts.map(function(p){ return p.passed ? _rgba('--s-success',1) : _rgba('--s-danger',1); }),
       pointBorderWidth:1},
      {label:fitLabel, data:linePts, type:'line', order:2, borderColor:cLine, borderWidth:1.5,
       borderDash:[6,4], pointRadius:0, pointStyle:'line', tension:0, fill:false}
    ];
    if (!useResp) datasets.push(
      {label:'y = x', data:[{x:log?lo:0,y:log?lo:0},{x:hi,y:hi}], type:'line', order:3,
       borderColor:cIdeal, borderWidth:1, borderDash:[2,3], pointRadius:0, pointStyle:'line', fill:false});

    var _lvs = pts.map(function(p){return p._lv;}), _cal = cal, key = uid+'c1';
    var yLabel = useResp ? 'Response ratio (analyte / IS area)' : 'Calculated (ng/mL)';
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
          legend:{display:true, position:'top',
                  labels:{boxWidth:18, font:{size:10}, usePointStyle:true}},
          tooltip:{filter:function(ctx){ return ctx.datasetIndex === 0; },
                   callbacks:{label:function(ctx){
            var lv = _lvs[ctx.dataIndex] || {};
            var lines = ['L'+(lv.level||'?')+': '+lv.expected+' ng/mL'];
            if (lv.response_ratio != null) lines.push('Response ratio: '+lv.response_ratio.toExponential(3));
            else if (lv.calculated != null) lines.push('Calculated: '+lv.calculated.toFixed(3)+' ng/mL');
            if (lv.pct_deviation != null)
              lines.push('Deviation: '+(lv.pct_deviation>0?'+':'')+lv.pct_deviation.toFixed(1)+'%'
                         +(lv.limit_pct != null ? ' (limit ±'+lv.limit_pct+'%)' : ''));
            lines.push(lv.passed ? 'Pass' : 'Fail (click for detail)');
            return lines;
          }}}
        },
        scales:{
          x:{type: log ? 'logarithmic' : 'linear',
             title:{display:true, text:'Expected concentration (ng/mL)', font:{size:10}},
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
    var labels = lvs.map(function(l){ return 'L'+l.level; });
    var devs   = lvs.map(function(l){ return l.pct_deviation; });
    var wins   = lvs.map(function(l){ return calWindow(uid, l); });
    var yMax   = devRange(devs, wins);
    var _lvs2 = lvs, _cal2 = cal, key = uid+'c2';
    if (_ch[key]) _ch[key].destroy();
    _ch[key] = new Chart(canvas, {
      type:'line',
      data:{labels:labels, datasets:[
        {label:'Deviation', data:devs, showLine:false, pointRadius:4, pointHoverRadius:6,
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
            return ['L'+(lv.level||'?')+': '+(lv.expected||'?')+' ng/mL',
                    'Deviation: '+(dev>0?'+':'')+dev.toFixed(2)+'%',
                    w ? 'Window: ±'+w.hi+'%' : 'No window set',
                    lv.passed ? 'Pass' : 'Fail (click for detail)'];
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
            +'CCB'+(i>0?' '+(i+1):'')+': '+val+' ng/mL '+(r.passed?'✓':'✗')
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
      labels.push(qt+(counts[qt]>1?' '+counts[qt]:'')
                  +(r.expected_value!=null ? ' ('+parseFloat(r.expected_value).toFixed(1)+')' : ''));
      devs.push(r.pct_dev!=null ? r.pct_dev : null);
    });
    var wins = qcRows.map(function(r){ return qcWindow(uid, r); });
    var yMax = devRange(devs, wins);
    var ann = windowBoxes(wins);
    var wl = warnLines((limFor(uid).CCV || {}).warn);
    for (var k in wl) ann[k] = wl[k];
    var _cal3 = cal, _qcRows = qcRows, key = uid+'c3';
    if (_ch[key]) _ch[key].destroy();
    _ch[key] = new Chart(canvas, {
      type:'line',
      data:{labels:labels, datasets:[
        {label:'Check standard', data:devs, showLine:false, pointRadius:4, pointHoverRadius:6,
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
            var lines = [r.qc_type+': '+(r.expected_value!=null?r.expected_value:'?')+' ng/mL',
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
              cal.fit_type_override||cal.fit_type||'Linear',
              cal.weight_override||cal.weight_type||'',
              cal.origin_override||'exclude');
    drawPlot2(cal._uid, cal);
    drawPlot3(cal._uid, cal);
  }

  function cardHTML(cal) {
    var uid = 'c'+cal.id;
    cal._uid = uid;
    var r2disp = cal.r2 != null ? 'R\u00B2 '+cal.r2.toFixed(4) : 'R\u00B2 —';
    CAL_BY_UID[uid] = cal;
    var r2cls  = cal.r2_ok == null ? 'r2-na' : (cal.r2_ok ? 'r2-ok' : 'r2-fail');
    var sttcls = 'badge badge-'+(cal.status||'pending');
    var eqText = cal.fit_type_override
      ? (cal.fit_type_override+(cal.weight_override?' / '+cal.weight_override:'')
         +' (orig: '+cal.equation+')')
      : (cal.equation||'');

    var approvedBadge = cal.approved_by
      ? '<span>Approved</span>'
      : '<span class="badge badge-pending">Pending</span>';

    var ctrlHtml = '';
    if (IS_MGR) {
      var fitOpts = ['Linear','Quadratic','Average RF'].map(function(f){
        var s=(cal.fit_type_override||cal.fit_type||'Linear')===f?' selected':'';
        return '<option value="'+f+'"'+s+'>'+f+'</option>';
      }).join('');
      var wtOpts = ['','1/x','1/x2'].map(function(w){
        var l=w||'None'; var s=(cal.weight_override||cal.weight_type||'')===w?' selected':'';
        return '<option value="'+w+'"'+s+'>'+l+'</option>';
      }).join('');
      var origOpts = ['exclude','include','force'].map(function(o){
        var s=(cal.origin_override||'exclude')===o?' selected':'';
        return '<option value="'+o+'"'+s+'>Origin: '+o+'</option>';
      }).join('');
      ctrlHtml = '<div class="card-controls">'
        +'<label>Fit</label><select id="'+uid+'_ft" onchange="refit(\''+uid+'\')">'+fitOpts+'</select>'
        +'<label>Weight</label><select id="'+uid+'_wt" onchange="refit(\''+uid+'\')">'+wtOpts+'</select>'
        +'<select id="'+uid+'_ori" onchange="refit(\''+uid+'\')">'+origOpts+'</select>'
        +'<button class="save-ovr" onclick="saveOverride('+cal.id+',\''+uid+'\')">Save</button>'
        +'</div>';
    }

    return [
      '<div class="analyte-card" id="'+uid+'">',
      '  <div class="card-head">',
      '    <span class="analyte-name">'+cal.analyte+'</span>',
      '    <span class="r2-badge '+r2cls+'" id="'+uid+'_r2">'+r2disp+'</span>',
      '    '+approvedBadge,
      '  </div>',
      ctrlHtml,
      '  <div class="card-plots">',
      '    <div class="plot-section">',
      '      <div class="plot-label">',
      '        Calibration curve',
      '        <i class="rr-info" title="Response Ratio = Analyte peak area ÷ Internal Standard peak area. The calibration curve fits RR vs expected concentration.">?</i>',
      '        <label class="plot-opt"><input type="checkbox" id="'+uid+'_log" onchange="relog(\''+uid+'\')"> Log scale</label>',
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
      '  <div class="eq-line" id="'+uid+'_eq" title="Computed equation">'+eqText+'</div>',
      '</div>',
    ].join('\n');
  }

  function renderRun(run) {
    var n  = run.analytes.length;
    var np = run.analytes.filter(function(a){return a.r2_ok;}).length;
    var allApproved = run.analytes.every(function(a){return a.approved_by;});
    var anyApproved = run.analytes.some(function(a){return a.approved_by;});
    var meta = [run.instrument_id, run.analyst, run.method].filter(Boolean).join(' • ');
    var passBadge = '<span class="pass-badge '+(np===n?'pass-ok':'pass-fail')+'">'+np+'/'+n+' R\u00B2</span>';

    /* approval: Data Review's Calibration tab only (CAL_APPROVE); the
       archive shows the state */
    var approveBar = '';
    var A = (typeof CAL_APPROVE !== 'undefined') ? CAL_APPROVE : null;
    var st = A && A.state ? A.state : null;
    /* a curve re-used from an earlier worksheet is approved once: shown
       here as approved, read-only */
    var from = (A && A.from) ? ' (run on '+A.from+')' : '';
    if (allApproved) {
      approveBar = '<div class="approve-bar"><span class="approve-label">Run '+run.run_date+from+'</span>'
                  +'<span class="pass-badge pass-ok">Approved'
                  +(run.analytes[0].approved_by ? ' by '+run.analytes[0].approved_by : '')+'</span></div>';
    } else if (A && A.url && A.can) {
      approveBar = '<form class="approve-bar" method="POST" action="'+A.url+'">'
                  +'<input type="hidden" name="action" value="approve_calibration">'
                  +'<input type="hidden" name="tab" value="calibration">'
                  +'<span class="approve-label">Calibration of this run'+from+'</span>'
                  +'<input type="text" name="initials" required placeholder="Initials" maxlength="6">'
                  +'<button type="submit" class="btn btn-success btn-approve-run">Approve ('+n+' analytes)</button>'
                  +'</form>'
                  +'<form class="approve-bar" method="POST" action="'+A.url+'">'
                  +'<input type="hidden" name="action" value="reject_calibration">'
                  +'<input type="hidden" name="tab" value="calibration">'
                  +'<input type="text" name="note" required placeholder="Why the curve is rejected">'
                  +'<button type="submit" class="btn btn-danger">Reject</button>'
                  +'</form>';
    } else {
      approveBar = '<div class="approve-bar"><span class="approve-label">Run '+run.run_date+'</span>'
                  +'<span class="pass-badge pass-fail">'
                  +(st === 'rejected' ? 'Rejected' : (anyApproved ? 'Partly approved' : 'Not approved'))
                  +'</span></div>';
    }

    var runsHTML = [
      '<div class="run-section" id="run-'+run.run_date.replace(/-/g,'')+'">',
      '<div class="run-header">',
      '  <h3>'+run.run_date+(run.batch_id ? ' \u00B7 '+run.batch_id : '')
          +(run.run_time?' <span class="run-time">@ '+run.run_time+'</span>':'')+'</h3>',
      (meta ? '<span class="run-meta">'+meta+'</span>' : ''),
      /* every worksheet that used this curve set (stored once) */
      ((run.used_by||[]).length > 1 ? '<span class="run-meta">Used by '+run.used_by.join(', ')+'</span>' : ''),
      passBadge,
      '</div>',
      '<div class="cal-split">',
      '<nav class="cal-list" aria-label="Analytes">',
      run.analytes.map(function(a){
        var cls = a.r2_ok == null ? 'r2-na' : (a.r2_ok ? 'r2-ok' : 'r2-fail');
        return '<button type="button" data-cal="'+a.id+'" onclick="showCal('+a.id+')"><span>'+a.analyte+'</span>'
              +'<span class="r2-badge '+cls+'">'+(a.r2 != null ? a.r2.toFixed(4) : '\u2014')+'</span></button>';
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
    var ft  = ftEl  ? ftEl.value  : (cal.fit_type   || 'Linear');
    var wtp = wtEl  ? wtEl.value  : (cal.weight_type || '');
    var ori = oriEl ? oriEl.value : 'exclude';
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

  function saveOverride(calId, uid) {
    var ft  = (document.getElementById(uid+'_ft') ||{}).value||'';
    var wtp = (document.getElementById(uid+'_wt') ||{}).value||'';
    var ori = (document.getElementById(uid+'_ori')||{}).value||'';
    var fd = new FormData();
    fd.append('action','override');
    fd.append('calibration_id',calId);
    fd.append('fit_type_override',ft);
    fd.append('weight_override',wtp);
    fd.append('origin_override',ori);
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
