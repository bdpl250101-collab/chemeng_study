/* 검색, 과목 메뉴 토글, 목록 정렬 — 외부 의존성 없음 */
(function () {
  var root = window.__ROOT__ || "";

  // 모바일 과목 메뉴
  var toggle = document.querySelector(".nav-toggle");
  var side = document.getElementById("cat-nav");
  if (toggle && side) {
    toggle.addEventListener("click", function () {
      var open = side.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // 과목 페이지 정렬 (최신순 / 오래된순)
  var list = document.getElementById("cat-posts");
  document.querySelectorAll(".sort").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!list) return;
      var dir = btn.getAttribute("data-sort");
      var items = Array.prototype.slice.call(list.children);
      items.sort(function (a, b) {
        var da = a.getAttribute("data-date"), db = b.getAttribute("data-date");
        return dir === "asc" ? da.localeCompare(db) : db.localeCompare(da);
      });
      items.forEach(function (li) { list.appendChild(li); });
      document.querySelectorAll(".sort").forEach(function (b) { b.setAttribute("aria-pressed", b === btn ? "true" : "false"); });
      try { localStorage.setItem("catSort", dir); } catch (e) {}
    });
  });
  try {
    var saved = localStorage.getItem("catSort");
    if (saved === "asc" && list) { var b = document.querySelector('.sort[data-sort="asc"]'); if (b) b.click(); }
  } catch (e) {}

  // 검색
  var input = document.getElementById("q");
  var box = document.getElementById("search-results");
  if (!input || !box) return;
  var index = null, loading = null;

  function load() {
    if (index) return Promise.resolve(index);
    if (!loading) {
      loading = fetch(root + "search.json").then(function (r) { return r.json(); }).then(function (d) { index = d; return d; });
    }
    return loading;
  }
  function esc(s) { return s.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function highlight(text, terms) {
    var out = esc(text);
    terms.forEach(function (t) {
      var re = new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
      out = out.replace(re, "<mark>$1</mark>");
    });
    return out;
  }
  function snippet(text, terms) {
    var lower = text.toLowerCase(), pos = -1;
    for (var i = 0; i < terms.length; i++) { pos = lower.indexOf(terms[i]); if (pos >= 0) break; }
    if (pos < 0) return text.slice(0, 110);
    var start = Math.max(0, pos - 40);
    return (start > 0 ? "…" : "") + text.slice(start, start + 120) + "…";
  }
  function run() {
    var q = input.value.trim();
    if (q.length < 2) { box.hidden = true; box.innerHTML = ""; return; }
    load().then(function (data) {
      var terms = q.toLowerCase().split(/\s+/).filter(Boolean);
      var hits = [];
      data.forEach(function (p) {
        var t = p.t.toLowerCase(), x = p.x.toLowerCase();
        var score = 0;
        for (var i = 0; i < terms.length; i++) {
          var term = terms[i];
          if (t.indexOf(term) >= 0) score += 10;
          else if (x.indexOf(term) >= 0) score += 1;
          else { score = 0; break; }
        }
        if (score > 0) hits.push({ p: p, s: score });
      });
      hits.sort(function (a, b) { return b.s - a.s || b.p.d.localeCompare(a.p.d); });
      hits = hits.slice(0, 20);
      if (!hits.length) { box.innerHTML = '<p class="none">"' + esc(q) + '" 에 해당하는 글이 없습니다.</p>'; box.hidden = false; return; }
      box.innerHTML = "<ul>" + hits.map(function (h) {
        return '<li><a href="' + root + h.p.u + '"><span class="chip">' + esc(h.p.c) + "</span>" + highlight(h.p.t, terms) +
          '<span class="snip">' + highlight(snippet(h.p.x, terms), terms) + "</span></a></li>";
      }).join("") + "</ul>";
      box.hidden = false;
    });
  }
  var timer;
  input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(run, 120); });
  input.addEventListener("focus", function () { load(); if (input.value.trim().length >= 2) run(); });
  input.form && input.form.addEventListener("submit", function (e) { e.preventDefault(); run(); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { box.hidden = true; input.blur(); }
    if (e.key === "/" && document.activeElement !== input && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); input.focus(); }
  });
  document.addEventListener("click", function (e) { if (!box.contains(e.target) && e.target !== input) box.hidden = true; });
})();
