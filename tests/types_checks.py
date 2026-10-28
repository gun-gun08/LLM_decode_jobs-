"""Run inside `odoo shell`: Posted Type, Application Type and Experience Required (v19.0.30) for the four flows - a fetched job, a job a public user posted,
an application sent through our website form, and a click on an external Apply Now. One transaction, rolled back at the end: nothing is stored.

  Get-Content tests\\types_checks.py | docker compose --env-file .env -f docker/docker-compose.yml exec -T -e DBN=$env:ODOO_DB odoo sh -c 'odoo shell -d "$DBN" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'
"""
RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, (' - ' + str(detail)) if detail else ''))


Listing, App, Applicant, Job, Click = env['llmd.job.listing'], env['llmd.job.application'], env['hr.applicant'], env['hr.job'], env['llmd.job.click']
PERSONAL = {'user_id', 'applicant_name', 'email', 'phone', 'logged_in', 'partner_phone'}


def listing(ext, text='<p>Own the pipeline for our enterprise customers in Pune.</p>', **kw):
    return Listing.create(dict({'source': 'Company job boards', 'ext_id': ext, 'title': 'Account Executive', 'company': 'Acme', 'location': 'Pune, Maharashtra',
                                'apply_url': 'https://careers.example.com/%s' % ext, 'description_html': text, 'employment_type': 'Full Time', 'categories': 'Sales'}, **kw))


print('\n=== 1. a FETCHED job (an external API / provider) ===')
years = listing('tc-years', '<p>We need 3-5 years of experience in B2B sales. Own the pipeline for our customers.</p>')
label = listing('tc-label', seniority='Mid-Senior Level')
none = listing('tc-none')
check('every job board listing is "Fetched" (it has a provider source)', (years.posted_type, label.posted_type, none.posted_type) == ('fetched',) * 3,
      (years.posted_type, label.posted_type, none.posted_type))
check('the stored board is all "Fetched" too', Listing.with_context(active_test=False).search_count([('posted_type', '!=', 'fetched')]) == 0)
check('Experience Required: the years the job text states ("3–5 yrs")', years.experience_required() == '3–5 yrs', years.experience_required())
check('... else the provider\'s own label, kept as it was sent ("Mid-Senior Level")', label.experience_required() == 'Mid-Senior Level', label.experience_required())
check('... and EMPTY when the job states none (nothing invented)', none.experience_required() == '', none.experience_required())

print('\n=== 2. a job posted by a PUBLIC USER ===')
portal = env['res.users'].with_context(no_reset_password=True).create({'name': 'TC Portal Poster', 'login': 'tc.portal.poster@example.com',
                                                                         'group_ids': [(6, 0, [env.ref('base.group_portal').id])]})
public_job = Job.with_user(portal).sudo().create({'name': 'TC Public Posted Role'})
staff_job = Job.create({'name': 'TC Staff Posted Role'})
check('a position created by a portal / public user is "Public User"', public_job.llmd_posted_type == 'public_user', (public_job.create_uid.login, public_job.llmd_posted_type))
check('a position our own team created stays EMPTY (it is neither fetched nor public)', not staff_job.llmd_posted_type, staff_job.llmd_posted_type)
public_job.sudo().write({'website_published': True})                        # the API takes published positions only
pub_app = App.process_api({'action': 'applicant', 'job': {'hr_job_id': public_job.id}, 'name': 'TC Api Person', 'email': 'tc.api@example.com'}, authorized=True)
pa = App.browse(pub_app.get('id'))
check('an application for it carries Posted Type "Public User"; sent by a provider, it is no Website Form', pub_app.get('ok') and pa.posted_type == 'public_user' and not pa.application_type,
      (pub_app, pa.posted_type, pa.application_type))

print('\n=== 3. an application sent through OUR WEBSITE FORM ===')
n_hr, n_rec = Applicant.search_count([]), App.search_count([])
rec, status = App.submit_own(years, {'name': 'TC Form Person', 'email': 'tc.form@example.com', 'note': '', 'consent': True}, '', '', b'', None)
check('one real application is saved (and one Recruitment applicant)', status == 'created' and App.search_count([]) == n_rec + 1 and Applicant.search_count([]) == n_hr + 1, status)
check('... Application Type "Website Form", Posted Type "Fetched"', (rec.application_type, rec.posted_type) == ('website_form', 'fetched'), (rec.application_type, rec.posted_type))
check('... Name and Email kept, no phone anywhere', (rec.applicant_name, rec.email) == ('TC Form Person', 'tc.form@example.com') and 'phone' not in App._fields and not rec.applicant_id.partner_phone)
check('... the job: Department, Job Type, Experience Required, Job Title, Company, Location, External Job ID, Original apply URL, Application Status, Application Date',
      (rec.department, rec.job_type, rec.experience_required, rec.job_title, rec.company, rec.location, rec.ext_id, rec.apply_url, rec.state)
      == ('Sales', 'Full-time', '3–5 yrs', 'Account Executive', 'Acme', 'Pune, Maharashtra', 'tc-years', 'https://careers.example.com/tc-years', 'submitted') and bool(rec.application_date),
      (rec.department, rec.job_type, rec.experience_required))
rec2, _s = App.submit_own(none, {'name': 'TC No Exp', 'email': 'tc.noexp@example.com', 'note': '', 'consent': True}, '', '', b'', None)
check('an application for a job that states no experience: Experience Required stays EMPTY', not rec2.experience_required, rec2.experience_required)
rec3, _s = App.submit_own(label, {'name': 'TC Label', 'email': 'tc.label@example.com', 'note': '', 'consent': True}, '', '', b'', None)
check('... and the provider\'s own label is kept as it was sent', rec3.experience_required == 'Mid-Senior Level', rec3.experience_required)

vals = Listing._prepare({'source': 'Company job boards', 'ext_id': 'tc-req-years2', 'title': 'Infrastructure Engineer', 'company': 'Acme', 'location': 'Bengaluru, India',
                         'apply_url': 'https://careers.example.com/tc-req-years2',
                         'html': '<p>We run the platform behind our product for customers in India and around Asia, with a small and friendly team.</p><h3>Requirements</h3><ul>'
                                 '<li>2–5 years in DevOps, SRE, infrastructure or backend engineering.</li><li>Scripting in Python, Go or Bash.</li></ul>'})
req2 = Listing.create({k: v for k, v in vals.items() if not k.startswith('_')})
check('years stated in a requirement line without the word "experience" ("2–5 years in DevOps ...") are kept as written', req2.experience_required() == '2–5 years',
      (req2.experience_required(), (req2.summary() or {}).get('experience_level')))
fresher = listing('tc-fresher', title='Data Analyst (Fresher)')
check('a title that says "Fresher" gives "Fresher" (and a plain title gives nothing)', fresher.experience_required() == 'Fresher' and none.experience_required() == '', fresher.experience_required())
r4, _s = App.submit_own(req2, {'name': 'TC Req Years', 'email': 'tc.reqyears@example.com', 'note': '', 'consent': True}, '', '', b'', None)
check('... and an application for that job saves it in Experience Required', r4.experience_required == '2–5 years', r4.experience_required)

print('\n=== 4. a click on an EXTERNAL Apply Now ===')
n_rec, n_hr = App.search_count([]), Applicant.search_count([])
click = Click.record_click(listing=years, visitor='visitor-tctctctctctctctc')
check('one click line: Application Type "External Apply Click", Posted Type "Fetched", the job details, status Clicked',
      (click.application_type, click.posted_type, click.job_title, click.ext_id, click.apply_url, click.status)
      == ('external_apply_click', 'fetched', 'Account Executive', 'tc-years', 'https://careers.example.com/tc-years', 'clicked') and bool(click.clicked_at),
      (click.application_type, click.posted_type))
check('... with NO personal data (no user, name, e-mail or phone field)', not (PERSONAL & set(Click._fields)))
check('... and it is NOT an application: Job Applications and Recruitment applicants unchanged', (App.search_count([]), Applicant.search_count([])) == (n_rec, n_hr))
check('no Job Applications record is ever an "External Apply Click"', App.with_context(active_test=False).search_count([('application_type', '=', 'external_apply_click')]) == 0)
nolink = Click.record_click(listing=listing('tc-nolink', apply_url=False), visitor='visitor-tcnolinktcnolink')
check('a click on a job without a valid link (nobody was sent anywhere) is no External Apply Click', nolink.status == 'no_link' and not nolink.application_type, nolink.application_type)

print('\n=== 5. the screens ===')
import re
lst = App.get_views([(False, 'list')])['views']['list']['arch']
shown = [f for f, attrs in re.findall(r'<field name="(\w+)"([^>]*)/?>', lst) if 'optional="hide"' not in attrs]
check('Job Applications list: Name, Email, Job Title, Company, Department, Job Type, Experience Required, External Job ID, Application Type, Posted Type, Status, Date',
      all(f in shown for f in ('applicant_name', 'email', 'job_title', 'company', 'department', 'job_type', 'experience_required', 'ext_id', 'application_type', 'posted_type', 'state', 'application_date'))
      and 'phone' not in lst, shown)
clk = Click.get_views([(False, 'list'), (False, 'form')])['views']
check('Apply Clicks list and form: Application Type and Posted Type, and still no name, e-mail or phone',
      all('name="%s"' % f in clk[k]['arch'] for f in ('application_type', 'posted_type') for k in ('list', 'form'))
      and not any('name="%s"' % f in clk[k]['arch'] for f in ('applicant_name', 'email', 'phone', 'user_id') for k in ('list', 'form')))

print('\n=== 6. the job\'s skills in Odoo\'s skill system (job listings only) ===')
Skill, Type = env['hr.skill'], env['hr.skill.type']
lang_t, soft_t = env.ref('hr_skills.hr_skill_type_lang'), env.ref('hr_skills.hr_skill_type_softskill')
n_lang, n_soft, n_app_sk = len(lang_t.skill_ids), len(soft_t.skill_ids), env['hr.applicant.skill'].search_count([])
def synced(ext, html):
    """A job saved the way the sync saves it (_prepare: its sections, summary and skills are worked out from its text)."""
    vals = Listing._prepare({'source': 'Company job boards', 'ext_id': ext, 'title': 'Backend Engineer', 'company': 'Acme', 'location': 'Pune, India', 'html': html,
                             'apply_url': 'https://careers.example.com/%s' % ext, 'employment_type': 'Full Time', 'categories': 'Engineering'})
    return Listing.create({k: v for k, v in vals.items() if not k.startswith('_')})


sk = synced('tc-skills', '<p>We are hiring a Backend Engineer to build and run the services behind our product for customers across India and Asia.</p><h3>Requirements</h3><ul>'
                         '<li>3+ years of backend development with Python and Django.</li><li>Experience with Kubernetes and Docker in production.</li>'
                         '<li>Excellent communication and problem-solving skills.</li><li>Fluent Mandarin is required.</li><li>Cantonese is a plus.</li>'
                         '<li>Stakeholder management and negotiation with partner teams.</li></ul>')
sk.link_odoo_skills()
tech_t = Type.search([('name', '=', 'Technical Skills')])
check('technical skills the text mentions go to "Technical Skills"', {'Python', 'Django', 'Kubernetes'} <= set(sk.technical_skill_ids.mapped('name'))
      and all(s.skill_type_id == tech_t for s in sk.technical_skill_ids), sk.technical_skill_ids.mapped('name'))
check('... Odoo\'s own Soft Skills are matched by name ("problem-solving" = "Problem-Solving"), none created', set(sk.soft_skill_ids.mapped('name')) == {'Communication', 'Problem-Solving'}
      and len(soft_t.skill_ids) == n_soft, sk.soft_skill_ids.mapped('name'))
check('... Odoo\'s own Languages are matched ("Mandarin" = "Mandarin Chinese"); a language Odoo does not list (Cantonese) is not invented', sk.language_skill_ids.mapped('name') == ['Mandarin Chinese']
      and len(lang_t.skill_ids) == n_lang and not Skill.search_count([('name', 'ilike', 'Cantonese')]), sk.language_skill_ids.mapped('name'))
check('... business skills (stakeholder management, negotiation) stay on the website only - no "Technical" or made-up skill for them',
      not (set(s.name.lower() for s in sk.skill_ids) & {'stakeholder management', 'negotiation'}) and 'stakeholder management' in (sk.skill_keys or ''))
n_skills = Skill.search_count([])
twin = synced('tc-skills-2', '<p>We are hiring a Platform Engineer for our product teams in Pune and around Asia, on call with the rest of the team.</p><h3>Requirements</h3>'
                             '<ul><li>Build services in Python and Django every day.</li><li>Run them on Kubernetes in production.</li></ul>')
twin.link_odoo_skills()
sk.link_odoo_skills()
shared = {s.name: s.id for s in sk.technical_skill_ids}
check('a second job with the same skills reuses them: no duplicate skill is created, the same names are the same Odoo skills, linking again changes nothing',
      Skill.search_count([]) == n_skills and {'Python', 'Django', 'Kubernetes'} <= set(twin.technical_skill_ids.mapped('name'))
      and all(shared[s.name] == s.id for s in twin.technical_skill_ids if s.name in shared) and sk.link_odoo_skills() == 0,
      (n_skills, Skill.search_count([]), twin.technical_skill_ids.mapped('name')))
check('... applicants get no skills from jobs (a job\'s needs are not a person\'s skills)', env['hr.applicant.skill'].search_count([]) == n_app_sk)
plain = listing('tc-skills-none', '<p>Welcome guests at the front desk.</p>')
plain.link_odoo_skills()
check('a job whose text names no known skill gets none (nothing assumed from its title)', not plain.skill_ids)

root = env.ref('hr_recruitment.menu_hr_recruitment_root')
menus = env['ir.ui.menu'].search([('id', 'child_of', root.id)]).mapped('complete_name')
check('the Recruitment menu has Job Applications and Apply Clicks, and no "All Applications" any more (its action and the applicants stay)',
      'Recruitment/Job Applications' in menus and 'Recruitment/Apply Clicks' in menus and not any(m.endswith('/All Applications') for m in menus)
      and bool(env.ref('hr_recruitment.crm_case_categ0_act_job', raise_if_not_found=False)), [m for m in menus if 'Application' in m])

print('\nSHELL RESULT: %d/%d checks passed' % (sum(RESULTS), len(RESULTS)))
env.cr.rollback()
