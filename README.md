# LLM Decode – Job Aggregator for Odoo 19 (local instance)

The complete source of the LLM Decode job board as it runs on the local Odoo 19 instance (addon `llmd_job_aggregator`, version **19.0.32.0.0**,
packaged 2026-10-24). It is the code that runs, not a copy of a document:

- **Job board** at `/jobs`: a worldwide board (Indian and international jobs, remote / hybrid / on-site). A landing page (search, categories, course-matched
  jobs, companies by region, all jobs with their filters) and results pages for a search, a category, a company, a place, a region, a course or a role; the
  directories `/jobs/categories` and `/jobs/regions`; real jobs from the working sources, de-duplicated.
- **Job details page** at `/jobs/ext/<id>`, with a job overview, key points shown as a numbered timeline, skills, similar jobs, and one Apply Now.
- **Apply Now** saves a line in *Recruitment > Apply Clicks*, then opens the employer's own application page.
- **Applications** come from:
  - our own application form, when switched on;
  - Odoo's form for our own positions;
  - an authorized provider API.

  All of them are saved in *Recruitment > Job Applications* and Odoo Recruitment.

Everything runs locally in Docker. Nothing in this package talks to or changes the live site.

---

## 1. Folder structure

```
LLMDecode_Odoo_Final/
├── odoo_addons/
│   └── llmd_job_aggregator/        the Odoo addon = website frontend + backend (the code Odoo loads)
│       ├── __manifest__.py         version, dependencies (website_hr_recruitment, mail), data files, website assets
│       ├── controllers/main.py     HTTP routes: /jobs board, /jobs/ext/<id> details, Apply Now redirect, application form, applicant API
│       ├── models/                 business logic (see the table below)
│       ├── views/                  QWeb website templates + backend views, menus, scheduled action, job sources
│       ├── static/src/css|js/      job board + job details styles (one font, one type scale), board interactions (filter sidebar / mobile drawer, instant filters, tabs, bookmarks, skeletons, sort menu)
│       ├── security/               ir.model.access.csv (access rules of the 6 models)
│       └── migrations/             data migrations 19.0.5 ... 19.0.20 (run automatically on "update")
├── docker/docker-compose.yml       PostgreSQL 16 + Odoo 19 (Odoo only on 127.0.0.1, database not published)
├── config/odoo.conf                Odoo server configuration (addons path, data dir, no database manager)
├── scripts/
│   ├── env.ps1                     loads .env into PowerShell, points the tools at the local instance
│   ├── setup.ps1                   one-command setup / update of the local instance
│   ├── seed_local.py               company address + the four positions of the live site (fresh database only)
│   ├── backup_local.ps1            database + filestore backup
│   ├── restore_local.ps1           restore into a new database (or replace, with confirmation)
│   ├── company_boards_probe.py     checks candidate company job boards against the public ATS APIs (no key)
│   ├── jsearch_probe.py            one real JSearch request with the key from .env (key never printed)
│   ├── temp_viewer_user.py         throw-away recruiter login for backend screenshots (odoo shell)
│   └── repair_site_images.py       puts Odoo's stock logo / favicon back if their files are missing (odoo shell)
├── tests/                          all test suites (see section 8) + gw.py (XML-RPC helper) + requirements.txt
├── docs/
│   ├── DEVELOPMENT_NOTES.md        the full development log of the local instance (design decisions, every version)
│   ├── LOCAL_CHANGES_AND_DEPLOY.md what changed locally and how it would be deployed (Hindi / English)
│   ├── LIVE_DEPLOY_PROMPT.md       the brief for a later deployment to the live site (not done - local only)
│   └── unapplied/sign_in_feature_patch.py   "sign in before Apply Now" - built, then taken out on request; NOT applied
├── .env.example                    every setting with placeholders - copy to .env
├── .gitignore                      keeps .env, backups and caches out of version control
└── README.md
```

### Where are the frontend and the backend?

**Run it from VS Code.** Open this folder in VS Code (`code .`): the task **Start local site** runs by itself (the first time VS Code asks
"Allow automatic tasks" - allow it). It starts Docker Desktop when it is not running, then PostgreSQL + Odoo, and opens the Jobs Explorer at
http://127.0.0.1:8070/jobs. Ctrl+Shift+B starts it again; *Terminal > Run Task...* has **Update addon (after a code change)**, **Stop local site**,
**Odoo log** and the tests. The same from PowerShell: `.\scripts\start_local.ps1`, `.\scripts\update_local.ps1`, `.\scripts\stop_local.ps1`. The
first install on a new computer is still `.\scripts\setup.ps1`.

There is **no separate frontend or backend application**. Odoo renders the website and serves the routes and the API from the same addon, so
both live in `odoo_addons/llmd_job_aggregator/`. Separate `frontend/` and `backend/` copies would not be loaded by Odoo and would drift from the
real code, so the package does not have them. This table shows where each part is:

| Part | Files |
|---|---|
| **Frontend: landing page** (`/jobs`): hero + search + popular searches, Explore by job category, Jobs matched to your LLM Decode courses (swapped in place), Companies by region (headquarters tabs), Latest Jobs (with a "Search all jobs with filters" link to `/jobs?view=all`) (shortcuts, Load More), Top 10 Countries Hiring, our open positions, Why LLM Decode + FAQ; the directories `/jobs/categories`, `/jobs/regions` and `/jobs/countries` | `views/board_templates.xml` (`landing_page`, `course_matches`, `results_main`, `company_card`, `category_directory`, `region_directory`, `latest_card`, `latest_batch`, `country_card`, `country_directory`, `job_card`), `static/src/css/llmd_jobs.css` (`.o_llmd_board`), `static/src/js/llmd_jobs.js` |
| **Frontend: results pages** (`/jobs?...`, `/jobs/category|company|location|role|region|course/<slug>`): breadcrumbs, heading, count, search, company strip, filter sidebar (drawer on small screens, experience slider, searchable lists, Apply Filters with the live count, Clear All), sort, chips, skeletons, job cards with View Details + Apply Now, pager | `views/board_templates.xml` (`results_page`, `job_card`), `static/src/css/llmd_jobs.css`, `static/src/js/llmd_jobs.js` |
| **Frontend: job details** (`/jobs/ext/<id>` and our own positions): breadcrumb, header card, Job Overview with the numbered key-points timeline, skills, facts, sticky Apply card, similar jobs | `views/job_view.xml` (shared layout), `views/board_templates.xml` (`board_detail`), `views/templates.xml` (our own positions), `static/src/css/llmd_jobs.css` (`.o_llmd_view`) |
| **Frontend: application form** (only when the form mode is on) + confirmation | `views/apply_templates.xml` |
| **Backend: routes and API** | `controllers/main.py` – `/jobs` (landing / results), `/jobs/category|company|location|role/<slug>`, `/jobs/course-matches`, `/jobs/results-count`, `/jobs/ext/<id>`, `/jobs/ext/<id>/go` (Apply Now click), `/jobs/position/<id>/go`, `/jobs/ext/<id>/apply` + `/applied` (form), `POST /api/llmd/applications` (provider API, `X-Api-Key`) |
| **Job fetching** (API integrations) | `models/sources.py` (Company job boards: Greenhouse / Lever / Ashby / SmartRecruiters, plus Adzuna, JSearch, Jooble, Himalayas, Indeed / Naukri partner feeds; retries, budgets), `models/job_source.py` (source records, status, which jobs to keep) |
| **Synchronization + de-duplication** | `models/listing.py` (`fetch_now`: stores, updates, hides; de-duplication on title + company + city; direct links only), `models/sync.py` (sync-run log), daily scheduled action in `views/listing_views.xml` |
| **Course-to-job matching, search, filters** | `models/board_config.py` (course profiles, roles, tracks, query list), `models/courses.py` (courses read from the site's eLearning data), `models/job_facets.py` (work mode, experience, job type, India, city from the job text), `models/vocab.py`, `models/course_snapshot.json` (the course page texts), `controllers/main.py` (`_llmd_state`, `_llmd_domain`, `_llmd_ranked`, `_llmd_results`, `_llmd_landing`, `_llmd_recommend`) |
| **Job text → summary + key points** | `models/parsers.py` (sections of a job text), `models/summary.py` (overview, key points, headings, bold lead phrase), `models/view_helpers.py` |
| **Apply Click tracking** | `models/click.py` (`llmd.job.click`), `views/click_views.xml` (Recruitment > Apply Clicks) |
| **Applications + Odoo storage** | `models/application.py` (`llmd.job.application`, hooks on `hr.applicant`), `models/apply_utils.py` (form + resume checks), `views/application_views.xml` (Recruitment > Job Applications) |
| **Our own positions** | `models/hr_job.py` (`llmd_content`, apply link), `views/hr_job_views.xml`, `views/templates.xml` |
| **Security** | `security/ir.model.access.csv` |

**"Jobs Explorer" (v19.0.28).** The board is called **Jobs Explorer** on the website: the browser title and the badge of the landing page, the breadcrumb
of every board page (results, directories, job details), the website menu and the footer (the menu and footer of the local site come from
`scripts/local_branding.py`). A label only: every route (`/jobs`, `/jobs/...`), URL, model and API stays as it was; the backend menu
*Recruitment > Job board* is unchanged.

**No Sync runs screen (v19.0.28).** The *Sync runs* menu, its page and the "Fetch jobs now" buttons are gone from the backend; the daily scheduled
action, the API integrations and the sync history (`llmd.job.sync`, read by the website's "Updated ... ago") stay. A sync now reads SmartRecruiters details 3 at
a time per board and 8 boards at a time, so that it ends well inside Odoo's 900 s limit of a request / scheduled action.

**Job skills in Odoo's skill system (v19.0.31).** No job API sends a list of skills (Greenhouse, Lever, Ashby, SmartRecruiters were checked; JSearch,
which may, does not answer): a job's skills are read from its own text (`skill_keys`, the parser's vocabulary in `models/vocab.py`). Every sync now also
links each job to Odoo skills (`llmd.job.listing.skill_ids`, `link_odoo_skills()`, `models/skill_map.py`), in three separate kinds:
**Technical Skills** - a skill type of its own (made by the first technical skill a job mentions, with the levels Beginner / Intermediate / Advanced /
Expert), holding only the technical names of the vocabulary that jobs really mention; **Languages** and **Soft Skills** - Odoo's own records, matched by name
("Mandarin" = "Mandarin Chinese", "problem solving" = "Problem-Solving"), never created. Business skills (sales, marketing, HR ...) and free lines stay on the
website only. A skill is created once and reused; only job listings are linked - no applicant or employee gets a skill from a job. The listing form shows
the three kinds; the list can show them and be searched by Odoo skill. The migration 19.0.31.0.0 links the stored jobs.

**One list of applications.** Odoo's own menu *Recruitment > Applications > All Applications* is hidden by this addon (`views/application_views.xml`,
`active = False` on `hr_recruitment.menu_crm_case_categ_all_app`): **Job Applications** is the one list of submitted applications and **Apply Clicks** the
one list of clicks. Only the menu item is switched off - its window action, the `hr.applicant` model and records, "By Job Positions" and every workflow stay.

**Posted Type, Application Type, Experience Required (v19.0.30).**
- **Posted Type** (Job board listings, Job Applications, Apply Clicks): *Fetched* = the job came from an external API / provider (every job board listing);
  *Public User* = one of our positions created by a portal / public website user (`hr.job.llmd_posted_type`, from its creator). A position our own team
  created is neither and stays empty. There is no page where a public user can post a job, so no such job exists today.
- **Application Type**: *Website Form* on a Job Applications record sent through our website's form (channel "Our website"); *External Apply Click* on an
  Apply Clicks line whose visitor was sent on to the original application page. A click never becomes a Job Applications record; an application from a
  provider or entered in Odoo has no Application Type.
- **Experience Required**, **Department**, **Job Type** on Job Applications, copied from the job when the application is saved: experience = the years a
  sentence about experience states ("3–5 yrs"), else the provider's own label as it sent it ("Mid-Senior Level"), else the years a requirement line states as
  written ("2–5 years in DevOps ..." -> "2–5 years", v19.0.32), else "Fresher" / "Entry Level" when the title says so, else empty (nothing guessed). The
  migration 19.0.32.0.0 fills the applications whose Experience Required was empty from their job; values already there are kept. The migration 19.0.30.0.0
  fills them for the stored records from their jobs; no record is added or removed. Test: `tests/types_checks.py` (odoo shell, rolled back).

**No personal data in Apply Clicks, no phone in applications (v19.0.29).** A line of *Recruitment > Apply Clicks* holds the job only: click time,
job title, company, source, external job ID, original apply URL and status - never a user, name, e-mail or phone, also not of a logged-in user (the
19.0.28 columns for that are dropped by the migration 19.0.29.0.0; every click line stays). Apply Now still sends the visitor straight to the original
application page. *Job Applications* show the name and e-mail of a real application (our form, Odoo's form of our positions, or a provider): no phone
field, no phone in the validation, the form, the API payload or the record (the migration drops the column and empties the phone of the linked Recruitment
applicants; every application stays). A click never creates an application. Test: `tests/click_user_test.py` (local portal account of
`scripts/local_test_user.py`).

**Dark theme, China & Hong Kong, languages (v19.0.28).**

- **Design**: every board page (landing, results, directories, job details, application form) is in one dark theme - near-black navy surfaces in layers,
  violet accents with a little electric blue, soft glows, one font (Manrope). The header and footer of exactly these pages are dark too (`body:has(...)` in
  `static/src/css/llmd_jobs.css`); other pages of the site keep their theme. Motion: the hero content rises in steps, a slow aurora moves behind the hero,
  the heading accent shimmers, sections and cards fade up once as they scroll in (`revealBlocks` in `llmd_jobs.js`), cards lift with a lit edge, dropdowns
  and filter sections open smoothly, skeletons while results load. All of it stops with the reduced-motion setting.
- **Landing order**: hero + search -> categories -> course-matched jobs -> Latest Jobs -> Companies by region -> Top 10 countries -> Why LLM Decode + FAQ.
  The full search with its filters is `/jobs?view=all` (and every results page).
- **China & Hong Kong** is a region of its own (Mainland China, Hong Kong, Macau; Taiwan stays in Asia-Pacific), with more Chinese cities and "PRC".
  New company job boards (each checked live, public API): NetEase Games, XPENG, WeRide, Lalamove, HoYoverse, ByteDance (headquarters in China / Hong Kong),
  and OKX, Bybit, SHEIN, Airwallex, PingCAP, Baidu USA, BYD North America. Headquarters are listed only where verified (`board_config.COMPANY_HQ`).
  Abroad, each company's jobs are now picked **country by country** (`sources._by_country`), so a company hiring in many countries shows its Hong Kong
  and Shanghai jobs too, not only its newest country.
- **Languages** (`models/language.py`): `source_lang` = `zh` (the listing is in Chinese) or `zh-title` (only the title; the description is English), and
  `languages` = the languages the job text asks for, each *required* or *a plus* (English only when the text asks for it). Cards show "Listed in Chinese" /
  "Chinese title" and e.g. "Mandarin"; the detail page has a Languages row and a note. **No translation service is configured**, so Chinese text is shown as
  the employer wrote it - nothing is machine-translated or made up.
- **Cards** show the job's region next to its place; the detail page shows the region in its header.
- **Local branding** (`scripts/local_branding.py`, LOCAL database only): the header brand "LLM Decode", the menu Home / Courses / Job Board / Resources /
  Contact us (Courses and Resources = the public pages of learn.llmdecode.com) and a footer with the same navigation. The live site has its own.

**Latest Jobs and Top 10 Countries (v19.0.27).** Two sections of the landing page, after "Companies by region" and before "Why LLM Decode" (the "Browse all jobs" listing was taken off the landing page afterwards: Latest Jobs already shows the newest jobs, and its "Search all jobs with filters" link opens the full search with its filters at `/jobs?view=all`):

- **Latest Jobs** - "Fresh opportunities from companies worldwide": the newest jobs by their real posting date (a job without a date comes last and says
  "No posting date"; "New" only for a job really posted in the last 3 days), "Updated N minutes ago" = the end of the last sync that brought jobs (from the
  sync log, exact time in the tooltip), category shortcuts ("All jobs" + the 8 biggest categories, counted live), small cards in a 3 / 2 / 1-column grid
  (logo initial, title, company, city + country, work mode, job type, experience, three skills, posting date, View Details) and **Load More Jobs**: the next
  12 from **`/jobs/latest?page=<n>&category=<slug>`** (the button and the shortcuts fetch it in place; without JavaScript they reload the landing page with
  `?latest=<n>&latest_cat=<slug>`). The batches follow one fixed order, so no job comes twice.
- **Top 10 Countries Hiring** - the 10 countries with the most jobs (every work mode; Indian and international companies), each with its flag, name and
  number of jobs, opening `/jobs/location/<country>`; **Explore All Countries** opens **`/jobs/countries`**: every country with jobs, by region, searchable,
  with a separate **Remote only** view (`?mode=remote`, its own counts, its cards open the country with the remote filter). The flags are emoji drawn with
  the Noto Color Emoji font from Google Fonts (only the needed flags are loaded; Windows has no flag emoji of its own).

**A worldwide board (v19.0.26).** On 2026-10-25: 4,275 jobs - 1,633 in India and 2,642 in 53 other countries (United States 1,362, United Kingdom 181, Singapore 84 ...) - from 81 companies; on-site 2,827, remote 924, hybrid 524. Indian AND international jobs, remote, hybrid and on-site, from the companies' own job boards - not India only and not
remote only.

- **Sources:** the only working provider is still *Company job boards* (Greenhouse, Lever, Ashby, SmartRecruiters public APIs; 81 companies). It now
  keeps a company's jobs everywhere: per company and sync at most **100 in India** (`llmd_agg.company_boards_per_board`) and **50 elsewhere**
  (`llmd_agg.company_boards_per_board_world`, new), the newest of each. SmartRecruiters boards are read in pages: all their postings in India, then the
  first 300 worldwide (polite pauses between pages and detail requests). JSearch answers 401 (its key), Adzuna / Jooble / Himalayas stay off (direct
  links only), Indeed / Naukri have no feed - so they add nothing. The board never promises a number: it shows what the sources give.
- **Where a job is:** country, city and region are read from locations all over the world (`job_facets`: country names and ISO codes, big cities, US /
  Canadian / Australian state codes, "Remote - Europe", "APAC"); a location that names no country gives no country and no region. A world city never makes a
  job "in India".
- **Order:** without a keyword or course ("Most relevant") the newest job in India and the newest abroad come one after the other, so every page shows
  both; "Most recent" is by date only. Until v19.0.25 jobs in India came first.
- **Categories:** 18 now (+ Cybersecurity, Hardware & Embedded, Legal & Compliance, Supply Chain & Logistics, Healthcare & Life Sciences, Administration &
  Office, Education & Training). The landing page shows the 8 with the most jobs and **"Explore all N categories"** opens **`/jobs/categories`**: every
  category that has jobs (none without), most jobs first, with its jobs and companies, searchable. A category appears there as soon as a sync brings jobs
  for it.
- **Companies by region** (landing page): the companies grouped by where they have their **headquarters** (`board_config.COMPANY_HQ`: well-known public
  facts, kept in the code because no source sends them; a company that is not listed shows under "Headquarters not verified"), one tab per region, every
  company with its number of jobs; a company opens all its jobs, in India and abroad. Headquarters are not job locations: an American company hiring in
  Bengaluru stays under North America.
- **Explore all regions** opens **`/jobs/regions`**: every world region that has jobs - by where the JOBS are - with its countries (each a
  `/jobs/location/<country>` page), the regions of India, the companies hiring there (`/jobs/company/<company>?region=<region>`), how many jobs name no
  country, and which regions have none at the moment.
- **The landing page** now also holds the listing with its filters ("Browse all jobs" = the first page of `/jobs?view=all`), instead of "Latest jobs".
- Backend *Job board listings*: the columns Company headquarters / Company region and the groups "Company headquarters region" and "Country".
- The migration `19.0.26.0.0/post-worldwide.py` reads every stored job's location, category and company headquarters again.

**Course out of the filters, jobs by region (v19.0.25).**

- **No course in the general filters.** The filter panel, the active-filter chips and the search have no course control any more. A course is chosen only in
  "Jobs matched to your LLM Decode courses" on the landing page (catalogue, course matching and recommendations unchanged). Its "View all N course-matched
  jobs" opens the course's own page **`/jobs/course/<course>`** (heading "Jobs matched to ...", what the course teaches, "Choose another course"), where the
  general filters narrow the course's jobs like on a category page; "Clear all" stays on that page. Old links `/jobs?course=<code>&...` move there (301) with
  their other filters; `?course=` is no filter parameter any more (`/jobs/results-count` takes `scope=course&scope_value=<code>`).
- **"Explore jobs by region"** replaces the city / country cards of the landing page. Every job gets a stored **world region** (`region`: Global / Worldwide,
  India & South Asia, Asia-Pacific, Europe, North America, Latin America, Middle East & Africa - from the country its location names, `job_facets.region_of`)
  and, in India, a **region of India** (`india_zone`: North, South, West, East & Central India - from its city, else the state or the state code of the
  location, `job_facets.india_zone_of`). A location that names no country gives no region; a job that only says "India" / "Remote - India" is in India &
  South Asia but in no region of India - the section says how many. Only regions with jobs are shown, each with its real count (the jobs are already one
  record per vacancy, so a job counts once). On 2026-10-25 every job is in India: India & South Asia 1,609; South India 1,079, North India 221, West India
  162, East & Central India 14; 133 name no city or state.
- **Region pages** `/jobs/region/<region>` (and `/page/<n>`) for every world region and region of India, with all the general filters; a **Region** select
  (`?region=<slug>`) in the Location section of every other results page; a typed location such as "South India" or "Europe" means that region. Work mode
  (remote / hybrid / on-site) stays a separate filter. Unknown region / course -> 404.
- On a region, course, company, location or role page the category pills filter that page (with its counts) instead of leaving it.
- Backend: *Job board listings* has the columns Region / Region of India and the groups Region, Region of India. The migration `19.0.25.0.0/post-regions.py`
  fills them for every stored job.

**More jobs (v19.0.24).** The board went from about 300 to about 1,600 real jobs (2026-10-25: 1,613 visible, 80 companies), all from the companies' own
job boards with direct application links:

- **81 company job boards** (`board_config.COMPANY_BOARDS`): the 42 of before plus 39 more that were checked live against the providers' public APIs
  (`scripts/company_boards_probe.py`), e.g. Swiggy, ServiceNow, Pure Storage, Glean, Fivetran, Netskope, Toast, Agoda, ClickHouse, SigNoz, SpotDraft, FamPay,
  Nium, Harvey, Notion. A board without jobs in India is not listed.
- **Which jobs are kept** (`board_config.board_relevant`): a job in India (or remote from India) whose title names a course role or course track, OR that
  falls into one of the 11 job categories (title, else role, else the company's department) - so finance, HR, operations, product, support and IT jobs of these
  companies are on the board too. Never: plant / workshop / field work, driving, care, kitchen, freelance gigs (`board_config.NON_OFFICE`).
- **Up to 100 jobs per company** and run (`COMPANY_PER_BOARD`, system parameter `llmd_agg.company_boards_per_board`), the newest first. SmartRecruiters
  boards are read page by page and only their postings in India (`country=in`): before, only the first 100 postings of a company worldwide were read.
- **Closed jobs go at once:** every sync notes all the postings each company board lists; a stored job its board no longer lists (the company closed it) is
  hidden in that same sync, so Apply Now never opens a closed job. A board that did not answer, or only partly, hides nothing.
- **Backend = website:** every job on the website is a record of *Recruitment > Job board > Job board listings* (the website reads nothing else). The list
  now has the columns Category, Experience, Work mode, Job type, Page on the website, and filters / groups by Category, Company, Source, Work mode, City,
  "Posted in the last 7 days", "Hidden (not on the website)".
- **Click check** `tests/link_check.py`: opens every board page and every link on them, every job's View Details and Apply Now (as a link checker: it saves
  no Apply click) and a polite sample of the companies' application pages.
- One sync now takes about 7 minutes (about 1,700 jobs with full text); the daily scheduled action runs it in the background.

**The job board (v19.0.23): a landing page and results pages.** The layout follows the structure of large job boards (landing page with one search, then
results with filters on the left). Only the structure was used as a reference: no other site's branding, job data, counts, code or assets are used. Every
number on the pages is counted from the jobs stored in Odoo.

- **`/jobs` – landing page**, in this order:
  - hero with ONE search (keyword: title, skill, company; location: city or country) and "Popular searches" (the 6 course roles with the most jobs, each a
    `/jobs/role/<role>` page);
  - **Explore by job category**: a card per category with its number of jobs → `/jobs/category/<slug>`;
  - **Jobs matched to your LLM Decode courses**: one button per course of the catalog; the 6 closest matches of the chosen course and "View all N
    course-matched jobs" (`/jobs/course/<code>`, since v19.0.25). The button swaps the block in place (`/jobs/course-matches?course=<code>`); without JavaScript it reloads
    with `?rec=<code>`;
  - **Top companies hiring** (the 12 with the most jobs) → `/jobs/company/<slug>`;
  - **Open positions at LLM Decode** (our own published positions, only when there are any);
  - **Latest jobs**: the 9 newest, with pages (`?latest=2`) and "Browse all jobs";
  - **Explore jobs by region** (since v19.0.25; before: cities and countries): world regions and regions of India → `/jobs/region/<region>`;
  - **Why search jobs on LLM Decode** + 5 questions (what the board really does; no numbers).
- **Results pages** – one template (`results_page`) for `/jobs?...` (a search or filters), `/jobs/category/<slug>`, `/jobs/company/<slug>`,
  `/jobs/location/<slug>` (a city, `delhi-ncr`, a country such as `india`, or `remote`) and `/jobs/role/<role>`, each with `/page/<n>`:
  - breadcrumbs, heading, description, the count, the keyword + location search (keeps the other filters);
  - "Companies hiring" for these results: a click adds or removes that company, the category and the other filters stay;
  - filters on the left (a drawer on small screens): Location (region, country, then its cities; no course since v19.0.25), Experience (0–25+ years, two handles,
    Reset; only jobs that state years match a narrower range, and the panel says how many do), Work mode, Job Type (Full-time, Part-time, Internship,
    Contract), Time Posted (Any time, 24 hours, 7 days, 30 days), Category, Job Function, Role / Designation, Skills, Company (the last three can be
    searched). Every option shows its real count with the other filters applied;
  - **Apply Filters** shows how many jobs the chosen filters give before it is pressed (`/jobs/results-count`); **Clear All** stays on the page (a category, a course page ...);
  - sort: Most relevant (the search words in the title first, then the terms the course teaches, then jobs in India, then the newest) or Most recent;
  - removable chips, skeleton cards while loading, an empty state, pages that keep every filter.
- **Removed on purpose:** the Salary Range filter (the salary stays in the job records and on the detail page) and Freelance. **Not offered:** Industry and
  Company size – no working source gives them, and the panel says so instead of guessing.
- **Job cards** everywhere: company initial, category (a link), title, company (a link to its page), location, job type / work mode / years, up to 3
  skills, "Matches your course: ..." when a course is chosen, posted date, **View Details** and **Apply Now**. Apply Now is the tracked link
  `/jobs/ext/<id>/go`: the click is saved in Apply Clicks, then the original application page opens. A click is never counted as an application.
- **Categories** (`board_config.JOB_CATEGORIES`, one per job): AI & Machine Learning, IT & Software, Data & Analytics, Solutions & Pre-sales, Sales &
  Business Development, Marketing & Growth, Customer Support & Success, Product & Design, Finance & Accounting, People & HR, Operations & Strategy. The title
  decides first (ordered rules), then the course role, then the company's department. Old links `/jobs/category/engineering` and
  `/jobs/category/business-operations` move permanently (301) to `it-software` and `operations`.
- **Course matching:** which jobs a course leads to is unchanged (course → role profiles → jobs). New: each course's own page text (USPs, roadmap, outcomes,
  curriculum; `models/course_snapshot.json`, captured from the public course pages – no prices or ratings) gives the terms it teaches
  (`board_config.COURSE_TERMS`); each job stores the terms its text names (`term_keys`). Shared terms rank the course-matched jobs and explain them on the
  card. With the eLearning module installed, the terms come from the course's description and lesson names instead.
- **Menu:** the website's Jobs menu stays marked active on every board page (`models/website_menu.py`).
- New stored field: `term_keys`. The migration `19.0.23.0.0/post-recategorize.py` recomputes every job's category and job function.

---

## 2. How it works

```
 Company job boards (public ATS APIs, no key)  ┐
 Adzuna / JSearch / Jooble / feeds (optional)  ├─► llmd.job.source ──► fetch_now (daily scheduled action, or "Fetch jobs now")
                                               ┘        │                 keep India + course-relevant jobs, direct links only,
                                                        │                 de-duplicate (title + company + city), parse + summarise
                                                        ▼
                                              llmd.job.listing (PostgreSQL)  ◄── llmd.job.sync (one log line per run)
                                                        │
             /jobs  board: search, course → role, skills, location, work mode, sort  ─► /jobs/ext/<id>  details
                                                                                              │
                         Apply Now ─► /jobs/ext/<id>/go ─► llmd.job.click saved ─► 303 to the employer's own application page
             (form mode) Apply Now ─► /jobs/ext/<id>/apply ─► hr.applicant + resume + llmd.job.application saved, then "received"
             provider / ATS ─► POST /api/llmd/applications (X-Api-Key) ─► llmd.job.application
```

- **Database:** PostgreSQL 16 holds all records. Attachments, such as resumes, are in the Odoo filestore (Docker volume `llmd_odoo`).
- **Models:**
  - `llmd.job.source`: the sources and their status
  - `llmd.job.listing`: the jobs
  - `llmd.job.sync`: the sync runs
  - `llmd.job.click`: Apply Now clicks
  - `llmd.job.application`: the applications
  - `llmd.course.catalog`: the courses
  - plus extensions of `hr.job` and `hr.applicant`
- **Direct links only (default):** Apply Now always opens the employer's own page. Sources whose links open their own pages first (Adzuna, Jooble, Himalayas) are switched off, and their old jobs are hidden, never deleted.
- **What a click can't capture:** what a visitor types on an employer's site never comes back to Odoo. A click line therefore never contains applicant data. Applicant data comes only from:
  - our form;
  - Odoo's own form;
  - the key-protected provider API.

---

## 3. Prerequisites

- **Windows 10/11 with PowerShell 5.1+.** The scripts are PowerShell. Other systems can run the `docker compose` and `python` commands directly.
- **Docker Desktop** (engine running), plus about 3 GB free disk for the `odoo:19.0` and `postgres:16-alpine` images.
- **Python 3.10+** on your computer, for the tests and tools: `pip install -r tests\requirements.txt` (only `requests`).
- **Internet access** for fetching jobs from the public company job board APIs.

---

## 4. Configure

All commands run in PowerShell **from the package root** (`LLMDecode_Odoo_Final`).

**New instance:** `scripts\setup.ps1` creates `.env` from `.env.example` and gives `POSTGRES_PASSWORD` and `ODOO_PASSWORD` random local-only values. To do it by hand:

```powershell
Copy-Item .env.example .env      # then replace both "change-me" values
```

**Your existing local database:** copy the `.env` that created it into the package root, so the passwords match:

```powershell
Copy-Item <your old local_odoo folder>\.env .env
```

**API credentials** are all optional. The default source, Company job boards, needs no key. The settings in `.env` are explained line by line in `.env.example`. You can also enter them in Odoo:

1. Open **Settings > Technical > System Parameters** (developer mode: `http://127.0.0.1:8070/odoo/action-base.ir_config_list_action?debug=1`).
2. Use the parameter names `llmd_agg.adzuna_app_id`, `llmd_agg.adzuna_app_key`, `llmd_agg.jsearch_api_key`, `llmd_agg.jooble_api_key` or `llmd_agg.application_api_key`.

Never commit `.env`, never paste keys in a chat, and never use production passwords here.

**Switches** (System Parameters, all optional):

| Parameter | Values | Effect |
|---|---|---|
| `llmd_agg.apply_mode` | empty / `redirect` (default), `form` | `form` = Apply Now opens our application form (saved in Odoo) next to the tracked employer link |
| `llmd_agg.direct_links_only` | empty / `1` (default), `0` | `0` = also use sources whose links open a job board page first |
| `llmd_agg.company_boards` | empty (built-in 81 boards), `provider:board=Name,...`, `off` | which company job boards are read |
| `llmd_agg.company_boards_per_board` | number (default 100) | max jobs per company in India |
| `llmd_agg.company_boards_per_board_world` | number (default 50) | max jobs per company outside India |
| `llmd_agg.himalayas_mode` | `fallback` / `always` / `off` | the keyless remote-jobs fallback source |
| `llmd_agg.fallback_apply` | `1` | our own positions without a valid link use Odoo's application form |

---

## 5. Start the instance

There is **no separate frontend or backend server to start**. Odoo serves the website, the routes and the API.

**First time (new instance):**

```powershell
.\scripts\setup.ps1
```

This checks Docker, pulls the images, starts PostgreSQL, creates the database `llmd_local` with *Website Recruitment* and the addon (no demo data), starts Odoo, and seeds the company. It takes 10–15 minutes the first time. If the database already exists, it only updates the addon and seeds nothing.

**Day to day:**

```powershell
docker compose --env-file .env -f docker\docker-compose.yml up -d        # start
docker compose --env-file .env -f docker\docker-compose.yml stop         # stop (data stays)
docker compose --env-file .env -f docker\docker-compose.yml logs -f odoo # Odoo log
```

**Volumes are shared with the original folder.** The project name `llmd-local` and its volumes are the same as in the original `local_odoo` folder. Running `up -d` here takes over the existing local database and mounts the addon from this folder; no data is copied. Do this whenever the containers were last started from another folder.

**Never use `down -v`** unless you want to delete the database and filestore.

**A second, separate instance:** set `COMPOSE_PROJECT_NAME` and a free `ODOO_PORT` in its `.env`.

---

## 6. Install or update the addon

```powershell
. .\scripts\env.ps1
docker compose --env-file .env -f docker\docker-compose.yml run --rm odoo odoo -d $env:ODOO_DB --db-filter="^$($env:ODOO_DB)$" -u llmd_job_aggregator --stop-after-init
docker compose --env-file .env -f docker\docker-compose.yml restart odoo
```

- **New database:** use `-i 'website_hr_recruitment,llmd_job_aggregator' --without-demo=all` instead of `-u ...` (keep the quotes in PowerShell), or simply run `scripts\setup.ps1`.
- **After `-u`:** migrations in `migrations/` run automatically. Version 19.0.20 rebuilds the stored job summaries.
- **CSS / JS changes** need the Odoo restart; that is when the website asset bundle is rebuilt. In the browser, press Ctrl+F5.
- **Backend alternative:** Apps > *LLM Decode - Jobs from the job APIs* > Upgrade (developer mode).

---

## 7. Open the website and Odoo

| What | URL |
|---|---|
| Job board | http://127.0.0.1:8070/jobs |
| A job category | http://127.0.0.1:8070/jobs/category/engineering (also `data-analytics`, `solutions-presales`, `sales`, `marketing`, `product-design`, `customer-success`, `business-operations`) |
| A job's details | http://127.0.0.1:8070/jobs/ext/&lt;id&gt; (click **See Details** on a card) |
| Odoo backend | http://127.0.0.1:8070/odoo (user `admin`, password = `ODOO_PASSWORD` from `.env`) |
| Jobs in the backend | Recruitment > Job board > Job board listings (button **Fetch jobs now**), Recruitment > Job board > Sync runs |
| Apply Now clicks | Recruitment > Apply Clicks (list, form, search, pivot, graph) |
| Applications | Recruitment > Job Applications; Recruitment > Applications (Odoo's own) |

---

## 8. Testing

```powershell
. .\scripts\env.ps1                      # every session: loads .env, ODOO_URL = http://127.0.0.1:<ODOO_PORT>
pip install -r tests\requirements.txt    # once
```

**Job fetching (real data):**

```powershell
python tests\board_test.py fetch
```

This reads every connected source now and stores the jobs. The daily scheduled action, or **Fetch jobs now** in the backend, does the same. The result per source is under *Sync runs*.

**Whole website + data:**

```powershell
python tests\board_test.py test
```

318 checks on the current local data (result on 2026-10-24, v19.0.23: **318/318**). The suite also creates a temporary published position when the database has none, to check "Open positions at LLM Decode", and removes it again. They cover:

- sources, normalization and de-duplication;
- the landing page: hero search (an empty search shows all jobs), popular searches, every category card count, the course buttons and the course-matched block of every course (ranking by what the course teaches, "View all" = the results page, no-JS fallback), top companies, latest jobs and their pages, every location card and its page, why + FAQ without numbers, one font, the active Jobs menu;
- the results page: every filter and its counts (course, country / city, experience slider, work mode, job type, time posted, category, function, role, skills, company), no Salary / Freelance / Industry / Company size, the live count of Apply Filters, sort, chips, Clear all (keeps the course), pages, empty state;
- 20 filter combinations on all jobs and 10 inside a category, each checked against the database and against `/jobs/results-count`; known answers for location and work mode with 8 temporary jobs; jobs in India first;
- every category page walked page by page, the old category links (301), the company strip (a toggle that keeps the category and the other filters), company, location and role pages, unknown slugs (404);
- course → role → jobs → View Details → detail page (breadcrumb with the category, company link, the numbered key-points timeline, similar jobs, ONE Apply Now with no site name);
- Apply Now from a card and from the detail page → click saved → 303 to the employer, never an application;
- the form mode: CSRF, validation, resume, duplicates, the record saved before "received";
- the provider API (key only) and the backend views;
- cleanup of every temporary test record.

**End to end (real API):**

```powershell
python tests\e2e_flow.py
```

40 steps (**40/40**): fetch → save in Odoo → Jobs page → details → Apply Now click saved → employer page → form mode → applicant + Job Applications record → API with key only. It removes its test records again; add `--keep` to keep the click lines.

**Database persistence (ORM checks).** These run inside Odoo in one rolled-back transaction, so nothing is stored. Run them in Git Bash; PowerShell 5.1 can add a byte-order mark that Odoo's shell rejects.

```bash
cat tests/orm_checks.py | docker compose --env-file .env -f docker/docker-compose.yml exec -T -e DBN=llmd_local odoo sh -c 'odoo shell -d "$DBN" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'
cat tests/orm_checks_app.py | docker compose --env-file .env -f docker/docker-compose.yml exec -T -e DBN=llmd_local odoo sh -c 'odoo shell -d "$DBN" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'
```

- `orm_checks.py`: 35 checks (**35/35**) of sources, direct links only, India, budgets and failing sources.
- `orm_checks_app.py`: 60 checks (**60/60**) of click lines, the form transaction, the Job Applications sync, status buttons, the API and the sync lock.

Two tracebacks in their output ("boom", "this job cannot be saved") are deliberate failure tests.

**Unit tests** need no Odoo and no network:

```powershell
python tests\sources_test.py ; python tests\summary_test.py ; python tests\about_test.py ; python tests\facets_test.py ; python tests\apply_test.py
```

Results: 35, 18, 12, 16 and 12 tests, all OK. Also `python tests\categories_test.py`: 12 tests of the 11 categories, job function, years, country and skill rules with real titles and departments, the course-term vocabulary and the URL slugs.

**Courses from eLearning:** `tests\course_checks.py` (14 checks, **14/14**) needs a scratch database that has eLearning installed. The steps are at the top of the file.

**Note after a fresh setup:** the daily sync job runs once right away and takes about a minute. Wait until *Recruitment > Job board > Sync runs* shows it finished before running `board_test.py`; `fetch` reports "another sync is already running" until then.

**Try it by hand:**

1. **Filters:** on `/jobs`, pick a course, then a role, a location such as *Delhi NCR*, and a work mode. The count and the chips must match the cards.
2. **Apply Now:** open a job, click **Apply Now**. The employer page opens in a new tab, and a new line appears in *Recruitment > Apply Clicks*.
3. **Application submission:**
   1. Set the System Parameter `llmd_agg.apply_mode` = `form`.
   2. Open a job, then **Apply Now** → the form.
   3. Submit name, e-mail and an optional resume.
   4. The applicant appears in *Recruitment > Applications* and in *Recruitment > Job Applications*.
   5. Remove the parameter to go back to the default.
4. **Persistence:** restart the containers (`... restart`). Jobs, clicks and applications are still there.
5. **Leftovers:** `python tests\e2e_leftovers.py` lists test records an older test version may have left (`--delete` removes them).

---

## 9. Back up and restore

A backup contains **all** data: applicant names, e-mails, phones, resumes and click lines. Keep it private. `backups/` is git-ignored; never upload or share it.

```powershell
.\scripts\backup_local.ps1
```

This writes `backups\llmd_local_<date-time>\database.dump` (pg_dump custom format) and `filestore\` (attachments).

```powershell
.\scripts\restore_local.ps1 -From backups\llmd_local_<date-time>
```

This restores into a **new** database, `llmd_local_restored`; the current one is not touched. To open it, set `ODOO_DB=llmd_local_restored` in `.env` and restart Odoo.

```powershell
.\scripts\restore_local.ps1 -From backups\llmd_local_<date-time> -Database llmd_local -Replace
```

This **replaces** the database. It asks you to type the name and stops Odoo during the swap.

**By hand** (what the scripts do):

```powershell
docker compose --env-file .env -f docker\docker-compose.yml exec -T db pg_dump -U odoo -Fc -f /tmp/b.dump llmd_local
docker compose --env-file .env -f docker\docker-compose.yml cp db:/tmp/b.dump backups\database.dump
docker compose --env-file .env -f docker\docker-compose.yml cp odoo:/var/lib/odoo/filestore/llmd_local backups\filestore
```

Restore with `createdb`, `pg_restore --no-owner`, `docker compose cp` of the filestore to `/var/lib/odoo/filestore/<db>`, then `chown -R odoo:odoo` on it.

---

## 10. What is included, and what is not

**Included:**

- the full addon (identical to the running one);
- Docker and Odoo configuration;
- setup, seed, backup and restore scripts;
- every test suite that passes against the current code, and the developer tools the docs refer to;
- the documentation;
- the unapplied sign-in patch, clearly marked.

**Not included, on purpose:**

- **`.env`.** It holds passwords and API keys. Use `.env.example`.
- **Database and filestore data.** They contain personal data. Make your own backup with `scripts\backup_local.ps1`; see section 9.
- **The earlier live-site "Job Summary automation".** This covers `install.py`, `server_action.py`, `final_test.py`, `views.py`, `snapshot.py`, `role_profile.py`, `build_library.py`, the role library files and `test_local.ps1`. It is a server action + automation rule for learn.llmdecode.com, not installed in the local instance, and not part of the aggregator.
- **The older `llmd_related_jobs` module** (related jobs on course pages, 2026-10-21). It is not installed locally and not used by the aggregator.
- **Superseded checks** that test a replaced layout or removed methods:
  - `agg_test.py`, `agg_handwritten_test.py`, `agg_cleanup.py`, `agg_preview.py`;
  - `parser_test.py`, `parser_live_test.py`;
  - `inspect_apply.py`, `jooble_probe.py`, `jooble_403.py`.
- **Logs, data snapshots and earlier zip files** from the working folder.

---

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| `Docker engine is not running` | Start Docker Desktop and wait until the engine is running |
| Odoo cannot connect to the database after switching folders | `.env` has a different `POSTGRES_PASSWORD` than the one the volume was created with – copy the original `.env` |
| Style changes do not show | Restart Odoo (asset bundle), then Ctrl+F5 |
| `board_test.py only runs against the local instance` | Run `. .\scripts\env.ps1` first in that PowerShell window |
| Odoo shell rejects piped script | Pipe it from Git Bash (`cat file \| ...`), not PowerShell 5.1 |
| JSearch shows "Error" (HTTP 401) | The key in `.env` is not active; check it with `python scripts\jsearch_probe.py` |
