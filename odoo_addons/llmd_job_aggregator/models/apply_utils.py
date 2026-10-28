"""Checks for the applicant data an authorized provider integration sends (pure Python, no Odoo imports: unit-tested by rolelib/apply_test.py).

Everything that arrives is untrusted: text is cleaned and limited, the e-mail is validated, and a resume (optional) must be a real PDF / Word file of a sensible size (the file's
first bytes are checked, not just its name). An application is a name and an e-mail: no phone number is read or kept.
"""
import io
import re
import zipfile

MAX_RESUME = 5 * 1024 * 1024
RESUME_EXT = {
    'pdf': 'application/pdf',
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}
LIMITS = {'name': 120, 'email': 254, 'note': 2000}

_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,}$")


def one_line(value, limit):
    """Single-line text: control characters removed, white space collapsed, cut at `limit`."""
    return re.sub(r'\s+', ' ', _CONTROL.sub('', str(value or ''))).strip()[:limit]


def multi_line(value, limit):
    """Text that may contain line breaks (the message)."""
    text = _CONTROL.sub('', str(value or '')).replace('\r\n', '\n').replace('\r', '\n')
    return re.sub(r'\n{3,}', '\n\n', text).strip()[:limit]


def valid_email(value):
    return bool(value) and len(value) <= LIMITS['email'] and bool(_EMAIL.match(value)) and '..' not in value


def safe_filename(name, ext):
    """A file name without any path, with only harmless characters and the checked extension."""
    base = re.split(r'[\\/]', str(name or ''))[-1]
    base = re.sub(r'\.[A-Za-z0-9]{1,5}$', '', base)
    base = re.sub(r'[^A-Za-z0-9._ -]+', '_', base).strip(' ._-')[:80] or 'resume'
    return '%s.%s' % (base, ext)


def check_resume(filename, data, required=False):
    """-> (error, extension, mimetype, safe file name). `error` is '' when the file is fine or when there is no file and none is required."""
    name = str(filename or '')
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if not data:
        return ('Please attach your resume.' if required else ''), '', '', ''
    if ext not in RESUME_EXT:
        return 'The resume must be a PDF, DOC or DOCX file.', '', '', ''
    if len(data) > MAX_RESUME:
        return 'The resume is larger than %d MB. Please upload a smaller file.' % (MAX_RESUME // (1024 * 1024)), '', '', ''
    ok = False
    if ext == 'pdf':
        ok = data[:1024].lstrip().startswith(b'%PDF-')
    elif ext == 'doc':
        ok = data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')
    elif ext == 'docx':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
                ok = '[Content_Types].xml' in names and any(n.startswith('word/') for n in names)
        except (zipfile.BadZipFile, ValueError):
            ok = False
    if not ok:
        return 'This file does not look like a real %s document. Please upload your resume as a PDF, DOC or DOCX file.' % ext.upper(), '', '', ''
    return '', ext, RESUME_EXT[ext], safe_filename(name, ext)


def validate(form, consent_required=True):
    """The received data -> (clean values, {field: message}). Name and e-mail are required; the consent only when consent_required (a form of ours); an authorized provider
    answers for the consent of its own applicants. A phone number is never read: one sent anyway is ignored."""
    vals = {
        'name': one_line(form.get('name'), LIMITS['name']),
        'email': one_line(form.get('email'), LIMITS['email']).lower(),
        'note': multi_line(form.get('note'), LIMITS['note']),
        'consent': str(form.get('consent') or '').lower() not in ('', '0', 'false', 'no', 'off', 'none'),
    }
    errors = {}
    if len(vals['name']) < 2 or not re.search(r'[^\W\d_]', vals['name']):
        errors['name'] = 'Please enter the full name.'
    if not valid_email(vals['email']):
        errors['email'] = 'Please enter a valid email address.'
    if consent_required and not vals['consent']:
        errors['consent'] = 'Please agree to the storing of the details so that the application can be processed.'
    return vals, errors
