"""Unit tests of the filter values worked out from job text (models/job_facets.py): no Odoo, no network.

    python tests\\facets_test.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'odoo_addons', 'llmd_job_aggregator', 'models'))
import job_facets as F  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')


class JobTypeTests(unittest.TestCase):
    def test_values(self):
        for text, want in (('Full Time', 'fulltime'), ('full_time permanent', 'fulltime'), ('Full Time Contract', 'contract'), ('Part Time', 'parttime'), ('part-time', 'parttime'),
                           ('Contractor', 'contract'), ('Contract', 'contract'), ('Freelance', 'contract'), ('Internship', 'internship'), ('Intern', 'internship'), ('', ''), ('Other', '')):
            self.assertEqual(F.job_type(text), want, text)

    def test_title_is_used_when_the_field_is_empty(self):
        self.assertEqual(F.job_type('', 'Marketing Intern'), 'internship')
        self.assertEqual(F.job_type('', 'Data Analyst (Contract)'), 'contract')
        self.assertEqual(F.job_type('', 'Python Developer'), '')


class ExperienceTests(unittest.TestCase):
    def test_title_words(self):
        for title, want in (('Marketing Intern', 'internship'), ('Graduate Trainee - Sales', 'internship'), ('Senior Python Developer', 'senior'), ('Sr. Data Analyst', 'senior'),
                            ('Lead Data Scientist', 'senior'), ('Head of Growth', 'senior'), ('Junior SEO Specialist', 'entry'), ('Associate Account Executive', 'entry'),
                            ('Associate Director, Sales', 'senior'), ('Sales Manager', 'mid'), ('Account Executive', ''), ('Fresher - Business Development', 'fresher')):
            self.assertEqual(F.exp_level(title), want, title)

    def test_source_seniority_field(self):
        for field, want in (('Entry-level', 'entry'), ('Mid-level', 'mid'), ('Senior', 'senior'), ('Mid-level, Senior', 'mid'), ('Manager', 'senior'), ('Fresher', 'fresher'), ('', '')):
            self.assertEqual(F.exp_level('Data Scientist', field), want, field)

    def test_years_of_experience_in_the_text(self):
        for text, want in (('We need 0 years of experience, freshers welcome.', 'fresher'), ('Experience: 1-2 years in sales.', 'entry'), ('Minimum 3 years of experience in marketing.', 'mid'),
                           ('At least 5+ years experience with Python.', 'mid'), ('8+ years of relevant experience required.', 'senior'), ('We have been in business for 10 years.', '')):
            self.assertEqual(F.exp_level('Data Scientist', '', text), want, text)
        self.assertEqual(F.years_asked('Experience: 3-5 years. Nice to have: 8 years of cloud experience'), 3)

    def test_nothing_is_invented(self):
        self.assertEqual(F.exp_level('Data Scientist', '', 'Join our team and build great models.'), '')


class WorkModeTests(unittest.TestCase):
    def test_location_words(self):
        for loc, want in (('Remote · India', 'remote'), ('Remote · Worldwide', 'remote'), ('Worldwide', 'remote'), ('Hybrid - Bengaluru', 'hybrid'), ('Bengaluru, Karnataka', 'onsite'),
                          ('Gurugram, Haryana, India', 'onsite'), ('', '')):
            self.assertEqual(F.work_mode(loc), want, loc)

    def test_title_and_text(self):
        self.assertEqual(F.work_mode('Pune', 'Python Developer (Remote)'), 'remote')
        self.assertEqual(F.work_mode('Pune', 'Python Developer', 'This is a fully remote position.'), 'remote')
        self.assertEqual(F.work_mode('Pune', 'Python Developer', 'Hybrid work model: three days in the office.'), 'hybrid')
        self.assertEqual(F.work_mode('Pune', 'Cloud Engineer', 'Experience with hybrid cloud platforms.'), 'onsite')
        self.assertEqual(F.work_mode('Pune', 'Sales Manager', 'You will visit customers; we may offer remote days.'), 'onsite')

    def test_short_snippets_of_the_job_apis(self):
        for snippet, want in (('Work from home opportunity for sales executives.', 'remote'), ('This role is remote across India.', 'remote'), ('Remote-friendly team, apply now.', 'remote'),
                              ('Location: Pune. Hybrid basis, 3 days office.', 'hybrid'), ('The position is hybrid with flexible days.', 'hybrid'), ('Work 3 days in the office and 2 days remote days per week.', 'hybrid'),
                              ('Manage key accounts in Pune and visit customers.', 'onsite'), ('Our remote teams use Slack.', 'onsite')):
            self.assertEqual(F.work_mode('Pune, Maharashtra', 'Account Executive', snippet), want, snippet)


class IndiaTests(unittest.TestCase):
    def test_india(self):
        for loc, countries, want in (('Gurugram, Haryana', 'IN', True), ('Bengaluru', 'India', True), ('Pune, Maharashtra', '', True), ('Remote · India + 12 more countries', 'India, USA', True),
                                     ('Hyderabad, Telangana, India', '', True), ('Remote · Worldwide', 'Worldwide', False), ('London, UK', 'GB', False), ('Remote · United States', 'United States', False),
                                     ('Indianapolis, Indiana', 'US', False), ('', 'IN', True)):
            self.assertEqual(F.is_india(loc, countries), want, (loc, countries))

    def test_city(self):
        for loc, want in (('Bangalore, Karnataka', 'Bengaluru'), ('Gurgaon, Haryana', 'Gurugram'), ('New Delhi', 'Delhi'), ('Greater Pune Area', 'Pune'), ('Pune, Maharashtra', 'Pune'),
                          ('Bengaluru, Karnataka, India', 'Bengaluru'), ('Remote · India', ''), ('London, UK', ''), ('', '')):
            self.assertEqual(F.city_of(loc), want, loc)


class CombinedTests(unittest.TestCase):
    def test_one_call(self):
        got = F.facets('Junior Python Developer', 'Remote · Bengaluru', 'IN', 'Full Time', '', 'Experience: 1-2 years')
        self.assertEqual(got, {'exp_level': 'entry', 'job_type': 'fulltime', 'work_mode': 'remote', 'india': True, 'city': 'Bengaluru'})


class SalaryTests(unittest.TestCase):
    """The Salary Range filter: a stated salary in lakhs per year. The texts are real ones from the local database."""

    def test_rupee_salaries_in_lpa(self):
        cases = {'Rs 15 - 25 lakhs p.a.': (15.0, 25.0), 'INR 480,000 – 600,000 per year': (4.8, 6.0), 'INR 1,068,800 – 1,496,300 per year': (10.69, 14.96),
                 'Rs 35000 - Rs 40000 per month': (4.2, 4.8), 'INR 4,408,400 per year': (44.08, 44.08), '₹50k per month': (6.0, 6.0), 'Rs 7 - 10 LPA': (7.0, 10.0)}
        for text, want in cases.items():
            self.assertEqual(F.salary_lpa(text), want, text)

    def test_nothing_is_guessed(self):
        for text in ('$ 12000 p.a.', 'USD 180,000 – 250,000 per year', 'EUR 40,000 – 60,000 per year', 'Competitive salary', '', None, 'Rs 500 per hour'):
            self.assertEqual(F.salary_lpa(text), (0.0, 0.0), text)

    def test_ranges_overlap(self):
        self.assertEqual(F.salary_ranges_of(4.8, 6.0), ['3-6', '6-10'])
        self.assertEqual(F.salary_ranges_of(2.0, 2.0), ['0-3'])
        self.assertEqual(F.salary_ranges_of(15.0, 25.0), ['10+'])
        self.assertEqual(F.salary_ranges_of(0.0, 0.0), [])
        self.assertEqual([k for k, label, lo, hi in F.SALARY_RANGES], ['0-3', '3-6', '6-10', '10+'])

    def test_filter_options(self):
        self.assertEqual([label for k, label in F.JOB_TYPES], ['Full-time', 'Part-time', 'Internship', 'Contract'])
        self.assertEqual([label for k, label in F.EXP_FILTER], ['Fresher', 'Internship', 'Entry-level', 'Mid-level', 'Senior'])


class RegionTests(unittest.TestCase):
    """"Explore jobs by region": a job is in a region only when its location says so (real locations of the database, 2026-10-25)."""

    def place(self, location, india, mode='onsite'):
        country = F.country_of(location, india)
        return F.region_of(country, location, mode), F.india_zone_of(location, F.city_of(location), country)

    def test_regions_of_india_from_city_state_or_state_code(self):
        cases = {('Bengaluru, Karnataka, India', True): ('india-south-asia', 'south-india'), ('Sanand, GJ, India', True): ('india-south-asia', 'west-india'),
                 ('Kurukshetra, HR, India', True): ('india-south-asia', 'north-india'), ('Agartala, TR, India', True): ('india-south-asia', 'east-central-india'),
                 ('telangana, India', True): ('india-south-asia', 'south-india'), ('Remote - Tamil Nadu, India', True): ('india-south-asia', 'south-india'),
                 ('Gurugram, Haryana', True): ('india-south-asia', 'north-india'), ('Pune, Maharashtra', True): ('india-south-asia', 'west-india')}
        for (location, india), want in cases.items():
            self.assertEqual(self.place(location, india), want, location)

    def test_a_job_that_only_says_india_is_in_no_region_of_india(self):
        for location in ('India', 'Remote · India', 'Remote - India', 'India (Remote)'):
            self.assertEqual(self.place(location, True, 'remote'), ('india-south-asia', ''), location)

    def test_world_regions_and_nothing_guessed(self):
        self.assertEqual(self.place('London, UK', False), ('europe', ''))
        self.assertEqual(self.place('Remote - United States', False, 'remote'), ('north-america', ''))
        self.assertEqual(self.place('Dubai', False), ('middle-east-africa', ''))
        self.assertEqual(self.place('Remote · Worldwide', False, 'remote'), ('worldwide', ''))
        self.assertEqual(self.place('Remote', False, 'remote'), ('', ''))                  # no country: no region
        self.assertEqual(self.place('Worldwide', False, 'onsite'), ('', ''))              # "anywhere" only counts for a remote job
        self.assertEqual(self.place('Sometown', False), ('', ''))

    def test_countries_and_cities_of_the_world(self):
        cases = {'San Francisco, CA': ('United States', 'San Francisco', 'north-america'), 'Remote - US': ('United States', '', 'north-america'),
                 'Toronto, ON': ('Canada', 'Toronto', 'north-america'), 'Sydney NSW': ('Australia', 'Sydney', 'asia-pacific'), 'Renningen, Germany': ('Germany', '', 'europe'),
                 'Sao Paulo, Brazil': ('Brazil', 'Sao Paulo', 'latin-america'), 'Tel Aviv-Yafo, Israel': ('Israel', 'Tel Aviv', 'middle-east-africa'),
                 'NYC': ('United States', 'New York', 'north-america'), 'Hong Kong': ('Hong Kong', '', 'china'), 'Shanghai': ('China', 'Shanghai', 'china'), 'Taipei': ('Taiwan', 'Taipei', 'asia-pacific')}
        for location, (country, city, region) in cases.items():
            c = F.country_of(location, F.is_india(location))
            self.assertEqual((c, F.world_city_of(location), F.region_of(c, location, 'onsite')), (country, city, region), location)
        self.assertFalse(F.is_india('London, UK') or F.is_india('Indianapolis, IN'))           # a world city never makes a job Indian
        self.assertEqual(F.facets('X', 'London, UK', '', '', '', '')['city'], 'London')
        self.assertEqual(F.facets('X', 'Pune, India', '', '', '', '')['city'], 'Pune')

    def test_a_region_named_without_a_country(self):
        self.assertEqual(F.region_of('', 'Remote - Europe', 'remote'), 'europe')
        self.assertEqual(F.region_of('', 'APAC', 'remote'), 'asia-pacific')
        self.assertEqual(F.region_of('', 'Remote - EMEA', 'remote'), '')                 # Europe, Middle East AND Africa: no one region
        self.assertEqual(F.COUNTRY_OF_CODE['de'], 'Germany')                              # the ISO codes SmartRecruiters sends

    def test_every_region_has_a_name_and_every_country_one_region(self):
        slugs = [s for s, _n, _t, _i in F.REGIONS + F.INDIA_ZONES]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertTrue(set(F.COUNTRY_REGION.values()) <= {s for s, _n, _t, _i in F.REGIONS})
        self.assertTrue(all(c in F._COUNTRIES for c in F.COUNTRY_REGION))


if __name__ == '__main__':
    unittest.main(verbosity=2)
