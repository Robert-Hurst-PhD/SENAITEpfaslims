/* Show-if for logbook and Lab workflow questions (logbook_field_macros.pt):
   a question shown only when an earlier answer matches. Mirrors
   logbook_schema.visible_names / condition_met: a hidden question hides
   what depends on it; its inputs are disabled, so they are neither required
   nor posted (the server drops a hidden answer too). A question whose
   controlling field is not on this page (guided mode, another step) keeps
   the state the server drew from the saved answers. Loaded by the logbook
   pages and the guided extraction. */
(function () {
  'use strict';
  /* ── Show-if: a question shown only when an earlier answer matches.
     Mirrors logbook_schema.visible_names / condition_met: a hidden question
     hides what depends on it; its inputs are disabled, so they are neither
     required nor posted (the server drops a hidden answer too). A question
     whose controlling field is not on this page (guided mode, another step)
     keeps the state the server drew from the saved answers. ── */
  function answerOf(name) {
    var q = document.querySelector('.lb-q[data-q="' + name + '"]');
    if (!q) return undefined;
    if (q.hidden) return null;
    var out = [];
    Array.prototype.forEach.call(q.querySelectorAll('input, select, textarea'), function(el) {
      if (el.disabled) return;
      if (el.type === 'radio') { if (el.checked) out.push(el.value); }
      else if (el.type === 'checkbox') { if (el.checked) out.push(el.getAttribute('data-value') || el.value); }
      else if (el.type !== 'hidden' && el.name === name && (el.value || '').trim()) out.push(el.value);
    });
    return out;
  }

  function conditionMet(cond, answers) {
    var op = cond.op || 'eq', want = cond.value;
    if (op === 'filled') return answers.length > 0;
    if (op === 'in') {
      var list = Array.isArray(want) ? want : [want];
      return answers.some(function(a) { return list.indexOf(a) !== -1; });
    }
    var hit = answers.indexOf(String(want)) !== -1;
    return op === 'eq' ? hit : !hit;
  }

  function applyShowIf() {
    Array.prototype.forEach.call(document.querySelectorAll('.lb-q[data-show-if]'), function(q) {
      var cond;
      try { cond = JSON.parse(q.getAttribute('data-show-if')); } catch (e) { return; }
      var answers = answerOf(cond.field);
      if (answers === undefined) return;
      var shown = answers !== null && conditionMet(cond, answers);
      q.hidden = !shown;
      Array.prototype.forEach.call(q.querySelectorAll('input, select, textarea, button'), function(el) {
        if (!shown && !el.disabled) { el.disabled = true; el.setAttribute('data-sif-off', '1'); }
        else if (shown && el.getAttribute('data-sif-off')) { el.disabled = false; el.removeAttribute('data-sif-off'); }
      });
    });
  }

  window.PFAS_applyShowIf = applyShowIf;
  document.addEventListener('change', applyShowIf);
  document.addEventListener('input', applyShowIf);
  document.addEventListener('DOMContentLoaded', applyShowIf);
})();
