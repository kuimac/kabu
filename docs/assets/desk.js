(function () {
  function apply(panel) {
    var limit = Number(panel.getAttribute("data-fold") || "0");
    var filter = panel.getAttribute("data-filter") || "all";
    var open = panel.classList.contains("is-open");
    var items = panel.querySelectorAll(".fold-item");
    var matched = 0;
    items.forEach(function (el) {
      var attr = el.getAttribute("data-attr") || "";
      var ok = filter === "all" || attr === filter;
      el.classList.toggle("is-hidden", !ok);
      if (!ok) {
        el.classList.remove("is-clipped");
        return;
      }
      matched += 1;
      var clip = !open && limit > 0 && matched > limit;
      el.classList.toggle("is-clipped", clip);
    });
    var empty = panel.querySelector(".filter-empty");
    if (empty) empty.hidden = matched !== 0;
    var btn = panel.querySelector("[data-fold-toggle]");
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

  document.querySelectorAll("[data-panel]").forEach(function (panel) {
    panel.querySelectorAll("[data-filter-value]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        panel.setAttribute("data-filter", btn.getAttribute("data-filter-value") || "all");
        panel.querySelectorAll("[data-filter-value]").forEach(function (other) {
          var on = other === btn;
          other.classList.toggle("is-on", on);
          other.setAttribute("aria-pressed", on ? "true" : "false");
        });
        apply(panel);
      });
    });
    var toggle = panel.querySelector("[data-fold-toggle]");
    if (toggle) {
      toggle.addEventListener("click", function () {
        panel.classList.toggle("is-open");
        apply(panel);
      });
    }
    apply(panel);
  });

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
})();
