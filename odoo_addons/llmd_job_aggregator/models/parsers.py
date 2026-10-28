"""Turns the text of a real job listing into the sections of the job page:
About the Role, Key Responsibilities, Required Skills, Qualifications, Experience (and Preferred, when the listing has it).

Nothing is invented: every line shown is a sentence / bullet of the listing, only sorted under the right heading.
Lines that name the employer or its products, salary / benefits, links, e-mail addresses or company-culture talk are dropped.
Pure Python (no Odoo imports) so it can be tested on its own.
"""
import difflib
import html as htmllib
import re
from html.parser import HTMLParser

try:
    from .vocab import COMMON_CAPS, SKILLS, TECH_OK
except ImportError:                                  # imported on its own (tests)
    from vocab import COMMON_CAPS, SKILLS, TECH_OK

_SKILL_RX = [(name, re.compile(rx, re.I)) for name, rx in SKILLS]

BULLET_RE = re.compile(r'^\s*(?:[•·○●◦■▪▫►▶‣⁃→✓✔➡➢➤❖✦*]|[-–—](?=\s)|\d{1,2}[.)](?=\s))\s*')
GLYPH_RE = re.compile('[•·○●◦■▪▫►▶‣⁃→✓✔➡➢➤❖✦]|[🀀-🿿]|[☀-➿]|[️‍]')
META_RE = re.compile(r'^(role|title|company|location|contact|project duration|duration|department|employment|position|job type|work mode|shift|salary|ctc|notice|'
                     r'job id|req(uisition)? ?(id|no)|posted|apply|email|e-mail|phone|website|address|openings?|vacanc\w+|hours|schedule)\s*[:\-]', re.I)
EXP_META_RE = re.compile(r'^experience\s*[:\-]\s*(.+)$', re.I)

OTHER_HEAD = re.compile(r'benefit|perk|compensation|salary|what we offer|offer you|we offer|about (us|the company|our)|who we are|why (join|work|this|you)|our (culture|values|mission|story|team|company|product)|'
                        r'equal|diversity|how to apply|hiring process|interview|company (description|overview|profile)|working at|life at|join (us|our|the team)|growth|what.?s in it|'
                        r'success in this role|measured by|the team|meet the|our story|more about|disclaimer|legal|privacy|accommodation|'
                        r'culture|company summary|what makes \w+ (special|unique|different)|^about (?!(the |this )?(role|job|position|opportunity)\b|you\b)|'
                        r'^(the )?(values|vision)\b|values that|rewards|wellness|insurance|fraud|applicants|inclusion|veterans|at a glance|how we work', re.I)
# headings of the qualifications that would otherwise be read as responsibilities ("What you will need", "You might thrive in this role if you")
REQ_FIRST_HEAD = re.compile(r'what (you.?ll|you will|you) (need|bring|have)|what we (look|are looking|.?re looking) for|we look for|thrive|seeking someone|typically have|'
                            r'expect to demonstrate|position expectations?|you.?ll (need|bring)|makes you a (match|fit)|you.?re a (match|fit)|good fit', re.I)
NICE_HEAD = re.compile(r'nice[- ]to[- ]have|preferred|bonus|good to have|a plus|desirable|extra points|would be (a )?plus|\bplus\b|advantage', re.I)
DUTY_HEAD = re.compile(r'responsibilit|what you.?ll (be )?(do|doing|own|work)|what you will (do|work|own)|duties|day[- ]to[- ]day|key (tasks|activities)|how you.?ll contribute|'
                       r'in this role|you will|the work|what the job|what you.?ll be|your impact|deliverables|scope of work|job (description|duties)|accountabilit|'
                       r'what will you (do|own|work|drive)|you.?ll (do|own|drive|build|work on)|your mission', re.I)
REQ_HEAD = re.compile(r'requirement|qualification|what you.?ll need|what you need|what you bring|what we.?re looking for|looking for in|who you are|about you|must[- ]have|minimum|'
                      r'you have|your (profile|background|experience)|essential|education|eligibility|candidate|ideal|you should|competenc|expect from you', re.I)
SKILL_HEAD = re.compile(r'\bskills?\b|technical|tech stack|technologies|tools', re.I)
ABOUT_HEAD = re.compile(r'about (the |this )?(role|job|position|opportunity)|job summary|role (summary|overview|description)|position (summary|overview)|summary|overview|the role|your role|'
                        r'the opportunity|job overview|description|^(the )?role$', re.I)

COMPANY_DESC_RE = re.compile(r'\b(is|are|was|has|have|provides?|offers?|builds?|helps?)\b.{0,40}\b(a|an|the|leading|global|company|platform|provider|leader|startup|organization|firm)\b', re.I)
BAD_RE = re.compile(r'https?://|www\.|@|[$€£₹]|\bsalary\b|compensation|\bbenefits?\b|\bequity\b|\bvisa\b|sponsorship|resum[eé]|\bcv\b|apply (now|today|here|online)|'
                    r'time ?zone|\bpay\b|per (hour|month|year)|equal opportunity|background check|work permit|right to work|relocat|we offer|we provide|join (our|us|the)|'
                    r'\b(our|we|us)\b|annual leave|paid (time|leave)|\bpto\b|401k|insurance|holiday|stock options|bonus pool|referral|confidential|eeo|equal employment|e-verify|disabilit|veteran|himalayas|originally posted|powered by|click here|posted on|read more|show more|see more', re.I)
CULTURE_RE = re.compile(r'fast-paced|innovation-driven|team culture|work-life|diverse|inclusive|passionate about|competitive|world.?s (most|leading|best)|\bunicorn\b|series [a-f]\b|'
                        r'\bjoin\b.{0,20}\bteam\b|growing company|great place|rocket|ninja|rockstar', re.I)
EXP_RE = re.compile(r'\b\d+\s*[+–\-]?\s*(?:\d+\s*)?(?:years?|yrs?)\b|\byears? of\b|\bfresher|\bentry[- ]level|\bno experience', re.I)
SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9“"(])')
LONG_WORD_OK = {'troubleshooting', 'responsibilities', 'representatives', 'recommendations', 'communications', 'collaboratively', 'telecommunications', 'interdisciplinary',
                'professionally', 'organizational', 'infrastructures', 'implementations', 'configurations', 'documentations', 'infrastructure-as-code'}


class _Lines(HTMLParser):
    BLOCK = {'p', 'div', 'section', 'article', 'tr', 'ul', 'ol', 'table', 'blockquote', 'br', 'hr'}
    HEAD = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self._segs, self._kind, self._bold, self._skip, self._li = [], [], 'p', 0, 0, 0

    def _flush(self):
        text = re.sub(r'\s+', ' ', ''.join(t for t, _ in self._segs)).strip()
        if text:
            self.out.append((self._kind if self._kind == 'h' else ('li' if self._li else self._kind), text, all(b for t, b in self._segs if t.strip())))
        self._segs, self._kind = [], 'p'

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self._skip += 1
        elif tag in self.HEAD:
            self._flush()
            self._kind = 'h'
        elif tag == 'li':
            self._flush()
            self._li += 1
        elif tag in self.BLOCK:
            self._flush()
        elif tag in ('strong', 'b'):
            self._bold += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self._skip = max(0, self._skip - 1)
        elif tag in self.HEAD or tag in self.BLOCK:
            self._flush()
        elif tag == 'li':
            self._flush()
            self._li = max(0, self._li - 1)
        elif tag in ('strong', 'b'):
            self._bold = max(0, self._bold - 1)

    def handle_data(self, data):
        if not self._skip:
            self._segs.append((data, self._bold > 0))

    def close(self):
        super().close()
        self._flush()


def lines(markup):
    """[(kind, text)] with kind h (heading), li (bullet) or p (paragraph) - from HTML, escaped HTML or plain text with bullet glyphs."""
    markup = markup or ''
    if re.search(r'&lt;(p|div|ul|li|h[1-6]|br)\b', markup, re.I):
        markup = htmllib.unescape(markup)
    if not re.search(r'<[a-z][^>]*>', markup, re.I):
        markup = markup.replace('\n', '<br>')
    parser = _Lines()
    parser.feed(markup)
    parser.close()
    out = []
    for kind, text, bold in parser.out:
        text = GLYPH_RE.sub(' ', text) if kind != 'h' else GLYPH_RE.sub('', text)
        m = BULLET_RE.match(text)
        if m and kind == 'p':
            kind, text = 'li', text[m.end():]
        elif m:
            text = text[m.end():]
        text = re.sub(r'\s+', ' ', text).strip()
        if not text:
            continue
        if kind == 'p' and len(text) <= 80 and (text.endswith(':') or (bold and not re.search(r'[.!?]$', text))):
            kind = 'h'
        if kind == 'h':
            text = text.rstrip(':').strip()
        out.append((kind, text))
    return out


def classify_heading(text, current):
    if OTHER_HEAD.search(text) and not (DUTY_HEAD.search(text) or REQ_HEAD.search(text) or REQ_FIRST_HEAD.search(text) or NICE_HEAD.search(text)):
        return None
    if NICE_HEAD.search(text):
        return 'nice'
    if REQ_FIRST_HEAD.search(text):
        return 'req'
    if DUTY_HEAD.search(text):
        return 'duties'
    if REQ_HEAD.search(text):
        return 'req'
    if SKILL_HEAD.search(text):
        return 'skills'
    if ABOUT_HEAD.search(text):
        return 'about'
    if len(text) <= 40 and current in ('duties', 'req', 'nice', 'skills'):      # a sub-heading inside the section ("Backend", "Tools")
        return current
    return None


def split_sections(ls):
    out = {k: [] for k in ('pre', 'about', 'duties', 'req', 'nice', 'skills')}
    exp_meta, section = [], 'pre'
    for kind, text in ls:
        if kind == 'h':
            section = classify_heading(text, section)
            continue
        m = EXP_META_RE.match(text)
        if m:
            exp_meta.append(m.group(1).strip().rstrip('.'))
            continue
        if META_RE.match(text):
            continue
        if section in out:
            out[section].append((kind, text))
    return out, exp_meta


# ---------------------------------------------------------------------------------------------------------- employer-specific filters
def _company_core(company):
    return re.sub(r'\b(inc|llc|ltd|gmbh|corp|corporation|co|limited|plc|labs|group|technologies|holdings|pvt|private|solutions|services|consulting)\b\.?', ' ', (company or '').lower()).strip(' ,.-')


def _name_words(ls):
    caps, lower = {}, set()
    for _, text in ls:
        for sent in SENT_SPLIT.split(text):
            for i, tok in enumerate(re.findall(r'[A-Za-z][A-Za-z0-9]*', sent)):
                low = tok.lower()
                if tok[0].islower():
                    lower.add(low)
                elif i > 0 and len(tok) >= 4:
                    caps[low] = caps.get(low, 0) + 1
    return {w for w, n in caps.items() if n >= 2 and w not in lower and w not in TECH_OK and w not in COMMON_CAPS}


def _foreign_name(text):
    for tok in re.findall(r'\b[A-Za-z][A-Za-z0-9]*\b', text):
        if tok.lower() in TECH_OK:
            continue
        if re.search(r'[a-z][A-Z]', tok) or (tok.isupper() and len(tok) >= 5) or re.match(r'^[A-Z]{2,}[a-z]', tok):
            return True
    return False


class Filter:
    def __init__(self, ls, company, title, strict=True):
        self.strict = strict
        self.core = _company_core(company)
        title_words = set(re.findall(r'[a-z0-9]+', (title or '').lower()))
        self.names = _name_words(ls) - title_words
        self.prefixes = [t[:5] for t in re.findall(r'[a-z]{5,}', self.core)]

    def named(self, text):
        low = text.lower()
        if len(self.core) >= 3 and self.core in low:
            return True
        words = re.findall(r'[a-z][a-z0-9]+', low)
        return any(w in self.names for w in words) or any(w.startswith(p) for w in words for p in self.prefixes)

    def ok(self, text, lo=18, hi=190):
        if not self.strict:                      # job board: the listing is shown as the employer wrote it, only junk is dropped
            return (lo <= len(text) <= max(hi, 320) and text.count('(') == text.count(')') and len(text.split()) >= 3
                    and not re.search(r'https?://|www\.|@|himalayas|originally posted|click here|apply (now|today|here|online)|read more|show more', text, re.I))
        if not lo <= len(text) <= hi or text.count('(') != text.count(')') or BAD_RE.search(text) or CULTURE_RE.search(text) or _foreign_name(text) or self.named(text):
            return False
        if re.search(r'\.\s+[a-z]|\?\s*$|^(do|are|would|have|can|will) you\b', text) or len(text.split()) < 3 or text.count(',') >= 6:
            return False
        return not any(len(w) >= 15 and w not in LONG_WORD_OK for w in re.findall(r'\b[a-z]+\b', text))


def _clean_item(text):
    text = re.sub(r'^[A-Za-z][A-Za-z &/]{1,30}:\s*(?=[A-Z])', '', text)          # "Backend: Build APIs" -> "Build APIs"
    text = re.sub(r'\s+', ' ', text).strip().rstrip('.;,: ')
    return text[:1].upper() + text[1:] if text else text


def _units(items):
    """Bullets stay as they are; paragraphs are split into sentences."""
    for kind, text in items:
        if kind == 'li':
            yield _clean_item(text)
        else:
            for sent in SENT_SPLIT.split(text):
                yield _clean_item(sent)


def _dedupe(seq, limit):
    out, seen = [], set()
    for x in seq:
        key = re.sub(r'\W+', '', x.lower())
        if key and key not in seen:
            seen.add(key)
            out.append(x)
        if len(out) >= limit:
            break
    return out


def skills_of(text, limit=12):
    found = []
    for i, (name, rx) in enumerate(_SKILL_RX):
        n = len(rx.findall(text))
        if n:
            found.append((-n, i, name))
    return [n for _, _, n in sorted(found)[:limit]]


def parse_listing(markup, company='', title='', strict=True):
    """-> dict(about, duties, skills, quals, experience, preferred); empty parts stay empty (shown only when the listing has them)."""
    ls = lines(markup)
    sec, exp_meta = split_sections(ls)
    flt = Filter(ls, company, title, strict)

    def good(items, lo=18, hi=190):
        return [x for x in _units(items) if flt.ok(x, lo, hi)]

    # About the role: sentences of the summary section, or the opening paragraphs before the first heading
    about_src = [(k, t) for k, t in sec['about'] if k == 'p'] or [(k, t) for k, t in sec['pre'] if k == 'p']
    sentences = [s for s in good(about_src, 30, 330) if not (strict and COMPANY_DESC_RE.search(s) and not re.search(r'\byou(r)?\b', s, re.I))]
    sentences = [s for s in sentences if not re.match(r'(that|this|it|these|those|however|but|and|also|so|then|if you)\b', s, re.I)]
    about, total = [], 0
    for s in _dedupe(sentences, 8):
        if total + len(s) > (640 if strict else 1100):
            break
        about.append(s + '.')
        total += len(s) + 2
    duties = _dedupe(good(sec['duties']), 8 if strict else 14)
    req_all = _dedupe(good(sec['req']) + good([(k, t) for k, t in sec['skills'] if len(t) > 36]), 14 if strict else 20)
    experience = [x for x in req_all if EXP_RE.search(x)]
    quals = [x for x in req_all if x not in experience]
    experience = _dedupe(exp_meta + experience, 4)
    preferred = _dedupe(good(sec['nice']), 5)
    explicit = [t for k, t in sec['skills'] if len(t) <= 36 and not BAD_RE.search(t) and not (strict and flt.named(t))] if strict else [t for k, t in sec['skills'] if len(t) <= 36 and not re.search(r'https?://|@|himalayas|originally posted|click here|apply|posted on|read more', t, re.I)]
    text_for_skills = ' '.join(t for _, t in ls if (not BAD_RE.search(t) if strict else not re.search(r'https?://|@', t)))
    skills = _dedupe([_clean_item(x) for x in explicit] + skills_of(text_for_skills), 12)
    cap = 8 if strict else 14
    return {'about': ' '.join(about), 'duties': duties[:cap], 'skills': skills, 'quals': quals[:cap], 'experience': experience, 'preferred': preferred}


def richness(p):
    return ((2 if len(p.get('about', '')) >= 100 else 0) + min(len(p.get('duties', [])), 6) / 2.0 + min(len(p.get('quals', [])), 6) / 2.0
            + (1 if p.get('experience') else 0) + (1 if len(p.get('skills', [])) >= 3 else 0))


def usable(p):
    """A listing can fill the page when it gives at least three responsibilities or three qualifications."""
    return len(p.get('duties', [])) >= 3 or len(p.get('quals', [])) >= 3


# ---------------------------------------------------------------------------------------------------------- titles
SENIORITY_RE = re.compile(r'\b(senior|sr|junior|jr|lead|principal|staff|intern|trainee|associate|remote|hybrid|contract|freelance|ii|iii)\b', re.I)
TITLE_WORDS = ('engineer developer manager analyst designer scientist architect consultant specialist executive representative administrator coordinator assistant '
               'ai ml data stack mern full backend frontend front back end python java javascript typescript node react angular vue web mobile android ios flutter '
               'sales marketing digital product project program business customer success support service content writer editor copy recruiter talent accountant finance '
               'devops cloud security network system database qa quality test tester sre software hr human resources operations legal ui ux graphic video seo social media '
               'machine learning artificial intelligence generative llm nlp cyber analytics intelligence researcher technician officer director head agent associate').split()


def fix_title(title):
    """Search form of a title: camelCase split and obvious typos corrected ('AiEngenner' -> 'ai engineer'), only to the vocabulary above."""
    t = re.sub(r'([a-z])([A-Z])', r'\1 \2', title or '')
    t = re.sub(r'[^A-Za-z0-9+# ]+', ' ', t).lower()
    out = []
    for w in t.split():
        if w in TITLE_WORDS or len(w) <= 3:
            out.append(w)
            continue
        close = difflib.get_close_matches(w, TITLE_WORDS, 1, 0.72 if len(w) >= 7 else 0.8)
        if close:
            out.append(close[0])
            continue
        for i in range(2, len(w) - 2):                                  # 'aiengenner' -> 'ai' + 'engineer'
            a, b = w[:i], w[i:]
            ca = a if a in TITLE_WORDS else (difflib.get_close_matches(a, TITLE_WORDS, 1, 0.9) or [None])[0]
            cb = b if b in TITLE_WORDS else (difflib.get_close_matches(b, TITLE_WORDS, 1, 0.8) or [None])[0]
            if ca and cb and len(a) >= 2:
                out += [ca, cb]
                break
        else:
            out.append(w)
    return ' '.join(out)


def norm_title(title):
    t = re.sub(r'[^a-z0-9+# ]+', ' ', fix_title(title))
    return ' '.join(w for w in SENIORITY_RE.sub(' ', t).split())


def title_score(wanted, listing):
    a, b = norm_title(wanted), norm_title(re.sub(r'<[^>]+>', ' ', listing or ''))
    if not a or not b:
        return 0.0
    if len(a.split()) == 1:                                                 # a one-word title ("Test") is too vague: only a listing with exactly that title counts
        plain = re.sub(r'[^a-z0-9+# ]+', ' ', re.sub(r'<[^>]+>', ' ', (listing or '').lower())).split()
        return 1.0 if plain == [a] else min(difflib.SequenceMatcher(None, a, b).ratio(), 0.5)
    junior_only = bool(re.search(r'intern|trainee', listing or '', re.I)) and not re.search(r'intern|trainee', wanted or '', re.I)
    if a == b:
        return 0.0 if junior_only else 1.0
    score = difflib.SequenceMatcher(None, a, b).ratio()
    aw, bw = a.split(), b.split()
    if all(w in bw for w in aw):
        score = max(score, 0.9 - 0.05 * min(len(bw) - len(aw), 6))
    return 0.0 if junior_only else score                                     # an internship is not the job unless the job itself says intern


def plain_text(markup):
    """Plain text of stored HTML: tags removed, entities decoded once (the stored HTML escapes an apostrophe as &#x27;), spaces collapsed."""
    return re.sub(r'\s+', ' ', htmllib.unescape(re.sub(r'<[^>]+>', ' ', str(markup or '')))).strip()


# ---------------------------------------------------------------------------------------------------------- snippet-only APIs (Adzuna, Jooble)
def clean_snippet(text):
    t = htmllib.unescape(re.sub(r'<[^>]+>', ' ', text or ''))
    t = re.sub(r'\s+', ' ', t).strip()
    trimmed = re.sub(r'(\.\.\.|…)\s*$', '', t).strip()
    if trimmed != t or not re.search(r'[.!?]["”’)]?$', t):
        ends = list(re.finditer(r'[.!?]["”’)]?(?=\s|$)', trimmed))
        if ends and ends[-1].end() >= 60:
            trimmed = trimmed[:ends[-1].end()]
        t = trimmed.strip()
    return t


def parse_snippet(text, company='', title='', strict=True):
    flt = Filter([('p', text)], company, title, strict)
    sents = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    req = [s for s in sents if EXP_RE.search(s) or re.search(r'\b(skills?|proficien\w*|knowledge|degree|bachelor\w*|qualification\w*|must|required|ability|familiar\w*|certif\w*)\b', s, re.I)]
    rest = [s for s in sents if s not in req]
    about = ' '.join(rest) if rest else (sents[0] if sents else '')
    experience = [s.rstrip('.') for s in req if EXP_RE.search(s)][:3]
    quals = [s.rstrip('.') for s in req if s.rstrip('.') not in experience][:5]
    return {'about': about, 'duties': [], 'skills': skills_of(text, 10), 'quals': [q for q in quals if flt.ok(q, 12, 260)], 'experience': experience, 'preferred': []}
