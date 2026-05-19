(function () {
  var STORAGE_KEY = "portal-tracking-ids";
  var STORAGE_CAP = 50;

  function loadIds() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); }
    catch (e) { return []; }
  }
  function saveIds(ids) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(ids)); }
    catch (e) { }
  }

  // Theme toggle
  var html = document.documentElement;
  var themeBtn = document.getElementById("btn-theme-toggle");

  function syncThemeIcon() {
    if (!themeBtn) return;
    var icon = themeBtn.querySelector("i");
    if (!icon) return;
    var dark = html.getAttribute("data-bs-theme") === "dark";
    icon.className = dark ? "bi bi-sun-fill" : "bi bi-moon-fill";
  }
  syncThemeIcon();

  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var next = html.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      html.setAttribute("data-bs-theme", next);
      try { localStorage.setItem("portal-theme", next); } catch (e) { }
      syncThemeIcon();
    });
  }

  // Request count badge
  var badge = document.getElementById("request-count-badge");

  function syncBadge() {
    if (!badge) return;
    var count = loadIds().length;
    if (count > 0) {
      badge.textContent = count;
      badge.classList.remove("d-none");
    } else {
      badge.classList.add("d-none");
    }
  }
  syncBadge();

  // Tracking ID recording
  document.querySelectorAll("[data-tracking-ids-add]").forEach(function (el) {
    var id = el.getAttribute("data-tracking-ids-add");
    if (!id) return;
    var ids = loadIds().filter(function (x) { return x !== id; });
    ids.unshift(id);
    saveIds(ids.slice(0, STORAGE_CAP));
    syncBadge();
  });

  // Tracking ID list
  document.querySelectorAll("[data-tracking-ids-list]").forEach(function (list) {
    var empty = list.querySelector("[data-tracking-ids-empty]");
    var clearTrigger = document.getElementById("clear-stored-button");
    var clearCount = document.getElementById("clear-stored-count");
    var unknown = list.getAttribute("data-tracking-ids-unknown") || "";

    function render(ids) {
      list.querySelectorAll(".tracking-row").forEach(function (n) { n.remove(); });
      if (ids.length === 0) {
        if (empty && !list.contains(empty)) list.appendChild(empty);
        if (clearTrigger) clearTrigger.classList.add("d-none");
        return;
      }
      if (empty && list.contains(empty)) empty.remove();
      if (clearTrigger) clearTrigger.classList.remove("d-none");
      if (clearCount) clearCount.textContent = ids.length;
      ids.forEach(function (id) {
        var row = document.createElement("div");
        row.className =
          "tracking-row list-group-item d-flex align-items-center gap-2";
        var a = document.createElement("a");
        a.href = "/requests/" + encodeURIComponent(id);
        a.className = "font-monospace small flex-grow-1 text-decoration-none";
        a.textContent = id;
        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn btn-sm btn-link text-body-secondary p-0";
        remove.title = "Remove from this browser";
        remove.setAttribute("aria-label", "Remove " + id);
        remove.innerHTML = '<i class="bi bi-x-lg"></i>';
        remove.addEventListener("click", function () {
          var current = loadIds().filter(function (x) { return x !== id; });
          saveIds(current);
          syncBadge();
          render(current);
        });
        row.appendChild(a);
        row.appendChild(remove);
        list.appendChild(row);
      });
    }

    var ids = loadIds();
    if (unknown) {
      ids = ids.filter(function (id) { return id !== unknown; });
      saveIds(ids);
      syncBadge();
    }
    render(ids);

    document.querySelectorAll("[data-tracking-ids-clear]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        saveIds([]);
        syncBadge();
        render([]);
      });
    });
  });

  // Checkboxes
  document.querySelectorAll("[data-select-all]").forEach(function (master) {
    var selector = master.dataset.selectAll;
    var scopeSel = master.dataset.selectAllScope;
    var scope = scopeSel ? master.closest(scopeSel) : document;
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
    master.addEventListener("change", function () {
      children().forEach(function (c) { c.checked = master.checked; });
    });
    scope.querySelectorAll(selector).forEach(function (c) {
      c.addEventListener("change", refresh);
    });
    refresh();
  });

  // Clipboard copy
  document.querySelectorAll("[data-copy-target]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var target = document.querySelector(btn.dataset.copyTarget);
      if (!target) return;
      target.select();
      try {
        navigator.clipboard.writeText(target.value);
        var icon = btn.querySelector("i");
        if (icon) {
          var prev = icon.className;
          icon.className = "bi bi-check-lg";
          setTimeout(function () { icon.className = prev; }, 1500);
        }
      } catch (e) { }
    });
  });

  // Table row management
  document.addEventListener("click", function (event) {
    var addBtn = event.target.closest("[data-add-row]");
    if (addBtn) {
      var scope = addBtn.closest("[data-location], form, body");
      var tbody = scope ? scope.querySelector("[data-rows]") : null;
      if (!tbody) return;
      var first = tbody.querySelector("tr");
      if (!first) return;
      var clone = first.cloneNode(true);
      clone.querySelectorAll("input").forEach(function (i) { i.value = ""; });
      tbody.appendChild(clone);
      return;
    }
    var removeBtn = event.target.closest("[data-remove-row]");
    if (removeBtn) {
      var row = removeBtn.closest("tr");
      var body = removeBtn.closest("[data-rows]");
      if (row && body && body.children.length > 1) row.remove();
    }
  });
})();
