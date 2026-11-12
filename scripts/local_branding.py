"""LOCAL ONLY - the LLM Decode branding of the local test website (it starts as Odoo's demo "My Website"): the LLM Decode logo as the header brand (scripts/assets/llm_decode_logo.webp),
the menu Home / Courses / Jobs Explorer (no Resources / Contact us in the header), and a footer. Copy the logo into the container first, then run it
in the odoo shell of the LOCAL database:

    docker cp scripts/assets llmd-local-odoo-1:/tmp/assets
    cat scripts/local_branding.py | docker compose --env-file .env -f docker/docker-compose.yml exec -T -e DBN=llmd_local odoo \
        sh -c 'odoo shell -d "$DBN" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'

The live site (learn.llmdecode.com) already has its own logo, menu (Home, Courses, SOP Library, Forum, Contact us) and footer: never run this there.
Courses and Resources point to the public pages of learn.llmdecode.com, because the local database has no eLearning module. Running it twice changes nothing more."""

LEARN = 'https://learn.llmdecode.com'
assert env.cr.dbname == 'llmd_local', 'local_branding.py is for the local test database only'          # noqa: F821 (env is the odoo shell's)

website = env['website'].sudo().get_current_website()                                                     # noqa: F821
website.name = 'LLM Decode'

# the header shows the LLM Decode logo (the same image as jobs.llmdecode.ai / learn.llmdecode.com, scripts/assets/llm_decode_logo.webp)
# instead of the demo "Your Logo" or the site name as text: first the name option off, then the logo option on (both change the same brand spot)
import base64, os                                                                                         # noqa: E402
LOGO = os.path.join(os.environ.get('LLMD_SCRIPTS', '/tmp'), 'assets', 'llm_decode_logo.webp')
if os.path.exists(LOGO):
    with open(LOGO, 'rb') as fh:
        website.logo = base64.b64encode(fh.read())
else:
    print('branding: logo file not found at %s - copy scripts/assets into the container (see the docstring); the logo stays as it is' % LOGO)
View = env['ir.ui.view'].sudo().with_context(active_test=False, website_id=website.id)                   # noqa: F821
for key, active in (('website.option_header_brand_name', False), ('website.option_header_brand_logo', True)):
    for view in View.search([('key', '=', key)]):
        if view.website_id.id in (website.id, False) and view.active != active:
            view.with_context(website_id=website.id).write({'active': active})                          # copy-on-write: only this website changes

# the menu: Home, Courses, Jobs Explorer (the job board, /jobs) - Resources and Contact us are not in the header
Menu = env['website.menu'].sudo()                                                                         # noqa: F821
top = website.menu_id
want = [('Home', '/', 10), ('Courses', LEARN + '/slides', 20), ('Jobs Explorer', '/jobs', 30)]      # no Resources / Contact us in the header (as asked)
for name, url, seq in want:
    menu = Menu.search([('parent_id', '=', top.id), ('url', '=', url)], limit=1)
    if not menu and url == '/jobs':
        menu = Menu.search([('parent_id', '=', top.id), ('name', '=', 'Jobs')], limit=1)
    vals = {'name': name, 'url': url, 'sequence': seq, 'parent_id': top.id, 'website_id': website.id, 'new_window': url.startswith('http')}
    if menu:
        menu.write(vals)
    else:
        Menu.create(vals)

# the footer: what LLM Decode is, and the same navigation - the original four Bootstrap columns side by side (4 on a desktop, 2 per row on a tablet, stacked on a phone);
# the layout needs only Bootstrap, llmd_jobs.css ("the footer") only tunes the spacing
FOOTER = """<data inherit_id="website.layout" name="Default" active="True">
    <xpath expr="//div[@id='footer']" position="replace">
        <div id="footer" class="oe_structure oe_structure_solo text-break" t-ignore="true" t-if="not no_footer">
            <section class="s_text_block o_llmd_footer" data-snippet="s_text_block" data-name="Container">
                <div class="container">
                    <div class="row g-4">
                        <div class="col-12 col-md-6 col-lg-4">
                            <h5>LLM Decode</h5>
                            <p class="o_llmd_footer_text">Practical AI courses for builders and sellers - and Jobs Explorer: real openings, straight from the companies' own job pages, matched to what each course teaches.</p>
                        </div>
                        <div class="col-12 col-md-6 col-lg-3">
                            <h5>Jobs Explorer</h5>
                            <ul class="list-unstyled o_llmd_footer_links">
                                <li><a href="/jobs">Jobs Explorer</a></li>
                                <li><a href="/jobs/all">All jobs</a></li>
                                <li><a href="/companies">Companies</a></li>
                                <li><a href="/categories">Industries</a></li>
                                <li><a href="/locations">Locations</a></li>
                                <li><a href="/regions">Regions</a></li>
                            </ul>
                        </div>
                        <div class="col-12 col-md-6 col-lg-2">
                            <h5>Learn</h5>
                            <ul class="list-unstyled o_llmd_footer_links">
                                <li><a href="%(learn)s/slides" target="_blank" rel="noopener">Courses</a></li>
                                <li><a href="%(learn)s/library" target="_blank" rel="noopener">Resources</a></li>
                                <li><a href="%(learn)s/forum" target="_blank" rel="noopener">Forum</a></li>
                            </ul>
                        </div>
                        <div class="col-12 col-md-6 col-lg-3">
                            <h5>Help</h5>
                            <ul class="list-unstyled o_llmd_footer_links">
                                <li><a href="/jobs/faq">Jobs Explorer FAQ</a></li>
                                <li><a href="/contactus">Contact us</a></li>
                            </ul>
                        </div>
                    </div>
                </div>
            </section>
        </div>
    </xpath>
</data>""" % {'learn': LEARN}
footer = View.search([('key', '=', 'website.footer_custom')], limit=1)
if footer:
    footer.write({'arch_db': FOOTER})                                                                    # copy-on-write: a copy for this website

# the copyright line: the site's name instead of the demo "Company name"
copyright_view = View.search([('key', '=', 'website.footer_copyright_company_name')], limit=1)
if copyright_view and 'Company name' in (copyright_view.arch_db or ''):
    copyright_view.write({'arch_db': copyright_view.arch_db.replace('Copyright &amp;copy; Company name', 'Copyright &amp;copy; LLM Decode')})   # copy-on-write: this website only

env.cr.commit()                                                                                           # noqa: F821
print('branding:', website.name, '| menu:', ', '.join(m.name for m in top.child_id.sorted('sequence')))
