"""Run inside `odoo shell` of a SCRATCH database that has eLearning (website_slides) and llmd_job_aggregator installed - NOT of the real local database (it has no eLearning):
the Jobs page reads its courses from the eLearning course data of the site (published courses of type "training"). Everything runs in one transaction that is rolled back.

  docker compose --env-file .env -f docker/docker-compose.yml run --rm odoo odoo -d llmd_courses_test --db-filter='^llmd_courses_test$' -i website_slides,llmd_job_aggregator --without-demo=all --stop-after-init
  Get-Content tests\\course_checks.py | docker compose --env-file .env -f docker/docker-compose.yml exec -T odoo sh -c 'odoo shell -d llmd_courses_test --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'
  (then drop the scratch database again: docker compose --env-file .env -f docker/docker-compose.yml exec db psql -U <user> -d postgres -c 'DROP DATABASE llmd_courses_test')
"""
from odoo.addons.llmd_job_aggregator.controllers.main import JobBoard
from odoo.addons.llmd_job_aggregator.models import board_config as C

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, (' - ' + str(detail)) if detail else ''))


Channel, Listing, Catalog = env['slide.channel'], env['llmd.job.listing'], env['llmd.course.catalog']
print('\n=== P. the course list is read from the eLearning course data ===')
check('this scratch database has eLearning (so the catalog must NOT use the built-in fallback list)', Catalog.has_course_data() and Catalog.courses() == [], Catalog.courses())
live = [('How to sell complex products with AI', 'training', True), ('2 DAY GEN AI ENGINEERING MASTERMIND', 'training', True), ('A–Z Claude Masterclass', 'training', True),
        ('From Leads to Sales: Funnel Building 101', 'training', True), ('SOP Library', 'documentation', True), ('Unpublished draft course', 'training', False), ('Advanced Kubernetes Operations', 'training', True)]
made = [Channel.create({'name': n, 'channel_type': t, 'is_published': p, 'sequence': i}) for i, (n, t, p) in enumerate(live)]
courses = Catalog.courses()
names = [c['name'] for c in courses]
check('the published training courses are offered, in the order of the course list - documentation channels and unpublished courses are not',
      names == ['How to sell complex products with AI', '2 DAY GEN AI ENGINEERING MASTERMIND', 'A–Z Claude Masterclass', 'From Leads to Sales: Funnel Building 101', 'Advanced Kubernetes Operations'], names)
check('every course is marked as read from the course data (not from the built-in list)', all(c['dynamic'] for c in courses))
prof = {c['name']: c['profiles'] for c in courses}
check('the job profile of each course follows its own text: sell, GenAI, Claude, funnel (the funnel course does not get the sales profile)',
      prof['How to sell complex products with AI'] == ['sell-ai'] and prof['2 DAY GEN AI ENGINEERING MASTERMIND'] == ['genai-mastermind'] and prof['A–Z Claude Masterclass'] == ['claude-masterclass']
      and prof['From Leads to Sales: Funnel Building 101'] == ['funnel-101'], prof)
new = [c for c in courses if c['name'] == 'Advanced Kubernetes Operations'][0]
check('a new course that fits no profile is still offered, with search words from its name instead of roles', new['profiles'] == [] and new['words'][:2] == ['advanced', 'kubernetes'], new)
sell = courses[0]
check('an older link (?course=sell-ai) leads to the course with that profile; an unknown code leads nowhere', Catalog.resolve('sell-ai', courses) == sell and Catalog.resolve(sell['code'], courses) == sell
      and Catalog.resolve('c999999', courses) is None and Catalog.resolve('', courses) is None)
check('the roles of a course come from its profile (sales roles for the sell course, none for the new course)', {c for c, _l in C.roles_for_profiles(sell['profiles'])} >= {'sales_manager', 'account_executive'}
      and C.roles_for_profiles(new['profiles']) == [])

print('\n=== Q. the jobs of a course ===')
def job(ext, title, roles, courses_, text='<p>x</p>'):
    return Listing.create({'source': 'test', 'ext_id': ext, 'title': title, 'company': 'Q Co', 'location': 'Pune', 'roles': roles, 'courses': courses_, 'tags': ',sales,', 'search_text': title, 'apply_url': 'https://example.com/' + ext,
                           'description_html': text})
j_sell = job('q1', 'Q Sales Manager', ',sales_manager,', ',sell-ai,')
j_ai = job('q2', 'Q AI Engineer', ',ai_engineer,', ',genai-mastermind,claude-masterclass,')
j_k8s = job('q3', 'Q Kubernetes Platform Engineer', '', '')
state = {'q': 'Q ', 'course': '', 'role': '', 'track': '', 'loc': 'all', 'exp': [], 'jtype': [], 'mode': ''}
domain = lambda course, **kw: JobBoard._llmd_domain(dict(state, **kw), course)
search = lambda d: Listing.search(d)
check('the sell course shows the sales job only', search(domain(courses[0])) == j_sell)
check('the GenAI course and the Claude course both show the AI engineer job', search(domain(courses[1])) == j_ai and search(domain(courses[2])) == j_ai)
check('the new course (no profile) finds jobs that name its topic', search(domain(new)) == j_k8s)
check('a role only narrows inside its course', search(domain(courses[0], role='sales_manager')) == j_sell and not search(domain(courses[0], role='ai_engineer')))
check('without a course nothing is filtered by course', search(domain(None)) == j_sell | j_ai | j_k8s)

print('\n=== R. the list follows the course data ===')
made[0].write({'name': 'How to sell complex products with AI (2nd edition)'})
made[3].write({'is_published': False})
names = [c['name'] for c in Catalog.courses()]
check('renaming a course changes the dropdown and unpublishing removes it - nothing is typed in anywhere', 'How to sell complex products with AI (2nd edition)' in names and 'From Leads to Sales: Funnel Building 101' not in names, names)
check('the renamed sell course still gets its profile (the name still says "sell")', Catalog.courses()[0]['profiles'] == ['sell-ai'])

print('\nSHELL RESULT: %d/%d checks passed' % (sum(RESULTS), len(RESULTS)))
env.cr.rollback()
