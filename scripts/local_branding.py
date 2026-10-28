"""LOCAL ONLY - the LLM Decode branding of the local test website (it starts as Odoo's demo "My Website"): the name "LLM Decode" as the header brand,
the menu Home / Courses / Jobs Explorer / Resources / Contact us, and a footer with the same navigation. Run it in the odoo shell of the LOCAL database:

    cat scripts/local_branding.py | docker compose --env-file .env -f docker/docker-compose.yml exec -T -e DBN=llmd_local odoo \
        sh -c 'odoo shell -d "$DBN" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'

The live site (learn.llmdecode.com) already has its own logo, menu (Home, Courses, SOP Library, Forum, Contact us) and footer: never run this there.
Courses and Resources point to the public pages of learn.llmdecode.com, because the local database has no eLearning module. Running it twice changes nothing more."""

LEARN = 'https://learn.llmdecode.com'
assert env.cr.dbname == 'llmd_local', 'local_branding.py is for the local test database only'          # noqa: F821 (env is the odoo shell's)

website = env['website'].sudo().get_current_website()                                                     # noqa: F821
website.name = 'LLM Decode'

# the header shows the site name (text) instead of the demo "Your Logo" image
View = env['ir.ui.view'].sudo().with_context(active_test=False, website_id=website.id)                   # noqa: F821
for key, active in (('website.option_header_brand_logo', False), ('website.option_header_brand_name', True)):
    view = View.search([('key', '=', key)], limit=1)
    if view and view.active != active:
        view.write({'active': active})                                                                    # copy-on-write: only this website changes
brand = View.search([('key', '=', 'website.option_header_brand_name'), ('website_id', '=', website.id)], limit=1)
if brand:                                                                                                 # the demo text "My Website" -> LLM Decode
    brand.write({'arch_db': brand.arch_db.replace('>My Website</a>', '><span>LLM Decode</span></a>')})

# the menu: Home, Courses, Jobs Explorer (the job board, /jobs), Resources, Contact us
Menu = env['website.menu'].sudo()                                                                         # noqa: F821
top = website.menu_id
want = [('Home', '/', 10), ('Courses', LEARN + '/slides', 20), ('Jobs Explorer', '/jobs', 30), ('Resources', LEARN + '/library', 40), ('Contact us', '/contactus', 60)]
for name, url, seq in want:
    menu = Menu.search([('parent_id', '=', top.id), ('url', '=', url)], limit=1)
    if not menu and url == '/jobs':
        menu = Menu.search([('parent_id', '=', top.id), ('name', '=', 'Jobs')], limit=1)
    vals = {'name': name, 'url': url, 'sequence': seq, 'parent_id': top.id, 'website_id': website.id, 'new_window': url.startswith('http')}
    if menu:
        menu.write(vals)
    else:
        Menu.create(vals)

# the footer: what LLM Decode is, and the same navigation
FOOTER = """<data inherit_id="website.layout" name="Default" active="True">
    <xpath expr="//div[@id='footer']" position="replace">
        <div id="footer" class="oe_structure oe_structure_solo text-break" t-ignore="true" t-if="not no_footer">
            <section class="s_text_block pt48 pb24" data-snippet="s_text_block" data-name="Container">
                <div class="container">
                    <div class="row">
                        <div class="col-lg-5 pb24">
                            <h5>LLM Decode</h5>
                            <p>Practical AI courses for builders and sellers - and Jobs Explorer: real openings, straight from the companies' own job pages, matched to what each course teaches.</p>
                        </div>
                        <div class="col-6 col-lg-2 pb24">
                            <h5>Jobs Explorer</h5>
                            <ul class="list-unstyled">
                                <li><a href="/jobs">Jobs Explorer</a></li>
                                <li><a href="/jobs?view=all">Search all jobs</a></li>
                                <li><a href="/jobs/categories">Categories</a></li>
                                <li><a href="/jobs/countries">Countries</a></li>
                                <li><a href="/jobs/regions">Regions</a></li>
                            </ul>
                        </div>
                        <div class="col-6 col-lg-2 pb24">
                            <h5>Learn</h5>
                            <ul class="list-unstyled">
                                <li><a href="%(learn)s/slides" target="_blank" rel="noopener">Courses</a></li>
                                <li><a href="%(learn)s/library" target="_blank" rel="noopener">Resources</a></li>
                                <li><a href="%(learn)s/forum" target="_blank" rel="noopener">Forum</a></li>
                            </ul>
                        </div>
                        <div class="col-lg-3 pb24">
                            <h5>Help</h5>
                            <ul class="list-unstyled">
                                <li><a href="/jobs#faq">Jobs Explorer FAQ</a></li>
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

env.cr.commit()                                                                                           # noqa: F821
print('branding:', website.name, '| menu:', ', '.join(m.name for m in top.child_id.sorted('sequence')))
