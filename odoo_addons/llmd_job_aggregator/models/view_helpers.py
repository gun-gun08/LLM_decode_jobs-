"""Small helpers for the job detail page (pure Python, no Odoo imports): short text, the "About the Role" points, 'posted ... ago'."""
import re
from datetime import datetime, timezone

try:
    from .parsers import SENT_SPLIT
except ImportError:                                  # imported on its own (tests)
    from parsers import SENT_SPLIT


def short_about(text, limit=320):
    """The first sentences of `text` that fit in `limit` characters (never cut in the middle of a word)."""
    text = re.sub(r'\s+', ' ', text or '').strip()
    if len(text) <= limit:
        return text
    out = ''
    for sentence in SENT_SPLIT.split(text):
        candidate = (out + ' ' + sentence).strip()
        if len(candidate) > limit:
            break
        out = candidate
    if out:
        return out
    return text[:limit].rsplit(' ', 1)[0].rstrip(',;:-') + '…'


def ago(dt, now=None):
    """'Posted 3 days ago' for a naive UTC datetime ('' when unknown)."""
    if not dt:
        return ''
    seconds = ((now or datetime.now(timezone.utc).replace(tzinfo=None)) - dt).total_seconds()
    if seconds < 0:
        return 'Just posted'
    days = int(seconds // 86400)
    if days <= 0:
        return 'Posted today'
    if days == 1:
        return 'Posted yesterday'
    if days < 14:
        return 'Posted %d days ago' % days
    if days < 60:
        return 'Posted %d weeks ago' % (days // 7)
    return 'Posted %d months ago' % (days // 30)


# ---------------------------------------------------------------------------------------------- "About the Role" from a snippet made of excerpts
_ELLIPSIS = re.compile(r'\s*(?:\.{3,}|…)+\s*')
_HEADS = (r'about (?:the|this|our) (?:role|job|position|company|team|opportunity)|about us|job (?:overview|description|summary)|'
          r'role (?:overview|description|summary)|position (?:overview|summary)|the role|overview|summary|(?:required|key) skills|skills required|(?:key )?responsibilities|qualifications|requirements')
_HEAD_COLON = re.compile(r'^(?:%s)\s*(?::-|:|-|–|—)\s*' % _HEADS, re.I)
_HEAD_SPACE = re.compile(r'^(?:%s)\s+(?=[A-Z])' % _HEADS, re.I)
_HEAD_CAPS = re.compile(r"^(?:ABOUT|ROLE|OVERVIEW|THE ROLE)(?: [A-Z&'.]+)*\s*:?\s+(?=[A-Z][a-z])")
_HEAD_INSIDE = re.compile(r"\s+(?:About (?:the|this|our) (?:[Rr]ole|[Jj]ob|[Cc]ompany|[Tt]eam|[Pp]osition|[Oo]pportunity)|About Us|ABOUT(?: [A-Z&'.]+)+|Job (?:Overview|Description|Summary))"
                          r"(?:\s*(?::-|:)\s*|\s+(?=[A-Z]))")
_LABELS = re.compile(r'(?<=[^\s.:;,·|(])(?<!Required)(?<!Job)(?<!Engagement)(?<!Internship)(?<!Contract)(?<!Project)(?<!Program)(?<!Role)(?<!Position)(?<!Working)\s+(?=(?:Required Experience|Experience|Duration|Stipend|Job Type|Position Type|Type|Location|Salary|CTC|Work Mode|Working Hours|Shift|Openings|Eligibility|Education|Department|Joining|Job Title|Position|Notice Period|Qualification)\s*:)')
_APPLY_HERE = re.compile(r'\b(?:interested\s*[?!.]?\s*)?(?:apply here|click here(?: to apply)?|apply now)\b\s*[:.!]?\s*', re.I)
_JUNK = re.compile(r'^(?:read more|click here|apply now|apply here|learn more|visit our)\b', re.I)
_LEAD_PARTIAL = re.compile(r'^[a-z][^.!?]{0,90}[.!?]\s+(?=[A-Z])')
_SENT_END = re.compile(r'[.!?]["”’)]?(?=\s|$)')


def _clean_excerpt(piece, title=''):
    """One excerpt of a snippet -> readable text ('' when nothing useful is left)."""
    p = re.sub(r'\s+', ' ', piece or '').strip()
    p = re.sub(r'^[\s,;:.\-–—•·|]+', '', p)
    p = re.sub(r'([a-z0-9)\]])([.!?])([A-Z][a-z])', r'\1\2 \3', p)          # "hyperscalers.We are" -> "hyperscalers. We are"
    p = re.sub(r'(\w)- (?=\w)', r'\1-', p)                                  # "AI- powered" -> "AI-powered"
    p = re.sub(r'\s+([,;:.!?])(?=\s|$)', r'\1', p)                         # "Cloud , in" -> "Cloud, in"; "Management ." -> "Management."
    p = re.sub(r'\(\s+', '(', re.sub(r'\s+\)', ')', re.sub(r'(?<=\S)/\s+', '/', re.sub(r'\s*~\s*', ' ', p))))    # "( Remote/ Hybrid)" -> "(Remote/Hybrid)"
    p = re.sub(r'([a-z])(We|You|Our|This|As) (?=[a-z])', r'\1. \2 ', p)       # "TransformationWe are" -> "Transformation. We are"
    p = re.sub(r'^[A-Z][\w+#.-]*(?: [\w+#.-]+)?[.!?]\s+(?=\S+(?:\s+\S+){4})', '', p)   # a one- or two-word scrap first: "Python. Experience with ..."
    p = re.sub(r"(?<=[a-z]) (?=(?:This is|We are|We're|You will|You'll|Join us|Are you|Do you)\b)", '. ', p)
    m = _LEAD_PARTIAL.match(p)
    if m and (len(m.group(0).split()) <= 6 or len(p[m.end():].split()) >= 8):   # "it. TELUS Digital is ..." -> "TELUS Digital is ..."
        p = p[m.end():]
    starts_sentence = False
    for _round in range(2):                                                 # headings the section title already says
        new = _HEAD_CAPS.sub('', _HEAD_SPACE.sub('', _HEAD_COLON.sub('', p)))
        starts_sentence = starts_sentence or new != p
        p = new
    p = _HEAD_INSIDE.sub(lambda mm: ' ' if re.search(r'[.!?]$', p[:mm.start()]) else '. ', p)
    norm = lambda x: re.sub(r'\s*[-–—]\s*', ' - ', x.lower())
    if title and norm(p).startswith(norm(title)):
        cut = len(title)
        while cut < len(p) and norm(p[:cut]) != norm(title):
            cut += 1
        p = re.sub(r'^[\s,;:|\-–—]+', '', p[cut:])
        p = re.sub(r'^(?:at|in|with|for)\s[^.!?]{0,40}?[.!?]?\s(?=(?:Are|Do|We|You|This|Our|Join|As)\b)', '', p)
        starts_sentence = True
    p = _LABELS.sub(' · ', p)
    p = _APPLY_HERE.sub(' ', p).replace('  ', ' ')
    p = re.sub(r'\s+(?:About Us|About the (?:Company|Role|Job|Team))\W*$', '', p)
    p = p.strip().rstrip(',;:-–—|•· ')
    if not p or _JUNK.match(p):
        return ''
    ends = list(_SENT_END.finditer(p))
    if ends and ends[-1].end() < len(p):                                    # the excerpt was cut in the middle of a sentence
        tail = p[ends[-1].end():].strip()
        p = p[:ends[-1].end()] if len(tail.split()) < 8 else p.rstrip(',;:-') + '…'
    elif not ends:
        p = p.rstrip(',;:- ') + '…'
    if not starts_sentence and re.match(r'^\(?[a-z]', p):                  # it starts in the middle of a sentence
        q = re.sub(r'^\([^)]{0,80}\)\s*', '', p)                          # a cut-off aside: "(such as Snowflake agents) to surface ..."
        q = re.sub(r'^(?:and|or|but|also|plus)\s+', '', q)                 # "and build dashboards" -> "Build dashboards"
        if q != p or re.match(r'^to\s', q):                                # now it reads as a point of its own
            p = q[:1].upper() + q[1:]
        else:
            p = '…' + p
    return p


def about_points(text, title='', max_points=4, point_limit=240, total_limit=650):
    """The "About the Role" text as a short list of readable points.

    A job board snippet is made of excerpts of the job text joined with "..." ("...(such as Snowflake agents) to surface... Partner... ...a challenge"): every excerpt
    becomes one point, cleaned (spacing, glued sentences, headings like "About the role", the job title repeated, scraps of a few words, "Read more"). A normal text stays one
    point (at most 320 characters, cut after a whole sentence)."""
    pieces = []
    for part in _ELLIPSIS.split(re.sub(r'\s+', ' ', text or '')):
        pieces += [x for x in re.split(r'\s*[•·]\s+', part) if x.strip()]
    limit = 320 if len(pieces) == 1 else point_limit
    points, seen, total = [], set(), 0
    for piece in pieces:
        p = _clean_excerpt(piece, title)
        words = len(p.strip('…').split())
        if words < 5 or p.lower() in seen:
            continue
        if p.startswith('…') and words < 12 and len(pieces) > 1:            # a short scrap that starts mid-sentence adds nothing
            continue
        p = short_about(p, limit)
        if points and total + len(p) > total_limit:
            break
        seen.add(p.lower())
        points.append(p)
        total += len(p)
        if len(points) >= max_points:
            break
    return points


# ---------------------------------------------------------------------------------------------- the 3 "About the Role" points: about the JOB, true
_ROLE_WORDS = re.compile(r"\b(?:you will|you'll|your role|in this role|responsib\w*|we are looking|we're looking|looking for|we are hiring|is hiring|hiring|seeking|"
                         r"analy[sz]\w*|build\w*|develop\w*|design\w*|manag\w*|lead\w*|own\w*|work(?:ing)? (?:with|closely|on)|collaborat\w*|support\w*|creat\w*|"
                         r"deliver\w*|implement\w*|automat\w*|experience|years?|skills?|proficien\w*|knowledge|degree|required|requirements?|must|intern\w*|stipend|"
                         r"duration|hybrid|remote|on-?site|office|location|stakeholders?|reports?|reporting|dashboards?|insights?|data|models?|customers?|clients?|"
                         r"products?|roadmap|strategy|campaigns?|sales|pipeline|code|engineer\w*)\b", re.I)
_BOILER = re.compile(r"\b(?:founded|mission|headquarter\w*|our company|we are an? (?:leading|global|fast|world)|is an? (?:[\w,-]+ ){0,4}(?:company|platform|organi[sz]ation|"
                     r"operating system|startup|provider|leader|brand|group|firm)|global leader|operates as|operating model|in (?:19|20)\d\d|blog|visit\w*|read more|"
                     r"culture|equal opportunit\w*|divers\w*|inclusi\w*|awards?|fortune|worldwide|countries|employees|combined company|acquisition|acquired|"
                     r"investors?|funded|series [a-d]|backed by|trusted by|offices? (?:in|across)|will vary|depending on|plenty|personas|categories)\b", re.I)
_ROLE_NOUN = re.compile(r'\b(?:manager|engineer|analyst|developer|intern\w*|scientist|designer|executive|specialist|consultant|associate|architect|lead|head|officer|director|administrator|coordinator|marketer|writer|strategist|programmer|researcher|trainee|fresher|representative|owner)\b', re.I)
_ROLE_INTRO = re.compile(r"\b(?:(?:we are|we're|is|are|currently) (?:seeking|looking for|hiring)|you will|you'll|in this role|the role is|your responsibilit\w*)\b", re.I)
_SENIORITY = {'senior', 'junior', 'principal', 'lead', 'head', 'sr', 'jr', 'mid', 'level', 'associate', 'staff', 'chief', 'the', 'and', 'for', 'with', 'of', 'to', 'in', 'at'}


def _score(sentence, title_words, skill_words, company=''):
    s = sentence.lower()
    score = 2.0 * sum(1 for w in title_words if re.search(r'\b%s' % re.escape(w), s))
    score += 1.5 * sum(1 for w in skill_words if w in s)
    score += min(len(_ROLE_WORDS.findall(sentence)), 4) + (2.0 if _ROLE_INTRO.search(sentence) else 0)
    score -= 2.5 * len(_BOILER.findall(sentence))
    score -= 1.0 if sentence.startswith('…') else 0
    score -= 0.5 if sentence.endswith('…') else 0
    first = re.findall(r'[a-z]{4,}', (company or '').lower())[:1]
    score -= 1.5 if first and s.lstrip('…').startswith(first[0][:5]) else 0
    return score


def job_facts(title, company='', location='', work_mode='', job_type='', level='', salary='', skills=()):
    """True points made only from what is stored for the job (used when its text gives fewer than 3 points about the role)."""
    facts = []
    where = ', '.join(x for x in (work_mode, location) if x)
    clean = re.sub(r'\s*\((?:remote|hybrid|on-?site|wfh|work from home)[^)]*\)', '', title or '', flags=re.I)           # "(Remote)" is said after the company
    clean = re.sub(r'\s*(?:/|-|–|\|)\s*(?:remote|hybrid|on-?site|wfh)\b.*$', '', clean, flags=re.I)                     # "Data Analyst /REMOTE IN INDIA"
    clean = re.sub(r'\s*[-–|]\s*\(?\s*$', '', clean).strip() or (title or '')
    if clean:
        facts.append('%s role%s%s.' % (clean.rstrip('.'), (' at %s' % company) if company else '', (' (%s)' % where) if where else ''))
    skills = [s for s in skills if s][:4]
    if skills:
        facts.append('Skills asked for: %s.' % (skills[0] if len(skills) == 1 else '%s and %s' % (', '.join(skills[:-1]), skills[-1])))
    kind = ' · '.join(x for x in (('Job type: %s' % job_type) if job_type else '', ('Level: %s' % level) if level and level != job_type else '',
                                   ('Salary: %s' % salary.rstrip('. ')) if salary else '') if x)
    if kind:
        facts.append(kind + '.')
    return facts


def _title_words(title):
    """The words of the ROLE part of a job title ("TELUS Digital - Group Product Manager - AI" -> group, product, manager), without seniority words."""
    parts = [x for x in re.split(r'\s+[-|–—:]\s+|\s*\|\s*', title or '') if x.strip()]
    role_parts = [x for x in parts if _ROLE_NOUN.search(x)] or parts
    return [w for w in re.findall(r"[a-z][a-z+#.-]{2,}", ' '.join(role_parts).lower()) if w not in _SENIORITY]


def role_points(text, title='', skills=(), facts=(), n=3, extra=(), company=''):
    """Exactly `n` points (when there is enough to say) about the ROLE: the sentences of the job text that are most about the job itself - its title, its skills, the work,
    the requirements - in their original order; company history, mission, culture, "read more" and scraps score low and are left out. When the text gives fewer than `n`
    such sentences, true facts of the job (`facts`, see job_facts()) fill the list. `extra` = more sentences of the same job text (its requirements).
    Nothing is made up: every point is a sentence of the job text or a stored fact."""
    title_words = _title_words(title)
    skill_words = sorted({w for s in skills for w in re.findall(r'[a-z][a-z+#.-]{3,}', s.lower())})
    candidates, seen = [], set()
    excerpts = about_points(text, title, max_points=50, point_limit=10 ** 6, total_limit=10 ** 7)
    excerpts += [x for e in extra for x in about_points(e if re.search(r'[.!?…]$', e or '') else (e or '') + '.', title, point_limit=10 ** 6)]
    for excerpt in excerpts:
        for sentence in SENT_SPLIT.split(excerpt):
            sentence = sentence.strip()
            if len(sentence.strip('…').split()) < 5 or sentence.lower() in seen:
                continue
            seen.add(sentence.lower())
            candidates.append((len(candidates), sentence))
    scored = [(_score(s, title_words, skill_words, company), i, s) for i, s in candidates]
    best = sorted([x for x in scored if x[0] >= 3.0], key=lambda x: (-x[0], x[1]))[:n]
    fill = [f for f in dict.fromkeys(facts) if f][:max(0, n - len(best))]
    if len(best) + len(fill) < n:
        weaker = [x for x in scored if 1.0 <= x[0] < 3.0 and not _BOILER.search(x[2])]
        best += sorted(weaker, key=lambda x: (-x[0], x[1]))[:n - len(best) - len(fill)]
    return [short_about(s, 230) for _sc, _i, s in sorted(best, key=lambda x: x[1])] + fill
