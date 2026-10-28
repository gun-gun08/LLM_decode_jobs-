/** @odoo-module ignore **/
/* LLM Decode - the job board (/jobs and its results pages). A plain script that only adds comfort to pages that already work without it:
   - the filter panel: "Apply Filters" tells how many jobs the chosen filters give before it is pressed (/jobs/results-count),
     long lists (roles, skills, companies) can be searched, the cities follow the chosen country, the experience slider has a Reset,
   - on small screens the filters open as a drawer (without the script they are a plain panel above the jobs),
   - the course selector of the landing page swaps the course-matched jobs in place (/jobs/course-matches; without the script it reloads the page),
   - after a filter, sort or page change on the same results page the page opens at the jobs instead of the top,
   - the bookmark of a job card is remembered in this browser (localStorage; nothing is sent anywhere),
   - skeleton cards show while the next results load, the sort menu closes on an outside click or Escape, the cards appear as they scroll in. */
(function () {
    "use strict";

    var SAVED_KEY = "llmd_saved_jobs";
    var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function each(list, fn) {
        Array.prototype.forEach.call(list, fn);
    }

    function readSaved() {
        try {
            var list = JSON.parse(window.localStorage.getItem(SAVED_KEY) || "[]");
            return Array.isArray(list) ? list.map(String) : [];
        } catch (e) {
            return [];
        }
    }

    function writeSaved(list) {
        try {
            window.localStorage.setItem(SAVED_KEY, JSON.stringify(list));
        } catch (e) {
            /* private mode or storage blocked: the bookmark only lasts for this page */
        }
    }

    // ---- bookmarks (this browser only)
    function bindBookmarks(root) {
        var saved = readSaved();
        each(root.querySelectorAll(".o_llmd_bookmark[data-job]"), function (btn) {
            if (btn.getAttribute("data-llmd-bound")) {
                return;
            }
            btn.setAttribute("data-llmd-bound", "1");
            var id = btn.getAttribute("data-job");
            var icon = btn.querySelector("i");
            function paint(on) {
                btn.setAttribute("aria-pressed", on ? "true" : "false");
                btn.setAttribute("aria-label", on ? "Remove from saved jobs" : "Save this job");
                if (icon) {
                    icon.className = on ? "fa fa-bookmark" : "fa fa-bookmark-o";
                }
            }
            paint(saved.indexOf(id) !== -1);
            btn.addEventListener("click", function () {
                var now = readSaved();
                var at = now.indexOf(id);
                if (at === -1) {
                    now.push(id);
                } else {
                    now.splice(at, 1);
                }
                writeSaved(now);
                paint(at === -1);
                btn.classList.remove("is-pop");
                void btn.offsetWidth;
                btn.classList.add("is-pop");
            });
        });
    }

    // ---- the cards appear as they scroll in
    function revealCards(board, root) {
        var cells = Array.prototype.slice.call(root.querySelectorAll(".o_llmd_grid .o_llmd_cell:not(.is-in)"));
        if (still || !cells.length || !("IntersectionObserver" in window)) {
            cells.forEach(function (cell) { cell.classList.add("is-in"); });
            return;
        }
        var seen = false;
        var observer = new IntersectionObserver(function (entries) {
            seen = true;
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-in");
                    observer.unobserve(entry.target);
                }
            });
        }, { rootMargin: "0px 0px -40px 0px", threshold: 0.06 });
        board.classList.add("o_llmd_js");
        cells.forEach(function (cell, i) {
            cell.style.setProperty("--d", (i % 3) * 90 + "ms");
            observer.observe(cell);
        });
        window.setTimeout(function () {                  // a browser that never reports what is visible: show every card
            if (!seen) {
                cells.forEach(function (cell) { cell.classList.add("is-in"); });
            }
        }, 1500);
    }

    // ---- the sections and the other cards fade up once as they scroll in (never with reduced motion; without the script they are simply there)
    var REVEAL = ".o_llmd_lsec .o_llmd_lhead, .o_llmd_catcard, .o_llmd_cocard, .o_llmd_countrycard, .o_llmd_regioncard, .o_llmd_regionrow, .o_llmd_why_item, " +
        ".o_llmd_faq_item, .o_llmd_cm_head, .o_llmd_course_pick, .o_llmd_lchips, .o_llmd_hq_tabs";

    function revealBlocks(board) {
        var blocks = Array.prototype.slice.call(board.querySelectorAll(REVEAL));
        if (still || !blocks.length || !("IntersectionObserver" in window)) {
            return;
        }
        var seen = false;
        var observer = new IntersectionObserver(function (entries) {
            seen = true;
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-in");
                    observer.unobserve(entry.target);
                }
            });
        }, { rootMargin: "0px 0px -30px 0px", threshold: 0.05 });
        board.classList.add("o_llmd_rv_on");
        blocks.forEach(function (el) {
            var siblings = el.parentNode ? Array.prototype.indexOf.call(el.parentNode.children, el) : 0;
            el.classList.add("o_llmd_rv");
            el.style.setProperty("--d", Math.min(siblings % 6, 5) * 60 + "ms");
            observer.observe(el);
        });
        window.setTimeout(function () {                  // a browser that never reports what is visible: show everything
            if (!seen) {
                blocks.forEach(function (el) { el.classList.add("is-in"); });
            }
        }, 1500);
    }

    // ---- an empty field stays out of the address (the slider at its full range, "Any time", an empty keyword)
    function dropEmpty(form) {
        each(form.elements, function (el) {
            if (!el.name || el.disabled) {
                return;
            }
            var off = (el.hasAttribute("data-default") && el.value === el.getAttribute("data-default")) ||
                (el.type !== "checkbox" && el.type !== "radio" && !el.value) || (el.type === "radio" && el.checked && !el.value);
            if (off) {
                el.disabled = true;
                el.setAttribute("data-llmd-off", "1");
            }
        });
    }

    function filterParams(form) {
        var params = new URLSearchParams();
        each(form.elements, function (el) {
            if (!el.name || el.disabled || ((el.type === "checkbox" || el.type === "radio") && !el.checked)) {
                return;
            }
            if (!el.value || (el.hasAttribute("data-default") && el.value === el.getAttribute("data-default"))) {
                return;
            }
            params.append(el.name, el.value);
        });
        return params;
    }

    function init() {
        var board = document.querySelector(".o_llmd_board");
        if (!board || board.getAttribute("data-llmd-ready")) {
            return;
        }
        board.setAttribute("data-llmd-ready", "1");
        bindBookmarks(board);
        revealBlocks(board);

        window.addEventListener("pageshow", function () {
            board.classList.remove("is-loading");
            each(board.querySelectorAll("[data-llmd-off]"), function (el) {
                el.disabled = false;
                el.removeAttribute("data-llmd-off");
            });
        });

        // ---- skeleton cards while the next results load (filters, sort, pager, chips, companies)
        function loading() {
            board.classList.add("is-loading");
        }
        board.addEventListener("click", function (ev) {
            var a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
            if (!a || ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.shiftKey || a.target === "_blank") {
                return;
            }
            var href = a.getAttribute("href") || "";
            if (board.querySelector(".o_llmd_skeletons") && /^\/jobs(\/(category|company|location|role)\/[^/?#]+)?(\/page\/\d+)?(\?|$)/.test(href)) {
                loading();
            }
        });

        // ---- the keyword + location search: an empty search shows all jobs (not the landing page)
        each(board.querySelectorAll("form.o_llmd_bigsearch"), function (search) {
            search.addEventListener("submit", function () {
                dropEmpty(search);
                var any = Array.prototype.some.call(search.elements, function (el) { return el.name && !el.disabled && el.value; });
                if (!any && (search.getAttribute("action") || "") === "/jobs") {
                    var all = document.createElement("input");
                    all.type = "hidden";
                    all.name = "view";
                    all.value = "all";
                    search.appendChild(all);
                }
            });
        });

        // ---- the filter panel
        var form = board.querySelector("#o_llmd_board_form");
        if (form) {
            var applyBtn = form.querySelector(".o_llmd_apply_filters");
            var liveN = form.querySelector(".o_llmd_live_n");
            var liveW = form.querySelector(".o_llmd_live_w");
            var timer = null;
            var asked = 0;
            function recount() {
                window.clearTimeout(timer);
                timer = window.setTimeout(function () {
                    var params = filterParams(form);
                    params.set("scope", form.getAttribute("data-scope") || "all");
                    params.set("scope_value", form.getAttribute("data-scope-value") || "");
                    var mine = ++asked;
                    if (applyBtn) {
                        applyBtn.classList.add("is-counting");
                    }
                    window.fetch("/jobs/results-count?" + params.toString(), { headers: { "Accept": "application/json" }, credentials: "same-origin" })
                        .then(function (r) { return r.ok ? r.json() : null; })
                        .then(function (data) {
                            if (mine !== asked || !data || typeof data.count !== "number") {
                                return;
                            }
                            if (liveN) {
                                liveN.textContent = data.count;
                            }
                            if (liveW) {
                                liveW.textContent = data.count === 1 ? "job" : "jobs";
                            }
                            if (applyBtn) {
                                applyBtn.classList.toggle("is-zero", data.count === 0);
                            }
                        })
                        .catch(function () { /* the count stays as it was; Apply Filters still works */ })
                        .then(function () {
                            if (mine === asked && applyBtn) {
                                applyBtn.classList.remove("is-counting");
                            }
                        });
                }, 250);
            }
            form.addEventListener("change", function (ev) {
                if (ev.target && ev.target.classList && ev.target.classList.contains("o_llmd_listfilter")) {
                    return;
                }
                recount();
            });
            form.addEventListener("submit", function () {
                loading();
                dropEmpty(form);
            });

            // the long lists: type to find a role, a skill or a company
            each(form.querySelectorAll(".o_llmd_listfilter"), function (input) {
                var list = input.nextElementSibling;
                if (!list) {
                    return;
                }
                var none = document.createElement("p");
                none.className = "o_llmd_nomatch";
                none.hidden = true;
                none.textContent = "Nothing matches.";
                list.parentNode.insertBefore(none, list.nextSibling);
                input.addEventListener("keydown", function (ev) {
                    if (ev.key === "Enter") {
                        ev.preventDefault();                     // Enter here searches the list, it does not apply the filters
                    }
                });
                input.addEventListener("input", function () {
                    var q = input.value.trim().toLowerCase();
                    var shown = 0;
                    each(list.querySelectorAll(".o_llmd_check"), function (label) {
                        var text = (label.querySelector(".o_llmd_check_txt") || label).textContent.toLowerCase();
                        var box = label.querySelector("input");
                        var on = !q || text.indexOf(q) !== -1 || (box && box.checked);
                        label.hidden = !on;
                        shown += on ? 1 : 0;
                    });
                    none.hidden = shown > 0;
                });
            });

            // the cities follow the chosen country (a city of another country is unticked)
            var country = form.querySelector('select[name="country"]');
            function cities() {
                var wanted = country ? country.value : "";
                each(form.querySelectorAll('.o_llmd_checklist[data-depends="country"] .o_llmd_check'), function (label) {
                    var on = !wanted || label.getAttribute("data-country") === wanted;
                    label.hidden = !on;
                    var box = label.querySelector("input");
                    if (!on && box && box.checked) {
                        box.checked = false;
                    }
                });
            }
            if (country) {
                country.addEventListener("change", cities);
                cities();
            }

            // the experience slider: two handles that cannot cross, a live label, Reset
            each(form.querySelectorAll(".o_llmd_range"), function (range) {
                var lo = range.querySelector('input[name="exp_min"]');
                var hi = range.querySelector('input[name="exp_max"]');
                var fill = range.querySelector(".o_llmd_range_fill");
                var outLo = range.querySelector(".o_llmd_range_lo");
                var outHi = range.querySelector(".o_llmd_range_hi");
                var reset = range.querySelector(".o_llmd_range_reset");
                var max = parseInt(range.getAttribute("data-max"), 10) || 25;
                if (!lo || !hi) {
                    return;
                }
                function paint(moved) {
                    var a = parseInt(lo.value, 10);
                    var b = parseInt(hi.value, 10);
                    if (a > b) {
                        if (moved === lo) {
                            lo.value = b;
                            a = b;
                        } else {
                            hi.value = a;
                            b = a;
                        }
                    }
                    if (fill) {
                        fill.style.left = (a * 100 / max) + "%";
                        fill.style.right = (100 - b * 100 / max) + "%";
                    }
                    if (outLo) {
                        outLo.textContent = a;
                    }
                    if (outHi) {
                        outHi.textContent = b >= max ? max + "+" : b;
                    }
                    lo.style.zIndex = a >= max - 1 ? "3" : "";          // at the right end the lower handle stays reachable
                }
                lo.addEventListener("input", function () { paint(lo); });
                hi.addEventListener("input", function () { paint(hi); });
                if (reset) {
                    reset.addEventListener("click", function () {
                        lo.value = 0;
                        hi.value = max;
                        paint();
                        recount();
                    });
                }
                paint();
            });
        }

        // ---- small screens: the filters open as a drawer
        var side = board.querySelector(".o_llmd_side");
        var openBtn = board.querySelector(".o_llmd_filter_btn");
        var closeBtn = board.querySelector(".o_llmd_drawer_close");
        var backdrop = board.querySelector(".o_llmd_backdrop");
        var narrow = window.matchMedia ? window.matchMedia("(max-width: 991.98px)") : null;
        function drawerOpen() {
            return board.classList.contains("o_llmd_drawer_open");
        }
        function setDrawer(open, quiet) {
            board.classList.toggle("o_llmd_drawer_open", open);
            document.documentElement.classList.toggle("o_llmd_noscroll", open);
            if (backdrop) {
                backdrop.hidden = !open;
            }
            if (openBtn) {
                openBtn.setAttribute("aria-expanded", open ? "true" : "false");
            }
            if (open && side) {
                side.setAttribute("tabindex", "-1");
                side.focus({ preventScroll: true });
            } else if (!open && openBtn && !quiet) {
                openBtn.focus({ preventScroll: true });
            }
        }
        if (side && openBtn) {
            board.classList.add("o_llmd_drawer_ready");
            window.setTimeout(function () { board.classList.add("o_llmd_drawer_anim"); }, 60);      // the drawer slides only after the first paint
            openBtn.addEventListener("click", function () { setDrawer(true); });
            if (closeBtn) {
                closeBtn.addEventListener("click", function () { setDrawer(false); });
            }
            if (backdrop) {
                backdrop.addEventListener("click", function () { setDrawer(false); });
            }
            document.addEventListener("keydown", function (ev) {
                if (ev.key === "Escape" && drawerOpen()) {
                    setDrawer(false);
                }
            });
            if (narrow && narrow.addEventListener) {
                narrow.addEventListener("change", function () {
                    if (!narrow.matches && drawerOpen()) {
                        setDrawer(false, true);
                    }
                });
            }
        }

        // ---- the landing page: the course selector swaps the course-matched jobs in place
        // ---- Latest Jobs: a category shortcut swaps the cards, "Load More Jobs" adds the next batch (/jobs/latest; without the script both reload the page)
        var latestGrid = board.querySelector("#llmd_latest_grid");
        var moreBtn = board.querySelector(".o_llmd_load_more");
        var shownOut = board.querySelector(".o_llmd_latest_shown");
        var totalOut = board.querySelector(".o_llmd_latest_total");
        function loadLatest(cat, page, append) {
            if (!latestGrid || !window.fetch) {
                return false;
            }
            latestGrid.classList.toggle("is-loading", !append);
            if (moreBtn) {
                moreBtn.classList.add("is-loading");
            }
            window.fetch("/jobs/latest?category=" + encodeURIComponent(cat || "") + "&page=" + page, { credentials: "same-origin" })
                .then(function (r) {
                    if (!r.ok) {
                        throw new Error(r.status);
                    }
                    return r.text();
                })
                .then(function (html) {
                    var box = document.createElement("div");
                    box.innerHTML = html;
                    var batch = box.querySelector(".o_llmd_latest_batch");
                    if (!batch) {
                        throw new Error("no batch");
                    }
                    if (!append) {
                        latestGrid.innerHTML = "";
                    }
                    while (batch.firstElementChild) {
                        latestGrid.appendChild(batch.firstElementChild);
                    }
                    bindBookmarks(latestGrid);
                    if (shownOut) {
                        shownOut.textContent = latestGrid.querySelectorAll(".o_llmd_lcard").length;
                    }
                    if (totalOut) {
                        totalOut.textContent = batch.getAttribute("data-total");
                    }
                    if (moreBtn) {
                        moreBtn.hidden = batch.getAttribute("data-more") !== "1";
                        moreBtn.setAttribute("data-page", String(page + 1));
                        moreBtn.setAttribute("data-cat", cat || "");
                        moreBtn.setAttribute("href", "/jobs?latest=" + (page + 1) + (cat ? "&latest_cat=" + encodeURIComponent(cat) : "") + "#latest");
                    }
                })
                .catch(function () {
                    window.location.href = "/jobs?latest=" + page + (cat ? "&latest_cat=" + encodeURIComponent(cat) : "") + "#latest";      // the plain way
                })
                .then(function () {
                    latestGrid.classList.remove("is-loading");
                    if (moreBtn) {
                        moreBtn.classList.remove("is-loading");
                    }
                });
            return true;
        }
        each(board.querySelectorAll(".o_llmd_lchip[data-cat]"), function (chip) {
            chip.addEventListener("click", function (ev) {
                if (ev.metaKey || ev.ctrlKey || ev.shiftKey || !latestGrid) {
                    return;
                }
                ev.preventDefault();
                each(board.querySelectorAll(".o_llmd_lchip"), function (c) {
                    var on = c === chip;
                    c.classList.toggle("active", on);
                    if (on) {
                        c.setAttribute("aria-current", "true");
                    } else {
                        c.removeAttribute("aria-current");
                    }
                });
                loadLatest(chip.getAttribute("data-cat"), 1, false);
            });
        });
        if (moreBtn) {
            moreBtn.addEventListener("click", function (ev) {
                if (ev.metaKey || ev.ctrlKey || ev.shiftKey || !latestGrid) {
                    return;
                }
                ev.preventDefault();
                loadLatest(moreBtn.getAttribute("data-cat"), parseInt(moreBtn.getAttribute("data-page"), 10) || 2, true);
            });
        }

        // ---- companies by region: one tab per headquarters region (without the script every region shows, one under the other)
        var hqTabs = Array.prototype.slice.call(board.querySelectorAll(".o_llmd_hq_tab[data-tab]"));
        var hqPanels = Array.prototype.slice.call(board.querySelectorAll(".o_llmd_hq_panel[data-panel]"));
        function showHq(name) {
            hqTabs.forEach(function (t) {
                var on = t.getAttribute("data-tab") === name;
                t.classList.toggle("active", on);
                t.setAttribute("aria-selected", on ? "true" : "false");
            });
            hqPanels.forEach(function (p) { p.classList.toggle("active", p.getAttribute("data-panel") === name); });
        }
        if (hqTabs.length && hqPanels.length) {
            board.classList.add("o_llmd_js_tabs");
            showHq(hqTabs[0].getAttribute("data-tab"));
            hqTabs.forEach(function (t) {
                t.addEventListener("click", function (ev) {
                    ev.preventDefault();
                    showHq(t.getAttribute("data-tab"));
                });
            });
        }

        // ---- the directories: type to find a category
        each(board.querySelectorAll(".o_llmd_dir_filter"), function (input) {
            var items = board.querySelectorAll(input.getAttribute("data-target"));
            var none = board.querySelector(".o_llmd_dir_none");
            input.addEventListener("input", function () {
                var q = input.value.trim().toLowerCase();
                var shown = 0;
                each(items, function (el) {
                    var on = !q || (el.getAttribute("data-name") || el.textContent.toLowerCase()).indexOf(q) !== -1;
                    el.hidden = !on;
                    shown += on ? 1 : 0;
                });
                if (none) {
                    none.hidden = shown > 0;
                }
            });
        });

        var pick = board.querySelector(".o_llmd_course_pick");
        var matches = board.querySelector("#llmd_course_matches");
        if (pick && matches && window.fetch) {
            pick.addEventListener("click", function (ev) {
                var btn = ev.target && ev.target.closest ? ev.target.closest(".o_llmd_cpill[data-course]") : null;
                if (!btn) {
                    return;
                }
                ev.preventDefault();
                if (btn.classList.contains("active")) {
                    return;
                }
                var code = btn.getAttribute("data-course");
                each(pick.querySelectorAll(".o_llmd_cpill"), function (b) {
                    var on = b === btn;
                    b.classList.toggle("active", on);
                    b.setAttribute("aria-selected", on ? "true" : "false");
                });
                matches.classList.add("is-loading");
                matches.setAttribute("aria-busy", "true");
                window.fetch("/jobs/course-matches?course=" + encodeURIComponent(code), { credentials: "same-origin" })
                    .then(function (r) {
                        if (!r.ok) {
                            throw new Error(r.status);
                        }
                        return r.text();
                    })
                    .then(function (html) {
                        matches.innerHTML = html;
                        bindBookmarks(matches);
                        revealCards(board, matches);
                        if (window.history && window.history.replaceState) {
                            window.history.replaceState(null, "", "/jobs?rec=" + encodeURIComponent(code) + "#courses");
                        }
                    })
                    .catch(function () {
                        window.location.href = "/jobs?rec=" + encodeURIComponent(code) + "#courses";   // the plain way: reload with that course
                    })
                    .then(function () {
                        matches.classList.remove("is-loading");
                        matches.removeAttribute("aria-busy");
                    });
            });
        }

        // ---- after a filter, sort or page change on the same results page, the page opens at the jobs (a new search starts at the top)
        var results = document.getElementById("llmd-results");
        var base = function (path) { return path.replace(/\/page\/\d+\/?$/, "").replace(/\/$/, ""); };
        var same = false;
        try {
            var from = document.referrer ? new URL(document.referrer) : null;
            same = !!from && from.origin === window.location.origin && base(from.pathname) === base(window.location.pathname) && from.href !== window.location.href;
        } catch (e) {
            same = false;
        }
        if (results && same && !window.location.hash) {
            var moved = false;
            ["wheel", "touchstart", "keydown", "mousedown"].forEach(function (name) {
                window.addEventListener(name, function () { moved = true; }, { once: true, passive: true });
            });
            results.scrollIntoView({ block: "start" });
            window.addEventListener("load", function () {          // fonts and images can still move the page: aim again unless the visitor already scrolled
                if (!moved) {
                    results.scrollIntoView({ block: "start" });
                }
            });
        }

        // ---- the sort menu closes on an outside click or Escape
        var sort = board.querySelector(".o_llmd_sort");
        document.addEventListener("click", function (ev) {
            if (sort && sort.open && !sort.contains(ev.target)) {
                sort.open = false;
            }
        });
        document.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape" && sort && sort.open) {
                sort.open = false;
                var s = sort.querySelector("summary");
                if (s) {
                    s.focus();
                }
            }
        });

        // ---- the cards already on screen stay as they are; the others appear as they scroll in
        var viewport = window.innerHeight || document.documentElement.clientHeight;
        each(board.querySelectorAll(".o_llmd_grid .o_llmd_cell"), function (cell) {
            var r = cell.getBoundingClientRect();
            if (viewport && r.top < viewport && r.bottom > 0) {
                cell.classList.add("is-in");
            }
        });
        revealCards(board, board);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
