"""Unit tests of the listing language and the languages a job asks for (models/language.py), of the worldwide pick of each company's jobs
(sources._by_country) and of the China & Hong Kong region (models/job_facets.py): no Odoo, no network.

    python tests\\language_test.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'odoo_addons', 'llmd_job_aggregator', 'models'))
import job_facets as F  # noqa: E402
import language as L  # noqa: E402
import sources as S  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')


class ListingLanguageTests(unittest.TestCase):
    def test_chinese_listing(self):
        self.assertEqual(L.listing_language('高级软件工程师', '负责公司核心产品的研发工作。' * 20), 'zh')
        self.assertEqual(L.listing_language('Engineer', '负责公司核心产品的研发工作，参与系统架构设计。' * 10), 'zh')

    def test_chinese_title_english_description(self):
        text = 'Responsible to ensure EC motor building sets design tasks fulfilled according to given project targets and fulfilling the quality requirements. ' * 3
        self.assertEqual(L.listing_language('资深电机机械设计工程师（标准设计平台）_EM', text), 'zh-title')

    def test_chinese_and_english(self):
        self.assertEqual(L.listing_language('资深电机机械设计工程师', '负责公司核心产品的研发工作。' * 20 + ' Responsible for the design of motor parts and their tests. ' * 8), 'zh-en')

    def test_english_listing(self):
        self.assertEqual(L.listing_language('Senior Engineer (Shanghai)', 'Build services for our Shanghai team.'), '')
        self.assertEqual(L.listing_language('Software Engineer 软件', 'English text ' * 40), '')       # a word or two of Chinese in an English title


class LanguagesAskedTests(unittest.TestCase):
    def test_required_and_plus(self):
        text = L.plain('<ul><li>Fluent in Mandarin and English is a must</li><li>Cantonese is a plus.</li><li>Experience with programming languages such as Python</li></ul>'
                       '<p>精通日语优先</p>')
        self.assertEqual(L.languages_asked(text), [('Mandarin', 'required'), ('Cantonese', 'plus'), ('English', 'required'), ('Japanese', 'plus')])

    def test_no_language_without_a_sentence_about_it(self):
        self.assertEqual(L.languages_asked(L.plain('<p>Serve Chinese customers across Asia. Programming languages: Go, Rust.</p>')), [])
        self.assertEqual(L.languages_asked(L.plain('<p>We work with German and French partners.</p>')), [])
        self.assertEqual(L.languages_asked(''), [])

    def test_required_wins_over_plus(self):
        text = L.plain('<li>Mandarin is a plus for the APAC team.</li><li>Business-level Mandarin is required.</li>')
        self.assertEqual(L.languages_asked(text), [('Mandarin', 'required')])

    def test_each_clause_on_its_own(self):
        self.assertEqual(L.languages_asked(L.plain('<p>English as work language, Mandarin a plus.</p>')), [('Mandarin', 'plus'), ('English', 'required')])
        self.assertEqual(L.languages_asked(L.plain('<p>Nice to Have: Bilingual in English and Mandarin</p>')), [('Mandarin', 'plus'), ('English', 'plus')])
        self.assertEqual(L.languages_asked(L.plain('Requirements:<br/>Fluent Mandarin<br/>Python')), [('Mandarin', 'required')])

    def test_encode_decode(self):
        pairs = [('Mandarin', 'required'), ('English', 'plus')]
        self.assertEqual(L.decode(L.encode(pairs)), pairs)
        self.assertEqual(L.decode(''), [])
        self.assertEqual(L.decode(None), [])


class ChinaRegionTests(unittest.TestCase):
    def test_places(self):
        for loc, want in (('Hong Kong SAR', ('Hong Kong', 'china')), ('Hangzhou, Zhejiang', ('China', 'china')), ('Remote - PRC', ('China', 'china')),
                          ('Macao', ('Macau', 'china')), ('Taipei, Taiwan', ('Taiwan', 'asia-pacific')), ('Singapore', ('Singapore', 'asia-pacific'))):
            country = F.country_of(loc)
            self.assertEqual((country, F.region_of(country, loc, 'onsite')), want, loc)

    def test_region_list(self):
        self.assertIn('china', F.REGION_LABELS)
        self.assertEqual(F.COUNTRY_REGION['China'], 'china')
        self.assertNotIn('China', F.REGION_COUNTRIES['asia-pacific'])


class WorldPickTests(unittest.TestCase):
    def test_each_country_gets_a_turn(self):
        jobs = [{'location': 'Singapore', 'n': i} for i in range(6)] + [{'location': 'Hong Kong', 'n': 10}, {'location': 'Shanghai, China', 'n': 11}]
        picked = S._by_country(jobs, 4)
        self.assertEqual([j['location'] for j in picked], ['Singapore', 'Hong Kong', 'Shanghai, China', 'Singapore'])

    def test_limit_and_order_inside_a_country(self):
        jobs = [{'location': 'London', 'n': 1}, {'location': 'London', 'n': 2}, {'location': 'Berlin', 'n': 3}]
        self.assertEqual([j['n'] for j in S._by_country(jobs, 10)], [1, 3, 2])
        self.assertEqual(S._by_country(jobs, 0), [])


if __name__ == '__main__':
    unittest.main(verbosity=1)
