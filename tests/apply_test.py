"""Unit tests of the checks of applicant data (our application form, the data of an authorized provider) and of the resume (models/apply_utils.py): no Odoo, no network.

    python tests\\apply_test.py
"""
import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'odoo_addons', 'llmd_job_aggregator', 'models'))
import apply_utils as A  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')

PDF = b'%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF'
DOC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\x00' * 64


def make_docx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', '<w:document/>')
    return buf.getvalue()


GOOD = {'name': 'Asha Verma', 'email': 'Asha.Verma@Example.com', 'phone': '+91 98765 43210', 'note': 'Hello\r\n\r\n\r\n\r\nThere', 'consent': '1'}


class FormTests(unittest.TestCase):
    def test_good_form(self):
        vals, errors = A.validate(GOOD)
        self.assertEqual(errors, {})
        self.assertEqual(vals['email'], 'asha.verma@example.com')
        self.assertEqual(vals['note'], 'Hello\n\nThere')

    def test_required_fields_name_and_email(self):
        _vals, errors = A.validate({})
        self.assertEqual(set(errors), {'name', 'email', 'consent'})
        self.assertEqual(A.validate(dict(GOOD, phone=''))[1], {})

    def test_name(self):
        for bad in ('', 'A', '12345', '!!!', '   '):
            self.assertIn('name', A.validate(dict(GOOD, name=bad))[1], bad)
        self.assertEqual(A.validate(dict(GOOD, name='  Anjali   Rao \x00 '))[0]['name'], 'Anjali Rao')
        self.assertNotIn('name', A.validate(dict(GOOD, name='Renée Müller'))[1])
        self.assertEqual(len(A.validate(dict(GOOD, name='x' * 500))[0]['name']), 120)

    def test_email(self):
        for bad in ('plain', 'a@b', 'a b@c.com', '@c.com', 'a@@c.com', 'a@c..com', 'a@-c.com', 'x' * 260 + '@c.com', 'a@c.c'):
            self.assertIn('email', A.validate(dict(GOOD, email=bad))[1], bad)
        for ok in ('a@c.in', 'first.last+tag@sub.example.co.in'):
            self.assertNotIn('email', A.validate(dict(GOOD, email=ok))[1], ok)

    def test_no_phone_is_read(self):
        for sent in ('abc', '+91 98765 43210', ''):
            vals, errors = A.validate(dict(GOOD, phone=sent))
            self.assertNotIn('phone', vals, sent)
            self.assertNotIn('phone', errors, sent)

    def test_consent_only_when_required(self):
        self.assertEqual(A.validate({}, consent_required=False)[1].keys(), {'name', 'email'})
        self.assertEqual(A.validate(dict(GOOD, consent=''), consent_required=False)[1], {})

    def test_consent(self):
        for off in ('', '0', 'false', 'off', None):
            self.assertIn('consent', A.validate(dict(GOOD, consent=off))[1], off)
        for on in ('1', 'on', 'true', True):
            self.assertNotIn('consent', A.validate(dict(GOOD, consent=on))[1], on)

    def test_note_is_cut(self):
        self.assertEqual(len(A.validate(dict(GOOD, note='n' * 5000))[0]['note']), 2000)


class ResumeTests(unittest.TestCase):
    def test_real_files_are_accepted(self):
        for name, data, mime in (('cv.pdf', PDF, 'application/pdf'), ('cv.DOC', DOC, 'application/msword'), ('My CV.docx', make_docx(), A.RESUME_EXT['docx'])):
            error, ext, mimetype, safe = A.check_resume(name, data)
            self.assertEqual((error, mimetype), ('', mime), name)
            self.assertTrue(safe.endswith('.' + ext))

    def test_a_resume_is_optional_unless_required(self):
        self.assertEqual(A.check_resume('', b'')[0], '')
        self.assertIn('attach', A.check_resume('', b'', required=True)[0])

    def test_wrong_type_size_or_content(self):
        self.assertIn('PDF, DOC or DOCX', A.check_resume('cv.exe', PDF)[0])
        self.assertIn('PDF, DOC or DOCX', A.check_resume('cv.pdf.exe', PDF)[0])
        self.assertIn('larger than 5 MB', A.check_resume('cv.pdf', PDF + b'0' * A.MAX_RESUME)[0])
        self.assertIn('does not look like', A.check_resume('cv.pdf', b'MZ\x90\x00 this is a program')[0])
        self.assertIn('does not look like', A.check_resume('cv.docx', b'just text')[0])
        self.assertIn('does not look like', A.check_resume('cv.docx', PDF)[0])
        self.assertIn('does not look like', A.check_resume('cv.doc', b'plain text file')[0])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('evil.txt', 'not word')
        self.assertIn('does not look like', A.check_resume('cv.docx', buf.getvalue())[0])

    def test_file_names_are_safe(self):
        self.assertEqual(A.safe_filename('../../etc/passwd.pdf', 'pdf'), 'passwd.pdf')
        self.assertEqual(A.safe_filename('C:\\Users\\me\\CV <final>.pdf', 'pdf'), 'CV _final.pdf')
        self.assertEqual(A.safe_filename('...pdf', 'pdf'), 'resume.pdf')
        self.assertLessEqual(len(A.safe_filename('a' * 400 + '.pdf', 'pdf')), 84)


if __name__ == '__main__':
    unittest.main(verbosity=2)
