r"""Unit tests of the job categories and the category-page filters (models/board_config.py, models/job_facets.py): no Odoo, no network.
The titles and departments are real ones from the local database (2026-10-24).

    python tests\categories_test.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'odoo_addons', 'llmd_job_aggregator', 'models'))
import board_config as C  # noqa: E402
import job_facets as F  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')


class CategoryTests(unittest.TestCase):

    def test_titles(self):
        cases = {
            'Senior Machine Learning Engineer': 'ai-machine-learning', 'Platform Engineer - AI Infrastructure': 'ai-machine-learning', 'GenAI Engineer - Database': 'ai-machine-learning',
            'Staff Software Engineer - Infrastructure': 'it-software', 'Site Reliability Engineer': 'it-software', 'IT Support Engineer': 'it-software',
            'Senior Data Analyst - Power BI': 'data-analytics', 'Lead Data Engineer': 'data-analytics', 'Staff Data Analyst, People Analytics': 'data-analytics',
            'Solutions Architect': 'solutions-presales', 'Senior Sales Engineer - Public Sector': 'solutions-presales', 'Applied AI Architect': 'solutions-presales',
            'Enterprise Account Executive, Mumbai': 'sales', 'Enterprise Account Executive, Growth (State Ministries)': 'sales', 'Senior Associate, Mid Market Sales': 'sales',
            'Partner Marketing Manager': 'marketing', 'Growth Marketing Intern': 'marketing', 'Product Marketing Manager': 'marketing',
            'Senior Product Manager - Data & Analytics Platform': 'product-design', 'Senior Product Designer (AI Builder)': 'product-design',
            'Technical Account Manager': 'customer-success', 'Customer Success Manager - Growth and Retention': 'customer-success',
            'Talent Acquisition Specialist - IT Recruitment': 'people-hr', 'Revenue Analyst': 'finance', 'Senior Accountant': 'finance',
            'Director - Global Revenue Operations': 'operations', 'Business Operations Manager': 'operations',
            # the categories of a worldwide board (v19.0.26)
            'Senior Security Engineer': 'cybersecurity', 'Account Executive, Security': 'sales', 'Firmware Engineer': 'hardware-embedded', 'Senior Counsel, Privacy': 'legal-compliance',
            'Compliance Analyst': 'legal-compliance', 'Demand Planner - North': 'supply-chain', 'Procurement Specialist': 'supply-chain', 'Executive Assistant to CEO': 'admin-office',
            'Clinical Research Associate': 'healthcare-life-sciences', 'Regulatory Affairs Manager': 'healthcare-life-sciences', 'Corporate Trainer': 'education-training',
        }
        for title, want in cases.items():
            self.assertEqual(C.job_category(title), want, title)

    def test_role_then_department_when_the_title_says_nothing(self):
        self.assertEqual(C.job_category('Associate II', ',account_executive,', 'Other'), 'sales')
        self.assertEqual(C.job_category('Associate II', '', 'Customer Success'), 'customer-success')
        self.assertEqual(C.job_category('Associate II', '', 'Rohit Dosi (Bing and Etisalat)'), '')

    def test_headquarters_only_when_verified(self):
        self.assertEqual((C.company_hq('Bosch Group'), C.company_hq('razorpay software private limited'), C.company_hq('Spotify')), ('Germany', 'India', 'Sweden'))
        self.assertEqual(C.company_hq('Elastic'), '')                    # two headquarters: not verified
        self.assertEqual(C.company_hq('A Company Added Later'), '')

    def test_department_when_the_title_and_role_say_nothing(self):
        self.assertEqual(C.job_category('Associate II', '', 'Information Technology'), 'it-software')
        self.assertEqual(C.job_category('Associate II', '', 'Finance'), 'finance')
        self.assertEqual(C.job_category('Associate II', '', 'People Operations'), 'people-hr')

    def test_every_category_has_a_page(self):
        slugs = [s for s, _l, _d, _i in C.JOB_CATEGORIES]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertTrue(all(s.replace('-', '').isalpha() for s in slugs))
        self.assertEqual(len(slugs), 18)
        self.assertTrue(all(new in slugs for new in C.OLD_CATEGORY_SLUGS.values()))         # the old links lead to a page that exists
        self.assertFalse(set(C.OLD_CATEGORY_SLUGS) & set(slugs))


class CourseTermTests(unittest.TestCase):
    """The words a course teaches (from its own page text) and the jobs that ask for them: used to rank and explain the course-matched jobs."""

    def test_terms_in_vocabulary_order(self):
        text = 'Learn Claude prompting, build RAG with LangChain and Python; B2B sales objections and closing; landing pages and funnels'
        self.assertEqual(C.course_terms(text), ['claude', 'prompting', 'rag', 'langchain', 'python', 'sales', 'b2b', 'objections', 'funnels', 'landing'])
        self.assertEqual(C.course_terms(''), [])
        self.assertEqual(C.course_terms('A course about cooking.'), [])

    def test_every_term_has_a_label(self):
        keys = [k for k, _l, _rx in C.COURSE_TERMS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(C.COURSE_TERM_LABELS.get(k) for k in keys))

    def test_match_is_shared_terms_as_labels(self):
        self.assertEqual(C.course_match(['claude', 'rag', 'sales'], ['sales', 'rag', 'python']), [C.COURSE_TERM_LABELS['rag'], C.COURSE_TERM_LABELS['sales']])
        self.assertEqual(C.course_match([], ['sales']), [])
        self.assertEqual(C.course_match(['sales'], ['']), [])


class SlugTests(unittest.TestCase):

    def test_slugify(self):
        self.assertEqual(C.slugify('Hevo Data'), 'hevo-data')
        self.assertEqual(C.slugify('  Rubrik, Inc. '), 'rubrik-inc')
        self.assertEqual(C.slugify('Delhi NCR'), 'delhi-ncr')
        self.assertEqual(C.slugify(''), '')


class FunctionTests(unittest.TestCase):

    def test_departments(self):
        cases = {'APJ Field Sales': 'sales', 'Enterprise Sales-340': 'sales', 'SW Eng - Applications-674': 'engineering', 'Field Engineering - Other': 'solutions',
                 'Data Science & Analytics': 'data', 'Product Design': 'design', 'Partner Success Services': 'customer', 'Revenue, OTC & QTC': 'finance',
                 'People Operations': 'people', 'Information Technology': 'it', 'Kunal (OneDSP ) - Non Tech': '', 'Rohit Dosi (Bing and Etisalat)': '', 'Other': '', 'General Business': ''}
        for dept, want in cases.items():
            self.assertEqual(C.job_function(dept), want, dept)


class YearsTests(unittest.TestCase):

    def test_ranges(self):
        cases = {'You have 5+ years of experience in sales.': (5, None), 'Experience: 3-5 years in analytics.': (3, 5), 'At least 7 years experience with Python.': (7, None),
                 '2 to 4 yrs of relevant experience.': (2, 4), 'We value experience. Join a team of 50 people.': (None, None), 'A 10 year old company. 4+ years of experience required.': (4, None)}
        for text, want in cases.items():
            self.assertEqual(F.years_range(text), want, text)


class CountryAndSkillTests(unittest.TestCase):

    def test_country(self):
        self.assertEqual(F.country_of('Bengaluru, KA, India', True), 'India')
        self.assertEqual(F.country_of('Remote - United States', False), 'United States')
        self.assertEqual(F.country_of('Remote', False), '')

    def test_skill_key(self):
        self.assertEqual(F.skill_key('  Stakeholder   Management '), 'stakeholder management')
        self.assertEqual(F.skill_key('A, B'), 'a b')


if __name__ == '__main__':
    unittest.main(verbosity=2)
