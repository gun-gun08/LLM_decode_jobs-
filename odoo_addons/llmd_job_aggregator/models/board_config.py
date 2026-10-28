"""What the job board is about: the LLM Decode courses, the job roles each course leads to, the category chips, and the job sources.
Pure data + tiny helpers (no Odoo imports), shared by the model, the controller and the tests."""
import re

# ---------------------------------------------------------------------------------------------------------------- courses
# The page reads its courses from the eLearning course data of the Odoo site (models/courses.py). This list is ONLY the fallback for an Odoo database that has no
# eLearning module (like the local test database) - the same four courses that are published on learn.llmdecode.com - and the codes of older links.
COURSES = [
    ('sell-ai', 'How to sell complex products with AI'),
    ('genai-mastermind', '2 DAY GEN AI ENGINEERING MASTERMIND'),
    ('claude-masterclass', 'A–Z Claude Masterclass'),
    ('funnel-101', 'From Leads to Sales: Funnel Building 101'),
]
COURSE_LABELS = dict(COURSES)

# Which job roles a course leads to is worked out from the course's own text (name, tags, description): a course "has" every profile whose pattern its text matches,
# and the profile codes are the ones used in ROLES below. A course that matches no profile gets jobs from the words of its name instead (see course_words()).
COURSE_PROFILES = [
    ('sell-ai', r'\bsell(ing)?\b'),
    ('genai-mastermind', r'\bgen ?ai\b|generative|\bllms?\b|ai engineering|machine learning|\bpython\b'),
    ('claude-masterclass', r'\bclaude\b|\bprompt(ing)?\b|\bai automation\b|\bchatgpt\b'),
    ('funnel-101', r'\bfunnels?\b|\bleads?\b|digital marketing|\bseo\b|\bgrowth\b|\bmarketing\b'),
]
_STOP = {'with', 'from', 'your', 'the', 'and', 'for', 'how', 'to', 'day', 'a-z', 'complete', 'course', 'masterclass', 'mastermind', 'beginners', 'guide', 'introduction', 'learn'}

# ---------------------------------------------------------------------------------------------------------------- job roles
# (code, label, regex on the lower-case job title, search query for the job APIs, the courses it is relevant for)
ROLES = [
    ('sales_manager', 'Sales Manager', r'sales (manager|head|lead|director)|head of sales|regional sales', 'sales manager', ['sell-ai']),
    ('account_executive', 'Account Executive', r'account (executive|manager|director)|enterprise sales|key account', 'account executive', ['sell-ai']),
    ('bdm', 'Business Development Manager', r'business development|\bbdm\b|partnerships?', 'business development manager', ['sell-ai', 'funnel-101']),
    ('sdr', 'Sales Development Representative', r'sales development|\bsdr\b|\bbdr\b|lead gen|outbound|inside sales', 'sales development representative', ['sell-ai', 'funnel-101']),
    ('csm', 'Customer Success Manager', r'customer success', 'customer success manager', ['sell-ai']),
    ('solutions_eng', 'Solutions / Sales Engineer', r'solutions? (engineer|consultant|architect)|sales engineer|pre-?sales', 'solutions engineer', ['sell-ai']),
    ('ai_engineer', 'AI Engineer', r'\bai\b.*(engineer|developer)|artificial intelligence|ai/ml', 'ai engineer', ['genai-mastermind', 'claude-masterclass']),
    ('genai_engineer', 'Generative AI / LLM Engineer', r'generative|\bgenai\b|\bllm|gen ai|foundation model', 'generative ai engineer', ['genai-mastermind']),
    ('ml_engineer', 'Machine Learning Engineer', r'machine learning|\bml\b|mlops|deep learning', 'machine learning engineer', ['genai-mastermind']),
    ('prompt_engineer', 'Prompt Engineer', r'prompt', 'prompt engineer', ['genai-mastermind', 'claude-masterclass']),
    ('data_scientist', 'Data Scientist', r'data scien', 'data scientist', ['genai-mastermind']),
    ('python_dev', 'Python Developer', r'python', 'python developer', ['genai-mastermind']),
    ('ai_automation', 'AI Automation Specialist', r'automation|ai agent|agentic|workflow|no-?code', 'ai automation', ['claude-masterclass']),
    ('ai_pm', 'AI Product Manager', r'(ai|ml|machine learning).*(product|program) manager|(product|program) manager.*(ai|ml|machine learning)|ai product', 'ai product manager', ['claude-masterclass']),
    ('data_analyst', 'Data Analyst', r'data analy|business analy|analytics|\bbi\b', 'data analyst', ['claude-masterclass']),
    ('content_writer', 'Content / Copywriter', r'content|copywrit|writer|editor', 'content writer', ['claude-masterclass']),
    ('digital_marketing', 'Digital Marketing Manager', r'digital marketing|marketing manager|marketing specialist|online marketing', 'digital marketing manager', ['funnel-101']),
    ('growth', 'Growth Marketer', r'growth', 'growth marketing', ['funnel-101']),
    ('demand_gen', 'Demand Generation Manager', r'demand gen|funnel|acquisition', 'demand generation', ['funnel-101']),
    ('seo', 'SEO Specialist', r'\bseo\b|search engine', 'seo specialist', ['funnel-101']),
    ('paid_media', 'Paid Media / Performance Marketer', r'paid|performance marketing|\bppc\b|\bsem\b|ads specialist|media buyer', 'paid media', ['funnel-101']),
    ('marketing_automation', 'Marketing Automation / CRM Specialist', r'marketing automation|crm|hubspot|email marketing|lifecycle|marketing operations', 'marketing automation', ['funnel-101']),
]
ROLE_LABELS = {code: label for code, label, _rx, _q, _c in ROLES}

# ---------------------------------------------------------------------------------------------------------------- category chips (all courses together)
TRACKS = [
    ('genai', 'GenAI', r'generative|\bgenai\b|\bllm|prompt engineer|\bgpt\b'),
    ('claude', 'Claude', r'\bclaude\b'),
    ('python', 'Python', r'\bpython\b|django|fastapi|flask'),
    ('aiml', 'AI/ML', r'\bai\b|machine learning|\bml\b|deep learning|artificial intelligence|computer vision|\bnlp\b'),
    ('data', 'Data Analytics', r'data (analy|scien|engineer)|analytics|business intelligence|\bbi\b'),
    ('sales', 'Sales', r'\bsales\b|account executive|business development|revenue'),
    ('marketing', 'Digital Marketing', r'marketing|\bseo\b|growth|social media|content (manager|strategist|writer)'),
]
TRACK_LABELS = {code: label for code, label, _rx in TRACKS}
EXTRA_QUERIES = ['generative ai', 'llm engineer', 'claude', 'ai engineer', 'digital marketing', 'seo specialist']   # for the chips that no role query covers

# ---------------------------------------------------------------------------------------------------------------- job sources (code, name, kind, home page, how to switch it on)
SOURCES = [
    ('adzuna', 'Adzuna', 'api', 'https://www.adzuna.in', 'Set ADZUNA_APP_ID and ADZUNA_APP_KEY (free signup: developer.adzuna.com).'),
    ('jsearch', 'JSearch', 'api', 'https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch',
     'Set JSEARCH_API_KEY (RapidAPI "JSearch", or OpenWebNinja: then also set JSEARCH_BASE_URL=https://api.openwebninja.com/jsearch/search). The free plans allow only a few hundred requests a month.'),
    ('company', 'Company job boards', 'api', 'https://developers.greenhouse.io/job-board.html',
     'No key needed: the public job boards of the companies in the system parameter llmd_agg.company_boards (Greenhouse, Lever, Ashby, SmartRecruiters). Jobs in India and worldwide that fit a course role or one of the job categories: per company at most llmd_agg.company_boards_per_board (100) in India and llmd_agg.company_boards_per_board_world (50) elsewhere, the newest; Apply Now goes straight to the company page.'),
    ('jooble', 'Jooble', 'api', 'https://in.jooble.org', 'Set JOOBLE_API_KEY (free key: jooble.org/api/about; the free plan allows 500 requests per key).'),
    ('indeed', 'Indeed', 'feed', 'https://in.indeed.com', 'Needs an official Indeed partner job feed: set INDEED_FEED_URL (and INDEED_FEED_TOKEN if it needs one). Indeed has no public self-serve job-search API.'),
    ('naukri', 'Naukri.com', 'feed', 'https://www.naukri.com', 'Needs an official Naukri partner job feed: set NAUKRI_FEED_URL (and NAUKRI_FEED_TOKEN if it needs one). Naukri has no public self-serve job-search API.'),
    ('himalayas', 'Himalayas', 'api', 'https://himalayas.app', 'No key needed; remote jobs only. A TEMPORARY fallback: read only while Adzuna / JSearch / Jooble / the feeds return fewer than 20 jobs (system parameter llmd_agg.himalayas_mode: fallback = default / always / off).'),
]
# The company job boards that were checked against the providers' public APIs (scripts/company_boards_probe.py; first 42 on 2026-10-23, the next 39 on 2026-10-25):
# every one answered and had jobs in India. "provider:board" or "provider:board=Company name" (Lever and Ashby do not send the company name).
# Override: system parameter llmd_agg.company_boards.
COMPANY_BOARDS = """
greenhouse:databricks, greenhouse:stripe, greenhouse:mongodb, greenhouse:elastic, greenhouse:gitlab, greenhouse:okta, greenhouse:rubrik, greenhouse:hackerrank, greenhouse:druva,
greenhouse:airbnb, greenhouse:coinbase, greenhouse:anthropic, greenhouse:groww, greenhouse:inmobi, greenhouse:cloudflare, greenhouse:datadog, greenhouse:twilio, greenhouse:zscaler,
greenhouse:razorpaysoftwareprivatelimited, greenhouse:turing, greenhouse:zetaglobal, greenhouse:sigmoid, greenhouse:samsara, greenhouse:figma, greenhouse:coursera,
greenhouse:purestorage, greenhouse:gleanwork, greenhouse:fivetran, greenhouse:netskope, greenhouse:toast, greenhouse:agoda, greenhouse:sumologic, greenhouse:jfrog,
greenhouse:newrelic, greenhouse:mixpanel, greenhouse:yugabyte, greenhouse:startree, greenhouse:adyen, greenhouse:grafanalabs, greenhouse:observeai, greenhouse:binance,
greenhouse:cockroachlabs, greenhouse:scaleai, greenhouse:neteasegames=NetEase Games, greenhouse:xpengmotors=XPENG, greenhouse:okx=OKX, greenhouse:bybit=Bybit,
greenhouse:shein=SHEIN, greenhouse:baidu=Baidu USA, greenhouse:byd=BYD North America, greenhouse:pingcap=PingCAP,
lever:cred=CRED, lever:meesho=Meesho, lever:zeta=Zeta, lever:hevodata=Hevo Data, lever:paytm=Paytm, lever:mindtickle=Mindtickle,
lever:fampay=FamPay, lever:netomi=Netomi, lever:nium=Nium, lever:outreach=Outreach, lever:pocketfm=Pocket FM, lever:spotify=Spotify, lever:crypto=Crypto.com, lever:weride=WeRide, lever:lalamove=Lalamove,
ashby:openai=OpenAI, ashby:atlan=Atlan, ashby:sarvam=Sarvam AI, ashby:elevenlabs=ElevenLabs, ashby:composio=Composio, ashby:cursor=Cursor, ashby:writer=Writer,
ashby:signoz=SigNoz, ashby:clickhouse=ClickHouse, ashby:spotdraft=SpotDraft, ashby:harvey=Harvey, ashby:cognition=Cognition, ashby:smallest=Smallest.ai, ashby:notion=Notion,
ashby:temporal=Temporal, ashby:hoyoverse=HoYoverse, ashby:airwallex=Airwallex,
smartrecruiters:Freshworks, smartrecruiters:BoschGroup, smartrecruiters:Experian, smartrecruiters:NielsenIQ, smartrecruiters:Swiggy=Swiggy, smartrecruiters:ServiceNow,
smartrecruiters:Continental, smartrecruiters:AbbVie, smartrecruiters:WesternDigital, smartrecruiters:Unacademy, smartrecruiters:bytedance=ByteDance
"""
COMPANY_PER_BOARD = 100                                                   # jobs per company and run IN INDIA (the newest): enough for the big employers, no company fills the board alone
COMPANY_PER_BOARD_WORLD = 50                                              # jobs per company and run ELSEWHERE in the world (the newest): a worldwide mix without one company filling it

# Where each company of the board has its headquarters (for "Companies by region") - public, well-known facts, kept here because no job source sends them.
# Only companies whose headquarters are clear are listed; a company that is not listed (or is added later) shows as "headquarters not verified". The
# headquarters are NOT where a job is: an American company may hire in India and an Indian company may hire remotely worldwide.
COMPANY_HQ = {
    'United States': ('AbbVie', 'Airbnb', 'Anthropic', 'ClickHouse', 'Cloudflare', 'Cockroach Labs', 'Cognition', 'Coinbase', 'Coursera', 'Cursor', 'Databricks', 'Datadog',
                      'Druva', 'Everpure', 'Figma', 'Fivetran', 'Freshworks', 'GitLab', 'Glean', 'Grafana Labs', 'HackerRank', 'Harvey', 'Mixpanel', 'MongoDB', 'Netskope',
                      'New Relic', 'NielsenIQ', 'Notion', 'Observe.AI', 'Okta', 'OpenAI', 'Outreach', 'Rubrik', 'Samsara', 'Scale AI', 'ServiceNow', 'StarTree', 'Stripe',
                      'Sumo Logic', 'Temporal', 'Toast', 'Turing', 'Twilio', 'Western Digital', 'Writer', 'YugabyteDB', 'Zeta Global', 'Zscaler',
                      'Baidu USA', 'BYD North America'),                # the US companies of Baidu and BYD (their own boards)
    'India': ('CRED', 'FamPay', 'Groww', 'InMobi', 'Meesho', 'Paytm', 'Pocket FM', 'Razorpay Software Private Limited', 'Razorpay', 'Sarvam AI', 'Swiggy', 'Unacademy', 'Zeta'),
    'Germany': ('Bosch Group', 'Continental'), 'Ireland': ('Experian',), 'Netherlands': ('Adyen',), 'Sweden': ('Spotify',), 'Singapore': ('Agoda', 'Nium', 'Crypto.com', 'SHEIN'),
    'China': ('ByteDance', 'HoYoverse', 'NetEase Games', 'WeRide', 'XPENG'), 'Hong Kong': ('Lalamove',), 'United Arab Emirates': ('Bybit',),
}
_HQ_OF = {name.lower(): country for country, names in COMPANY_HQ.items() for name in names}

# Who put a job on the board, and how a person applied (Job Applications, Apply Clicks, Job board listings)
POSTED_TYPES = [('fetched', 'Fetched'), ('public_user', 'Public User')]
APPLICATION_TYPES = [('website_form', 'Website Form'), ('external_apply_click', 'External Apply Click')]


def company_hq(company):
    """The country of a company's headquarters (COMPANY_HQ), or '' when it is not verified."""
    return _HQ_OF.get((company or '').strip().lower(), '')
SOURCE_NAMES = {code: name for code, name, _k, _h, _n in SOURCES}
SOURCE_PRIORITY = {name: i for i, (_c, name, _k, _h, _n) in enumerate(SOURCES)}
# Every search query is sent in three variants, so that the results hold Remote, Hybrid AND On-site jobs and not only the remote ones that a plain "remote" search favours:
# '' = the plain query (jobs in India, mostly on-site), 'remote' and 'hybrid' = the same query asking for remote / hybrid work.
QUERY_MODES = ('', 'remote', 'hybrid')
# How many of these (query, mode) searches one scheduled run sends to each source (they rotate day by day, so every one is used within a few days). 0 = all of them.
QUERIES_PER_RUN = {'adzuna': 39, 'jsearch': 6, 'jooble': 9}
# The request budget that is never exceeded: (default budget, counted 'total' or per calendar 'month'). Overridable with the system parameter llmd_agg.<code>_budget.
REQUEST_BUDGET = {'jooble': (450, 'total'), 'jsearch': (150, 'month')}
# Direct links only (default, at the user's request): Apply Now must open the employer's / company's own job page. Adzuna, Jooble and Himalayas only ever give a link to
# THEIR OWN page, so they are not asked and their jobs are hidden (never deleted). System parameter llmd_agg.direct_links_only = 0 brings them back.
DIRECT_LINKS_ONLY = True
BOARD_LINK_SOURCES = ('adzuna', 'jooble', 'himalayas')
KEEP_DAYS = 30                                   # a job that no source has returned for this long is hidden (only checked when a source did return jobs); longer than the rotation of the small plans

OLD_TRACK_PARAMS = set(TRACK_LABELS)       # old links used ?course=genai for the chips


def role_codes(title):
    low = (title or '').lower()
    return [code for code, _l, rx, _q, _c in ROLES if re.search(rx, low)]


def courses_of_roles(roles):
    out = []
    for code, _l, _rx, _q, courses in ROLES:
        if code in roles:
            out += [c for c in courses if c not in out]
    return [c for c, _ in COURSES if c in out]


def all_queries():
    seen, out = set(), []
    for q in [r[3] for r in ROLES] + EXTRA_QUERIES:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def query_variants():
    """[(query, mode)] for every search query, the three work modes of one query next to each other (so a rotating window of a few searches still covers all three)."""
    return [(q, mode) for q in all_queries() for mode in QUERY_MODES]


def roles_for_course(course):
    return [(code, label) for code, label, _rx, _q, courses in ROLES if course in courses]


def course_profiles(text):
    """The course profiles (codes used in ROLES) that a course's text matches."""
    low = (text or '').lower()
    return [code for code, rx in COURSE_PROFILES if re.search(rx, low)]


def roles_for_profiles(profiles):
    return [(code, label) for code, label, _rx, _q, courses in ROLES if any(p in courses for p in profiles)]


def course_words(text):
    """Search words from a course's own text, for a course that matches no profile."""
    out = []
    for w in re.findall(r'[a-z][a-z+#.-]{3,}', (text or '').lower()):
        if w not in _STOP and w not in out:
            out.append(w)
    return out[:6]


def slugify(text):
    """The URL part of a company, a city or a country: lower case, words joined by '-' ("Hevo Data" -> hevo-data)."""
    return re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')


def norm_key(title, company, location):
    """Same job from two sources -> same key: title + company + first place name, letters and digits only."""
    def n(text):
        return re.sub(r'[^a-z0-9]+', '', (text or '').lower())
    place = re.sub(r'remote|·|worldwide', ' ', (location or '').lower()).split(',')[0]
    return '%s|%s|%s' % (n(title), n(company), n(place)[:20])


# ---------------------------------------------------------------------------------------------------------------- job categories (/jobs/category/<slug>)
# Every job belongs to ONE category: its title decides (the most specific family first), then its course role, then the department its company files it under.
JOB_CATEGORIES = [
    ('ai-machine-learning', 'AI & Machine Learning', 'Machine learning, AI, generative AI, LLM and applied-science roles.', 'fa-magic'),
    ('it-software', 'IT & Software', 'Software engineering, platform, infrastructure, reliability and IT roles.', 'fa-code'),
    ('cybersecurity', 'Cybersecurity', 'Security engineering, application and cloud security, threat detection and response.', 'fa-shield'),
    ('hardware-embedded', 'Hardware & Embedded', 'Hardware, chip design, embedded systems and firmware roles.', 'fa-microchip'),
    ('data-analytics', 'Data & Analytics', 'Data analysts, data scientists, data engineers and business intelligence roles.', 'fa-bar-chart'),
    ('solutions-presales', 'Solutions & Pre-sales', 'Solutions engineers and architects who help customers choose and adopt a product.', 'fa-puzzle-piece'),
    ('sales', 'Sales & Business Development', 'Account executives, business development, partnerships and sales leadership roles.', 'fa-line-chart'),
    ('marketing', 'Marketing & Growth', 'Growth, content, digital, demand generation, brand and product marketing roles.', 'fa-bullhorn'),
    ('customer-success', 'Customer Support & Success', 'Customer success, technical account management, services and support roles.', 'fa-life-ring'),
    ('product-design', 'Product & Design', 'Product managers, product designers and UX roles.', 'fa-object-group'),
    ('finance', 'Finance & Accounting', 'Finance, accounting, tax, treasury, revenue and audit roles.', 'fa-money'),
    ('legal-compliance', 'Legal & Compliance', 'Counsel, legal operations, compliance, privacy and risk roles.', 'fa-balance-scale'),
    ('people-hr', 'People & HR', 'Talent acquisition, recruiting and people-operations roles.', 'fa-users'),
    ('operations', 'Operations & Strategy', 'Revenue and business operations, strategy and chief-of-staff roles.', 'fa-cogs'),
    ('supply-chain', 'Supply Chain & Logistics', 'Supply chain, procurement, sourcing, planning and logistics roles.', 'fa-truck'),
    ('healthcare-life-sciences', 'Healthcare & Life Sciences', 'Clinical, medical, regulatory and scientific roles in health and pharma.', 'fa-heartbeat'),
    ('admin-office', 'Administration & Office', 'Executive assistants, office, facilities and workplace roles.', 'fa-briefcase'),
    ('education-training', 'Education & Training', 'Teaching, training, learning & development and curriculum roles.', 'fa-graduation-cap'),
]
CATEGORY_LABELS = {slug: label for slug, label, _d, _i in JOB_CATEGORIES}
OLD_CATEGORY_SLUGS = {'engineering': 'it-software', 'business-operations': 'operations'}      # links of v19.0.22 still work (301)
_CATEGORY_BY_TITLE = [                                                       # order matters: "Data Engineer" is data, "Solutions Engineer" is pre-sales,
    ('solutions-presales', r'\bsolutions?\s+(engineer|architect|consultant|specialist)|\bsales engineer|\bpre-?\s?sales|\bapplied ai architect|\bcustomer engineer|\bfield engineer'),
    ('it-software', r'\bit (support|help ?desk|administrator|admin|operations|analyst|engineer|specialist|manager)\b|\bhelp ?desk\b|\bsystems? administrator\b|\bdesktop support\b'),  # "IT Support" is IT, not customer support
    ('cybersecurity', r'cyber ?security|information security|\binfosec\b|security (engineer\w*|analyst|architect|researcher|operations|specialist|consultant|lead|manager)|'
                      r'(application|product|cloud|network|offensive|data) security|\bappsec\b|threat|vulnerabilit|penetration|\bsoc\b|incident response|detection engineer|red team'),
    ('hardware-embedded', r'\b(hardware|embedded|firmware|vlsi|asic|fpga|silicon|pcb|rtl|analog|mixed[- ]signal|semiconductor|chip design|design verification|physical design)\b'),
    ('education-training', r'\b(teacher|tutor|instructor|trainer|faculty|lecturer|educator|curriculum|instructional design\w*|learning (and|&) development|l&d|teaching)\b'),
    ('product-design', r'\bproduct (manager|owner|lead|management|designer|design)|\bux\b|\bui\b|\bdesigner\b|user research'),      # "Product Manager - Data Platform" is product
    ('finance', r'\b(financial|finance|fp&a|accounting|tax|revenue) analyst'),
    ('healthcare-life-sciences', r'\b(clinical|medical|pharma\w*|patient|healthcare|health care|physician|regulatory affairs|pharmacovigilance|biolog\w*|biotech\w*|laborator\w*|'
                                 r'chemist\w*|scientific|drug|therapeutic|oncology|immunology|life sciences|epidemiolog\w*)\b'),
    ('legal-compliance', r'\b(legal|counsel|attorney|lawyer|paralegal|compliance|privacy|kyc|aml|contracts? manager|governance,? risk)\b'),
    ('data-analytics', r'\bdata (analyst|analytics|scien\w*|engineer\w*|platform|architect\w*)|analytics|\banalyst\b|business intelligence|\bbi\b|insights|statistic'),
    ('people-hr', r'\b(human resources|hr|people|talent|recruit\w*|hiring partner)\b'),
    ('finance', r'\b(finance|financial|accounting|accountant|payroll|tax|treasury|audit\w*|commission|revenue manager|revenue accounting|controller)\b|senior manager, revenue'),
    ('supply-chain', r'\b(supply chain|logistics|procurement|purchasing|sourcing|inventory|demand plann\w*|supply plann\w*|fulfil?ment|distribution|vendor management|customs|trade compliance)\b'),
    ('operations', r'\b(revenue (operations|intelligence)|rev ?ops|business operations|sales operations|chief of staff|strategy and operations|operations (manager|lead|analyst|associate|specialist)|strategy)\b'),
    ('admin-office', r'executive assistant|administrative (assistant|coordinator|specialist|officer)|office (manager|coordinator|administrator|assistant)|receptionist|front desk|'
                     r'facilities|workplace (experience|coordinator|manager|services)|personal assistant|secretary|data entry'),
    ('marketing', r'marketing|copywrit|\bseo\b|\bsem\b|demand gen|social media|\bbrand\b|communications'),
    ('customer-success', r'customer success|\bsupport\b|technical account manager|\btam\b|implementation|onboarding|customer experience|professional services|client success'),
    ('sales', r'\bsales\b|account executive|account manager|business development|\bbdm\b|\bbdr\b|\bsdr\b|partnerships?\b|alliances|\bchannel\b|\brenewals?\b|inside sales|key account'),
    ('marketing', r'\bgrowth\b|\bcontent\b|campaign|community|\bpr\b'),        # weaker words: only when no sales / success word says otherwise
    ('data-analytics', r'\bdata\b'),
    ('ai-machine-learning', r'machine learning|\bml\b|mlops|\bai\b|artificial intelligence|\bllms?\b|gen ?ai|generative|deep learning|\bnlp\b|computer vision|applied scien|research scien|prompt'),
    ('it-software', r'engineer|developer|\bdevops\b|\bsre\b|programmer|architect|\bit\b|software|infrastructure|scientist|platform|security|network|systems?\b'),
]
_CATEGORY_BY_TITLE = [(slug, re.compile(rx, re.I)) for slug, rx in _CATEGORY_BY_TITLE]
_CATEGORY_BY_ROLE = {'sales_manager': 'sales', 'account_executive': 'sales', 'bdm': 'sales', 'sdr': 'sales', 'csm': 'customer-success', 'solutions_eng': 'solutions-presales',
                     'ai_engineer': 'ai-machine-learning', 'genai_engineer': 'ai-machine-learning', 'ml_engineer': 'ai-machine-learning', 'prompt_engineer': 'ai-machine-learning',
                     'python_dev': 'it-software', 'ai_automation': 'ai-machine-learning', 'data_scientist': 'data-analytics', 'data_analyst': 'data-analytics', 'ai_pm': 'product-design',
                     'content_writer': 'marketing', 'digital_marketing': 'marketing', 'growth': 'marketing', 'demand_gen': 'marketing', 'seo': 'marketing',
                     'paid_media': 'marketing', 'marketing_automation': 'marketing'}

# The team a company files the job under (its own "department" on its job board), mapped onto one list: the "Job Function" filter. A department that names no
# function ("Other", "General Business", a manager's name, a cost centre) gives none.
JOB_FUNCTIONS = [
    ('solutions', 'Solutions & Pre-sales', r'field engineering|solution|pre-?sales|sales engineering|\bsa\b|\bse\b'),
    ('data', 'Data & Analytics', r'\bdata\b|analytics|business intelligence|insights'),
    ('design', 'Design', r'design'),
    ('product', 'Product', r'\bproduct\b(?! marketing)'),
    ('marketing', 'Marketing', r'marketing|growth|brand|communications|content'),
    ('customer', 'Customer Success & Services', r'customer success|support|services|partner success|\bsuccess\b|technical account'),
    ('security', 'Security', r'security'),
    ('legal', 'Legal & Compliance', r'legal|compliance'),
    ('supply', 'Supply Chain', r'supply chain|procurement|purchasing|logistics|sourcing'),
    ('medical', 'Medical & Scientific', r'medical|clinical|research and development|r&d|scientific|regulatory'),
    ('finance', 'Finance', r'financ|accounting|total rewards|\botc\b|\bqtc\b'),
    ('sales', 'Sales', r'sales|go to market|\bgtm\b|revenue|business development|partner|commerc|account'),
    ('it', 'IT', r'information technology|\bit\b|tech ops'),                    # before engineering: "Information Technology" is IT
    ('engineering', 'Engineering', r'engineering|\beng\b|software|platform|infrastructure|(?<!non )\btech\b|technology|\bmodels\b|applied ai|ai builder|enterprise ai|documentation'),
    ('people', 'People & HR', r'\bhr\b|people|talent|recruit|human'),
    ('operations', 'Operations & Strategy', r'operations|strategy'),
]
FUNCTION_LABELS = {key: label for key, label, _rx in JOB_FUNCTIONS}
_FUNCTIONS = [(key, re.compile(rx, re.I)) for key, _label, rx in JOB_FUNCTIONS]


def job_function(department):
    """The Job Function of a company department ("APJ Field Sales" -> sales, "SW Eng - Applications-674" -> engineering); '' when it names none."""
    text = re.sub(r'[-–]?\s*\d{2,}\b', ' ', department or '')                 # cost-centre numbers
    for key, rx in _FUNCTIONS:
        if rx.search(text):
            return key
    return ''


# Jobs the board does not carry even when a word of the title fits a category: plant / workshop / field work, driving, care, kitchen - and freelance gigs.
NON_OFFICE = re.compile(r'mechanical|\bcivil\b|electrical|manufactur|\bplant\b|production (engineer|operator|supervisor|associate)|technician|welder|machinist|\bdriver\b|\bnurse'
                        r'|pharmacist|warehouse|assembly|maintenance|\bhvac\b|\bcnc\b|metallurg|chemical engineer|\bcook\b|\bchef\b|security guard|housekeeping|electrician'
                        r'|plumber|\bfitter\b|\bpicker\b|\bpacker\b|delivery (executive|partner|boy|associate)|\brider\b|freelance', re.I)


def board_relevant(title, department=''):
    """Does a job belong on the board? Its title names a course role or a course track, or the job falls into one of the job categories (by its title, else its
    department) - never plant / workshop / field work or a freelance gig."""
    low = (title or '').lower()
    if not low.strip() or NON_OFFICE.search(low):
        return False
    roles = role_codes(title)
    return bool(roles) or any(re.search(rx, low) for _c, _l, rx in TRACKS) or bool(job_category(title, ',%s,' % ','.join(roles) if roles else '', department))


def job_category(title, roles='', department=''):
    """The ONE category of a job (a key of JOB_CATEGORIES), or '' when nothing about it fits one."""
    for slug, rx in _CATEGORY_BY_TITLE:
        if rx.search(title or ''):
            return slug
    for code in (roles or '').strip(',').split(','):
        if code in _CATEGORY_BY_ROLE:
            return _CATEGORY_BY_ROLE[code]
    function = job_function(department)
    return {'solutions': 'solutions-presales', 'data': 'data-analytics', 'design': 'product-design', 'product': 'product-design', 'marketing': 'marketing',
            'customer': 'customer-success', 'sales': 'sales', 'engineering': 'it-software', 'it': 'it-software', 'finance': 'finance',
            'people': 'people-hr', 'operations': 'operations', 'security': 'cybersecurity', 'legal': 'legal-compliance', 'supply': 'supply-chain',
            'medical': 'healthcare-life-sciences'}.get(function, '')


# ---------------------------------------------------------------------------------------------------------------- course terms (course-based recommendations)
# The words a course teaches and a job asks for, in ONE vocabulary: found in a course's own text (name, description, modules, outcomes) and in a job's title and
# full text, they rank the jobs of a course and say why each one matches ("Matches: Python, LLMs, RAG").
COURSE_TERMS = [
    ('claude', 'Claude', r'\bclaude\b'), ('chatgpt', 'ChatGPT / OpenAI', r'chatgpt|\bopenai\b|\bgpt-?\d'), ('prompting', 'Prompt engineering', r'\bprompt(s|ing| engineering)?\b'),
    ('llms', 'LLMs', r'\bllms?\b|large language models?'), ('rag', 'RAG', r'\brag\b|retrieval[- ]augmented'), ('agents', 'AI agents', r'\bai agents?\b|\bagentic\b|multi-agent'),
    ('genai', 'Generative AI', r'generative ai|\bgen ?ai\b'), ('langchain', 'LangChain / LlamaIndex', r'langchain|llama ?index'), ('python', 'Python', r'\bpython\b'),
    ('ml', 'Machine learning', r'machine learning|\bmlops\b'), ('automation', 'Automation', r'\bautomat(e|ed|es|ing|ion)\b'), ('workflows', 'Workflows', r'\bworkflows?\b'),
    ('apis', 'APIs', r'\bapis?\b'), ('coding', 'Coding', r'\bcoding\b|\bcode\b'), ('data', 'Data analysis', r'data analy\w*|\banalytics\b'),
    ('sales', 'Sales', r'\bsales\b|\bselling\b'), ('b2b', 'B2B', r'\bb2b\b'), ('objections', 'Objection handling', r'objection'), ('negotiation', 'Negotiation', r'negotiat\w*'),
    ('stakeholders', 'Stakeholder management', r'stakeholder'), ('closing', 'Closing deals', r'clos(e|ing) (deals?|the deal)|deal cycle|sales cycle'),
    ('leads', 'Lead generation', r'lead gen\w*|\bleads\b|prospect\w*'), ('funnels', 'Sales funnels', r'\bfunnels?\b'), ('landing', 'Landing pages', r'landing pages?'),
    ('email', 'Email marketing', r'email (marketing|sequences?|campaigns?)|newsletters?'), ('copywriting', 'Copywriting', r'copywrit\w*'),
    ('ads', 'Paid ads', r'google ads|facebook ads|meta ads|\bppc\b|paid (media|social|ads)|performance marketing'), ('seo', 'SEO', r'\bseo\b'),
    ('crm', 'CRM', r'\bcrm\b|hubspot|salesforce'), ('content', 'Content creation', r'content (creation|marketing|writing|strategy)'), ('conversion', 'Conversion optimisation', r'conversion|a/b test'),
]
COURSE_TERM_LABELS = {key: label for key, label, _rx in COURSE_TERMS}
_COURSE_TERMS = [(key, re.compile(rx, re.I)) for key, _label, rx in COURSE_TERMS]


def course_terms(text):
    """The keys of COURSE_TERMS a text talks about (a course's text, or a job's title + text), in vocabulary order."""
    text = text or ''
    return [key for key, rx in _COURSE_TERMS if rx.search(text)]


def course_match(course_keys, job_keys):
    """The terms a course and a job share (labels, in vocabulary order): the reason a recommended job matches a course."""
    shared = set(course_keys) & set(job_keys)
    return [COURSE_TERM_LABELS[key] for key, _label, _rx in COURSE_TERMS if key in shared]
