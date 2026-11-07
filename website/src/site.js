// Tribos homepage: the hero console, pointer-lit cards, reveal on scroll, mobile menu, copy buttons, demo video.
(function () {
  "use strict";

  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------------------------------------------------------------- reveal on scroll
  var items = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !reduced) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.06 });
    items.forEach(function (el) { io.observe(el); });
  } else {
    items.forEach(function (el) { el.classList.add("in"); });
  }

  // ---------------------------------------------------------------- header hairline once the page scrolls
  var header = document.querySelector("[data-header]");
  if (header) {
    var edge = function () {
      var scrolled = window.scrollY > 8;
      header.classList.toggle("border-smoke", scrolled);
      header.classList.toggle("border-smoke/0", !scrolled);
    };
    window.addEventListener("scroll", edge, { passive: true });
    edge();
  }

  // ---------------------------------------------------------------- pointer-lit cards
  document.querySelectorAll(".spot").forEach(function (card) {
    card.addEventListener("pointermove", function (e) {
      var r = card.getBoundingClientRect();
      card.style.setProperty("--x", (e.clientX - r.left) + "px");
      card.style.setProperty("--y", (e.clientY - r.top) + "px");
    });
  });

  // ---------------------------------------------------------------- the hero console
  var consoleEl = document.querySelector("[data-console]");
  if (consoleEl) {
    var tabs = Array.prototype.slice.call(consoleEl.querySelectorAll("[data-tab]"));
    var panels = {};
    consoleEl.querySelectorAll("[data-scenario]").forEach(function (p) { panels[p.getAttribute("data-scenario")] = p; });
    var timers = [];
    var autoplay = !reduced;
    var current = 0;
    var STEP_MS = 620;
    var HOLD_MS = 3200;

    var clear = function () { timers.forEach(clearTimeout); timers = []; };

    var show = function (index, play) {
      clear();
      current = index;
      tabs.forEach(function (t, i) {
        var on = i === index;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
        var bar = t.querySelector(".progress");
        if (bar) { bar.classList.remove("run"); void bar.offsetWidth; }
      });
      var key = tabs[index].getAttribute("data-tab");
      Object.keys(panels).forEach(function (k) { panels[k].hidden = k !== key; });
      var steps = panels[key].querySelectorAll(".step");
      if (!play) {
        steps.forEach(function (s) { s.classList.add("on"); });
        return;
      }
      steps.forEach(function (s) { s.classList.remove("on"); });
      steps.forEach(function (s, i) {
        timers.push(setTimeout(function () { s.classList.add("on"); }, 250 + i * STEP_MS));
      });
      var total = 250 + steps.length * STEP_MS + HOLD_MS;
      if (autoplay) {
        var bar = tabs[index].querySelector(".progress");
        if (bar) { bar.style.setProperty("--dur", total + "ms"); bar.classList.add("run"); }
        timers.push(setTimeout(function () { show((index + 1) % tabs.length, true); }, total));
      }
    };

    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () {
        autoplay = false;
        show(i, !reduced);
      });
      t.addEventListener("keydown", function (e) {
        var n = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!n) return;
        e.preventDefault();
        var next = (i + n + tabs.length) % tabs.length;
        tabs[next].focus();
        autoplay = false;
        show(next, !reduced);
      });
    });

    // Play when the console comes into view; pause when it leaves.
    if ("IntersectionObserver" in window && !reduced) {
      var started = false;
      new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting && !started) { started = true; show(current, true); }
          else if (!e.isIntersecting && started) { clear(); started = false; }
        });
      }, { threshold: 0.35 }).observe(consoleEl);
    } else {
      show(0, false);
    }
  }

  // ---------------------------------------------------------------- gallery filter
  var filters = document.querySelectorAll("[data-filter]");
  var cards = document.querySelectorAll("[data-gallery] [data-tags]");
  filters.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var want = btn.getAttribute("data-filter");
      filters.forEach(function (b) { b.setAttribute("aria-pressed", String(b === btn)); });
      cards.forEach(function (card) {
        var tags = (card.getAttribute("data-tags") || "").split(/\s+/);
        card.hidden = want !== "all" && tags.indexOf(want) < 0;
      });
    });
  });

  // ---------------------------------------------------------------- mobile menu
  var toggle = document.querySelector("[data-menu-toggle]");
  var menu = document.querySelector("[data-menu]");
  if (toggle && menu) {
    toggle.addEventListener("click", function () {
      var open = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!open));
      menu.classList.toggle("hidden", open);
    });
    menu.addEventListener("click", function (e) {
      if (e.target.closest("a")) {
        toggle.setAttribute("aria-expanded", "false");
        menu.classList.add("hidden");
      }
    });
  }

  // ---------------------------------------------------------------- copy buttons
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var target = document.querySelector(btn.getAttribute("data-copy"));
      if (!target) return;
      var label = btn.textContent;
      var done = function (text) {
        btn.textContent = text;
        setTimeout(function () { btn.textContent = label; }, 1600);
      };
      var select = function () {
        var range = document.createRange();
        range.selectNodeContents(target);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(target.innerText).then(function () { done("Copied"); }, function () { select(); done("Selected"); });
      } else {
        select();
        done("Selected");
      }
    });
  });

  // ---------------------------------------------------------------- demo video: click to play in place
  document.querySelectorAll("[data-video]").forEach(function (box) {
    var play = box.querySelector("[data-video-play]");
    if (!play || location.protocol === "file:") return; // embeds refuse file:// pages; the link still opens the video
    play.addEventListener("click", function (e) {
      e.preventDefault();
      var frame = document.createElement("iframe");
      frame.src = "https://www.youtube-nocookie.com/embed/" + box.getAttribute("data-video") + "?autoplay=1&rel=0";
      frame.title = "Tribos demo video";
      frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
      frame.allowFullscreen = true;
      frame.className = "block aspect-video w-full rounded-[1rem]";
      play.replaceWith(frame);
    });
  });
})();
