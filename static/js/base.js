const TRACKING_IDS_KEY = 'peeringportal-tracking-ids';
// The portal stored the ids under this key before it followed the Peering Manager naming
const LEGACY_TRACKING_IDS_KEY = 'portal-tracking-ids';
const TRACKING_IDS_CAP = 50;

function saveTrackingIds(ids) {
  try {
    localStorage.setItem(TRACKING_IDS_KEY, JSON.stringify(ids));
  } catch (e) { }
}

function loadTrackingIds() {
  var raw = localStorage.getItem(TRACKING_IDS_KEY);
  var legacy = raw === null;
  if (legacy) {
    raw = localStorage.getItem(LEGACY_TRACKING_IDS_KEY);
  }

  var ids;
  try {
    ids = JSON.parse(raw || '[]');
  } catch (e) {
    return [];
  }

  // Carry the ids over on first read, they are the only copy the visitor has
  if (legacy && ids.length > 0) {
    saveTrackingIds(ids);
  }
  return ids;
}

function syncTrackingIdBadge() {
  var badge = document.getElementById('request-count-badge');
  if (!badge) return;

  var count = loadTrackingIds().length;
  if (count > 0) {
    badge.textContent = count;
    badge.classList.remove('d-none');
  } else {
    badge.classList.add('d-none');
  }
}

function recordTrackingId(el) {
  var id = el.getAttribute('data-tracking-ids-add');
  if (!id) return;

  var ids = loadTrackingIds().filter(function (x) { return x !== id; });
  ids.unshift(id);
  saveTrackingIds(ids.slice(0, TRACKING_IDS_CAP));
  syncTrackingIdBadge();
}

function initTrackingIdList(list) {
  var empty = list.querySelector('[data-tracking-ids-empty]');
  var clearTrigger = document.getElementById('clear-stored-button');
  var clearCount = document.getElementById('clear-stored-count');
  var unknown = list.getAttribute('data-tracking-ids-unknown') || '';

  function render(ids) {
    list.querySelectorAll('.tracking-row').forEach(function (n) { n.remove(); });
    if (ids.length === 0) {
      if (empty && !list.contains(empty)) list.appendChild(empty);
      if (clearTrigger) clearTrigger.classList.add('d-none');
      return;
    }

    if (empty && list.contains(empty)) empty.remove();
    if (clearTrigger) clearTrigger.classList.remove('d-none');
    if (clearCount) clearCount.textContent = ids.length;

    ids.forEach(function (id) {
      var row = document.createElement('div');
      row.className = 'tracking-row list-group-item d-flex align-items-center gap-2';
      var link = document.createElement('a');
      link.href = '/requests/' + encodeURIComponent(id);
      link.className = 'font-monospace small flex-grow-1 text-decoration-none';
      link.textContent = id;
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'btn btn-sm btn-link text-body-secondary p-0';
      remove.title = 'Remove from this browser';
      remove.setAttribute('aria-label', 'Remove ' + id);
      remove.innerHTML = '<i class="bi bi-x-lg"></i>';
      remove.addEventListener('click', function () {
        var current = loadTrackingIds().filter(function (x) { return x !== id; });
        saveTrackingIds(current);
        syncTrackingIdBadge();
        render(current);
      });
      row.appendChild(link);
      row.appendChild(remove);
      list.appendChild(row);
    });
  }

  var ids = loadTrackingIds();
  if (unknown) {
    ids = ids.filter(function (id) { return id !== unknown; });
    saveTrackingIds(ids);
    syncTrackingIdBadge();
  }
  render(ids);

  document.querySelectorAll('[data-tracking-ids-clear]').forEach(function (button) {
    button.addEventListener('click', function () {
      saveTrackingIds([]);
      syncTrackingIdBadge();
      render([]);
    });
  });
}

function initSelectAll(master) {
  var selector = master.dataset.selectAll;
  var scopeSelector = master.dataset.selectAllScope;
  var scope = scopeSelector ? master.closest(scopeSelector) : document;
  if (!scope) return;

  function children() {
    return Array.prototype.filter.call(
      scope.querySelectorAll(selector),
      function (el) { return !el.disabled; }
    );
  }

  function refresh() {
    var all = children();
    var checked = all.filter(function (el) { return el.checked; });
    master.checked = all.length > 0 && checked.length === all.length;
    master.indeterminate = checked.length > 0 && checked.length < all.length;
    if (all.length === 0) master.disabled = true;
  }

  master.addEventListener('change', function () {
    children().forEach(function (c) { c.checked = master.checked; });
  });
  scope.querySelectorAll(selector).forEach(function (c) {
    c.addEventListener('change', refresh);
  });
  refresh();
}

function initCopyButton(button) {
  button.addEventListener('click', function () {
    var target = document.querySelector(button.dataset.copyTarget);
    if (!target) return;

    var text = target.value !== undefined ? target.value : target.textContent.trim();
    if (typeof target.select === 'function') target.select();
    try {
      navigator.clipboard.writeText(text);
      var icon = button.querySelector('i');
      if (icon) {
        var previous = icon.className;
        icon.className = 'bi bi-check-lg';
        setTimeout(function () { icon.className = previous; }, 1500);
      }
    } catch (e) { }
  });
}

// Disable submit buttons once a form is submitted to avoid duplicate requests
function initSubmitLock(form) {
  form.addEventListener('submit', function () {
    Array.prototype.forEach.call(form.elements, function (el) {
      if (el.type !== 'submit' || el.disabled) return;
      el.disabled = true;
      el.setAttribute('data-submitting', '');
      el.insertAdjacentHTML(
        'afterbegin',
        '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>'
      );
    });
  });
}

function restoreSubmitButtons() {
  document.querySelectorAll('[data-submitting]').forEach(function (el) {
    el.disabled = false;
    el.removeAttribute('data-submitting');
    var spinner = el.querySelector('.spinner-border');
    if (spinner) spinner.remove();
  });
}

function handleRowButtons(event) {
  var addButton = event.target.closest('[data-add-row]');
  if (addButton) {
    var scope = addButton.closest('[data-location], form, body');
    var rows = scope ? scope.querySelector('[data-rows]') : null;
    if (!rows) return;
    var first = rows.querySelector('tr');
    if (!first) return;
    var clone = first.cloneNode(true);
    clone.querySelectorAll('input').forEach(function (i) { i.value = ''; });
    rows.appendChild(clone);
    return;
  }

  var removeButton = event.target.closest('[data-remove-row]');
  if (removeButton) {
    var row = removeButton.closest('tr');
    var body = removeButton.closest('[data-rows]');
    if (row && body && body.children.length > 1) row.remove();
  }
}

document.addEventListener('DOMContentLoaded', function () {
  const colourModeButton = document.getElementById('colour-mode-button');
  if (colourModeButton) {
    colourModeButton.addEventListener('click', function () {
      setColourMode(getCurrentColourMode() === 'dark' ? 'light' : 'dark', colourModeButton);
    });
    setColourMode(getCurrentColourMode(), colourModeButton, true);
  }

  syncTrackingIdBadge();
  document.querySelectorAll('[data-tracking-ids-add]').forEach(recordTrackingId);
  document.querySelectorAll('[data-tracking-ids-list]').forEach(initTrackingIdList);
  document.querySelectorAll('[data-select-all]').forEach(initSelectAll);
  document.querySelectorAll('[data-copy-target]').forEach(initCopyButton);
  document.querySelectorAll('form').forEach(initSubmitLock);
  document.addEventListener('click', handleRowButtons);
});

// Restore submit buttons when a page is served from the back/forward cache
window.addEventListener('pageshow', function (event) {
  if (event.persisted) restoreSubmitButtons();
});
