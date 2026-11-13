(function (root) {
  function normalizeLabel(text) {
    return String(text || "").replace(/[\s\u3000]+/g, "").replace(/％/g, "%");
  }

  function columnKind(label) {
    var text = normalizeLabel(label);
    if (!text) return "";
    if (text.indexOf("アクション") !== -1) return "text";
    if (text.indexOf("シグナル") !== -1) return "text";
    if (text.indexOf("騰落") !== -1) return "number";
    if (text.indexOf("前日比") !== -1) return "number";
    if (text.indexOf("変化%") !== -1 || text.indexOf("変化率") !== -1) return "number";
    if (text === "差" || text.indexOf("差額") !== -1 || /差%?$/.test(text)) return "number";
    return "";
  }

  function isEmptySortText(text) {
    var value = String(text || "").replace(/[\s\u3000]+/g, "");
    return value === "" || /^[—―－\-–−ー]+$/.test(value);
  }

  function parseSortNumber(text) {
    if (isEmptySortText(text)) return null;
    var raw = String(text).replace(/[！-～]/g, function (ch) {
      return String.fromCharCode(ch.charCodeAt(0) - 0xfee0);
    });
    raw = raw.replace(/￥/g, "").replace(/¥/g, "").replace(/[−‐―ー]/g, "-");
    raw = raw.replace(/[,\s+%円]/g, "");
    var match = raw.match(/-?\d+(?:\.\d+)?/);
    if (!match) return null;
    var value = Number(match[0]);
    return value === value ? value : null;
  }

  function textSortKey(text) {
    var value = String(text || "").replace(/[\s\u3000]+/g, " ").trim();
    if (isEmptySortText(value)) return null;
    return value;
  }

  function compareSort(left, right, direction) {
    var leftEmpty = left.value == null;
    var rightEmpty = right.value == null;
    if (leftEmpty || rightEmpty) {
      if (leftEmpty && rightEmpty) return left.index - right.index;
      return leftEmpty ? 1 : -1;
    }
    var diff = typeof left.value === "number"
      ? left.value - right.value
      : String(left.value).localeCompare(String(right.value), "ja");
    if (diff === 0) return left.index - right.index;
    return direction === "desc" ? -diff : diff;
  }

  var api = {
    normalizeLabel: normalizeLabel,
    isEmptySortText: isEmptySortText,
    columnKind: columnKind,
    parseSortNumber: parseSortNumber,
    textSortKey: textSortKey,
    compareSort: compareSort
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (!root || !root.document) return;

  var document = root.document;
  var sortIndex = new WeakMap();

  function owned(panel, selector) {
    return Array.prototype.filter.call(panel.querySelectorAll(selector), function (el) {
      return el.closest("[data-panel]") === panel;
    });
  }

  function apply(panel) {
    var limit = Number(panel.getAttribute("data-fold") || "0");
    var filter = panel.getAttribute("data-filter") || "all";
    var open = panel.classList.contains("is-open");
    var matched = 0;
    owned(panel, ".fold-item").forEach(function (el) {
      var attr = el.getAttribute("data-attr") || "";
      var signals = el.getAttribute("data-signals") || "";
      var ok = filter === "all" || (signals ? signals.split(/\s+/).indexOf(filter) !== -1 : attr === filter);
      el.classList.toggle("is-hidden", !ok);
      if (!ok) {
        el.classList.remove("is-clipped");
        return;
      }
      matched += 1;
      var clip = !open && limit > 0 && matched > limit;
      el.classList.toggle("is-clipped", clip);
    });
    var empty = owned(panel, ".filter-empty")[0];
    if (empty) empty.hidden = matched !== 0;
    var btn = owned(panel, "[data-fold-toggle]")[0];
    if (!btn) return;
    var rest = matched - limit;
    if (limit > 0 && rest > 0) {
      btn.hidden = false;
      btn.textContent = open ? limit + "件まで閉じる" : "残り" + rest + "件を表示";
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    } else {
      btn.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }
  }

  function headerButtonLabel(th) {
    var button = th.querySelector(".th-sort");
    if (!button) return "";
    if (th.getAttribute("aria-sort") === "ascending") return (button.getAttribute("data-label") || "") + "、昇順。押すと降順";
    if (th.getAttribute("aria-sort") === "descending") return (button.getAttribute("data-label") || "") + "、降順。押すと昇順";
    return (button.getAttribute("data-label") || "") + "で並べ替え";
  }

  function refreshHeaderLabels(table) {
    if (!table.tHead || !table.tHead.rows.length) return;
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th) {
      var button = th.querySelector(".th-sort");
      if (button) button.setAttribute("aria-label", headerButtonLabel(th));
    });
  }

  function clearHeaderSort(scope) {
    scope.querySelectorAll("th.is-sortable").forEach(function (th) {
      th.setAttribute("aria-sort", "none");
      var button = th.querySelector(".th-sort");
      if (button) button.setAttribute("aria-label", (button.getAttribute("data-label") || "") + "で並べ替え");
    });
  }

  function sortByColumn(table, th, kind, index) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var next = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
    var direction = next === "descending" ? "desc" : "asc";
    var rows = Array.prototype.slice.call(tbody.rows);
    rows.forEach(function (row, rowIndex) {
      if (!sortIndex.has(row)) sortIndex.set(row, rowIndex);
    });
    var keyed = rows.map(function (row) {
      var cell = row.cells[index];
      var text = cell ? cell.textContent || "" : "";
      return {
        row: row,
        value: kind === "number" ? parseSortNumber(text) : textSortKey(text),
        index: sortIndex.get(row)
      };
    });
    keyed.sort(function (left, right) {
      return compareSort(left, right, direction);
    });
    var fragment = document.createDocumentFragment();
    keyed.forEach(function (item) {
      fragment.appendChild(item.row);
    });
    tbody.appendChild(fragment);
    if (table.tHead && table.tHead.rows.length) {
      Array.prototype.forEach.call(table.tHead.rows[0].cells, function (cell) {
        if (!cell.classList.contains("is-sortable")) return;
        cell.setAttribute("aria-sort", cell === th ? next : "none");
      });
    }
    refreshHeaderLabels(table);
    var panel = table.closest("[data-panel]");
    if (!panel) return;
    owned(panel, "[data-sort-value]").forEach(function (button) {
      button.classList.remove("is-on");
      button.setAttribute("aria-pressed", "false");
    });
    apply(panel);
  }

  function enhanceTables() {
    document.querySelectorAll("table").forEach(function (table) {
      if (!table.tHead || !table.tHead.rows.length || !table.tBodies.length) return;
      var specs = [];
      Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, index) {
        if (th.querySelector(".th-sort")) return;
        var label = normalizeLabel(th.textContent);
        var kind = columnKind(label);
        if (!kind) return;
        specs.push({ th: th, index: index, label: label, kind: kind });
      });
      if (!specs.length) return;
      table.classList.add("has-col-sort");
      specs.forEach(function (spec) {
        var button = document.createElement("button");
        var mark = document.createElement("span");
        button.type = "button";
        button.className = "th-sort";
        button.setAttribute("data-label", spec.label);
        button.textContent = spec.label;
        mark.className = "sort-mark";
        mark.setAttribute("aria-hidden", "true");
        button.appendChild(mark);
        spec.th.textContent = "";
        spec.th.classList.add("is-sortable");
        spec.th.setAttribute("aria-sort", "none");
        spec.th.appendChild(button);
        button.setAttribute("aria-label", spec.label + "で並べ替え");
        button.addEventListener("click", function () {
          sortByColumn(table, spec.th, spec.kind, spec.index);
        });
      });
    });
  }

  document.querySelectorAll("[data-panel]").forEach(function (panel) {
    owned(panel, "[data-filter-value]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        panel.setAttribute("data-filter", btn.getAttribute("data-filter-value") || "all");
        owned(panel, "[data-filter-value]").forEach(function (other) {
          var on = other === btn;
          other.classList.toggle("is-on", on);
          other.setAttribute("aria-pressed", on ? "true" : "false");
        });
        apply(panel);
      });
    });
    owned(panel, "[data-sort-value]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var mode = btn.getAttribute("data-sort-value") || "score";
        var items = owned(panel, ".fold-item");
        if (items.length) {
          var parent = items[0].parentElement;
          items.sort(function (a, b) {
            function group(action) {
              if (mode === "sell") return action === "sell" ? 0 : action === "buy" ? 1 : 2;
              if (mode === "buy") return action === "buy" ? 0 : action === "sell" ? 1 : 2;
              return 0;
            }
            var diff = group(a.getAttribute("data-action") || "") - group(b.getAttribute("data-action") || "");
            if (diff !== 0) return diff;
            return Number(a.getAttribute("data-rank") || "0") - Number(b.getAttribute("data-rank") || "0");
          });
          items.forEach(function (el) { parent.appendChild(el); });
        }
        clearHeaderSort(panel);
        owned(panel, "[data-sort-value]").forEach(function (other) {
          var on = other === btn;
          other.classList.toggle("is-on", on);
          other.setAttribute("aria-pressed", on ? "true" : "false");
        });
        apply(panel);
      });
    });
    var toggle = owned(panel, "[data-fold-toggle]")[0];
    if (toggle) {
      toggle.addEventListener("click", function () {
        panel.classList.toggle("is-open");
        apply(panel);
      });
    }
    apply(panel);
  });

  enhanceTables();

  var menuBtn = document.querySelector("[data-menu-toggle]");
  var menu = document.getElementById("sidemenu");
  function setMenu(open) {
    document.body.classList.toggle("menu-open", open);
    if (menuBtn) menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (menuBtn && menu) {
    menuBtn.addEventListener("click", function () {
      setMenu(!document.body.classList.contains("menu-open"));
    });
    menu.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        setMenu(false);
      });
    });
    document.querySelectorAll("[data-menu-close]").forEach(function (el) {
      el.addEventListener("click", function () {
        setMenu(false);
      });
    });
  }
})(typeof window !== "undefined" ? window : null);
