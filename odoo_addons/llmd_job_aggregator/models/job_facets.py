"""What the Jobs page filters on, worked out from the text a job source gives: experience level, job type, work mode (remote / hybrid / on-site), India or not, and city.
Pure Python (no Odoo imports), unit-tested by rolelib/facets_test.py.

Nothing is invented: when a job gives no clue the value stays empty and the job simply does not match that filter.
"""
import re

# ---------------------------------------------------------------------------------------------------------------- the filter values shown on the page
EXP_LEVELS = [('fresher', 'Fresher'), ('internship', 'Internship'), ('entry', 'Entry-level'), ('mid', 'Mid-level'), ('senior', 'Senior-level')]
EXP_LABELS = dict(EXP_LEVELS)
JOB_TYPES = [('fulltime', 'Full-time'), ('parttime', 'Part-time'), ('internship', 'Internship'), ('contract', 'Contract')]
TYPE_LABELS = dict(JOB_TYPES)
WORK_MODES = [('remote', 'Remote'), ('hybrid', 'Hybrid'), ('onsite', 'On-site')]
MODE_LABELS = dict(WORK_MODES)
EXP_FILTER = [('fresher', 'Fresher'), ('internship', 'Internship'), ('entry', 'Entry-level'), ('mid', 'Mid-level'), ('senior', 'Senior')]       # the Experience Level filter
SALARY_RANGES = [('0-3', '₹0–3 LPA', 0.0, 3.0), ('3-6', '₹3–6 LPA', 3.0, 6.0), ('6-10', '₹6–10 LPA', 6.0, 10.0), ('10+', '₹10+ LPA', 10.0, None)]   # (key, label, from, to)

# ---------------------------------------------------------------------------------------------------------------- job type
_INTERN = re.compile(r'\binterns?\b|\binternship|\btrainee|\bapprentice')
_CONTRACT = re.compile(r'\bcontract|\bfreelanc|\btemporary\b|\bcontractor|\bconsultancy basis|\bfixed[- ]term')
_PART = re.compile(r'\bpart[- ]?time\b')
_FULL = re.compile(r'\bfull[- ]?time\b|\bpermanent\b')


def job_type(employment_type, title=''):
    """fulltime / parttime / internship / contract, or '' when the source does not say."""
    kind, head = (employment_type or '').lower(), (title or '').lower()
    for text in (kind, head):                       # the source's own field first, then the title
        if _INTERN.search(text):
            return 'internship'
        if _CONTRACT.search(text):
            return 'contract'
        if _PART.search(text):
            return 'parttime'
        if _FULL.search(text):
            return 'fulltime'
    return ''


# ---------------------------------------------------------------------------------------------------------------- experience level
_EXP_INTERN = re.compile(r'\binterns?\b|\binternship|\btrainee|\bapprentice')
_EXP_FRESHER = re.compile(r'\bfreshers?\b|\bfresh graduates?\b|\bgraduate (trainee|engineer|program)|\bcampus\b|\bno experience\b|\b0\s*(?:-|–|to)\s*1\s*years?|\bzero experience')
_EXP_ENTRY = re.compile(r'\bentry[- ]?level\b|\bjunior\b|\bjr\.?\b|\bbeginner\b|\bassociate\b|\bearly career\b')
_EXP_MID = re.compile(r'\bmid[- ]?level\b|\bmid[- ]?senior\b|\bintermediate\b|\bmid\b')
_EXP_SENIOR = re.compile(r'\bsenior\b|\bsr\.?\b|\blead\b|\bprincipal\b|\bstaff\b|\bhead of\b|\bdirector\b|\bvp\b|\bvice president\b|\bchief\b|\bexecutive\b|\bmanager\b|\bexpert\b')
_YEARS = re.compile(r'(\d{1,2})\s*(?:\+|(?:-|–|to)\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b')


def years_asked(text):
    """The smallest number of years of experience the text asks for, or None. Only sentences that talk about experience count."""
    best = None
    for sentence in re.split(r'(?<=[.;\n])\s+|\n', (text or '')[:6000]):
        if not re.search(r'experience|exp\.', sentence, re.I):
            continue
        for m in _YEARS.finditer(sentence):
            n = int(m.group(1))
            if n <= 40:
                best = n if best is None else min(best, n)
    return best


_YEAR_RANGE = re.compile(r'(\d{1,2})\s*(?:(?:-|–|to)\s*(\d{1,2}))?\s*\+?\s*(?:years?|yrs?)\b', re.I)


def years_range(text):
    """(from, to) years of experience the text asks for - the lowest requirement it states; `to` is None when open ("5+ years", "at least 5 years");
    (None, None) when the text states no years. Only sentences that talk about experience count."""
    best = None
    for sentence in re.split(r'(?<=[.;\n])\s+|\n', (text or '')[:6000]):
        if not re.search(r'experience|exp\.', sentence, re.I):
            continue
        for m in _YEAR_RANGE.finditer(sentence):
            low = int(m.group(1))
            high = int(m.group(2)) if m.group(2) else None
            if low > 40 or (high is not None and (high > 40 or high < low)):
                continue
            if best is None or low < best[0]:
                best = (low, high)
    return best or (None, None)


def exp_level(title, seniority='', text=''):
    """fresher / internship / entry / mid / senior, or '' when nothing in the job says. The title wins, then the source's seniority field, then the years asked for."""
    head, senior_field = (title or '').lower(), (seniority or '').lower()
    for pattern, level in ((_EXP_INTERN, 'internship'), (_EXP_FRESHER, 'fresher')):
        if pattern.search(head):
            return level
    if re.search(r'\bsenior\b|\bsr\.?\b|\bprincipal\b|\bstaff\b|\bhead of\b|\bdirector\b|\bvp\b|\bchief\b|\blead\b', head):
        return 'senior'
    if re.search(r'\bjunior\b|\bjr\.?\b|\bentry[- ]?level\b|\bassociate\b', head):
        return 'entry'
    for pattern, level in ((_EXP_INTERN, 'internship'), (_EXP_FRESHER, 'fresher'), (_EXP_ENTRY, 'entry'), (_EXP_MID, 'mid'), (_EXP_SENIOR, 'senior')):
        if pattern.search(senior_field):
            return level
    years = years_asked(text)
    if years is not None:
        return 'fresher' if years == 0 else 'entry' if years <= 2 else 'mid' if years <= 6 else 'senior'
    if _EXP_FRESHER.search((text or '')[:1500].lower()):
        return 'fresher'
    if re.search(r'\bmanager\b', head):
        return 'mid'                                                                          # "Sales Manager" asks for a few years of experience, not a leader's
    return ''


# ---------------------------------------------------------------------------------------------------------------- work mode
_HYBRID = re.compile(r'\bhybrid\b')
_HYBRID_TEXT = re.compile(r'\bhybrid (?:work|working|model|role|position|setup|set-up|schedule|mode|environment|opportunity|basis|policy|culture)\b|\b(?:work|working|role|position|job|location) (?:is |will be )?hybrid\b|'
                          r'\bhybrid\b[^.]{0,25}\b(?:office|remote|days a week|days per week)|\b(?:office|onsite|on-site)\b[^.]{0,25}\bremote\b[^.]{0,20}\bdays\b')
_REMOTE_PLACE = re.compile(r'\bremote\b|\bwork from home\b|\bwfh\b|\bwork-from-home\b|\banywhere\b|\bworldwide\b')
_REMOTE_TEXT = re.compile(r'\bfully remote\b|\b100% remote\b|\bremote (?:position|role|job|work|working|opportunity|first|location|basis|mode|setup|set-up)\b|\bwork[- ]from[- ]home\b|\bwork remotely\b|\bremote-(?:first|friendly)\b|'
                          r'\b(?:work|working|role|position|job|location) (?:is |will be )?(?:fully )?remote\b|\bwfh\b|\bremote\b[^.]{0,20}\bindia\b|\bindia\b[^.]{0,20}\bremote\b')


def work_mode(location, title='', text=''):
    """remote / hybrid / onsite, or '' when there is no location at all. A job with a real place and no sign of remote or hybrid work is on-site."""
    loc, head, body = (location or '').lower(), (title or '').lower(), (text or '')[:2500].lower()
    if _HYBRID.search(loc) or _HYBRID.search(head) or _HYBRID_TEXT.search(body):
        return 'hybrid'
    if _REMOTE_PLACE.search(loc) or _REMOTE_PLACE.search(head) or _REMOTE_TEXT.search(body):
        return 'remote'
    return 'onsite' if loc.strip() else ''


# ---------------------------------------------------------------------------------------------------------------- India and cities
CITY_ALIASES = {'bangalore': 'Bengaluru', 'bengaluru': 'Bengaluru', 'gurgaon': 'Gurugram', 'gurugram': 'Gurugram', 'bombay': 'Mumbai', 'mumbai': 'Mumbai', 'calcutta': 'Kolkata',
                'kolkata': 'Kolkata', 'madras': 'Chennai', 'chennai': 'Chennai', 'new delhi': 'Delhi', 'delhi': 'Delhi', 'delhi ncr': 'Delhi', 'noida': 'Noida', 'greater noida': 'Noida',
                'hyderabad': 'Hyderabad', 'pune': 'Pune', 'ahmedabad': 'Ahmedabad', 'jaipur': 'Jaipur', 'kochi': 'Kochi', 'cochin': 'Kochi', 'chandigarh': 'Chandigarh', 'indore': 'Indore',
                'coimbatore': 'Coimbatore', 'thiruvananthapuram': 'Thiruvananthapuram', 'trivandrum': 'Thiruvananthapuram', 'lucknow': 'Lucknow', 'nagpur': 'Nagpur', 'surat': 'Surat',
                'vadodara': 'Vadodara', 'bhubaneswar': 'Bhubaneswar', 'visakhapatnam': 'Visakhapatnam', 'mysuru': 'Mysuru', 'mysore': 'Mysuru', 'faridabad': 'Faridabad', 'ghaziabad': 'Ghaziabad',
                'navi mumbai': 'Navi Mumbai', 'thane': 'Thane', 'mohali': 'Mohali', 'kanpur': 'Kanpur', 'patna': 'Patna', 'guwahati': 'Guwahati', 'bhopal': 'Bhopal', 'ranchi': 'Ranchi'}
_STATES = ('maharashtra', 'karnataka', 'tamil nadu', 'telangana', 'haryana', 'uttar pradesh', 'gujarat', 'rajasthan', 'west bengal', 'kerala', 'punjab', 'madhya pradesh', 'odisha', 'bihar',
           'andhra pradesh', 'assam', 'jharkhand', 'chhattisgarh', 'uttarakhand', 'goa', 'himachal pradesh', 'jammu')
_INDIA_WORDS = re.compile(r'\bindia\b|\bindian\b|\bpan[- ]india\b')


def _parts(location):
    loc = re.sub(r'(?i)\bremote\b|\bhybrid\b|\bworldwide\b|\banywhere\b|[·•|()]', ',', location or '')
    return [p.strip() for p in loc.split(',') if p.strip()]


def city_of(location):
    """The Indian city a location names (normalized, e.g. Bangalore -> Bengaluru), or ''."""
    for part in _parts(location):
        key = re.sub(r'\s+', ' ', re.sub(r'(?i)\b(city|district|area|region|ncr)\b', '', part)).strip().lower()
        if key in CITY_ALIASES:
            return CITY_ALIASES[key]
        for alias, city in CITY_ALIASES.items():                     # "Pune, Maharashtra" and "Greater Pune Area" both name Pune
            if re.search(r'\b%s\b' % re.escape(alias), key):
                return city
    return ''


# ---------------------------------------------------------------------------------------------------------------- countries and regions of the world
# A job is in ONE world region: the one of the country its location names, a region its location names ("Remote - Europe", "APAC"), or "Global / Worldwide"
# for a remote job open to anywhere. A location that names neither gives no region - nothing is guessed. Inside India the city, else the state, gives a
# region of India; a job that only says "India" has none. Work mode (remote / hybrid / on-site) stays a filter of its own.
REGIONS = [
    ('worldwide', 'Global / Worldwide', 'Remote roles open to people anywhere in the world.', 'fa-globe'),
    ('india-south-asia', 'India & South Asia', 'India, Sri Lanka, Bangladesh, Nepal and Pakistan - on-site, hybrid and remote roles.', 'fa-map-marker'),
    ('china', 'China & Hong Kong', 'Mainland China, Hong Kong and Macau - at Chinese companies and at international companies with teams there.', 'fa-map-o'),
    ('asia-pacific', 'Asia-Pacific', 'Singapore, Japan, Korea, Taiwan, South-East Asia, Australia and New Zealand.', 'fa-sun-o'),
    ('europe', 'Europe', 'The United Kingdom, Ireland, continental Europe, the Nordics and Central & Eastern Europe.', 'fa-university'),
    ('north-america', 'North America', 'The United States and Canada.', 'fa-building-o'),
    ('latin-america', 'Latin America', 'Mexico, Central America, Brazil and the rest of South America.', 'fa-leaf'),
    ('middle-east-africa', 'Middle East & Africa', 'The Gulf, Israel, Turkey, Egypt and the rest of Africa.', 'fa-compass'),
]
INDIA_ZONES = [
    ('north-india', 'North India', 'Delhi NCR, Haryana, Punjab, Chandigarh, Uttar Pradesh, Rajasthan and the hill states.', 'N'),
    ('south-india', 'South India', 'Bengaluru, Hyderabad, Chennai, Kochi and the rest of Karnataka, Telangana, Tamil Nadu, Kerala and Andhra Pradesh.', 'S'),
    ('west-india', 'West India', 'Mumbai, Pune, Ahmedabad and the rest of Maharashtra, Gujarat and Goa.', 'W'),
    ('east-central-india', 'East & Central India', 'Kolkata, Bhubaneswar, Patna, Ranchi, Bhopal, Indore and the North-East.', 'E'),
]
REGION_LABELS = {slug: name for slug, name, _d, _i in REGIONS + INDIA_ZONES}
# every country the board knows, by region (ISO code, name); a country not listed simply gives no region
_REGION_OF_COUNTRY = {
    'india-south-asia': (('in', 'India'), ('lk', 'Sri Lanka'), ('bd', 'Bangladesh'), ('np', 'Nepal'), ('pk', 'Pakistan')),
    'china': (('cn', 'China'), ('hk', 'Hong Kong'), ('mo', 'Macau')),
    'asia-pacific': (('sg', 'Singapore'), ('jp', 'Japan'), ('kr', 'South Korea'), ('tw', 'Taiwan'), ('ph', 'Philippines'),
                     ('id', 'Indonesia'), ('my', 'Malaysia'), ('vn', 'Vietnam'), ('th', 'Thailand'), ('kh', 'Cambodia'), ('au', 'Australia'), ('nz', 'New Zealand')),
    'europe': (('gb', 'United Kingdom'), ('ie', 'Ireland'), ('de', 'Germany'), ('fr', 'France'), ('nl', 'Netherlands'), ('be', 'Belgium'), ('lu', 'Luxembourg'),
               ('ch', 'Switzerland'), ('at', 'Austria'), ('es', 'Spain'), ('pt', 'Portugal'), ('it', 'Italy'), ('gr', 'Greece'), ('se', 'Sweden'), ('dk', 'Denmark'),
               ('no', 'Norway'), ('fi', 'Finland'), ('is', 'Iceland'), ('pl', 'Poland'), ('cz', 'Czech Republic'), ('sk', 'Slovakia'), ('hu', 'Hungary'), ('ro', 'Romania'),
               ('bg', 'Bulgaria'), ('rs', 'Serbia'), ('hr', 'Croatia'), ('si', 'Slovenia'), ('ee', 'Estonia'), ('lv', 'Latvia'), ('lt', 'Lithuania'), ('ua', 'Ukraine')),
    'north-america': (('us', 'United States'), ('ca', 'Canada')),
    'latin-america': (('mx', 'Mexico'), ('br', 'Brazil'), ('ar', 'Argentina'), ('co', 'Colombia'), ('cl', 'Chile'), ('pe', 'Peru'), ('uy', 'Uruguay'), ('ec', 'Ecuador'),
                      ('cr', 'Costa Rica'), ('gt', 'Guatemala'), ('pa', 'Panama'), ('do', 'Dominican Republic'), ('pr', 'Puerto Rico')),
    'middle-east-africa': (('ae', 'United Arab Emirates'), ('sa', 'Saudi Arabia'), ('qa', 'Qatar'), ('bh', 'Bahrain'), ('kw', 'Kuwait'), ('om', 'Oman'), ('il', 'Israel'),
                           ('jo', 'Jordan'), ('lb', 'Lebanon'), ('tr', 'Turkey'), ('eg', 'Egypt'), ('ma', 'Morocco'), ('za', 'South Africa'), ('ng', 'Nigeria'),
                           ('ke', 'Kenya'), ('gh', 'Ghana'), ('rw', 'Rwanda')),
}
COUNTRY_REGION = {name: region for region, countries in _REGION_OF_COUNTRY.items() for _code, name in countries}
COUNTRY_OF_CODE = dict([(code, name) for countries in _REGION_OF_COUNTRY.values() for code, name in countries] + [('uk', 'United Kingdom')])
REGION_COUNTRIES = {region: [name for _code, name in countries] for region, countries in _REGION_OF_COUNTRY.items()}
# the order in which a location that names several countries is read: India first (the board's home), then the biggest job markets
_COUNTRIES = ('India', 'United States', 'United Kingdom', 'Canada', 'Australia', 'Singapore', 'Germany', 'France', 'Netherlands', 'Ireland') + tuple(
    name for countries in _REGION_OF_COUNTRY.values() for _code, name in countries
    if name not in ('India', 'United States', 'United Kingdom', 'Canada', 'Australia', 'Singapore', 'Germany', 'France', 'Netherlands', 'Ireland'))
_COUNTRY_NAME_RX = [(name, re.compile(r'\b%s\b' % re.escape(name), re.I)) for name in _COUNTRIES]
# big cities of the world (city -> country), so that "San Francisco, CA" or "Remote - London" says its country; Indian cities are CITY_ALIASES above
WORLD_CITIES = {
    'United States': ('New York', 'New York City', 'NYC', 'Brooklyn', 'San Francisco', 'South San Francisco', 'San Jose', 'Palo Alto', 'Mountain View', 'Menlo Park',
                      'Sunnyvale', 'Santa Clara', 'Redwood City', 'San Mateo', 'Oakland', 'Berkeley', 'Los Angeles', 'San Diego', 'Irvine', 'Seattle', 'Bellevue',
                      'Redmond', 'Austin', 'Dallas', 'Houston', 'Boston', 'Chicago', 'Denver', 'Boulder', 'Atlanta', 'Miami', 'Washington DC', 'Washington, D.C.',
                      'Philadelphia', 'Pittsburgh', 'Salt Lake City', 'Lehi', 'Phoenix', 'Raleigh', 'Durham', 'Nashville', 'Minneapolis', 'Detroit', 'St. Louis',
                      'Kansas City', 'Columbus', 'Indianapolis', 'Charlotte', 'Reston', 'Herndon', 'Portland'),
    'Canada': ('Toronto', 'Vancouver', 'Montreal', 'Montréal', 'Ottawa', 'Calgary', 'Waterloo', 'Edmonton'),
    'United Kingdom': ('London', 'Manchester', 'Edinburgh', 'Glasgow', 'Bristol', 'Oxford', 'Belfast', 'Leeds', 'Reading', 'England', 'Scotland', 'Wales'),
    'Ireland': ('Dublin', 'Cork', 'Galway'),
    'Germany': ('Berlin', 'Munich', 'München', 'Hamburg', 'Frankfurt', 'Stuttgart', 'Cologne', 'Köln', 'Düsseldorf', 'Deutschland'),
    'France': ('Paris', 'Lyon', 'Toulouse'), 'Netherlands': ('Amsterdam', 'Rotterdam', 'The Hague', 'Utrecht', 'Eindhoven'), 'Belgium': ('Brussels', 'Antwerp'),
    'Spain': ('Madrid', 'Barcelona', 'Valencia', 'Malaga', 'Málaga'), 'Portugal': ('Lisbon', 'Lisboa', 'Porto'), 'Italy': ('Milan', 'Milano', 'Rome', 'Turin'),
    'Switzerland': ('Zurich', 'Zürich', 'Geneva', 'Basel', 'Lausanne'), 'Austria': ('Vienna', 'Wien'), 'Denmark': ('Copenhagen',), 'Sweden': ('Stockholm', 'Gothenburg', 'Malmö'),
    'Norway': ('Oslo',), 'Finland': ('Helsinki',), 'Poland': ('Warsaw', 'Warszawa', 'Krakow', 'Kraków', 'Wroclaw', 'Wrocław', 'Gdansk', 'Gdańsk'),
    'Czech Republic': ('Prague', 'Brno'), 'Romania': ('Bucharest', 'Cluj'), 'Hungary': ('Budapest',), 'Greece': ('Athens',), 'Ukraine': ('Kyiv', 'Kiev'),
    'Estonia': ('Tallinn',), 'Lithuania': ('Vilnius',), 'Bulgaria': ('Sofia',), 'Serbia': ('Belgrade',), 'Turkey': ('Istanbul', 'Ankara'),
    'Israel': ('Tel Aviv', 'Jerusalem', 'Haifa', 'Herzliya'), 'United Arab Emirates': ('Dubai', 'Abu Dhabi'), 'Saudi Arabia': ('Riyadh', 'Jeddah'), 'Qatar': ('Doha',),
    'Egypt': ('Cairo',), 'South Africa': ('Cape Town', 'Johannesburg'), 'Nigeria': ('Lagos',), 'Kenya': ('Nairobi',), 'Morocco': ('Casablanca',),
    'Singapore': ('Singapore',), 'Japan': ('Tokyo', 'Osaka'), 'South Korea': ('Seoul',), 'Australia': ('Sydney', 'Melbourne', 'Brisbane', 'Perth'),
    'New Zealand': ('Auckland', 'Wellington'), 'Hong Kong': ('Hong Kong',), 'Taiwan': ('Taipei',), 'Macau': ('Macao',),
    'China': ('Shanghai', 'Beijing', 'Shenzhen', 'Hangzhou', 'Guangzhou', 'Chengdu', 'Suzhou', 'Nanjing', 'Wuhan', "Xi'an", 'Tianjin', 'Xiamen', 'Hefei', 'Dongguan',
              'Qingdao', 'Mainland China'),
    'Philippines': ('Manila', 'Makati'), 'Indonesia': ('Jakarta',), 'Malaysia': ('Kuala Lumpur',), 'Thailand': ('Bangkok',), 'Vietnam': ('Ho Chi Minh City', 'Hanoi'),
    'Brazil': ('Sao Paulo', 'São Paulo', 'Rio de Janeiro'), 'Mexico': ('Mexico City', 'Ciudad de México', 'Guadalajara', 'Monterrey'), 'Colombia': ('Bogota', 'Bogotá', 'Medellin', 'Medellín'),
    'Argentina': ('Buenos Aires',), 'Chile': ('Santiago',), 'Peru': ('Lima',), 'Uruguay': ('Montevideo',),
    'Sri Lanka': ('Colombo',), 'Bangladesh': ('Dhaka',), 'Pakistan': ('Karachi', 'Lahore', 'Islamabad'), 'Nepal': ('Kathmandu',),
}
_NOT_A_CITY = {'England', 'Scotland', 'Wales', 'Deutschland', 'Singapore', 'Hong Kong', 'Macao', 'Mainland China'}               # say the country, are no city of the City filter
_CITY_CANON = {'New York City': 'New York', 'NYC': 'New York', 'Brooklyn': 'New York', 'South San Francisco': 'San Francisco', 'Washington, D.C.': 'Washington DC',
               'Montréal': 'Montreal', 'München': 'Munich', 'Köln': 'Cologne', 'Málaga': 'Malaga', 'Lisboa': 'Lisbon', 'Milano': 'Milan', 'Zürich': 'Zurich',
               'Wien': 'Vienna', 'Warszawa': 'Warsaw', 'Kraków': 'Krakow', 'Wrocław': 'Wroclaw', 'Gdańsk': 'Gdansk', 'Kiev': 'Kyiv', 'São Paulo': 'Sao Paulo',
               'Ciudad de México': 'Mexico City', 'Bogotá': 'Bogota', 'Medellín': 'Medellin', 'Makati': 'Manila'}
_WORLD_CITY_RX = [(re.compile(r'(?<![\w])%s(?![\w])' % re.escape(city), re.I), city, country) for country, cities in WORLD_CITIES.items() for city in cities]
# state / province codes of an address: "Austin, TX", "Toronto, ON", "Sydney NSW" (CA is read as California: "San Francisco, CA" is far more common than Canada)
_US_STATES = set('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split())
_CA_PROVINCES = set('ON BC QC AB MB NS SK NB NL PE'.split())
_AU_STATES = set('NSW VIC QLD ACT'.split())
_ABBREVIATIONS = [(re.compile(p), c) for p, c in ((r'\bU\.?S\.?A\b|\bU\.S\.(?=\W|$)|\bUS\b', 'United States'), (r'\bU\.?K\b', 'United Kingdom'), (r'\bU\.?A\.?E\b', 'United Arab Emirates'), (r'\bPRC\b', 'China'))]
_REGION_WORDS = [(re.compile(p, re.I), r) for p, r in ((r'\bapac\b|\basia[- ]pacific\b|\bsouth[- ]?east asia\b|\bsea\b(?= region)', 'asia-pacific'), (r'\beurope\b|\beu\b', 'europe'),
                                                      (r'\bnorth america\b|\bnoram\b|\bamericas\b(?!.*latin)', 'north-america'), (r'\blatam\b|\blatin america\b|\bsouth america\b', 'latin-america'),
                                                      (r'\bmiddle east\b|\bmena\b|\bgcc\b|\bafrica\b', 'middle-east-africa'))]


def _location_parts(location):
    return [p.strip() for p in re.split(r'[,;|·•/()]|\s-\s|\s–\s', location or '') if p.strip()]


def world_city_of(location):
    """The city outside India a location names (normalized, e.g. NYC -> New York), or ''."""
    for rx, city, _country in _WORLD_CITY_RX:
        if city not in _NOT_A_CITY and rx.search(location or ''):
            return _CITY_CANON.get(city, city)
    return ''


def country_of(location, india=False):
    """The country of a job: India for an Indian job, else the country its location names - by name, by a big city ("London"), by an abbreviation ("USA", "UK")
    or by a state / province code ("Austin, TX"); '' when it names none (nothing is guessed)."""
    if india:
        return 'India'
    loc = location or ''
    for name, rx in _COUNTRY_NAME_RX:
        if rx.search(loc):
            return name
    for rx, _city, country in _WORLD_CITY_RX:
        if rx.search(loc):
            return country
    for rx, country in _ABBREVIATIONS:
        if rx.search(loc):
            return country
    parts = [p.split()[-1] if p.split() else p for p in _location_parts(loc)]
    for code in parts:
        if code in _CA_PROVINCES:
            return 'Canada'
    for code in parts:
        if code in _AU_STATES:
            return 'Australia'
    for code in parts:
        if code in _US_STATES:
            return 'United States'
    return ''

_WORLDWIDE = re.compile(r'\b(worldwide|anywhere|global(ly)?)\b', re.I)
_ZONE_OF_CITY = {
    'north-india': ('Delhi', 'Gurugram', 'Noida', 'Faridabad', 'Ghaziabad', 'Chandigarh', 'Mohali', 'Jaipur', 'Lucknow', 'Kanpur'),
    'south-india': ('Bengaluru', 'Hyderabad', 'Chennai', 'Kochi', 'Coimbatore', 'Thiruvananthapuram', 'Visakhapatnam', 'Mysuru'),
    'west-india': ('Mumbai', 'Navi Mumbai', 'Thane', 'Pune', 'Ahmedabad', 'Surat', 'Vadodara', 'Nagpur'),
    'east-central-india': ('Kolkata', 'Bhubaneswar', 'Patna', 'Ranchi', 'Guwahati', 'Bhopal', 'Indore'),
}
ZONE_OF_CITY = {city: zone for zone, cities in _ZONE_OF_CITY.items() for city in cities}
_ZONE_OF_STATE = [(re.compile(r'\b(%s)\b' % rx, re.I), zone) for rx, zone in (
    (r'delhi|haryana|punjab|chandigarh|himachal|jammu|kashmir|ladakh|uttarakhand|uttar pradesh|rajasthan', 'north-india'),
    (r'karnataka|tamil nadu|kerala|telangana|telengana|andhra pradesh|puducherry|pondicherry', 'south-india'),
    (r'maharashtra|gujarat|goa', 'west-india'),
    (r'madhya pradesh|chhattisgarh|west bengal|odisha|orissa|bihar|jharkhand|assam|tripura|meghalaya|manipur|nagaland|mizoram|arunachal|sikkim', 'east-central-india'))]
# the two-letter state codes of Indian locations ("Sanand, GJ, India") - read only as a whole part of a location in India
_ZONE_OF_CODE = {code: zone for zone, codes in (
    ('north-india', 'DL HR PB CH HP JK UT UP RJ'), ('south-india', 'KA TN KL TG TS AP PY'), ('west-india', 'MH GJ GA'),
    ('east-central-india', 'MP CG CT WB OD OR BR JH AS TR ML MN NL MZ AR SK')) for code in codes.split()}


def region_of(country, location='', work_mode=''):
    """The world region of a job (a key of REGIONS): the region of its country, else a region its location names ("Remote - Europe", "APAC"), else
    "worldwide" for a remote job open to anywhere; '' otherwise."""
    if country:
        return COUNTRY_REGION.get(country, '')
    for rx, region in _REGION_WORDS:
        if rx.search(location or ''):
            return region
    if work_mode == 'remote' and _WORLDWIDE.search(location or ''):
        return 'worldwide'
    return ''


def india_zone_of(location, city='', country=''):
    """The region of India (a key of INDIA_ZONES) of a job in India: from its city, else the state its location names; '' when it says only "India"."""
    if country != 'India':
        return ''
    if city in ZONE_OF_CITY:
        return ZONE_OF_CITY[city]
    for rx, zone in _ZONE_OF_STATE:
        if rx.search(location or ''):
            return zone
    for part in re.split(r'[,·•|()/;-]', location or ''):
        code = part.strip()
        if len(code) == 2 and code.isupper() and code in _ZONE_OF_CODE:
            return _ZONE_OF_CODE[code]
    return ''


def skill_key(name):
    """The stored form of a skill for the Skills filter: lower case, single spaces, no commas."""
    return re.sub(r'[\s,]+', ' ', (name or '').strip().lower())


def is_india(location, countries=''):
    """True when the job is in India: the location or the country list says so, or it names an Indian city or state."""
    loc, cs = (location or '').lower(), (countries or '').lower()
    if _INDIA_WORDS.search(loc) or re.search(r'(^|[,\s])in($|[,\s])', cs) or _INDIA_WORDS.search(cs):
        return True
    if city_of(location):
        return True
    return any(s in loc for s in _STATES)


# ---------------------------------------------------------------------------------------------------------------- salary in lakhs per year (LPA)
_OTHER_CURRENCY = re.compile(r'\$|\busd\b|€|\beur\b|£|\bgbp\b|\baed\b|\bsgd\b|\baud\b|\bcad\b')
_RUPEES = re.compile(r'₹|\brs\b|\binr\b|\blakhs?\b|\blacs?\b|\blpa\b|\bcrores?\b')
_PER_MONTH = re.compile(r'per month|/\s*month|/\s*mo\b|\bmonthly\b|\bp\.?\s?m\.?(?=\s|$)')
_PER_SHORT = re.compile(r'per (?:hour|day|week)|/\s*(?:hr|hour|day|week)\b|\bhourly\b|\bdaily\b|\bweekly\b')
_AMOUNT = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*(k|lakhs?|lacs?|lpa|l|crores?|cr)?(?![a-z])')


def salary_lpa(text):
    """(from, to) in lakhs of rupees per year from a salary as the source states it ("Rs 15 - 25 lakhs p.a.", "INR 480,000 – 600,000 per year",
    "Rs 35000 - Rs 40000 per month"); (0.0, 0.0) when the text gives no rupee salary. Another currency or hourly / daily pay is never converted:
    the salary filter then simply does not match the job."""
    t = (text or '').lower().replace('–', '-').replace('—', '-')
    if not t.strip() or _OTHER_CURRENCY.search(t) or not _RUPEES.search(t) or _PER_SHORT.search(t):
        return (0.0, 0.0)
    in_lakhs = bool(re.search(r'\blakhs?\b|\blacs?\b|\blpa\b', t))
    values = []
    for number, unit in _AMOUNT.findall(t):
        n = float(number.replace(',', ''))
        if unit.startswith('cr'):
            value = n * 100
        elif unit.startswith('l'):
            value = n
        elif unit == 'k':
            value = n * 1000 / 100000
        elif in_lakhs and n < 1000:                                         # "15 - 25 lakhs": the unit is written once
            value = n
        else:
            value = n / 100000
        if value > 0:
            values.append(value)
    if not values:
        return (0.0, 0.0)
    if _PER_MONTH.search(t):
        values = [v * 12 for v in values]
    low, high = min(values[:2]), max(values[:2])
    if high > 1000:                                                         # not a believable yearly salary
        return (0.0, 0.0)
    return (round(low, 2), round(high, 2))


def salary_ranges_of(low, high):
    """The keys of SALARY_RANGES that a (from, to) LPA salary overlaps; [] for a job without a salary."""
    if high <= 0:
        return []
    return [key for key, _label, lo, hi in SALARY_RANGES if high >= lo and (hi is None or low < hi)]


# ---------------------------------------------------------------------------------------------------------------- the Salary filter: one band per job
# Each salary stays in the currency the employer states (no exchange rate is guessed): rupees in lakhs per year (LPA), dollars / euros / pounds in thousands per
# year. A job's band is the band of its LOWEST stated amount. A salary that cannot be read for sure (another currency, hourly pay, no amount) gets no band.
SALARY_BANDS = [('inr-0-10', '₹0–10 LPA', 'inr', 0, 10), ('inr-10-25', '₹10–25 LPA', 'inr', 10, 25), ('inr-25-50', '₹25–50 LPA', 'inr', 25, 50), ('inr-50', '₹50 LPA+', 'inr', 50, None)]
for _cur, _sym in (('usd', '$'), ('eur', '€'), ('gbp', '£')):
    SALARY_BANDS += [('%s-0-100' % _cur, '%s0–100K' % _sym, _cur, 0, 100), ('%s-100-150' % _cur, '%s100K–150K' % _sym, _cur, 100, 150),
                     ('%s-150-200' % _cur, '%s150K–200K' % _sym, _cur, 150, 200), ('%s-200-250' % _cur, '%s200K–250K' % _sym, _cur, 200, 250),
                     ('%s-250' % _cur, '%s250K+' % _sym, _cur, 250, None)]
SALARY_BAND_LABELS = {key: label for key, label, _c, _lo, _hi in SALARY_BANDS}
_FOREIGN = (('usd', re.compile(r'\$|\busd\b')), ('eur', re.compile(r'€|\beur\b')), ('gbp', re.compile(r'£|\bgbp\b')))
_ANY_OTHER = re.compile(r'₹|\binr\b|\bsgd\b|\baud\b|\bcad\b|\baed\b|\bchf\b|\bhkd\b|\bjpy\b|¥')
_K_AMOUNT = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*(k|m)?(?![a-z])')


def salary_k(text):
    """(currency, lowest yearly amount in thousands) for a salary in dollars, euros or pounds ("$177.7K – $266.5K", "€60,000 - €80,000 per year");
    ('', 0.0) when it is in another currency, mixes currencies, is hourly / daily or gives no believable yearly amount."""
    t = (text or '').lower().replace('–', '-').replace('—', '-')
    found = [cur for cur, rx in _FOREIGN if rx.search(t)]
    if len(found) != 1 or _ANY_OTHER.search(t) or _PER_SHORT.search(t):
        return ('', 0.0)
    values = []
    for number, unit in _K_AMOUNT.findall(t.split('•')[0]):                 # the first part is the pay; what follows (equity %, bonus) is not
        n = float(number.replace(',', ''))
        value = n if unit == 'k' else n * 1000 if unit == 'm' else n / 1000 if n >= 1000 else 0.0
        if value > 0:
            values.append(value)
    if not values:
        return ('', 0.0)
    low = min(values[:2]) * (12 if _PER_MONTH.search(t) else 1)
    return (found[0], round(low, 1)) if 10 <= low <= 5000 else ('', 0.0)


def salary_band(text):
    """The SALARY_BANDS key of a job's salary (by its lowest amount, in its own currency), or '' when it has none that can be read for sure."""
    low, _high = salary_lpa(text)
    cur, value = ('inr', low) if low > 0 else salary_k(text)
    if not cur:
        return ''
    return next((key for key, _l, c, lo, hi in SALARY_BANDS if c == cur and value >= lo and (hi is None or value < hi)), '')


# ---------------------------------------------------------------------------------------------------------------- one call for a listing
def facets(title, location, countries, employment_type, seniority, text):
    return {'exp_level': exp_level(title, seniority, text), 'job_type': job_type(employment_type, title), 'work_mode': work_mode(location, title, text),
            'india': is_india(location, countries), 'city': city_of(location) or world_city_of(location)}
