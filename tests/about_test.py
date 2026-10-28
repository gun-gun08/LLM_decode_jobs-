r"""Unit tests of the "About the Role" points (models/view_helpers.about_points): job board snippets are excerpts joined with "...". Real snippets from the local database.

    python tests\about_test.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'odoo_addons', 'llmd_job_aggregator', 'models'))
import view_helpers as V  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')

CIMPRESS = ('...(such as Snowflake agents) to surface automated insights, making data easy and intuitive for stakeholders to access independently. Partner... ...a challenge; '
            "we just call it another great day at work. We're Remote- First In 2020, Cimpress adopted a Remote-First operating model...")
TELUS = ('...it. TELUS Digital is solving the Physical AI bottleneck, capturing highly calibrated,... ...leading hyperscalers.We are hiring a Group Product Manager for the Physical AI '
         'Robotics product team... ...role is based in Bengaluru, India with a hybrid working arrangement.Why Join Us :- Early...')
KHAN = ('...This is a remote position. ABOUT KHAN ACADEMY Khan Academy is a fast-paced, nonprofit startup on a mission to provide a free... ...ROLE We are looking for a person who '
        'will help us with data management, transformation, analysis and visualization. The primary...')
THINKNOVA = ('...Thinknova is hiring for Data Analyst Intern Duration: 3 months Stipend: Up to 10,000 (performance-based) Type: Paid, remote internship About the Company Thinknova '
             'is offering a structured remote internship for freshers who want to begin a career in data analytics...')
POWER_APP = '...Senior Power App Developer | Microsoft Word VBA & Document Automation Required Experience: 7+ years Location: Pune, Hybrid - 3 days/week... ....'


class AboutPoints(unittest.TestCase):
    def test_the_screenshot_job(self):
        pts = V.about_points(CIMPRESS, 'Data Analyst')
        self.assertEqual(pts, ['To surface automated insights, making data easy and intuitive for stakeholders to access independently.',
                               "We're Remote-First In 2020, Cimpress adopted a Remote-First operating model…"])

    def test_scraps_and_cut_tails_are_dropped(self):
        pts = V.about_points(TELUS, 'TELUS Digital - Group Product Manager')
        self.assertNotIn('Partner', ' '.join(V.about_points(CIMPRESS)))
        self.assertTrue(all('Why Join Us' not in p for p in pts), pts)
        self.assertIn('We are hiring a Group Product Manager for the Physical AI Robotics product team…', pts)
        self.assertTrue(pts[0].startswith('TELUS Digital is solving'), pts)

    def test_headings_inside_the_text_are_removed(self):
        pts = V.about_points(KHAN, 'Data Analyst')
        self.assertEqual(pts[0][:60], 'This is a remote position. Khan Academy is a fast-paced, non')
        self.assertTrue(pts[1].startswith('We are looking for a person'), pts)
        self.assertNotIn('ABOUT', ' '.join(pts))
        self.assertNotIn('About the Company', V.about_points(THINKNOVA)[0])

    def test_labels_are_separated_and_the_title_is_not_repeated(self):
        self.assertIn('Intern · Duration: 3 months · Stipend: Up to 10,000 (performance-based) · Type: Paid, remote internship. Thinknova is offering', V.about_points(THINKNOVA)[0])
        self.assertEqual(V.about_points(POWER_APP, 'Senior Power App Developer | Microsoft Word VBA & Document Automation'),
                         ['Required Experience: 7+ years · Location: Pune, Hybrid - 3 days/week…'])

    def test_spacing_is_repaired(self):
        text = ' '.join(V.about_points(TELUS) + V.about_points(CIMPRESS))
        self.assertNotIn('Remote- First', text)
        self.assertNotIn('.We', text)
        self.assertNotIn('...', text)

    def test_a_normal_text_stays_one_point_and_junk_gives_none(self):
        normal = 'We are looking for an experienced Product Manager to lead the vision, development, and delivery of AI-driven products.'
        self.assertEqual(V.about_points(normal), [normal])
        self.assertEqual(V.about_points("You'll work..."), [])
        self.assertEqual(V.about_points('Read more about the combined company by visiting our blog ....'), [])
        self.assertEqual(V.about_points(''), [])

    def test_limits(self):
        many = ' ... '.join('Point number %d says something useful about this job and the team.' % i for i in range(10))
        pts = V.about_points(many)
        self.assertEqual(len(pts), 4)
        self.assertLessEqual(sum(len(p) for p in pts), 650)


class RolePoints(unittest.TestCase):
    """The 3 points shown under About the Role: sentences about the job itself, then true stored facts."""
    FACTS_1342 = V.job_facts('Data Analyst', 'Cimpress', 'India', 'Remote', '', '', '', ['Snowflake', 'Stakeholder Management'])

    def test_the_screenshot_job_gets_three_correct_points(self):
        pts = V.role_points(CIMPRESS, 'Data Analyst', ['Snowflake', 'Stakeholder Management'], self.FACTS_1342, company='Cimpress')
        self.assertEqual(pts, ['To surface automated insights, making data easy and intuitive for stakeholders to access independently.',
                               'Data Analyst role at Cimpress (Remote, India).', 'Skills asked for: Snowflake and Stakeholder Management.'])

    def test_company_history_is_not_a_point_about_the_role(self):
        pts = V.role_points(CIMPRESS, 'Data Analyst', ['Snowflake'], self.FACTS_1342, company='Cimpress')
        self.assertFalse(any('operating model' in p or 'In 2020' in p for p in pts), pts)
        telus = V.role_points(TELUS, 'TELUS Digital - Group Product Manager - AI/Robotics', [], ['Group Product Manager role at Xavient (Hybrid, Bangalore).'], company='Xavient')
        self.assertIn('We are hiring a Group Product Manager for the Physical AI Robotics product team…', telus)
        self.assertFalse(any(p.startswith('TELUS Digital is solving') for p in telus), telus)

    def test_never_more_than_three_and_nothing_made_up(self):
        facts = V.job_facts('Data Analyst', 'Khan Academy India', 'work from home', 'Remote', 'Contract', '', '', [])
        pts = V.role_points(KHAN, 'Data Analyst', [], facts, company='Khan Academy India')
        self.assertLessEqual(len(pts), 3)
        source = ' '.join(V.about_points(KHAN, 'Data Analyst', max_points=50, point_limit=10 ** 6, total_limit=10 ** 7))
        for p in pts:
            self.assertTrue(p in facts or p.strip('…')[:40] in source, p)
        self.assertIn('We are looking for a person who will help us with data management, transformation, analysis and visualization.', pts)

    def test_facts_fill_and_only_true_facts(self):
        self.assertEqual(V.job_facts('Data Analyst /REMOTE IN INDIA', 'RED Global', 'India', 'Remote')[0], 'Data Analyst role at RED Global (Remote, India).')
        self.assertEqual(V.job_facts('Backend + AI Intern (Remote)', 'Sparkable', 'India', 'Remote')[0], 'Backend + AI Intern role at Sparkable (Remote, India).')
        self.assertEqual(V.job_facts('AI Architect', 'X', '', '', '', '', 'Rs 15 - 30 lakhs p.a.')[-1], 'Salary: Rs 15 - 30 lakhs p.a.')
        self.assertEqual(V.role_points("You'll work...", 'Data Analyst', [], ['Data Analyst role at Clovity (India).', 'Level: Fresher.']),
                         ['Data Analyst role at Clovity (India).', 'Level: Fresher.'])

    def test_a_role_sentence_wins_over_scraps(self):
        text = ('...About the Role We are seeking a proactive AI engineer with a strong infrastructure background to join our team in Pune. You will design... '
                '...Required Skills Product Management .')
        pts = V.role_points(text, 'AI Automation Lead', [], ['AI Automation Lead role at Cephas (Pune).'])
        self.assertEqual(pts[0], 'We are seeking a proactive AI engineer with a strong infrastructure background to join our team in Pune.')
        self.assertFalse(any('Required Skills' in p for p in pts), pts)


if __name__ == '__main__':
    unittest.main(verbosity=2)
