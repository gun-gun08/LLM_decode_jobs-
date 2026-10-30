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
        var focus = board.getAttribute("data-focus") && document.getElementById(board.getAttribute("data-focus"));
        if (focus) {      // /jobs/latest-jobs/..., /jobs/course-match/...: the landing page opens at that section (no #anchor in the address)
            window.setTimeout(function () {
                focus.scrollIntoView({ block: "start" });
            }, 30);
        }
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

        // ---- a tag of a job card on a results page (work mode, type, experience, place, region, posted) ADDS its filter to the ones already chosen:
        // Harvey's page -> Remote -> Full-time = /companies/harvey/remote/full-time. A filter that holds one value (mode, region, posted, years) is replaced, one
        // that holds several (type, level, city ...) gets the value added. The page changes by a normal navigation, so refresh, Back and Forward keep the filters.
        // Without the script, or outside a results page (landing, job page), the tag is a plain link to that one filter.
        var MULTI = ["jtype", "level", "city", "company", "function", "category", "skill", "salary", "size", "role"];
        if (board.querySelector("#o_llmd_board_form")) {
            board.addEventListener("click", function (ev) {
                var a = ev.target && ev.target.closest ? ev.target.closest("a.o_llmd_tag_link, a.o_llmd_loc_link") : null;
                if (!a || ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button || !window.URL || !window.URLSearchParams) {
                    return;
                }
                var target = new URL(a.href, window.location.href);
                var filter = a.getAttribute("data-filter");         // the tag's own clean page (/jobs/remote, /locations/delhi ...) = this one filter
                if (filter) {
                    target = new URL("/jobs?" + filter, window.location.href);
                } else if (target.origin !== window.location.origin || target.pathname !== "/jobs") {
                    return;                                         // a company page, another site: as linked
                }
                var form = board.querySelector("#o_llmd_board_form");      // the filters chosen now (they are in the path, and in the panel): the form's values
                var params = new URLSearchParams();
                if (window.FormData) {
                    new FormData(form).forEach(function (value, key) {
                        if (value !== "" && typeof value === "string") {
                            params.append(key, value);
                        }
                    });
                }
                target.searchParams.forEach(function (value, key) {
                    if (MULTI.indexOf(key) !== -1) {
                        if (params.getAll(key).indexOf(value) === -1) {
                            params.append(key, value);
                        }
                    } else {
                        params.set(key, value);
                    }
                });
                if (target.searchParams.has("exp_min") && !target.searchParams.has("exp_max")) {
                    params.delete("exp_max");
                }
                ev.preventDefault();
                loading();
                window.location.href = (form.getAttribute("action") || "/jobs") + "?" + params.toString();      // the server writes them as the path (/companies/x/remote/full-time)
            });
        }
        board.addEventListener("click", function (ev) {
            var a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
            if (!a || ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.shiftKey || a.target === "_blank") {
                return;
            }
            var href = a.getAttribute("href") || "";
            if (board.querySelector(".o_llmd_skeletons") && (/^\/jobs(\/(all|role|course)(\/[^?#]*)?)?(\?|$)/.test(href) || /^\/(companies|categories|departments|locations|regions)\/[^?#]+$/.test(href))) {
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
        // ---- Latest Jobs: a category shortcut or a page number swaps the cards, the count and the page numbers (/jobs/latest; without the script both reload the page)
        var latestGrid = board.querySelector("#llmd_latest_grid");
        var latestNav = board.querySelector(".o_llmd_latest_nav");
        var shownOut = board.querySelector(".o_llmd_latest_shown");
        var totalOut = board.querySelector(".o_llmd_latest_total");
        var latestSec = board.querySelector("#latest");
        function latestPath(cat, page) {      // /jobs/latest-jobs[/<category>][/page/<n>] (controllers: latest_path)
            return "/jobs/latest-jobs" + (cat ? "/" + encodeURIComponent(cat) : "") + (page > 1 ? "/page/" + page : "");
        }
        function loadLatest(cat, page, toTop) {
            if (!latestGrid || !window.fetch) {
                return false;
            }
            latestGrid.classList.add("is-loading");
            if (latestNav) {
                latestNav.classList.add("is-loading");
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
                    latestGrid.innerHTML = "";
                    while (batch.firstElementChild) {
                        latestGrid.appendChild(batch.firstElementChild);
                    }
                    bindBookmarks(latestGrid);
                    var range = box.querySelector(".o_llmd_latest_batch_range");
                    if (shownOut && range) {
                        shownOut.textContent = range.textContent;
                    }
                    if (totalOut) {
                        totalOut.textContent = batch.getAttribute("data-total");
                    }
                    var nav = box.querySelector(".o_llmd_latest_batch_nav");
                    if (latestNav && nav) {
                        latestNav.innerHTML = nav.innerHTML;
                    }
                    if (window.history && window.history.replaceState) {      // the address says what is shown: a refresh or Back shows the same jobs
                        window.history.replaceState(null, "", latestPath(cat, page));
                    }
                    if (toTop && latestSec && latestSec.getBoundingClientRect().top < 0) {      // a page number at the bottom: back to the top of the new cards
                        latestSec.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
                    }
                })
                .catch(function () {
                    window.location.href = latestPath(cat, page);      // the plain way
                })
                .then(function () {
                    latestGrid.classList.remove("is-loading");
                    if (latestNav) {
                        latestNav.classList.remove("is-loading");
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
        if (latestNav) {
            latestNav.addEventListener("click", function (ev) {
                var link = ev.target && ev.target.closest ? ev.target.closest("a[data-page]") : null;
                if (!link || ev.metaKey || ev.ctrlKey || ev.shiftKey || !latestGrid) {
                    return;
                }
                ev.preventDefault();
                var pager = latestNav.querySelector(".o_llmd_latest_pager");
                loadLatest(pager ? pager.getAttribute("data-cat") : "", parseInt(link.getAttribute("data-page"), 10) || 1, true);
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
            var hqOpen = board.querySelector(".o_llmd_hq_tab.active[data-tab]") || hqTabs[0];      // /jobs/companies-by-region/<region>: that tab
            var oldHash = /^#hq-([\w-]+)$/.exec(window.location.hash);      // an older link /jobs#hq-<region>: that tab, and its address without the #
            var hashTab = oldHash && board.querySelector('.o_llmd_hq_tab[data-tab="' + oldHash[1] + '"]');
            if (hashTab) {
                hqOpen = hashTab;
                if (window.history && window.history.replaceState) {
                    window.history.replaceState(null, "", hashTab.getAttribute("href"));
                }
            }
            showHq(hqOpen.getAttribute("data-tab"));
            hqTabs.forEach(function (t) {
                t.addEventListener("click", function (ev) {
                    if (ev.metaKey || ev.ctrlKey || ev.shiftKey) {
                        return;
                    }
                    ev.preventDefault();
                    showHq(t.getAttribute("data-tab"));
                    if (window.history && window.history.replaceState) {      // the address says which tab is open (a refresh keeps it), no #anchor
                        window.history.replaceState(null, "", t.getAttribute("href"));
                    }
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

        // ---- the course space, one step at a time in the same place: start box -> course tabs -> the chosen course -> its matching jobs (and back)
        var pick = board.querySelector(".o_llmd_course_pick");
        var matches = board.querySelector("#llmd_course_matches");
        var flow = board.querySelector("#llmd_cm_flow");
        function glide() {
            var tries = 0;
            (function go() {
                flow.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
                // the header turning sticky on the first scroll can stop a smooth scroll short: carry on until the course space is in view
                window.setTimeout(function () {
                    var top = flow.getBoundingClientRect().top;
                    if ((top > window.innerHeight / 2 || top < -40) && ++tries < 4) {
                        go();
                    }
                }, 700);
            })();
        }
        function setStep(step, code) {
            flow.setAttribute("data-step", step);
            revealCards(board, flow);
            if (window.history && window.history.replaceState) {      // the address says the step: a refresh or Back shows the same
                window.history.replaceState(null, "", "/jobs/course-match/" + encodeURIComponent(code) + (step === "info" ? "" : "/" + step));
            }
        }
        function setActive(btn) {
            each(pick.querySelectorAll(".o_llmd_cpill"), function (b) {
                var on = b === btn;
                b.classList.toggle("active", on);
                b.setAttribute("aria-selected", on ? "true" : "false");
            });
        }
        if (flow && pick && matches && window.fetch) {
            // "Explore Matching Jobs": the four course tabs, none chosen yet
            board.addEventListener("click", function (ev) {
                var explore = ev.target && ev.target.closest ? ev.target.closest(".o_llmd_cd_jobs") : null;
                if (!explore || ev.metaKey || ev.ctrlKey || ev.shiftKey) {
                    return;
                }
                ev.preventDefault();
                setActive(null);
                setStep("pick", matches.querySelector(".o_llmd_cm").getAttribute("data-course"));
                glide();
            });
            // a course tab: that course's information (Visit Course, Sign Up Free, Find Matching Jobs) - swapped in without reloading the page
            pick.addEventListener("click", function (ev) {
                var btn = ev.target && ev.target.closest ? ev.target.closest(".o_llmd_cpill[data-course]") : null;
                if (!btn) {
                    return;
                }
                ev.preventDefault();
                var code = btn.getAttribute("data-course");
                setActive(btn);
                var loaded = matches.querySelector(".o_llmd_cm");
                if (loaded && loaded.getAttribute("data-course") === code) {
                    setStep("info", code);
                    return;
                }
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
                        setStep("info", code);
                    })
                    .catch(function () {
                        window.location.href = "/jobs/course-match/" + encodeURIComponent(code);   // the plain way: reload with that course
                    })
                    .then(function () {
                        matches.classList.remove("is-loading");
                        matches.removeAttribute("aria-busy");
                    });
            });
            // "Find Matching Jobs": the course's jobs replace its information; "Back to Courses": the tabs again
            matches.addEventListener("click", function (ev) {
                var to = ev.target && ev.target.closest ? ev.target.closest(".o_llmd_cm_find, .o_llmd_cm_back") : null;
                var cm = to && matches.querySelector(".o_llmd_cm");
                if (!cm || ev.metaKey || ev.ctrlKey || ev.shiftKey) {
                    return;
                }
                ev.preventDefault();
                setStep(to.classList.contains("o_llmd_cm_find") ? "jobs" : "pick", cm.getAttribute("data-course"));
                glide();
            });
        }
        if (matches) {
            // "Load More Jobs": the next batch of the course's matching jobs, added below the ones shown (/jobs/course-matches?page=)
            matches.addEventListener("click", function (ev) {
                var more = ev.target && ev.target.closest ? ev.target.closest(".o_llmd_cm_more") : null;
                var cm = more && matches.querySelector(".o_llmd_cm");
                var grid = cm && cm.querySelector("#llmd_cm_jobs");
                if (!grid || !window.fetch || ev.metaKey || ev.ctrlKey || ev.shiftKey) {
                    return;
                }
                ev.preventDefault();
                var code = cm.getAttribute("data-course");
                var page = parseInt(more.getAttribute("data-page"), 10) || 2;
                more.classList.add("is-loading");
                window.fetch("/jobs/course-matches?course=" + encodeURIComponent(code) + "&page=" + page, { credentials: "same-origin" })
                    .then(function (r) {
                        if (!r.ok) {
                            throw new Error(r.status);
                        }
                        return r.text();
                    })
                    .then(function (html) {
                        var box = document.createElement("div");
                        box.innerHTML = html;
                        var batch = box.querySelector("#llmd_cm_jobs.o_llmd_grid");
                        var next = box.querySelector(".o_llmd_cm");
                        if (!batch || !next) {
                            throw new Error("no batch");
                        }
                        while (batch.firstElementChild) {
                            grid.appendChild(batch.firstElementChild);
                        }
                        bindBookmarks(grid);
                        revealCards(board, grid);
                        var shown = cm.querySelector(".o_llmd_cm_shown");
                        if (shown) {
                            shown.textContent = grid.querySelectorAll(".o_llmd_job").length;
                        }
                        var foot = more.parentNode;
                        if (next.getAttribute("data-more") === "1") {
                            more.setAttribute("data-page", String(page + 1));
                            more.setAttribute("href", "/jobs/course-match/" + encodeURIComponent(code) + "/jobs/page/" + (page + 1));
                        } else if (foot) {
                            foot.hidden = true;
                        }
                    })
                    .catch(function () {
                        window.location.href = more.getAttribute("href");      // the plain way: reload with one batch more
                    })
                    .then(function () {
                        more.classList.remove("is-loading");
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

    // ---- a job's detail page: Apply Now signs in / signs up in a window over the page (Odoo's own /web/login and /web/signup), then the SAME job's application
    // opens: our form in the window (sent from there, its confirmation shown there), or the employer's page in a new tab. Without the script: the usual login page.
    function initApply() {
        var modal = document.getElementById("llmd_auth");
        var btn = document.querySelector(".o_llmd_apply_card a.o_llmd_apply");
        if (!modal || !btn || modal.getAttribute("data-llmd-ready") || !window.fetch || !window.FormData || !window.DOMParser) {
            return;
        }
        modal.setAttribute("data-llmd-ready", "1");
        var box = modal.querySelector(".o_llmd_auth_box");
        var authStep = modal.querySelector('[data-step="auth"]');
        var applyStep = modal.querySelector('[data-step="apply"]');
        var errBox = modal.querySelector(".o_llmd_auth_err");
        var formHref = modal.getAttribute("data-form");
        var goHref = modal.getAttribute("data-go");
        var internalHref = modal.getAttribute("data-internal");
        var signInFirst = modal.getAttribute("data-sign-in") === "1";
        var opener = null;

        function parse(html) {
            return new DOMParser().parseFromString(html, "text/html");
        }
        function pathOf(url) {
            try {
                return new URL(url, window.location.href).pathname;
            } catch (e) {
                return "";
            }
        }
        function state() {
            return window.fetch("/jobs/auth/state", { credentials: "same-origin", cache: "no-store" }).then(function (r) {
                if (!r.ok) {
                    throw new Error(r.status);
                }
                return r.json();
            });
        }
        function showErr(text) {
            errBox.textContent = text || "";
            errBox.hidden = !text;
        }
        function busy(form, on, label) {
            var b = form.querySelector('[type="submit"]');
            if (b) {
                if (on) {
                    b.setAttribute("data-label", b.textContent);
                    b.textContent = label;
                } else if (b.getAttribute("data-label")) {
                    b.textContent = b.getAttribute("data-label");
                }
                b.disabled = on;
            }
        }
        function setTab(tab) {
            each(modal.querySelectorAll(".o_llmd_auth_tab"), function (t) {
                var on = t.getAttribute("data-tab") === tab;
                t.classList.toggle("active", on);
                t.setAttribute("aria-selected", on ? "true" : "false");
            });
            each(modal.querySelectorAll("form.o_llmd_auth_form"), function (f) {
                f.hidden = f.getAttribute("data-tab") !== tab;
            });
            each(modal.querySelectorAll("[data-tab-show]"), function (s) {
                s.hidden = s.getAttribute("data-tab-show") !== tab;
            });
            showErr("");
            var first = modal.querySelector('form[data-tab="' + tab + '"] input:not([type="hidden"])');
            if (first && !modal.hidden) {
                first.focus();
            }
        }
        function setCsrf(token) {
            each(modal.querySelectorAll('form.o_llmd_auth_form input[name="csrf_token"]'), function (i) {
                i.value = token || "";
            });
        }
        function open(step) {
            opener = document.activeElement;
            modal.hidden = false;
            document.documentElement.classList.add("o_llmd_auth_on");
            authStep.hidden = step !== "auth";
            applyStep.hidden = step === "auth";
            if (step === "auth") {
                setTab("login");
            } else {
                box.focus();
            }
        }
        function close() {
            modal.hidden = true;
            document.documentElement.classList.remove("o_llmd_auth_on");
            if (opener && opener.focus) {
                opener.focus();
            }
        }
        function panel(html) {
            authStep.hidden = true;
            applyStep.hidden = false;
            applyStep.innerHTML = html;
            box.scrollTop = 0;
            box.focus();
        }
        function esc(text) {
            var d = document.createElement("div");
            d.textContent = text || "";
            return d.innerHTML;
        }
        var jobLine = modal.querySelector(".o_llmd_auth_job").outerHTML;
        var welcome = "";      // after a sign-up: said once above the application
        function hello() {
            var text = welcome;
            welcome = "";
            return text ? '<div class="alert alert-success o_llmd_auth_welcome" role="status"><i class="fa fa-check-circle" aria-hidden="true"></i> ' + esc(text) + "</div>" : "";
        }

        // after the sign-in (or for somebody already signed in): the application of this job
        function next(name) {
            if (formHref) {
                loadForm();
            } else if (goHref) {
                var w = window.open(goHref, "_blank");      // still within the click that signed in; a blocked pop-up leaves the button below
                if (w) {
                    w.opener = null;
                }
                panel('<span class="o_llmd_auth_icon o_llmd_auth_ok" aria-hidden="true"><i class="fa fa-check"/></span>' +
                    '<h2 class="o_llmd_auth_title">You are signed in' + (name ? ", " + esc(name) : "") + "</h2>" + jobLine + hello() +
                    '<p class="o_llmd_auth_note">' + (w ? "The employer's application page for this job opened in a new tab. Send your application there."
                        : "Continue to the employer's application page for this job.") + "</p>" +
                    '<a class="o_llmd_auth_submit o_llmd_auth_go" target="_blank" rel="noopener noreferrer nofollow" href="' + esc(goHref) + '">' +
                    (w ? "Open it again" : "Continue to application") + ' <i class="fa fa-external-link" aria-hidden="true"/></a>' +
                    '<button type="button" class="o_llmd_auth_link o_llmd_auth_done" data-llmd-close="1">Back to the job</button>');
            } else if (internalHref) {
                window.location.href = internalHref;
            }
        }
        function loading() {
            panel('<div class="o_llmd_auth_wait" role="status"><span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Opening the application form…</div>');
        }
        function renderForm(doc) {
            var form = doc.querySelector("form.o_llmd_apply_form");
            if (!form) {
                return false;
            }
            var alert = doc.querySelector(".o_llmd_apply_page .alert-danger");
            var employer = form.querySelector("a.btn-link");
            if (employer) {
                employer.parentNode.removeChild(employer);
            }
            panel('<h2 class="o_llmd_auth_title">Apply for this job</h2>' + jobLine + hello() + (alert ? alert.outerHTML : "") + '<div class="o_llmd_auth_formbox"></div>');
            applyStep.querySelector(".o_llmd_auth_formbox").appendChild(document.importNode(form, true));
            var live = applyStep.querySelector("form.o_llmd_apply_form");
            var send = live.querySelector('[type="submit"]');
            if (send) {
                send.className = "o_llmd_auth_submit";
            }
            live.addEventListener("submit", function (ev) {
                ev.preventDefault();
                submitForm(live);
            });
            var bad = live.querySelector(".is-invalid") || live.querySelector('input:not([type="hidden"]):not([tabindex="-1"])');
            if (bad) {
                bad.focus();
            }
            return true;
        }
        function loadForm() {
            loading();
            window.fetch(formHref, { credentials: "same-origin" })
                .then(function (r) {
                    return r.text().then(function (html) {
                        return { path: pathOf(r.url), doc: parse(html) };
                    });
                })
                .then(function (res) {
                    if (res.path === "/web/login") {      // not signed in after all (the session ended): sign in again
                        return startAuth("Please sign in again to apply.");
                    }
                    if (!renderForm(res.doc)) {
                        throw new Error("no form");
                    }
                })
                .catch(function () {
                    window.location.href = formHref;      // the plain way: the form page
                });
        }
        function submitForm(form) {
            busy(form, true, "Submitting…");
            window.fetch(form.getAttribute("action"), { method: "POST", body: new FormData(form), credentials: "same-origin" })
                .then(function (r) {
                    return r.text().then(function (html) {
                        return { path: pathOf(r.url), doc: parse(html) };
                    });
                })
                .then(function (res) {
                    if (/\/applied$/.test(res.path)) {      // saved: the confirmation, here
                        var done = res.doc.querySelector(".o_llmd_apply_page .container");
                        if (!done) {
                            throw new Error("no confirmation");
                        }
                        each(done.querySelectorAll('a[href="/jobs"]'), function (a) {
                            a.parentNode.removeChild(a);
                        });
                        panel('<div class="o_llmd_auth_done_box">' + done.innerHTML + "</div>" +
                            '<button type="button" class="o_llmd_auth_link o_llmd_auth_done" data-llmd-close="1">Back to the job</button>');
                        var btns = applyStep.querySelectorAll(".btn-primary");
                        each(btns, function (b) {
                            b.className = "o_llmd_auth_submit o_llmd_auth_go";
                        });
                        modal.setAttribute("data-applied", "1");
                        return;
                    }
                    if (res.path === "/web/login") {
                        return startAuth("Your session ended. Please sign in again, then send the form once more.");
                    }
                    if (!renderForm(res.doc)) {      // errors come back in the form itself
                        throw new Error("unexpected answer");
                    }
                })
                .catch(function () {
                    busy(form, false);
                    var note = form.querySelector(".o_llmd_auth_send_err");
                    if (!note) {
                        note = document.createElement("div");
                        note.className = "alert alert-danger o_llmd_auth_send_err";
                        note.setAttribute("role", "alert");
                        form.insertBefore(note, form.firstChild);
                    }
                    note.textContent = "Your application could not be sent right now, so nothing was saved. Please try again.";
                });
        }
        function startAuth(message) {
            open("auth");
            showErr(message || "");
            return state().then(function (s) {
                setCsrf(s.csrf_token);
                if (s.signed_in || !s.login_required) {      // signed in meanwhile (another tab): straight on
                    next(s.name);
                }
            }).catch(function () {
                window.location.href = btn.getAttribute("href");
            });
        }

        btn.addEventListener("click", function (ev) {
            if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button) {
                return;
            }
            if (signInFirst) {
                ev.preventDefault();
                startAuth();
            } else if (formHref) {      // signed in: the form at once, in the window
                ev.preventDefault();
                open("apply");
                loadForm();
            }      // signed in, employer's page / our position's form: the link as it is
        });

        each(modal.querySelectorAll("[data-tab]"), function (t) {
            if (t.tagName === "BUTTON") {
                t.addEventListener("click", function () {
                    setTab(t.getAttribute("data-tab"));
                });
            }
        });
        modal.addEventListener("click", function (ev) {
            if (ev.target.closest && ev.target.closest("[data-llmd-close]")) {
                close();
            }
        });
        document.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape" && !modal.hidden) {
                close();
            } else if (ev.key === "Tab" && !modal.hidden) {      // focus stays in the window
                var items = [].filter.call(box.querySelectorAll("a[href], button:not([disabled]), input:not([type='hidden']):not([tabindex='-1']), textarea, select"), function (el) {
                    return el.offsetParent !== null;
                });
                if (!items.length) {
                    return;
                }
                var first = items[0];
                var last = items[items.length - 1];
                if (ev.shiftKey && (document.activeElement === first || document.activeElement === box)) {
                    ev.preventDefault();
                    last.focus();
                } else if (!ev.shiftKey && document.activeElement === last) {
                    ev.preventDefault();
                    first.focus();
                }
            }
        });

        each(modal.querySelectorAll("form.o_llmd_auth_form"), function (form) {
            form.addEventListener("submit", function (ev) {
                ev.preventDefault();
                var signup = form.getAttribute("data-tab") === "signup";
                var missing = [].filter.call(form.querySelectorAll("input[required]"), function (i) {
                    return !i.value.trim();
                });
                if (missing.length) {
                    showErr("Please fill in " + (signup ? "every field." : "your email and password."));
                    missing[0].focus();
                    return;
                }
                if (signup && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(form.elements.login.value.trim())) {
                    showErr("Please enter a valid email address.");
                    form.elements.login.focus();
                    return;
                }
                if (signup) {
                    form.elements.login.value = form.elements.login.value.trim();
                    form.elements.confirm_password.value = form.elements.password.value;      // one password field; Odoo's sign-up checks the pair
                }
                showErr("");
                busy(form, true, signup ? "Creating your account…" : "Signing in…");
                var body = new FormData(form);
                if (signup) {
                    form.elements.confirm_password.value = "";      // the password is only in the request to Odoo, nowhere else on the page
                }
                window.fetch(form.getAttribute("action"), { method: "POST", body: body, credentials: "same-origin" })
                    .then(function (r) {
                        return r.text().then(function (text) {
                            return { path: pathOf(r.url), text: text };
                        });
                    })
                    .then(function (res) {
                        busy(form, false);
                        if (res.path === "/jobs/auth/state") {      // Odoo signed the person in and sent them to `redirect`
                            var s = JSON.parse(res.text);
                            if (!s.signed_in) {
                                throw new Error("not signed in");
                            }
                            form.reset();
                            welcome = signup ? "Your account is created and you are signed in." : "";
                            modal.setAttribute("data-signed-in", "1");
                            signInFirst = false;
                            next(s.name);
                            return;
                        }
                        if (res.path !== "/web/login" && res.path !== "/web/signup") {      // another step of the sign-in (e.g. two-factor code): that page
                            window.location.href = res.path;
                            return;
                        }
                        var doc = parse(res.text);
                        var alert = doc.querySelector("form .alert-danger, .oe_login_form .alert-danger, .oe_signup_form .alert-danger");
                        var token = doc.querySelector('form input[name="csrf_token"]');
                        if (token) {
                            setCsrf(token.value);
                        }
                        showErr(alert ? alert.textContent.trim() : (signup ? "Your account could not be created. Please check your details." : "Wrong email or password."));
                        var pw = form.querySelector('input[type="password"]');
                        if (pw && !signup) {
                            pw.value = "";
                            pw.focus();
                        }
                    })
                    .catch(function () {
                        busy(form, false);
                        showErr("Something went wrong. Please try again.");
                    });
            });
        });
    }

    function start() {
        init();
        initApply();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
