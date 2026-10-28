> **Note (package copy, 2026-10-24):** this is the development log of the original working folder. Paths in it refer to that layout:
> `local_odoo/addons/` = `odoo_addons/`, `local_odoo/*.ps1` = `scripts/`, `rolelib/<test>.py` = `tests/`, `rolelib/<tool>.py` = `scripts/`.
> Sections about the earlier LIVE-site "Job Summary automation" (`install.py`, `final_test.py`, `views.py`, `server_action.py`, `snapshot.py`,
> `role_profile.py`, `build_library.py`, `test_local.ps1`) and the older checks `agg_test.py` / `parser_test.py` describe work that is NOT part of this
> package: it is not installed in the local instance and those checks test a layout that was replaced. See the main README, "What is not included".

# LLM Decode - local Odoo test instance

A throw-away **Odoo 19.0 + PostgreSQL 16** (Docker) on your PC, used to test the job-page changes before they go to https://learn.llmdecode.com.
Nothing in this folder talks to the live site, and the tools **refuse to write to the live site** unless you set `ALLOW_PRODUCTION=yes` yourself.

## What it is - and what it is not

| | |
|---|---|
| Is | stock Odoo 19.0 with ONLY the Recruitment module (`website_hr_recruitment` and what it depends on) plus `base_automation` (the engine of the job-description rule) - no eLearning, shop or forum; the same company address and the same 4 jobs as live (Sales manager, AiEngenner, Test, Mern Stack) |
| Is not | a copy of the live site. The live theme / navigation and these custom modules are **not** there: `llmd_landing`, `llmd_certification`, `llmd_sop_library`, `webhook_llm`, `website_sale_one_page_checkout`, `odoo_mcp_manager`. So menus and styling differ; job data, the automation and the Apply Now logic are tested for real |
| Port | `http://127.0.0.1:8070` (8069 is already used on this PC by another Odoo 20 - it is left alone). The database port is not published |

## Working URLs (after setup)

* Jobs list: http://127.0.0.1:8070/jobs  -  e.g. http://127.0.0.1:8070/jobs/data-analyst-6
* Admin: http://127.0.0.1:8070/odoo  (user `admin`, password in `local_odoo\.env`, database `llmd_local`)

## Prerequisites

* Docker Desktop running (`docker --version`), Python 3.10+ (`python --version`), PowerShell.
* About **6 GB free on C:** (download ~815 MB: `odoo:19.0` ~700 MB, `postgres:16-alpine` ~116 MB; Docker unpacks to ~3 GB and its disk file grows with it). With less, Docker's filesystem turns read-only and the database initialisation fails with `read-only file system`.
* Port 8070 free (change `ODOO_PORT` in `.env` otherwise).

## Environment variables

Local values live in `local_odoo\.env` (created by `setup.ps1` with random local-only passwords; it is git-ignored and never contains a live key).

| Variable | Meaning | Default |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | local database login | `odoo` / random |
| `ODOO_PORT` | local web port | `8070` |
| `ODOO_DB` | local database name | `llmd_local` |
| `ODOO_USER` / `ODOO_PASSWORD` | local Odoo admin login (used by the test tools via XML-RPC) | `admin` / random |
| `ODOO_MASTER_PASSWORD` | local Odoo database-manager password | random |
| `ODOO_URL` | set by `env.ps1` to `http://127.0.0.1:<ODOO_PORT>`: makes every tool use the LOCAL instance | - |
| `MCP_KEY` | live gateway key - **only for reading the live site**; `env.ps1` removes it from the session | - |
| `ALLOW_PRODUCTION` | `yes` unlocks writes to the live site. **Never set it without your approval** | unset |

## Commands

```powershell
cd local_odoo
.\setup.ps1          # once: downloads the Odoo image, creates the Recruitment-only database, seeds the 4 jobs (10-15 min)
.\setup.ps1 -Reset   # delete the local database and start again (local only)
.\test_local.ps1     # applies the changes locally and runs every test (repeatable)
```

Open `http://127.0.0.1:8070/jobs` (public) or `http://127.0.0.1:8070/odoo` (login `admin`, password from `.env`).

```powershell
docker compose stop          # stop (data is kept)
docker compose up -d         # start again
docker compose down -v       # delete the local instance completely (only the local one)
. .\env.ps1; python ..\rolelib\final_test.py check 1 2 3 4      # re-check pages any time
```


## Job board (module `llmd_job_aggregator`, local only)

**v19.0.20 (2026-10-24, after the user's screenshots):** the hero is shorter (less space above and below; the search card now starts about 450 px from the top on a 1280 px screen) and the desk illustration is replaced by a job-related one: a career path Learn -> Apply -> Get hired with a job card (with an Apply button), a resume and an offer letter (moving path, floating cards, a paper plane; no logos, no numbers). The job detail page is redesigned in the same style: lavender band, breadcrumb "All Jobs", a header card (company initial, categories, work mode, title, company / location / job type / posted chips), the Job Overview card (key points as a vertical timeline: numbers 1, 2, 3 ... in small purple badges joined by a thin line, no boxes, thin dividers, the opening phrase of each point in bold - `summary.point_parts`, the text itself never changes; the job's own headings such as "What You Will Do?" head their points instead of being numbered and are left out when nothing follows them, `summary.is_heading_point` / `display()['point_groups']`; requirements that follow a headed group get the heading "Requirements"; skill chips, one facts line), a sticky "Interested in this role?" card with the one Apply Now and three steps, and "Similar jobs" (up to 3 real visible jobs with the same role or course track, as compact cards; our own positions show none). Its styles moved from an inline `<style>` into `llmd_jobs.css` (`.o_llmd_view`). Summary fix: a line that only opens a list ("You'll thrive with us if you:") is no longer shown as a key point; migration 19.0.20 rebuilt the stored summaries. Files: `views/job_view.xml`, `views/board_templates.xml` (`board_illustration`, `job_card`), `controllers/main.py` (`_llmd_similar`), `models/summary.py` (`_LEADIN`), `migrations/19.0.20.0.0/`.

**Design (v19.0.19, 2026-10-24, after the user's reference image):** a premium recruitment-platform look in lavender / white / deep purple, Manrope type (Fraunces italic for the accent line, Caveat for the hand-written notes) with one type scale (hero 52 px max, subtitle 18, section 28, job title 18, metadata 15, tags 12-13). Hero: "Career opportunities", "Turn your learning into real opportunities", three points (Direct from company job pages / Matched to your learning path / Updated daily) and a drawn SVG desk illustration (laptop with a job list, books Learn / Grow / Get Hired, lamp, plant; no company logos). Search card with tabs Find Jobs (keyword, course, role, Search Jobs), By Course (the course catalog with real matching-job counts) and By Skills (the skills the stored jobs ask for most, with counts); Location (incl. the new "Delhi NCR" = Delhi + Gurugram + Noida + Faridabad + Ghaziabad) and Work Mode pills; removable active-filter chips + Clear all filters. The old category-chip row is gone (old `?track=` links still work). Popular Locations (Bengaluru, Delhi NCR, Mumbai, Hyderabad, Pune, Chennai with real counts, drawn landmark icons, scroll arrows), Trending roles (the 6 roles with the most open jobs, real counts; a `?role=` link now works without a course), results row with the count and a Sort menu (Recommended / Newest first / Company A-Z, `?sort=`), pastel job cards (initial as logo, New = posted in the last 3 days, category, bookmark kept in this browser only, title, company, location, a 2-line description from the job summary, type / experience / work-mode tags, salary only when the job states one, posted, See Details), skeleton cards while the next results load, empty and "could not be loaded" states, the pager. Animations respect reduced motion. Advanced Filters (job type, experience, company, date posted, salary) were built and then removed on request; no job states a salary today, so a salary filter would have had nothing to work with. Files: `views/board_templates.xml`, `static/src/css/llmd_jobs.css`, `static/src/js/llmd_jobs.js` (website assets, scoped to `.o_llmd_board`), `controllers/main.py` (`_llmd_board`), `models/listing.py` (`card_track`, `card_text`, `facet_tags`, `is_new`). A CSS / JS change needs an Odoo restart (the website bundle is rebuilt then).

**/jobs** shows real jobs. Heading "Jobs for your learning path", subtitle "Discover real job opportunities matched to your course and skills." Flow: **course -> role -> matching jobs -> See Details -> Apply Now**.

* **Course dropdown**: the courses are **read from the LLM Decode course data of the Odoo site** (eLearning, `slide.channel`: published channels of type "training"; documentation channels such as the SOP library and unpublished courses are left out) - nothing is typed in. Which job roles a course leads to is worked out from the course's own name / tags / description (`COURSE_PROFILES` in `models/board_config.py`: sell, GenAI, Claude, funnel); a new course that fits none still appears and gets jobs that name its topic. Only when the database has no eLearning module at all (this local database) the four built-in names are used: How to sell complex products with AI, 2 DAY GEN AI ENGINEERING MASTERMIND, A-Z Claude Masterclass, From Leads to Sales: Funnel Building 101. Code: `models/courses.py`.
* **Role dropdown** (disabled until a course is chosen): only the roles relevant to that course that have real jobs right now, with counts. Choosing a role shows the matching jobs.
* **Category chips** under the search bar: All, GenAI, Claude, Python, AI/ML, Data Analytics, Sales, Digital Marketing (they combine with every other filter; their counts follow the filters).
* **Filters** (they work together, keep their state after a reload, and the pager and the chips keep them; on a phone they sit behind a "Filters" button): **Location** (All locations / India - the default / Remote (anywhere) / the Indian cities that have jobs) and **Work mode** (All Jobs / Remote / Hybrid / On-site). The Experience Level and Job Type filters were removed (old links with `?exp=` / `?jtype=` still open, those parameters are ignored). The work mode is worked out from the job's own text and API flags (`models/job_facets.py`) and stored on the job: a job with a real place and no sign of remote or hybrid work counts as On-site. **Indian jobs are listed first.**
* **Job card**: title, company, location, tags (job type, experience level, work mode), "Posted ... ago" and **See Details**. **No source / job-site name is shown anywhere** (cards, detail page); the source and the original application URL are kept internally.
* **Detail page `/jobs/ext/<id>`**: header card (title, company, location, salary, job type, posted), **ONE "Job Overview" card** with a short summary of the job (`models/summary.py`, stored as `llmd.job.listing.summary_json`, made automatically when a job is fetched or updated and, on a module update, for every stored job): a 1-2 sentence overview of the role, up to 8 points mixing the key responsibilities and the required skills & qualifications, the skill tags, and one line of stated facts (experience level and years, salary or stipend, job type, working hours, duration ...). The same summary is made for EVERY source (Jooble, Adzuna, JSearch, Himalayas, the company job boards, partner feeds, our own positions): company history and culture, benefits, inclusion / EEO text, hashtags, referral and interview-process text, "Originally posted on ..." and repeated lines are left out - also the legal and hiring notices of company careers pages (export control, "all qualified applicants ...", pay transparency, privacy notice, recruitment-fraud warnings, "by applying ..."), and the text under the company's own headings ("About <company>", "Who we are", "What we offer", "Equal Opportunity Employer"); the overview prefers the job's own "About the role" text; at most 250 words; nothing is made up - a fact the job does not state is simply not shown (a short Jooble snippet gives a short card; a full text gives 150-250 words). Title, company, location and the Apply Now link are never changed and a sticky **Apply Now** card (under the title on a phone). **Apply Now goes straight to the employer's own job / application page** (new tab) through the tracked redirect `/jobs/ext/<id>/go`: the click is saved in Odoo first (Recruitment -> Apply Clicks). There is no form by default; our own application form can be switched on with `llmd_agg.apply_mode = form` (see "Apply Now, the form and the click log" below). A missing or invalid application URL (anything but http/https with a host) = a disabled button. Same layout for our own positions (`views/job_view.xml`).
* Our own published positions are listed first on the unfiltered page (with See Details too); the stock Odoo list is at `/jobs?stock=1`.

### Sources (no menu any more - removed on request; the per-source result of every run is in Recruitment -> Job board -> Sync runs, a manual fetch is "Fetch jobs now" on Recruitment -> Job board -> Job board listings)

| Source | How | Status here |
|---|---|---|
| Adzuna | official API, `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` (free signup), India (`/jobs/in/`), short snippets | code + unit tests ready; **not connected until you add the keys** |
| JSearch | `JSEARCH_API_KEY` - RapidAPI "JSearch" (default host `jsearch.p.rapidapi.com`) or OpenWebNinja (also set `JSEARCH_BASE_URL=https://api.openwebninja.com/jsearch/search`); full job text + the employer's own apply link when it has one; searched as "<role> in India" | code + unit tests ready against the documented request / response format; **never run against the real API (no key): not verified live**; **not connected until you add the key** |
| Company job boards | **no key**: the public job-board APIs of the companies' own applicant tracking systems - Greenhouse (`boards-api.greenhouse.io`), Lever (`api.lever.co`), Ashby (`api.ashbyhq.com`), SmartRecruiters (`api.smartrecruiters.com`). 42 companies (list `COMPANY_BOARDS` in `models/board_config.py`, e.g. Databricks, Stripe, MongoDB, Okta, GitLab, Razorpay, Groww, InMobi, CRED, Meesho, Paytm, Zeta, OpenAI, Sarvam AI, Atlan, Freshworks, Bosch, Experian); full job text; only jobs in India (or remote from India) whose title fits a course role or category, at most 15 per company, newest first | **tested against the real APIs on 2026-10-23: works** - 298 jobs from 41 companies in about 50 s, every one with a direct link to the company's own job page (Greenhouse 80, Lever 57, Ashby 31, SmartRecruiters 23, the rest on the companies' own careers sites) |
| Jooble | official API, `JOOBLE_API_KEY`, location India, short snippets. The adapter uses the India domain `in.jooble.org` (jooble.org itself answers HTTP 403 to API calls) | **tested against the real API on 2026-10-23 with a real key: works** (plain + remote + hybrid searches of one query gave 20 India jobs each, a real mix of on-site / remote / hybrid) |
| Indeed | only through an official partner / employer job feed: `INDEED_FEED_URL` (+ `INDEED_FEED_TOKEN`). Indeed has no public self-serve job-search API | feed reader ready (XML / JSON); **not connected without a feed** |
| Naukri.com | only through an official partner job feed: `NAUKRI_FEED_URL` (+ `NAUKRI_FEED_TOKEN`). Naukri has no public self-serve job-search API | same: **not connected without a feed** |
| Himalayas | keyless public API, remote jobs only, `country=IN` - the TEMPORARY fallback described below | **tested against the real API**: 464 remote jobs |

**Himalayas is a TEMPORARY keyless fallback** (remote jobs only, jobs open to India): it is read only while the other sources together return fewer than 20 jobs (`llmd_agg.himalayas_mode`: `fallback` = default, `always`, `off`). As soon as Adzuna / JSearch / Jooble deliver enough jobs it says "Not needed" and its jobs are hidden (not deleted), so the page does not show only remote jobs. Without any key the board shows the Himalayas jobs (all remote); the Hybrid and On-site filters then find nothing, which is expected.
Nothing is scraped. A source that is not connected is never shown as working. Keys live only in `local_odoo\.env` (never committed, never in the page); after editing it run `docker compose up -d --force-recreate odoo`.
All connected sources are combined: jobs are normalized into one shape, the same job found by two sources (same title + company + place) is kept once (the richest description wins - JSearch's full text beats a snippet - and it keeps its own application URL; the other source is stored as "also on"), Indian jobs come first, and a failing source only changes its own status. Nothing is hidden by a run in which no source delivered anything (no keys never empties the board); a job that no source has returned for 14 days is hidden. The board refreshes daily (scheduled action) or with "Fetch jobs now".

**Remote, Hybrid and On-site:** every search query is sent three times - plain (jobs in India, mostly on-site), "remote" and "hybrid" (Adzuna / Jooble: the word is added to the search words; JSearch: its own `remote_jobs_only` filter for remote and the word "hybrid" for hybrid) - so the results are not only remote jobs. All three APIs are asked for India (Adzuna `/jobs/in/`, Jooble location India, JSearch "... in India" with `country=in`).
**The small plans are spared** (the 26 queries x 3 modes = 78 searches rotate: each run sends the next ones, so all are used within a few days): Adzuna 39 searches per run (`llmd_agg.adzuna_per_run`), Jooble 9 (`llmd_agg.jooble_per_run`), JSearch 6 (`llmd_agg.jsearch_per_run`). Budgets that are never exceeded: Jooble 450 requests in total (`llmd_agg.jooble_budget`), JSearch 150 per calendar month (`llmd_agg.jsearch_budget`). A job that no source has returned for 30 days is hidden. Raise the budgets only if your plan allows more.

### Where Apply Now leads (job board page or straight to the employer)

* **Direct links only (default since v19.0.14):** system parameter `llmd_agg.direct_links_only` (not set / `1` = on, `0` = off). While it is on, **Adzuna, Jooble and Himalayas are not asked at all** (no request is spent; their status says "Off") because their links always open their own page first; a job whose link is a job board page is never stored, and the jobs of those sources already on the board are **hidden, not deleted** (the 19.0.14 migration hid the 153 Jooble jobs; `0` and a fetch bring them back). Our own positions whose saved link is a job board page (e.g. a Himalayas listing) open **our own Odoo application form** `/jobs/apply/<slug>` instead; the click line names that form. Tested 2026-10-23: a real fetch sent 0 requests to Jooble (counter 424 -> 424), 294 visible jobs, 0 with a job board link.
* **No duplicates across platforms:** the duplicate key is title + company + the normalized city ("Bangalore" = "Bengaluru", "Gurgaon" = "Gurugram"; `job_facets.city_of`), and a job that is merged into another one in a run is hidden. Real data: 0 jobs stored twice (source + id, title + company + city, apply link); the same title of a company in different cities stays separate (separate openings, separate links).
* **Jooble** sends only its own link (`in.jooble.org/desc/...`) plus the NAME of the original site (e.g. `adsolave.monster.com` = foundit, the site behind most of the current jobs). The original URL is only on Jooble's page, so Apply Now opens Jooble first and Jooble sends the visitor on. Taking the link out of Jooble's page (scraping) is against Jooble's API terms and is not done. **Adzuna** and **Himalayas** work the same way (`adzuna.*` redirect, `himalayas.app` page).
* **JSearch** gives direct application links (the employer's site or the original portal such as foundit / Naukri / LinkedIn; the adapter prefers the link marked `is_direct`). Add `JSEARCH_API_KEY` (RapidAPI "JSearch", or OpenWebNinja + `JSEARCH_BASE_URL`) to `.env`, recreate the container and fetch: those jobs skip every job board. A partner feed (`INDEED_FEED_URL`, `NAUKRI_FEED_URL`, or another portal's feed) gives direct links too.
* **Company job boards** (no key, always on) give **direct links only**: Apply Now -> `/jobs/ext/<id>/go` -> 303 straight to the job on the company's own careers page (`job-boards.greenhouse.io/...`, `jobs.lever.co/.../apply`, `jobs.ashbyhq.com/...`, `jobs.smartrecruiters.com/...`, or the company's site such as `databricks.com/company/careers/...`) - no job board in between. Tested 2026-10-23 on one job of each kind (Databricks, GitLab, CRED, OpenAI, Freshworks): 303 to the company host, the company page opens (SmartRecruiters answers a script with 403 - bot protection - and opens normally in a browser), the click line is saved.
  * Which companies: system parameter **`llmd_agg.company_boards`** (Settings > Technical > System Parameters) = a comma-separated list `provider:board` or `provider:board=Company name` (Lever and Ashby do not send the company name), e.g. `greenhouse:stripe, lever:paytm=Paytm, ashby:openai=OpenAI, smartrecruiters:Freshworks`. Not set = the built-in list of 42; **`off`** = the source is switched off. Jobs per company: `llmd_agg.company_boards_per_board` (default 15). The board token is the last part of the company's careers URL (`job-boards.greenhouse.io/<token>`, `jobs.lever.co/<site>`, `jobs.ashbyhq.com/<name>`, `jobs.smartrecruiters.com/<CompanyId>`). Check new candidates first with `python ..\rolelib\company_boards_probe.py` (answers, jobs in India, fitting roles). A board that does not answer is skipped (logged); the source fails only when no board answers.
  * Code: `fetch_company_boards` + one reader per provider in `models/sources.py`, the India / course filter `_company_keep` in `models/job_source.py`, unit tests in `rolelib/sources_test.py` (`CompanyBoardTests`).
* When the same job comes from several sources, **the version with the direct link is kept** (`listing.is_board_link`, rank in `_dedupe`), so a Jooble duplicate never replaces a direct JSearch link.

### Apply Now, the form and the click log (Recruitment -> Job Applications / Apply Clicks)

**Flow (default):** `third-party APIs -> Odoo (llmd.job.listing) -> Jobs page / details -> Apply Now -> click line in Odoo (Apply Clicks) -> the employer's original job page`, where the person applies. **Optional form mode** (`llmd_agg.apply_mode = form`): Apply Now -> our form -> applicant + resume + record in Odoo Recruitment (Job Applications); the employer link stays next to it.

**Why an external portal cannot fill Job Applications - the limitation.** When a visitor applies on the employer's / job portal's own site (Jooble, Adzuna, JSearch, Indeed, Naukri ...), they type their details *there*. The job-search APIs we read are one-way: they give us jobs, never the people who applied, and a click on a link tells us nothing about what was typed on the other site. So **no applicant record is ever made from a click** - Apply Clicks only says "somebody clicked Apply on job X at time T". Applicant details from a portal can only arrive through an authorized integration (a partner API, a webhook / callback, e.g. an ATS or "Indeed Apply" postback) that the provider offers; none of the three connected APIs offers one. What our system CAN really receive is: (1) applications typed into **our own form**, (2) applications of **Odoo's own form** for our positions, (3) applicants sent to our **API with a key**.

* **Our form (only in form mode)** = `/jobs/ext/<id>/apply` (name, email, phone *optional*, resume *optional*, message, consent). On submit, in one savepoint: the Odoo **applicant** (`hr.applicant`, filed under an unpublished position made for that job - `hr.job.llmd_listing_id`), the **resume** as its attachment (PDF / DOC / DOCX, real file content checked, max 5 MB) and the **Job Applications record** are saved; only then the confirmation `/applied` (signed link) says "received". If saving fails nothing is stored and no success is shown. The applicant's source in Recruitment is the job source (internal, never shown on the site).
* **Job Applications record** (`llmd.job.application`): Applicant Name, Email, Phone, Job Title, Company, External Job ID, Channel (*Our website (Odoo form)*), Application Status (*Received*), Application Date, plus internal source, original apply URL, resume count, message, links to the applicant / position / listing. **One record per job and person** (unique constraint on job + e-mail; the same person applying again - e-mail in any case - makes no second applicant or record; one browser can send at most 30 applications an hour; a hidden bot field is a silent no-op).
* **System parameter `llmd_agg.apply_mode`**: not set / `redirect` (**default**) = no form, Apply Now goes straight to the employer through the tracked redirect (the form routes answer 404); `form` = Apply Now opens our form. Switch it any time under Settings > Technical > System Parameters. In the default mode Job Applications only gets the applicants that really reach us (Odoo's own form of our positions, the provider API) - what a person types on the employer's site never comes back (see the limitation above).
* **Apply Now (default) / "Apply on the employer's website" (form mode)** = `/jobs/ext/<id>/go`. In this order: (1) one line is saved (model `llmd.job.click`, menu **Recruitment -> Apply Clicks**: time, job title, company, location, source (internal), **external job ID**, **original apply URL**, status *Clicked* / *No apply link*, repeat flag, random browser id in cookie `llmd_vid`), (2) the visitor gets a 303 redirect to the job's own application URL. **Every click is a line**; crawlers and link checkers are not clicks; one browser can add at most 120 lines an hour; if saving fails the visitor is sent on anyway. A click carries **no name, e-mail or phone** (not even for a logged-in user) and is never an application.
* **Applicant data from a provider - only with the API key.** `POST /api/llmd/applications` (JSON-RPC, `{"jsonrpc": "2.0", "method": "call", "params": {...}}`) needs the header `X-Api-Key` = `LLMD_APPLICATION_API_KEY` in `.env` or the system parameter `llmd_agg.application_api_key`. Without a valid key (or with the key empty = API off) **nothing is accepted**. With the key the provider sends `{"action": "applicant", "job": {"listing_id": 1} | {"source": "Jooble", "ext_id": "123"} | {"hr_job_id": 2}, "name": ..., "email": ..., "phone": ... (optional), "note": ... (optional), "provider_ref": ... (optional)}`; the record is saved exactly as sent (state *Confirmed*, channel *Job provider (API)*); what was not sent stays empty; the same person + job again updates the record. Problems are an answer (`{"ok": false, "error": "validation", "fields": {...}}`), never a 500.
* **The list fills itself.** Recruitment -> Job Applications shows Applicant Name, Email, Phone, Job Title, Company, External Job ID, Channel, Application Status, Application Date (newest first). A hook on `hr.applicant` makes one record for every Odoo applicant that has a job, the moment it is created: website form of one of our positions or of a job = **Our website (Odoo form)**, typed in the backend or created from an e-mail = **Added in Odoo / by e-mail**, API = **Job provider (API)**; edits of the applicant's name / phone / e-mail are copied (an e-mail another record of the job already uses is not taken over). Status: select rows -> **Confirm / Withdraw / Back to Received**, or click the status in the form; search by name, e-mail, phone, job, company, external ID; filters by status, channel, date.
* Files: `models/application.py` (applications, form service, API service, hooks), `models/click.py` (click log), `models/apply_utils.py` (validation, resume check), `models/listing.py` (`ensure_job`, `apply_mode`), `controllers/main.py` (routes), `views/apply_templates.xml`, `views/click_views.xml`, `views/application_views.xml`. History: 19.0.8 form + clicks merged into one record; 19.0.9 form removed, one line per click; 19.0.11 form back (switchable); now Apply Now goes straight to the employer by default and the form is only on with `llmd_agg.apply_mode = form`.

### Synchronization (reliability)

* **Retries:** every API call is retried up to 3 times for temporary failures only (network error, timeout, HTTP 429 / 500 / 502 / 503 / 504; waits 1 s, 2 s, `Retry-After` up to 10 s). A bad key (401 / 403) is never retried. Each retry is counted in the plan's request budget. Only the host is logged, never a key.
* **Safe synchronization:** one sync at a time (PostgreSQL advisory lock: a second sync returns at once); every job is saved in its own savepoint - one that cannot be saved is logged (`odoo.log`) and skipped, the others are stored; jobs are created or updated by (source, external job ID), so nothing is stored twice; nothing is hidden by a run in which no source delivered.
* **Log:** Recruitment -> Job board -> **Sync runs** (time, scheduled / by hand, new / updated / hidden / duplicates / errors, per-source result and the jobs that could not be saved).

### Commands (PowerShell in `local_odoo`; first `. .\env.ps1`)

```powershell
python ..\rolelib\board_test.py fetch      # read every connected source now
python ..\rolelib\board_test.py test       # 213 checks: sources, data, page + Location / Work mode filters, course -> role -> jobs -> See Details -> Apply Now (straight to the employer, no form), no site name, safety, the optional form mode (CSRF, validation, resume, duplicates, confirmation), click lines, the provider API, backend views (uses temporary test jobs that are deleted again)
python ..\rolelib\e2e_flow.py              # 40 steps with the REAL API: fetch -> save in Odoo -> Jobs page -> details (one Apply Now, no form) -> optional form mode -> Apply Now click saved -> straight to the employer page -> API only with the key (the test applicant is removed again; add --keep to keep the click lines)
python ..\rolelib\sources_test.py          # 35 adapter unit tests (Adzuna / JSearch / Jooble / Himalayas / company job boards / feeds) with canned answers, incl. the retries - no keys needed
python ..\rolelib\company_boards_probe.py  # asks the candidate company boards (real public APIs, no key): which answer, how many jobs in India fit the courses
python ..\rolelib\apply_test.py            # 12 checks: applicant data (name, e-mail, optional phone, consent only when asked) and the resume (type, size, real content, safe file name)
python ..\rolelib\summary_test.py          # 18 tests of the job summary (format, word limit, what is left out, list lead-in lines, the Key points timeline: headings, numbering, bold opening phrase, nothing invented) with real job texts
python ..\rolelib\about_test.py            # 12 tests of the "About the Role" points (cleaning + the 3 role points) with real job board snippets
python ..\rolelib\facets_test.py           # 12 tests: work mode / experience / job type / India / city worked out from job text
# the two ORM check files run inside Odoo (rolled back, nothing stored). In Git Bash: cat ../rolelib/orm_checks.py | docker compose exec -T -e DBN=llmd_local odoo sh -c '...' ; PowerShell 5.1 can add a byte-order mark to the piped text, which Odoo's shell rejects - use Git Bash then.
Get-Content ..\rolelib\orm_checks.py | docker compose exec -T -e DBN=$env:ODOO_DB odoo sh -c 'odoo shell -d "$DBN" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'
                                           # 35 checks: direct links only (section N), the sources combined, Remote / Hybrid / On-site, India, budgets, a failing source, the Himalayas fallback, Apply Now data
Get-Content ..\rolelib\orm_checks_app.py | docker compose exec -T -e DBN=$env:ODOO_DB odoo sh -c 'odoo shell -d "$DBN" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'
                                           # 60 checks: every click is one line, no applicant data in a click, our form (applicant + resume + record saved together, nothing on failure, no duplicates), channel, sync on edits, status buttons, list columns, the provider API (key only), the sync lock
# rolelib\course_checks.py: 14 checks of the course catalog; they need a database WITH eLearning, so they run in a throw-away scratch database (instructions at the top of the file) - done once, the scratch database was dropped again
```
(`board_test.py test` creates temporary test jobs ("zzds-..." and "ZZFX ...") and deletes them again at the end.)

## Job detail page from real job listings (module `llmd_job_aggregator`, local only)

Whenever a job is **created**, its **title or location changes**, or it is **published**, the module looks for the best-matching real listing and saves its sections on the job.
The job page then shows, **details on the left** - About the Role, Key Responsibilities, Required Skills, Qualifications & Requirements, Experience (and Nice to have) - and a sticky **Apply Now card on the right** (on a phone the card comes right under the title). Only sections the listing really has are shown; nothing is invented.

* **Primary source: Himalayas job API** (no key): full listing text + the listing link; searched with `country=IN` so the listing is open to India. If no listing open to India fits, the text of a listing from anywhere may still be used - then **no apply link is saved** and the button stays disabled.
* **Adzuna / Jooble** (optional, need your own free keys in `local_odoo\.env`: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`; then `docker compose up -d --force-recreate odoo`): they return only a short snippet, so they are used only when a snippet is all there is.
* **Apply Now** opens the listing link in a new tab (http/https only). No valid link -> the button is shown disabled with a note (set the system parameter `llmd_agg.fallback_apply` to `1` to use Odoo's own application form instead).
* A page somebody wrote **by hand** is never replaced (it keeps its text and gets one Apply Now).
* Employer names, products, salary, benefits, links and company-culture sentences are filtered out of the copied text; some employer-specific wording of the source listing can still remain - read each new page once.

Commands (PowerShell in `local_odoo`; first `. .\env.ps1`):

```powershell
python ..\rolelib\agg_test.py refetch 1 2 3 4        # fetch again for existing jobs
python ..\rolelib\agg_test.py create "Data Analyst"   # a new job: the page is filled right after creating it
python ..\rolelib\agg_test.py check 1 2 3 4           # saved sections + rendered page + Apply Now link
python ..\rolelib\agg_preview.py "Data Analyst"       # raw Adzuna / Jooble answers (needs their keys)
docker compose run --rm odoo odoo -d llmd_local -u llmd_job_aggregator --stop-after-init   # after changing the module's files
```

## What `test_local.ps1` checks (the older role-library approach)

1. Baseline of the application form and of the other pages before any change.
2. Installs the Application URL field, the role library (23 roles), the server action and the automation rule; installs the two extension views (URL field on the job form, **one** Apply Now button).
3. Existing jobs 1-4 (title re-saved), three new jobs, a title change: the saved record has the Job Summary card, Skills, Responsibilities, Must Have (and Nice to have when the listing has it); the generic cards and the "What's great in the job?" block are gone; the rating column is identical to before.
4. Rendered pages: title, location, summary, skills, cards, ratings, **exactly one Apply Now**; its link is the job's Application URL (new tab) when set, otherwise Odoo's own application form; `javascript:` or other non-http(s) URLs are ignored.
5. The application form still has the same fields, and the other pages are unchanged.

## What is needed for a faithful copy of the live site (not available to me)

1. **Database backup with filestore** (Odoo *Manage Databases -> Backup -> zip*, or your host's snapshot) - to restore into the local instance.
2. **Source of the custom modules** listed above (and `odoo_mcp_manager`), and whether live runs Community or Enterprise (Enterprise source needs your licence).
3. Hosting details (self-hosted / Odoo.sh) and who may update modules there.

Restore (once you have the zip): `docker compose down -v`, then restore it via `http://127.0.0.1:8070/web/database/manager` (set `list_db = True` in `odoo.conf` for that), copy the custom modules into a `addons/` folder and mount it in `docker-compose.yml`.

## Deploying to the live site safely (only after you approve)

State today: the live site **already has** (applied earlier at your request) the `x_apply_url` field, the role library parameter, server action 747 and automation rule 1. **Not** on live: the two extension views (Apply Now) - they were refused by the permission check.

1. **Back up first**: Odoo database backup (with filestore) or host snapshot. Keep `rolelib\originals.json` and `rolelib\view_3074_before.xml`.
2. **Local tests all green** (above) and you have looked at the pages in the browser.
3. **Staging**: restore the backup on a staging copy and run the same scripts there (`ODOO_URL` = staging URL, with its admin login). Check again.
4. **Production window** (quiet time). In a PowerShell opened for this only:
   ```powershell
   $env:MCP_KEY = '<live gateway key>'      # typed by you, not stored anywhere
   $env:ALLOW_PRODUCTION = 'yes'
   python ..\rolelib\install.py             # library + field + action + rule (idempotent)
   python ..\rolelib\views.py               # the two extension views
   python ..\rolelib\final_test.py touch 1 2 3 4
   ```
   Then `python ..\rolelib\final_test.py check 1 2 3 4` and `python ..\rolelib\snapshot.py after`, and open a job page.
5. **Rollback** (any time): `python ..\rolelib\views.py --off` (page exactly as before), `python ..\rolelib\install.py --disable` (rule off), or restore the backup. Pages of existing jobs keep their last saved text.
6. **Afterwards**: close the shell (the variables disappear) and **rotate the gateway key** - it was pasted into a chat.
