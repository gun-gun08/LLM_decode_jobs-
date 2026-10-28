"""The language of a job listing and the languages the job asks for - read from the job's own text, nothing guessed.
Pure python (no Odoo imports), shared by the model and the tests.

- listing_language(title, text): 'zh' when the listing is written in Chinese, 'zh-en' when its text is in Chinese and English, 'zh-title' when only the
  title is in Chinese (the description is in English), else ''. No translation service is configured, so Chinese text is shown as the employer wrote it, marked
  "Listed in Chinese" / "Chinese title" - never with a made-up English version.
- languages_asked(text): the languages the job text asks for, each "required" or "a plus" ("Fluent Mandarin is a must" -> Mandarin: required). English
  counts only when the text asks for it explicitly; a listing written in English does not by itself make English a requirement."""
import re

_HAN = re.compile(r'[㐀-䶿一-鿿豈-﫿]')
_LATIN = re.compile(r'[A-Za-z]')
# (label, pattern of the language's name in English and in Chinese)
LANGUAGES = [
    ('Mandarin', r'mandarin|putonghua|普通话|(?<![a-z])chinese(?! (?:market|customers?|clients?|companies|new year|government|regulations?))|中文|汉语'),
    ('Cantonese', r'cantonese|粤语|廣東話|广东话'),
    ('English', r'english|英语|英文'),
    ('Japanese', r'japanese|日语'),
    ('Korean', r'korean|韩语'),
    ('Hindi', r'\bhindi\b'),
    ('Spanish', r'spanish'),
    ('Portuguese', r'portuguese'),
    ('French', r'\bfrench\b'),
    ('German', r'\bgerman\b'),
    ('Arabic', r'\barabic\b'),
    ('Vietnamese', r'vietnamese'),
    ('Thai', r'\bthai\b'),
    ('Indonesian', r'bahasa|indonesian'),
]
_LANG_RX = [(label, re.compile(p, re.I)) for label, p in LANGUAGES]
# a sentence asks for a language when it talks about speaking / writing it
_ASK = re.compile(r'fluen|proficien|native|bilingual|business[- ]level|working knowledge|command of|spoken|written|speak|verbal|language|read(?:ing)? and writ|'
                  r'communicat|skills? in|ability to (?:read|write|speak|communicate)|(?:is|are) (?:a )?(?:plus|must|required|preferred|essential)|精通|流利|熟练|母语|能力', re.I)
_PLUS = re.compile(r'\bplus\b|preferred|preferable|advantage|nice[- ]to[- ]have|bonus|desirable|is a benefit|would be great|helpful|优先|加分', re.I)
_SENTENCES = re.compile(r'(?<=[.!?;。！？；\n])\s*|\s*[•·•]\s*')
_TAGS = re.compile(r'<[^>]+>')


_BREAKS = re.compile(r'</(?:li|p|div|h[1-6]|tr)>|<br\s*/?>', re.I)


def plain(html):
    """The text of a job description with a sentence end at every list item, paragraph or line break (so that bullets stay apart)."""
    return re.sub(r'\s+', ' ', _TAGS.sub(' ', _BREAKS.sub('. ', html or ''))).strip()


def has_han(text):
    return bool(_HAN.search(text or ''))


def listing_language(title, text=''):
    """The language of a listing as the employer wrote it: 'zh' = in Chinese, 'zh-en' = in Chinese and English (both in the text), 'zh-title' = only the
    title is in Chinese (the description is English), '' = not Chinese."""
    title = title or ''
    body = (text or '')[:6000]
    han, lat = len(_HAN.findall(body)), len(_LATIN.findall(body))
    body_zh, body_en = han > 80, lat > 300
    han_t, lat_t = len(_HAN.findall(title)), len(_LATIN.findall(title))
    title_zh = bool(han_t) and han_t * 2 >= lat_t
    if body_zh:
        return 'zh-en' if body_en else 'zh'
    if title_zh:
        return 'zh-title' if body_en else 'zh'
    return ''


def languages_asked(text):
    """[(language, 'required' | 'plus')] in the order of LANGUAGES: the languages a sentence of the job text asks for."""
    found = {}
    for sentence in _SENTENCES.split(text or ''):
        if not sentence or not _ASK.search(sentence):
            continue
        head, _colon, body = sentence.rpartition(':')               # "Nice to have: Mandarin" - a heading before the colon counts for what follows it
        for clause in re.split(r'[,;]', body):
            for label, rx in _LANG_RX:
                if rx.search(clause):
                    kind = 'plus' if _PLUS.search(clause) or _PLUS.search(head) else 'required'
                    if found.get(label) != 'required':
                        found[label] = kind
    return [(label, found[label]) for label, _p in LANGUAGES if label in found]


def encode(pairs):
    return ','.join('%s:%s' % pair for pair in pairs)


def decode(value):
    return [tuple(x.split(':', 1)) for x in (value or '').split(',') if ':' in x]
