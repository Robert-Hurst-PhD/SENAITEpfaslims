/* The one top toolbar (templates/pfas_topbar.pt) -- loaded on PFAS pages by
   pfas_macros.pt and on core pages by core_overlay_link.pt.

   - dropdowns: a [data-pfas-drop] button toggles its sibling .dropdown-menu
     (no Bootstrap JS: PFAS pages do not load it; on core pages the buttons
     carry no data-toggle, so Bootstrap leaves them alone);
   - menu button: PFAS pages collapse their panel, core pages the sidebar;
   - core pages: the page's own H1 becomes the topbar title and the H1 is
     hidden, so the title sits in the bar on every page (CLAUDE.md 6C). */
(function () {
  function closeAll(except) {
    var open = document.querySelectorAll('#pfas-topbar .dropdown-menu.show');
    for (var i = 0; i < open.length; i++) {
      if (open[i] !== except) open[i].classList.remove('show');
    }
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('#pfas-topbar [data-pfas-drop]') : null;
    if (!btn) {
      if (!(e.target.closest && e.target.closest('#pfas-topbar .dropdown-menu'))) closeAll(null);
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    var menu = btn.parentNode.querySelector('.dropdown-menu');
    if (!menu) return;
    closeAll(menu);
    menu.classList.toggle('show');
    btn.setAttribute('aria-expanded', menu.classList.contains('show') ? 'true' : 'false');
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAll(null);
  });
  window.addEventListener('resize', function () { closeAll(null); });

  window.pfasTopbarToggle = function () {
    if (window.pfasTogglePanel && document.getElementById('pfas-shell')) {
      window.pfasTogglePanel();
    } else if (window.pfasSidebarCollapseToggle) {
      window.pfasSidebarCollapseToggle();
    }
  };

  function coreTitle() {
    if (document.body.classList.contains('pfas-app')) return;
    var title = document.getElementById('pfas-topbar-title');
    var h1 = document.querySelector('#content h1, .listing-title-viewlet h1, h1.documentFirstHeading');
    if (!title || !h1) return;
    var text = (h1.textContent || '').replace(/\s+/g, ' ').trim();
    if (!text) return;
    title.textContent = text;
    h1.classList.add('pfas-h1-in-topbar');
    var icon = h1.parentNode && h1.parentNode.querySelector('img');
    if (icon && h1.parentNode.classList.contains('listing-title-viewlet')) {
      icon.parentNode.classList.add('pfas-h1-in-topbar');
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', coreTitle);
  } else {
    coreTitle();
  }
})();
