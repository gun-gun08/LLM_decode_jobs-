r"""Unit tests of the job summary (models/summary.py): one format for every source, 150-250 words when the source sends the full text, nothing made up.
The texts are real jobs from the local database (a Himalayas full text, shortened; Jooble snippets).

    python tests\summary_test.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'odoo_addons', 'llmd_job_aggregator', 'models'))
import parsers as P  # noqa: E402
import summary as S  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')

FULL_HTML = (
    '<h4><em>This role is 100% remote across India location</em></h4><h4><strong>About OpenTable</strong></h4>'
    '<p>With millions of diners, 70,000+ restaurant partners and 25+ years of experience, OpenTable, part of Booking Holdings, Inc. (NASDAQ: BKNG), is an industry leader with a passion for helping restaurants thrive.</p>'
    '<p>Every employee at OpenTable has a tangible impact on what we do and how we do it. Hospitality is all about taking care of others, and it defines our culture.</p>'
    '<h4>About Role</h4><p>We are looking for a Senior Data Engineer - AI/ML to help build the data and AI infrastructure powering our next generation of intelligent products and experiences.</p>'
    '<h4>Benefits</h4><ul><li><p>Generous health insurance</p></li><li><p>Paid parental leave</p></li></ul>'
    '<h4>Inclusion</h4><p>We are committed to creating a workplace where everyone feels they belong. If you need accommodations during the application or interview process, please reach out to your recruiter.</p>'
    '<p>Refer a friend and earn a referral bonus! #hiring #dataengineering #remote</p><p>Originally posted on Himalayas</p>')
FULL_SECTIONS = {
    'about': '',
    'duties': ['Design and build AI/LLM data pipelines supporting training, inference, evaluation, embeddings, and retrieval workloads',
               'Build production-grade RAG systems, including ingestion, chunking, embedding generation, indexing, retrieval, reranking, and context construction',
               'Develop AI applications using LLMs, structured outputs, function/tool calling, and agentic workflows',
               'Build and optimize semantic search and vector retrieval systems',
               'Develop frameworks for LLM evaluation, monitoring, tracing, quality measurement, latency, and cost optimization',
               'Design scalable batch and streaming pipelines using Databricks, Apache Spark, Delta Lake, Snowflake, and Airflow',
               'Build data products and platforms that make structured and unstructured enterprise data accessible to AI applications',
               'Build data products and platforms that make structured and unstructured enterprise data accessible to AI apps'],
    'skills': ['LLMs', 'Databricks', 'RAG', 'Airflow', 'Snowflake', 'Spark', 'Python', 'SQL', 'Java'],
    'quals': ['Strong programming skills in Python and/or Scala/Java and advanced SQL', 'Hands-on experience with Databricks, Snowflake, Apache Spark, Delta Lake, and Airflow',
              'Strong experience with cloud data platforms such as Snowflake and/or Databricks', 'Practical experience building applications using LLMs or Generative AI',
              'Strong understanding of RAG architectures, embeddings, vector databases, semantic search, and retrieval systems',
              'Familiarity with LLM concepts including prompting, structured outputs, tool calling, and model evaluation',
              'Experience designing scalable, reliable, and observable production data systems'],
    'experience': ['5+ years of experience in data engineering, software engineering, distributed systems, or a related field'],
    'preferred': ['Experience with Kafka, MLflow, Unity Catalog, or model-serving platforms'],
}
KYNDRYL = ('<p>...well-being is prioritized and your potential can thrive. The Role We are seeking a highly experienced Senior Lead Data Engineer / Data Analyst to lead enterprise-wide data '
           'engineering, analytics, reporting, and regulatory data initiatives within the Banking and Financial...</p>')
PAVAGO = ('<p>... Data Analyst / Data Engineer – SQL, BI &amp; Data Analytics | Remote Position Type: Full-Time, Remote Working Hours: U.S. Business Hours About the Role At Pavago, '
          'one of our clients is hiring a Data Analyst / Data Engineer to transform business data into reliable reporting...</p>')
THINKNOVA = ('<p>...Thinknova is hiring for Data Analyst Intern Duration: 3 months Stipend: Up to 10,000 (performance-based) Type: Paid, remote internship About the Company Thinknova '
             'is offering a structured remote internship for freshers who want to begin a career in data analytics...</p>')
UNWANTED = ('benefit', 'insurance', 'parental', 'inclusion', 'belong', 'accommodation', 'interview', 'referral', 'refer a friend', '#', 'originally posted', 'culture', 'nasdaq', 'industry leader')


def text_of(sm):
    return ' '.join([sm['overview']] + sm['responsibilities'] + sm['requirements'] + [sm['experience_level'], sm['salary']] + sm['details'])


class FullText(unittest.TestCase):
    def setUp(self):
        self.sm = S.build('Senior Data Engineer (AI/ML)', 'OpenTable', 'India', 'Remote', 'Full-time', 'Senior-level', '', FULL_HTML, True, FULL_SECTIONS)

    def test_the_format(self):
        sm = self.sm
        self.assertTrue(sm['overview'].startswith('We are looking for a Senior Data Engineer'), sm['overview'])
        self.assertTrue(4 <= len(sm['responsibilities']) <= 6, sm['responsibilities'])
        self.assertTrue(4 <= len(sm['requirements']) <= 6, sm['requirements'])
        self.assertEqual(sm['experience_level'], 'Senior-level · 5+ years')
        self.assertEqual(sm['skills'][:3], ['LLMs', 'Databricks', 'RAG'])
        self.assertTrue(150 <= sm['words'] <= 250, sm['words'])

    def test_culture_benefits_hashtags_referrals_interviews_are_gone(self):
        low = text_of(self.sm).lower()
        for word in UNWANTED:
            self.assertNotIn(word, low, word)

    def test_lines_are_tidy_and_not_repeated(self):
        for line in self.sm['responsibilities'] + self.sm['requirements']:
            self.assertTrue((line[0].isupper() or line[0].isdigit()) and line[-1] in '.…', line)
        self.assertEqual(sum('Build data products and platforms' in x for x in self.sm['responsibilities']), 0 if len(self.sm['responsibilities']) < 7 else 1)
        dup = [x for x in self.sm['responsibilities'] if x.startswith('Build data products')]
        self.assertLessEqual(len(dup), 1)

    def test_no_salary_is_made_up(self):
        self.assertEqual(self.sm['salary'], '')

    def test_never_more_than_250_words(self):
        long = dict(FULL_SECTIONS, duties=[d + ' across many teams, regions, products and very large enterprise customers every single quarter' for d in FULL_SECTIONS['duties']],
                    quals=[q + ' in demanding, regulated, high-scale production environments with strict uptime and audit requirements' for q in FULL_SECTIONS['quals']])
        sm = S.build('Senior Data Engineer', 'OpenTable', 'India', '', '', '', '', FULL_HTML, True, long)
        self.assertLessEqual(sm['words'], 250)
        self.assertTrue(4 <= len(sm['responsibilities']) <= 6 and 4 <= len(sm['requirements']) <= 6)


COMPANY_HTML = (
    '<p>As a Solutions Architect at Databricks, you will help strategic customers in India design their data and AI platforms.</p>'
    '<h3>The impact you will have:</h3><ul><li>Be the trusted technical advisor for named strategic accounts</li><li>Lead architecture workshops and proofs of concept on Spark and Delta Lake</li>'
    '<li>Partner with the sales team to show how the platform solves business problems</li><li>Build reference architectures and demos for generative AI use cases</li></ul>'
    '<h3>What we look for:</h3><ul><li>8+ years of experience in data engineering or data science roles</li><li>Hands-on experience with Python, SQL and Apache Spark</li>'
    '<li>Experience with AWS, Azure or Google Cloud</li><li>Strong communication skills with technical and business stakeholders</li><li>The preferred qualifications are a bonus, not a requirement.</li></ul>'
    '<p>If access to export-controlled technology or source code is required for performance of job duties, it is within the employer\'s discretion whether to apply for a licence.</p>'
    '<p>All qualified applicants will receive consideration for employment without regard to race, color, religion, sex or national origin.</p>'
    '<p>Notice for New York City Applicants &amp; Employees: we may use Automated Employment Decision Tools.</p>'
    '<p>By applying for this role, you adhere to applicable laws and our privacy notice. If you meet these requirements, you are encouraged to apply.</p>'
    '<p>Recruitment Fraud Awareness - we will never ask candidates to make any payment as part of an application. How is life at Databricks?</p>'
    '<p>If you are a national of one of the listed countries, an export license may be required. We are the only vendor named a Leader in the Gartner Magic Quadrant.</p>')


class CompanyBoardText(unittest.TestCase):
    def test_legal_and_hiring_notices_of_company_pages_are_left_out(self):
        sections = P.parse_listing(COMPANY_HTML, 'Databricks', 'Solutions Architect', strict=False)          # as the sync stores it (sections_json)
        sm = S.build('Solutions Architect', 'Databricks', 'Bengaluru, India', '', 'Full Time', '', '', COMPANY_HTML, True, sections)
        low = text_of(sm).lower()
        for word in ('export', 'qualified applicants', 'automated employment', 'by applying', 'encouraged to apply', 'fraud', 'bonus', 'life at', 'privacy notice', 'gartner'):
            self.assertNotIn(word, low, word)
        self.assertIn('Lead architecture workshops and proofs of concept on Spark and Delta Lake.', sm['responsibilities'])
        self.assertIn('Hands-on experience with Python, SQL and Apache Spark.', sm['requirements'])


class OneBlock(unittest.TestCase):
    def test_everything_in_one_job_overview(self):
        sm = S.build('Senior Data Engineer (AI/ML)', 'OpenTable', 'India', 'Remote', 'Full-time', 'Senior-level', '', FULL_HTML, True, FULL_SECTIONS)
        block = S.display(sm)
        self.assertTrue(block['overview'].startswith('We are looking for'))
        self.assertEqual(len(block['points']), 8)
        self.assertEqual(block['points'][:4], sm['responsibilities'][:4])
        self.assertEqual(block['points'][4:], sm['requirements'][:4])
        self.assertEqual(block['facts'], 'Experience: Senior-level · 5+ years · Job type: Full-time')

    def test_nothing_empty_is_shown(self):
        sm = S.build('Data Analyst / Engineer', 'Kyndryl', 'Bangalore', '', '', '', '', KYNDRYL, False, {'skills': ['Data Analysis']})
        block = S.display(sm)
        self.assertEqual((block['points'], block['facts']), ([], ''))
        self.assertNotIn('Not specified', str(block))
        stipend = S.display(S.build('Data Analyst', 'thinknovaa', 'India', '', 'Internship', 'Internship', '', THINKNOVA, False, {}))
        self.assertEqual(stipend['facts'], 'Experience: Internship · Stipend: Up to 10,000 (performance-based) · Job type: Internship · Duration: 3 months')


class Snippets(unittest.TestCase):
    def test_kyndryl_short_snippet_nothing_invented(self):
        sm = S.build('Data Analyst / Engineer', 'Kyndryl', 'Bangalore', '', '', '', '', KYNDRYL, False, {'skills': ['Data Analysis']})
        self.assertTrue(sm['overview'].startswith('We are seeking a highly experienced Senior Lead Data Engineer / Data Analyst'), sm['overview'])
        self.assertEqual(sm['responsibilities'], [])
        self.assertEqual(sm['requirements'], [])
        self.assertEqual(sm['experience_level'], S.NOT_SPECIFIED)
        self.assertEqual(sm['salary'], '')
        self.assertNotIn('well-being', text_of(sm))

    def test_stated_details_are_read(self):
        sm = S.build('Data Analyst / Data Engineer', '', 'India', 'Remote', '', '', '', PAVAGO, False, {'skills': ['SQL']})
        self.assertIn('Job type: Full-Time, Remote', sm['details'])
        self.assertIn('Working hours: U.S. Business Hours', sm['details'])
        self.assertIn('hiring a Data Analyst / Data Engineer to transform business data', sm['overview'])

    def test_stipend_and_duration(self):
        sm = S.build('Data Analyst', 'thinknovaa', 'India', '', 'Internship', 'Internship', '', THINKNOVA, False, {})
        self.assertEqual(sm['salary'], 'Stipend: Up to 10,000 (performance-based)')
        self.assertIn('Duration: 3 months', sm['details'])
        self.assertEqual(sm['experience_level'], 'Internship')

    def test_a_job_without_text_only_shows_its_stored_facts(self):
        sm = S.build('Data Analyst (Fresher)', 'Clovity', 'India', '', '', 'Fresher', '', "<p>You'll work...</p>", False, {})
        self.assertEqual(sm['overview'], 'Data Analyst (Fresher) role at Clovity (India).')
        self.assertFalse(sm['from_text'])
        self.assertEqual((sm['responsibilities'], sm['requirements'], sm['experience_level']), ([], [], 'Fresher'))

    def test_a_stored_salary_is_kept_as_it_is(self):
        sm = S.build('Data Analyst', 'Aon', 'Bangalore', 'Hybrid', 'Full-time', '', 'Rs 7 - 10 lakhs p.a.', '<p>Job Title - Data Analyst Position type - Full Time</p>', False, {})
        self.assertEqual(sm['salary'], 'Rs 7 - 10 lakhs p.a.')


    def test_a_line_that_only_opens_a_list_is_not_a_point(self):
        sections = {'about': '', 'duties': [], 'quals': ["You'll thrive with us if you:", 'Have 5+ years of experience selling SaaS to mid-market companies',
                                                       'Are comfortable running the full sales cycle from first call to close'], 'experience': [], 'preferred': [], 'skills': []}
        sm = S.build('Account Executive', 'ElevenLabs', 'India', 'Remote', 'Full-time', '', '', '', True, sections)
        self.assertFalse([x for x in sm['requirements'] if 'if you' in x.lower()], sm['requirements'])
        self.assertTrue(any('5+ years' in x for x in sm['requirements']), sm['requirements'])

class KeyPointTimeline(unittest.TestCase):
    """The Key points of the detail page: the job's own headings head their points (never numbered), numbering runs 1, 2, 3 ..., the opening
    phrase is bold and nothing of the text changes. The lines are real ones from the local database (jobs 5157, 5269, 4989)."""

    def test_headings_are_not_points(self):
        for line in ('What You Will Do?', 'What is expected out of you?', "What We're Looking For.", 'What You’ll Do (Key Responsibilities).', 'Your work will directly result in.'):
            self.assertTrue(S.is_heading_point(line), line)
        for line in ('Basic understanding of Talent Acquisition and recruitment processes.', 'Preferred: bing Ads Certification.', 'Strong SQL.', 'Skills in SQL and Python.',
                     'Experience managing and converting inbound leads.'):
            self.assertFalse(S.is_heading_point(line), line)

    def test_groups_numbering_and_requirements_label(self):
        sm = {'responsibilities': ['You will move beyond standard feature delivery to define the technical vision.', 'Your work will directly result in.',
                                   'Architecting and deploying robust ML APIs and pipelines.', 'Setting the gold standard for ML Engineering practices.'],
              'requirements': ['A proven, demonstrable track record of successfully architecting ML systems.', 'Expert-level Object-Oriented Programming (OOP) expertise in Python and Java.']}
        groups = S.display(sm)['point_groups']
        self.assertEqual([g['heading'] for g in groups], ['', 'Your work will directly result in', 'Requirements'])
        self.assertEqual([r['n'] for g in groups for r in g['items']], [1, 2, 3, 4, 5])
        self.assertEqual(S.display(sm)['points'], [x for x in sm['responsibilities'] + sm['requirements'] if 'result in.' not in x])

    def test_a_heading_with_nothing_under_it_is_left_out_and_lists_join(self):
        sm = {'responsibilities': ['What You Will Do?'], 'requirements': ["You've built AI agents, not just used AI tools. You have shipped agentic systems.",
                                                                        'You have strong infrastructure fundamentals. You understand distributed systems.']}
        groups = S.display(sm)['point_groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['heading'], '')
        self.assertEqual([r['lead'] for r in groups[0]['items']], ["You've built AI agents, not just used AI tools.", 'You have strong infrastructure fundamentals.'])
        plain = S.display({'responsibilities': ['Build dashboards in Power BI for the sales team.'], 'requirements': ['Strong knowledge of SQL and Excel reporting.']})
        self.assertEqual(len(plain['point_groups']), 1)                     # no heading anywhere: one unbroken list

    def test_bold_opening_phrase_keeps_the_text(self):
        cases = {'Strong knowledge of Internet advertising: CPA, CPM, CPC, search marketing.': 'Strong knowledge of Internet advertising:',
                 'Preferred: bing Ads Certification.': 'Preferred:',
                 'Proficiency in MS Excel, Google Sheets, and Microsoft Office.': 'Proficiency in MS Excel',
                 'Build trust quickly with engineers, architects, and executives.': 'Build trust quickly',
                 'A Bachelor’s or Master’s degree in Computer Science, Artificial Intelligence, Mathematics.': 'A Bachelor’s or Master’s degree',
                 'A proven, demonstrable track record of successfully architecting ML systems.': 'A proven, demonstrable track record',
                 'Strong SQL.': 'Strong SQL.'}
        for text, lead in cases.items():
            got, rest = S.point_parts(text)
            self.assertEqual(got, lead, text)
            self.assertEqual(got + rest, text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
