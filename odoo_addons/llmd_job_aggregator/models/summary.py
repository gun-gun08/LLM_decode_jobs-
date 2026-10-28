"""A short, consistent summary of one job (pure Python, no Odoo imports: unit-tested by rolelib/summary_test.py).

Every source - a full job text (Himalayas, JSearch, partner feeds) or a short snippet (Jooble, Adzuna) - becomes the same shape:
a job overview (1-2 sentences), 4-6 key responsibilities, 4-6 required skills & qualifications, the experience level, the salary (only when the job
states one) and a few stated details (duration, working hours, shift, notice period). Company culture and history, benefits, hashtags, referral and
interview-process text, equal-opportunity statements, "originally posted on" and "apply here" lines are left out; near-duplicate lines are kept once.

Nothing is made up: every line is a sentence or a list item of the job itself, or a stored field of it. What the job does not say stays empty (the page
then shows "Not specified"). A short snippet therefore gives a short summary - the 150-250 words are reached when the source sends the full job text.
"""
import re

try:
    from . import view_helpers as V
    from .parsers import OTHER_HEAD, SENT_SPLIT, classify_heading, lines, plain_text
except ImportError:                                  # imported on its own (tests)
    import view_helpers as V
    from parsers import OTHER_HEAD, SENT_SPLIT, classify_heading, lines, plain_text

NOT_SPECIFIED = 'Not specified'
MAX_WORDS = 250
MIN_ITEMS, MAX_ITEMS = 4, 6

_JUNK = re.compile(
    r"(?:#\w+|\brefer(?:ral|rals|ring)?\b|\binterview(?:s|ing)? (?:process|rounds?|stages?|steps?|loop)\b|\b(?:first|second|third|final|technical|hr|managerial) round\b|"
    r"\bequal(?:[- ]employment)? opportunit\w*|\bdivers\w*|\binclusi\w*|\baccommodations?\b|\bbenefits?\b|\bperks?\b|\binsurance\b|\bpaid (?:time off|leave|vacation|parental|holidays?)\b|"
    r"\bwellness\b|\bwell-?being\b|\bculture\b|\boriginally posted\b|\bapply (?:now|here|today|at|via|through)\b|\bsend (?:your |us your |in your )?(?:cv|resume)\b|\bwhatsapp\b|"
    r"\bcall (?:us|on)\b|\bvisit (?:our|us)\b|\bfollow us\b|\bnasdaq\b|\bnyse\b|\bfounded in\b|\bour mission\b|\bglobal leader\b|\bindustry leader\b|\bpride ourselves\b|"
    r"\btime zones\b|\bdiscounts?\b|\bpension\b|\bvacation\b|\boffsites?\b|\bheadspace\b|\btherapy\b|\bmental health\b|\bteam outings?\b|\bfree (?:lunch|meals|snacks)\b|"
    r"\b(?:millions|billions|thousands) of (?:diners|customers|users|people|clients)\b|\b\d[\d,.]*\+?\s*(?:million |billion )?(?:diners|customers|clients|users|employees|"
    r"restaurant partners|partners|restaurants|members|countries|offices|brands)\b|\bpart of (?:the )?[\w&. ]{2,40}(?:group|holdings|family|inc)\b|"
    r"\b(?:attractive|competitive|best|lucrative) (?:salary |pay |compensation )?package\b|\bpackage is offered\b|\bwork from (?:\(almost\) )?anywhere for\b|\bdevelopment dollars\b|\bemployee resource\b|[\w.+-]+@[\w-]+\.\w+|https?://|\bread more\b|\bclick here\b|\bjob alerts?\b|"
    r"\bexport[- ]controlled\b|\bexport licen[cs]es?\b|\bgartner\b|\bforrester\b|\bnamed a leader\b|\bqualified applicants\b|\bconsideration for employment\b|\barrest and convictions?\b|\bautomated employment decision\b|\bapplicants? (?:&|and) employees\b|"
    r"\bprivacy (?:notice|policy|statement)\b|\bby applying\b|\bencouraged to apply\b|\bto apply for (?:roles|this|jobs|positions|the)\b|\bverify opportunities\b|"
    r"\bpreferred qualifications are a bonus\b|\balways looking for (?:people|talent)\b|\bnever ask (?:candidates|applicants)\b|\brecruitment (?:fraud|scams?)\b|"
    r"\bauthori[sz]ed channels\b|\bpay transparency\b|\bemployment laws\b|\bcomplies with all applicable\b|\blife at\b|\bour values\b|\bpassion for (?:the|our) mission\b)", re.I)
_RESP = re.compile(r"^(?:you will|you'll|you are responsible|responsible for|your (?:main )?(?:role|responsibilities)|"
                   r"(?:analy[sz]e|build|develop|design|manage|lead|own|drive|create|collaborate|work (?:with|closely|on)|partner|support|implement|maintain|monitor|"
                   r"prepare|conduct|ensure|identify|deliver|define|write|test|deploy|optimi[sz]e|automate|research|evaluate|translate|present|coordinate|perform|use|"
                   r"gather|clean|model|mentor|architect|establish|integrate|review|track|report|plan|execute|handle|assist|engage|communicate|document|train)\b)", re.I)
_RESP_INSIDE = re.compile(r"\b(?:you will|you'll) (?!be (?:part|joining|working with a))", re.I)
_REQ = re.compile(r"\b(?:experience (?:with|in|of)|years? of|yrs|proficien\w*|knowledge of|familiar\w*|degree|bachelor\w*|master\w*|b\.?\s?tech|m\.?\s?tech|mba|graduate|"
                  r"certif\w*|skills? in|(?:strong|excellent|good) (?:\w+ ){0,2}skills|must (?:have|be)|required|eligib\w*|understanding of|ability to|expertise in|"
                  r"hands-on|working knowledge|fluent|qualification\w*)\b", re.I)
_INTRO = re.compile(r"\b(?:we are|we're|is|are|currently) (?:seeking|searching for|looking for|hiring)\b|\b(?:this|the) (?:role|position|opportunity)\b|\bas an? [A-Z]|\bjoin (?:our|the|us)\b", re.I)
_LEADIN = re.compile(r"(?::|\b(?:if|when|where|who|that) you(?:'ll| will| have| are| can)?|\byou(?:'ll| will) (?:need|have|bring)|"     # a line that only opens a list:
                     r"\bwe(?:'re| are) looking for (?:someone|people|candidates) who)[\s.…:]*$", re.I)                               # "You'll thrive with us if you:"
_LABEL_NAMES = ('Required Experience', 'Experience', 'Position Type', 'Job Type', 'Employment Type', 'Duration', 'Stipend', 'Salary', 'CTC', 'Compensation', 'Working Hours',
                'Shift Time', 'Shift Timing', 'Shift', 'Notice Period', 'Joining', 'Eligibility', 'Education', 'Qualification', 'Job Title', 'Work Location', 'Location',
                'Working Style', 'Work Mode', 'Department', 'Cab Facility', 'Openings')
_ALIASES = {'shift time': 'shift', 'shift timing': 'shift'}
_LABEL = re.compile(r'^(%s)\s*:\s*(.+)$' % '|'.join(re.escape(x) for x in _LABEL_NAMES), re.I)
_LABEL_ANY = re.compile(r'(?<![A-Za-z])(%s)\s*(?::|\s[-–]\s)\s*' % '|'.join(re.escape(x) for x in _LABEL_NAMES), re.I)
_VALUE_END = re.compile(r'\s+(?:About\b|The Role\b|Job Description\b|Role\b|We\b|Our\b|At [A-Z]|Location\b|Work Mode\b|Job Type\b|Type\b)|(?<=[a-z0-9)])[.;](?:\s|$)')


def _words(text):
    return len((text or '').split())


def _key(text):
    return {w for w in re.findall(r'[a-z0-9+#]{3,}', (text or '').lower())}


def _similar(a, b):
    ka, kb = _key(a), _key(b)
    return bool(ka and kb) and len(ka & kb) / float(min(len(ka), len(kb))) >= 0.7


def _tidy(text, limit=24):
    """A clean line: no bullet signs or numbering, a capital first letter, one full stop, at most `limit` words (cut after a clause when possible)."""
    t = re.sub(r'\s+', ' ', text or '').strip()
    t = re.sub(r'^(?:[-–—•·*~>]+|\d{1,2}[.)])\s*', '', t).strip(' \t:;,')
    t = re.sub(r'\s+([,;:.!?])(?=\s|$)', r'\1', t)
    t = re.sub(r',?\s*(?:including but not limited to|including|such as|e\.g\.?|like)\s*[:.]?$', '', t, flags=re.I)        # a list that the job did not finish
    t = re.sub(r'\.\s+(\([^)]{1,80}\))\.?$', r' \1.', t)                                                                 # "competitions. (Kaggle, etc.)." -> "competitions (Kaggle, etc.)."
    if not t:
        return ''
    t = t[0].upper() + t[1:]
    words = t.split()
    if len(words) > limit:
        cut = ' '.join(words[:limit])
        k = max(cut.rfind(', '), cut.rfind('; '))
        if k > len(cut) * 0.6:
            cut = cut[:k]
        return cut.rstrip(',;:- ') + '…'
    return t if re.search(r'[.!?…]$', t) else t + '.'


def _add(items, line, seen, limit=24):
    line = _tidy(line, limit)
    if _words(line.strip('…')) < 4 or _JUNK.search(line) or _LEADIN.search(line) or ' · ' in line or _label_soup(line) or any(_similar(line, s) for s in seen):
        return False
    items.append(line)
    seen.append(line)
    return True


def _paragraphs(html):
    """[(paragraph, in a section of the job)] of a full job text: the paragraphs that are not list items (those are read from the parsed sections) and
    do not stand under a heading about the company, its benefits or legal notices ("About Mindtickle", "Who We Are", "What we offer", "Equal Opportunity
    Employer"). A heading about the team ("About the team") keeps its text: it describes the job's own team."""
    out, section, skip = [], 'pre', False
    for kind, text in lines(html):
        if kind == 'h':
            section = classify_heading(text, section)
            skip = section is None and bool(OTHER_HEAD.search(text)) and not re.search(r'\bteam\b', text, re.I)    # an unknown heading (the job title, a job code) keeps its text
        elif kind == 'p' and not skip:
            out.append((text, section in ('about', 'duties', 'req', 'nice', 'skills')))
    return out


def _texts(html, about, full_text, title):
    """The paragraphs of a full job text, or the cleaned excerpts of a snippet. A paragraph of a full text outside the job's own sections that speaks of
    the company, its benefits or culture goes as a whole; inside them ("About the role: ... 4,000 employees ...") only its junk sentences go (later)."""
    if full_text:
        return [t for t, in_job in _paragraphs(html) + [(about, True)] if t and (in_job or not _JUNK.search(t))]
    return V.about_points(plain_text(html) or about, title, max_points=50, point_limit=10 ** 6, total_limit=10 ** 7)


def _sentences(texts):
    out = [s.strip() for t in texts for s in SENT_SPLIT.split(t or '') if s.strip()]
    seen, result = set(), []
    for s in out:
        if s.lower() not in seen:
            seen.add(s.lower())
            result.append(s)
    return result


def _labels(sentences):
    """'Label: value' pairs the job states ("Experience: 7+ years · Stipend: Up to 10,000")."""
    found = {}
    for text in sentences:
        hits = list(_LABEL_ANY.finditer(text or ''))
        for n, m in enumerate(hits):
            end = hits[n + 1].start() if n + 1 < len(hits) else len(text)
            value = _VALUE_END.split(text[m.end():end].strip(' ·|'), 1)[0].strip(' .;,…·|')
            name = m.group(1).lower()
            if 1 <= _words(value) <= 10:
                found.setdefault(_ALIASES.get(name, name), value)
    return found


def _label_soup(text):
    """A line that is mostly "Label: value" pairs ("Job Title - Data Analyst Position type - Full Time Work Location - ...")."""
    return len(_LABEL_ANY.findall(text or '')) >= 2


def _years(texts):
    for t in texts:
        t = t or ''
        m = re.search(r'(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs)', t, re.I)
        if m and int(m.group(1)) < int(m.group(2)) <= 40:
            return '%s–%s years' % (m.group(1), m.group(2))
        m = re.search(r'(\d{1,2})\s*\+\s*(?:years?|yrs)|(?:minimum|min\.?|at least|over)\s+(?:of\s+)?(\d{1,2})\s*(?:years?|yrs)', t, re.I)
        if m and int(m.group(1) or m.group(2)) <= 40:
            return '%s+ years' % (m.group(1) or m.group(2))
        m = re.search(r'\b(\d{1,2})\s*(?:years?|yrs)\s+(?:of\s+)?(?:\w+\s+){0,3}(?:experience|exp)\b', t, re.I)
        if m and int(m.group(1)) <= 40:
            return '%s years' % m.group(1)
    return ''


_HEAD_POINT = re.compile(
    r"^(?:what|who|why|how|where)\b"                                                     # "What You Will Do?", "What We're Looking For."
    r"|^(?:key |your |main |core )?(?:responsibilities|duties|requirements|qualifications|skills|role|mission|impact)(?: (?:&|and) \w+)?$"
    r"|^(?:about (?:you|the role|the job|this role)|nice to have|good to have|bonus points|(?:preferred|minimum|basic|required) (?:qualifications|skills))$"
    r"|\b(?:in|for|to|with|of|include|includes|including|are|is|will|following)$", re.I)       # a list opener: "Your work will directly result in:"
_LEAD_LABEL = re.compile(r"^(.{2,70}?)(?::\s|\s[–—-]\s)")                                 # "Data pipelines: ...", "Ownership - ..."
_LEAD_SENTENCE = re.compile(r"[a-z0-9)%]\.(?=\s+[A-Z])")                                 # "You can debug across layers. You're comfortable ..."
_LEAD_BREAK = {'to', 'with', 'for', 'in', 'on', 'of', 'by', 'from', 'that', 'which', 'who', 'across', 'using', 'including', 'through', 'while', 'as',
               'at', 'into', 'about', 'within', 'via', 'when', 'where', 'because', 'but', 'like', 'such', 'under', 'over', 'between', 'without'}
_LEAD_TRAIL = {'a', 'an', 'the', 'and', 'or', 'of', 'to', 'in', 'on', 'for', 'with', 'your', 'our', 'their', 'its', 'at', 'by', 'as', 'is', 'are'}
REQ_LABEL = 'Requirements'


def is_heading_point(text):
    """True for a line of the job's own lists that is a heading, not a point ("What You Will Do?", "What We're Looking For.",
    "Your work will directly result in."). A real requirement ("Skills in SQL", "Preferred: ...") is never one."""
    t = (text or '').strip()
    words = len(t.split())
    if not t or words > 10:
        return False
    return (t.endswith('?') and words <= 10) or (words <= 8 and bool(_HEAD_POINT.search(t.rstrip('.:… '))))


def point_parts(text):
    """(lead, rest) of one key point, lead + rest == text: the opening phrase shown in bold - the label before a colon, a short first sentence,
    the first short clause, or the first words up to a preposition - and the rest in regular weight. A point of 4 words or fewer is all lead."""
    t = text or ''
    m = _LEAD_LABEL.match(t)
    if m and len(m.group(1).split()) <= 8:
        k = m.end(1) + (1 if t[m.end(1)] == ':' else 0)                  # the colon stays with the label
        return t[:k], t[k:]
    words = list(re.finditer(r'\S+', t))
    if len(words) <= 4:
        return t, ''
    m = _LEAD_SENTENCE.search(t)
    if m and 2 <= len(t[:m.end()].split()) <= 9 and len(t[m.end():].split()) >= 2:
        return t[:m.end()], t[m.end():]
    m = re.search(r'[,;(]', t)
    clause = len(t[:m.start()].split()) if m and len(t[m.start():].split()) >= 2 else 0       # "Proficiency in MS Excel, Google Sheets ..."
    first = 3 if words[0].group().lower() in ('a', 'an', 'the') else 2
    if clause < first:                                                    # "A proven, demonstrable track record" is not cut after "A proven"
        clause = 0 if first == 3 else clause
    end = None
    for i, w in enumerate(words[:8]):
        word = w.group().lower().strip('.,;:')
        if (i >= first and word in _LEAD_BREAK) or (i >= 3 and word in ('and', 'or')):
            end = i                                                       # "Build trust quickly | with engineers, architects ..."
            break
    if 1 <= clause <= 7 and (end is None or clause <= end):
        k = len(t[:m.start()].rstrip())
        return t[:k], t[k:]
    if end is None:
        end = min(5, len(words) - 2)
    while end > 2 and words[end - 1].group().lower().strip('.,;:') in _LEAD_TRAIL | {'&'}:
        end -= 1
    while end < len(words) - 2 and re.search(r"['’]s$", words[end - 1].group()):        # "strengthen MongoDB's presence"
        end += 1
    k = words[end - 1].end()
    return t[:k], t[k:]


def _segment(items, take):
    """[(heading, [points])] of one of the job's lists, up to `take` points: a heading line starts a new group, a heading with no point under it is left out."""
    groups, heading, count = [], '', 0
    for item in items:
        if count >= take:
            break
        if is_heading_point(item):
            heading = item.strip().rstrip('.: ')
            continue
        if not groups or groups[-1][0] != heading:
            groups.append((heading, []))
        groups[-1][1].append(item)
        count += 1
    return groups


def display(sm, max_points=8):
    """The summary as ONE "Job Overview" block: the overview, up to 4 responsibilities and 4 requirements as one numbered list, and one line of the
    stated facts (experience level, salary, job type, hours ...). What the job does not say is left out - no empty "Not specified" parts.
    `point_groups` = [{'heading', 'items': [{'n', 'text', 'lead', 'rest'}]}]: the job's own headings ("What You Will Do?") head their points instead of
    being numbered; when the requirements follow a headed group without a heading of their own they are headed "Requirements"."""
    duties, quals = list(sm.get('responsibilities') or []), list(sm.get('requirements') or [])
    real_d = [x for x in duties if not is_heading_point(x)]
    real_q = [x for x in quals if not is_heading_point(x)]
    half = max_points // 2
    take_d = min(len(real_d), max(half, max_points - len(real_q)))
    groups_d, groups_q = _segment(duties, take_d), _segment(quals, max_points - take_d)
    if groups_q and not groups_q[0][0] and any(h for h, _items in groups_d):
        groups_q[0] = (REQ_LABEL, groups_q[0][1])
    point_groups, n = [], 0
    for heading, items in groups_d + groups_q:
        if point_groups and not heading:                                  # no heading of its own: the same list goes on (one unbroken timeline)
            rows = point_groups[-1]['items']
        else:
            rows = []
            point_groups.append({'heading': heading, 'items': rows})
        for item in items:
            n += 1
            lead, rest = point_parts(item)
            rows.append({'n': n, 'text': item, 'lead': lead, 'rest': rest})
    points = [row['text'] for g in point_groups for row in g['items']]
    facts = []
    if sm.get('experience_level') and sm['experience_level'] != NOT_SPECIFIED:
        facts.append('Experience: %s' % sm['experience_level'])
    pay = sm.get('salary') or ''
    if pay:
        facts.append(pay if re.match(r'^(?:Stipend|CTC|Salary|Compensation):', pay) else 'Salary: %s' % pay)
    facts += list(sm.get('details') or [])
    return {'overview': sm.get('overview') or '', 'points': points, 'point_groups': point_groups, 'skills': list(sm.get('skills') or []), 'facts': ' · '.join(facts)}


def build(title, company='', location='', work_mode='', job_type='', level='', salary='', html='', full_text=False, sections=None):
    """The summary of one job as a dict: overview (str), responsibilities (list), requirements (list), experience_level (str), salary (str), details (list),
    from_text (the job text gave at least one line) and words (the length of the summary). `level`, `job_type`, `work_mode` are the labels the job already
    has; `sections` = the parsed sections of the job text (about, duties, quals, experience, preferred, skills)."""
    sec = dict(sections or {})
    if not full_text:                                                       # the items of a snippet are raw excerpts ("...Job Title: ... ...")
        for key in ('duties', 'quals', 'experience', 'preferred'):
            sec[key] = [p for item in (sec.get(key) or []) for p in V.about_points(item, title, max_points=10, point_limit=10 ** 6, total_limit=10 ** 7)]
        sec['quals'] = [q for q in sec['quals'] if _REQ.search(q)]          # the snippet parser guesses: only a real requirement stays one
    skills = [s for s in (sec.get('skills') or []) if s][:8]
    about = sec.get('about') or ''
    texts = _texts(html, about, full_text, title)
    sentences = [s for s in _sentences(texts) if not _JUNK.search(s)]
    labels = _labels(texts + list(sec.get('experience') or []) + list(sec.get('quals') or []))           # labels before sentences: "U.S. Business Hours" stays whole
    title_words = V._title_words(title)
    skill_words = sorted({w for s in skills for w in re.findall(r'[a-z][a-z+#.-]{3,}', s.lower())})
    seen = []

    # ---- overview: the one or two sentences that say best what the job is
    scored = []
    for i, s in enumerate(sentences):
        s = V._HEAD_COLON.sub('', s).strip()                              # "Job Summary: As a ..." -> "As a ..."
        if _words(s.strip('…')) < 6 or _LABEL.match(s) or ' · ' in s or _label_soup(s):
            continue
        score = (V._score(s, title_words, skill_words, company) + (2.0 if _INTRO.search(s) else 0) - (1.5 if _RESP.match(s) else 0)
                 + (1.5 if about and s in about else 0))                    # a sentence of the job's "About the role" before one about the company
        if score >= 2.0:
            scored.append((score, i, s))
    overview_parts, words = [], 0
    ranked = sorted(scored, key=lambda x: (-x[0], x[1]))[:2]
    for sc, i, s in ranked:
        s = V.short_about(s, 260)
        if overview_parts and (words + _words(s) > 60 or sc < ranked[0][0] - 1.5):
            continue
        overview_parts.append((i, s))
        words += _words(s)
    overview = ' '.join(s for _i, s in sorted(overview_parts))
    seen += [s for _i, s in overview_parts]

    # ---- key responsibilities: the job's own list first, then sentences that describe the work
    responsibilities = []
    for item in sec.get('duties') or []:
        if len(responsibilities) >= MAX_ITEMS:
            break
        _add(responsibilities, item, seen)
    for s in sentences:
        if len(responsibilities) >= MIN_ITEMS:
            break
        if (_RESP.match(s) or _RESP_INSIDE.search(s)) and not _REQ.search(s) and not _label_soup(s):
            _add(responsibilities, s, seen)

    # ---- required skills & qualifications: the job's requirements and experience lines, stated eligibility, then preferred ones (marked)
    requirements = []
    for item in list(sec.get('quals') or []) + list(sec.get('experience') or []):
        if len(requirements) >= MAX_ITEMS:
            break
        _add(requirements, item, seen)
    for name in ('eligibility', 'education', 'qualification'):
        if name in labels and len(requirements) < MAX_ITEMS:
            _add(requirements, '%s: %s' % (name.capitalize(), labels[name]), seen)
    for s in sentences:
        if len(requirements) >= MIN_ITEMS:
            break
        if _REQ.search(s) and not _label_soup(s) and ' · ' not in s:
            _add(requirements, s, seen)
    for item in sec.get('preferred') or []:
        if len(requirements) >= MIN_ITEMS:
            break
        _add(requirements, 'Preferred: ' + item[:1].lower() + item[1:], seen)

    # ---- experience level, salary and a few stated details
    years = _years([labels.get('required experience', ''), labels.get('experience', '')] + list(sec.get('experience') or []) + list(sec.get('quals') or []) + sentences)
    experience_level = ' · '.join(x for x in (level, years) if x) or NOT_SPECIFIED
    pay = (salary or '').strip()
    if not pay:
        for name, shown in (('salary', 'Salary'), ('ctc', 'CTC'), ('compensation', 'Compensation'), ('stipend', 'Stipend')):
            if name in labels:
                pay = '%s: %s' % (shown, labels[name]) if name in ('stipend', 'ctc') else labels[name]
                break
    details = ['%s: %s' % (shown, labels[name]) for name, shown in (('duration', 'Duration'), ('working hours', 'Working hours'), ('shift', 'Shift'),
                                                                      ('notice period', 'Notice period'), ('joining', 'Joining')) if name in labels]
    stated_type = labels.get('position type') or labels.get('job type') or labels.get('employment type') or ''
    if job_type or stated_type:
        details.insert(0, 'Job type: %s' % (job_type or stated_type))

    from_text = bool(overview or responsibilities or requirements)
    if not overview:
        where = ', '.join(x for x in (work_mode, location) if x)
        overview = '%s role%s%s.' % ((title or '').rstrip('.'), (' at %s' % company) if company else '', (' (%s)' % where) if where else '') if title else ''

    # ---- keep it short: at most MAX_WORDS words (the overview included)
    def total():
        return _words(overview) + sum(_words(x) for x in responsibilities + requirements) + _words(experience_level) + _words(pay) + sum(_words(x) for x in details)

    limit = 24
    while total() > MAX_WORDS:
        if len(responsibilities) > MIN_ITEMS and len(responsibilities) >= len(requirements):
            responsibilities.pop()
        elif len(requirements) > MIN_ITEMS:
            requirements.pop()
        elif limit > 14:
            limit -= 2
            responsibilities = [_tidy(x.rstrip('…'), limit) for x in responsibilities]
            requirements = [_tidy(x.rstrip('…'), limit) for x in requirements]
        else:
            break
    return {'overview': overview, 'responsibilities': responsibilities, 'requirements': requirements, 'skills': skills, 'experience_level': experience_level,
            'salary': pay, 'details': details, 'from_text': from_text, 'words': total()}
