"""NOT APPLIED. The "sign in before Apply Now" feature (built 2026-10-23 as v19.0.15, taken out again the same day at the user's request until it is approved).
Apply it from the project folder with:  python rolelib/sign_in_feature_patch.py   then upgrade the module (-u llmd_job_aggregator) and restart Odoo.
It makes Apply Now open Odoo's sign-in page first; afterwards the click line keeps the name, e-mail and phone of the signed-in account and Job Applications gets one record
"Sent to employer" per student (portal account) and job. Switch: system parameter llmd_agg.apply_login (0 = off). The tests for it are not included here.
"""
import ast
import io

base = 'local_odoo/addons/llmd_job_aggregator/'


def edit(path, pairs):
    s = io.open(base + path, encoding='utf-8').read()
    for old, new in pairs:
        assert old in s, (path, old[:100])
        s = s.replace(old, new, 1)
    if path.endswith('.py'):
        ast.parse(s)
    io.open(base + path, 'w', encoding='utf-8', newline='').write(s)
    print('updated', path)


edit('__manifest__.py', [("'version': '19.0.16.0.0',", "'version': '19.0.17.0.0',")])

edit('models/board_config.py', [
    ("BOARD_LINK_SOURCES = ('adzuna', 'jooble', 'himalayas')\n",
     "BOARD_LINK_SOURCES = ('adzuna', 'jooble', 'himalayas')\n"
     "# Sign in before Apply Now (default): the visitor signs in once with their own account, then goes straight to the employer; the click is saved with the name, e-mail\n"
     "# and phone of THAT account (no second form). System parameter llmd_agg.apply_login = 0 = anonymous clicks as before.\n"
     "APPLY_LOGIN = True\n"),
])

edit('models/listing.py', [
    ('''def direct_links_only(env):
    """True while only direct links are used (default): system parameter llmd_agg.direct_links_only = 0 / 1, else board_config.DIRECT_LINKS_ONLY."""
    value = (env['ir.config_parameter'].sudo().get_param('llmd_agg.direct_links_only') or '').strip().lower()
    if value in ('0', 'false', 'off', 'no'):
        return False
    if value in ('1', 'true', 'on', 'yes'):
        return True
    return bool(C.DIRECT_LINKS_ONLY)
''', '''def _switch(env, param, default):
    """A yes/no system parameter (0 / 1, false / true, off / on, no / yes); anything else = the default of board_config."""
    value = (env['ir.config_parameter'].sudo().get_param(param) or '').strip().lower()
    if value in ('0', 'false', 'off', 'no'):
        return False
    if value in ('1', 'true', 'on', 'yes'):
        return True
    return bool(default)


def direct_links_only(env):
    """True while only direct links are used (default): system parameter llmd_agg.direct_links_only, else board_config.DIRECT_LINKS_ONLY."""
    return _switch(env, 'llmd_agg.direct_links_only', C.DIRECT_LINKS_ONLY)


def apply_login_required(env):
    """True while Apply Now asks the visitor to sign in first (default): system parameter llmd_agg.apply_login, else board_config.APPLY_LOGIN."""
    return _switch(env, 'llmd_agg.apply_login', C.APPLY_LOGIN)
'''),
    ("""            'apply_url': apply_url, 'internal_href': '', 'apply_form_href': ('/jobs/ext/%d/apply' % self.id) if self.apply_mode() == 'form' else '', 'go_href': ('/jobs/ext/%d/go' % self.id) if apply_url else '',
            'source_text': '',""", """            'apply_url': apply_url, 'internal_href': '', 'apply_form_href': ('/jobs/ext/%d/apply' % self.id) if self.apply_mode() == 'form' else '', 'go_href': ('/jobs/ext/%d/go' % self.id) if apply_url else '',
            'source_text': '', **self._sign_in_vals(bool(apply_url)),"""),
    ('''    @api.model
    def _dedupe(self, prepared):''', '''    @api.model
    def _sign_in_vals(self, has_link):
        """For the Apply card: `sign_in` = the visitor must sign in first (they are not signed in), `tracked_user` = they are signed in and their account is saved with the click."""
        login = has_link and apply_login_required(self.env)
        public = self.env.user._is_public()
        return {'sign_in': bool(login and public), 'tracked_user': bool(login and not public)}

    @api.model
    def _dedupe(self, prepared):'''),
])

edit('models/hr_job.py', [
    ("        if apply_url and is_board_link(apply_url) and direct_links_only(self.env):\n",
     "        if apply_url and is_board_link(apply_url) and direct_links_only(self.env):\n"),
    ("            'source_text': '', 'source': source, 'internal_apply': internal,\n",
     "            'source_text': '', 'source': source, 'internal_apply': internal, **self.env['llmd.job.listing']._sign_in_vals(bool(apply_url)),\n"),
])

edit('models/click.py', [
    ('''A click is only a click: we cannot know whether the person then applied on the other site, so nothing here is an
application and no name or e-mail is stored (a click carries none). Names and e-mails exist only in `llmd.job.application`, and only when an authorized provider integration
sent them.
"""''', '''A click is only a click: we cannot know whether the person then applied on the other site.
Who clicked is known only when the visitor is SIGNED IN (the default asks them to sign in first, llmd_agg.apply_login): then the name, e-mail and phone of their own account
are saved with the click, and Recruitment > Job Applications gets one record per job and person with the status "Sent to employer". An anonymous click carries no name.
"""'''),
    ('''    repeat = fields.Boolean(string='Repeat click', readonly=True, help='The same browser had already clicked Apply Now on this job.')
''', '''    repeat = fields.Boolean(string='Repeat click', readonly=True, help='The same browser had already clicked Apply Now on this job.')
    # who clicked: only for a signed-in visitor, taken from their own account (nothing typed, nothing guessed)
    user_id = fields.Many2one('res.users', string='Signed-in account', ondelete='set null', index=True, readonly=True)
    applicant_name = fields.Char(string='Student Name', readonly=True)
    email = fields.Char(string='Email', readonly=True)
    phone = fields.Char(string='Phone', readonly=True)
    application_id = fields.Many2one('llmd.job.application', string='Job application', ondelete='set null', readonly=True)
'''),
    ('''    def record_click(self, listing=None, job=None, visitor=None, url=None):''', '''    def record_click(self, listing=None, job=None, visitor=None, url=None, user=None):'''),
    ('''        same: counting never blocks anybody)."""''', '''        same: counting never blocks anybody). `user` = the signed-in account of the visitor: its name, e-mail and phone are saved with the click and in Job Applications."""'''),
    ('''        rec = self.create(dict(info, clicked_at=now, status='clicked' if info['apply_url'] else 'no_link', visitor_key=visitor or False, repeat=repeat))''',
     '''        person = {}
        if user and not user._is_public():
            partner = user.partner_id
            person = {'user_id': user.id, 'applicant_name': partner.name or user.name, 'email': (user.email or partner.email or '').strip().lower() or False, 'phone': partner.phone or False}
        rec = self.create(dict(info, clicked_at=now, status='clicked' if info['apply_url'] else 'no_link', visitor_key=visitor or False, repeat=repeat, **person))
        if person and rec.status == 'clicked':
            rec.application_id = self.env['llmd.job.application'].record_sent(info, user)'''),
])

edit('models/application.py', [
    ('''STATES = [('submitted', 'Received'),''', '''STATES = [('sent', 'Sent to employer'), ('submitted', 'Received'),'''),
    ('''('external', "Applicant's own report (old)")]''', '''('external', "Applicant's own report (old)"), ('redirect', "Employer's website (signed in)")]'''),
    ('''* records of the earlier versions of this module (our own form, "I applied" reports) stay as they were.''',
     '''* a SIGNED-IN student who clicked Apply Now and was sent to the employer's own page - state `sent` ("Sent to employer"), channel `redirect`: name, e-mail and phone
  come from their own account; whether they finished the application on the employer's site is not known (a recruiter can confirm it);
* records of the earlier versions of this module (our own form, "I applied" reports) stay as they were.'''),
    ('''    # ------------------------------------------------------------------ OUR application form of a job: saved in Odoo''', '''    # ------------------------------------------------------------------ a signed-in student was sent to the employer's page (Apply Now)
    @api.model
    def record_sent(self, info, user):
        """The one record of this signed-in account for this job ("Sent to employer"), made the first time they click Apply Now. Name, e-mail and phone are those of their
        own account. A later click changes nothing (no duplicate); a record a recruiter confirmed or withdrew keeps its status."""
        self = self.sudo()
        partner = user.partner_id
        email = (user.email or partner.email or '').strip().lower()
        identity = ('e:%s' % email) if '@' in email else ('u:%d' % user.id)
        vals = {'applicant_name': partner.name or user.name, 'email': email if '@' in email else False, 'phone': partner.phone or False,
                'channel': 'redirect', 'state': 'sent', 'application_date': fields.Datetime.now()}
        rec, created = self._get_or_create(info, identity, vals)
        if not created:
            missing = {k: vals[k] for k in ('applicant_name', 'phone') if vals[k] and not rec[k]}
            if missing:
                rec.write(missing)
        return rec

    # ------------------------------------------------------------------ OUR application form of a job: saved in Odoo'''),
])

edit('controllers/main.py', [
    ('''from urllib.parse import urlencode
''', '''from urllib.parse import urlencode
'''),
    ('''    @staticmethod
    def _llmd_count(vid, **job):''', '''    @staticmethod
    def _llmd_sign_in_first():
        """Apply Now asks for a sign-in first (default, llmd_agg.apply_login) and the visitor is not signed in."""
        return L.apply_login_required(request.env) and request.env.user._is_public()

    @staticmethod
    def _llmd_to_login(path):
        """To Odoo's sign-in page; after signing in the visitor comes back to `path` (the same Apply Now) and goes on to the employer."""
        response = request.redirect('/web/login?' + urlencode({'redirect': path}))
        response.headers['Cache-Control'] = 'no-store'
        return response

    @staticmethod
    def _llmd_user():
        user = request.env.user
        return user if user and not user._is_public() else None

    @staticmethod
    def _llmd_count(vid, **job):'''),
    ('''        job = self._llmd_listing(listing_id)
        vid = self._llmd_visitor()
        self._llmd_count(vid, listing=job)
        url = job.safe_apply_url()
        return self._llmd_send_on(url, vid) if url else request.redirect('/jobs/ext/%d' % job.id)''', '''        job = self._llmd_listing(listing_id)
        url = job.safe_apply_url()
        if url and self._llmd_sign_in_first():
            return self._llmd_to_login('/jobs/ext/%d/go' % job.id)
        vid = self._llmd_visitor()
        self._llmd_count(vid, listing=job, user=self._llmd_user())
        return self._llmd_send_on(url, vid) if url else request.redirect('/jobs/ext/%d' % job.id)'''),
    ('''        self._llmd_count(vid, job=position)
        return self._llmd_send_on(url, vid) if url else request.redirect(position.website_url or '/jobs')''', '''        if url and self._llmd_sign_in_first():
            return self._llmd_to_login('/jobs/position/%d/go' % position.id)
        self._llmd_count(vid, job=position, user=self._llmd_user())
        return self._llmd_send_on(url, vid) if url else request.redirect(position.website_url or '/jobs')'''),
])

edit('views/job_view.xml', [
    ('''                            <p t-elif="d.get('go_href')" class="o_llmd_apply_help">You will be taken to the employer's application page.</p>''',
     '''                            <p t-elif="d.get('go_href') and d.get('sign_in')" class="o_llmd_apply_help">Sign in once with your account, then you go straight to the employer's application page. Your name and e-mail are saved with your click, so you do not fill in anything twice.</p>
                            <p t-elif="d.get('go_href') and d.get('tracked_user')" class="o_llmd_apply_help">You will be taken to the employer's application page. Your name and e-mail (from your account) are saved with your click.</p>
                            <p t-elif="d.get('go_href')" class="o_llmd_apply_help">You will be taken to the employer's application page.</p>'''),
])

edit('views/click_views.xml', [
    ('''                <field name="job_title"/>
                <field name="company"/>
                <field name="source"/>
                <field name="ext_id"/>
                <field name="apply_url" widget="url" optional="show"/>''', '''                <field name="applicant_name" optional="show"/>
                <field name="email" optional="show"/>
                <field name="job_title"/>
                <field name="company"/>
                <field name="source"/>
                <field name="ext_id"/>
                <field name="apply_url" widget="url" optional="show"/>'''),
    ('''                    <div class="alert alert-info" role="status" invisible="status != 'clicked'">Somebody clicked Apply Now and was sent to the employer's website. We do not know whether they applied there, and we do not know who they are: this is not an application.</div>''',
     '''                    <div class="alert alert-info" role="status" invisible="status != 'clicked' or user_id">Somebody clicked Apply Now and was sent to the employer's website. They were not signed in, so we do not know who they are, and we do not know whether they applied there: this is not an application.</div>
                    <div class="alert alert-success" role="status" invisible="status != 'clicked' or not user_id">A signed-in student clicked Apply Now and was sent to the employer's website. Their name, e-mail and phone come from their own account. Whether they finished the application on the employer's site is not known.</div>'''),
    ('''                        <group string="Click">
                            <field name="clicked_at"/>
                            <field name="repeat"/>
                        </group>''', '''                        <group string="Click">
                            <field name="clicked_at"/>
                            <field name="repeat"/>
                        </group>
                        <group string="Student" invisible="not user_id">
                            <field name="applicant_name"/>
                            <field name="email" widget="email"/>
                            <field name="phone" widget="phone"/>
                            <field name="user_id"/>
                            <field name="application_id"/>
                        </group>'''),
    ('''                <field name="job_title"/>
                <field name="company"/>
                <field name="ext_id"/>
                <field name="source"/>
                <field name="apply_url"/>''', '''                <field name="applicant_name"/>
                <field name="email"/>
                <field name="job_title"/>
                <field name="company"/>
                <field name="ext_id"/>
                <field name="source"/>
                <field name="apply_url"/>'''),
    ('''                <filter name="first" string="First clicks only" domain="[('repeat', '=', False)]"/>''', '''                <filter name="signed_in" string="Signed-in students" domain="[('user_id', '!=', False)]"/>
                <filter name="anonymous" string="Not signed in" domain="[('user_id', '=', False)]"/>
                <separator/>
                <filter name="first" string="First clicks only" domain="[('repeat', '=', False)]"/>'''),
])

edit('views/application_views.xml', [
    ('''decoration-success="state in ('submitted', 'confirmed')" decoration-warning="state == 'reported'" decoration-danger="state == 'withdrawn'" default_order="application_date desc">''',
     '''decoration-success="state in ('submitted', 'confirmed')" decoration-info="state == 'sent'" decoration-warning="state == 'reported'" decoration-danger="state == 'withdrawn'" default_order="application_date desc">'''),
    ('''                <field name="state" widget="badge" decoration-warning="state == 'reported'" decoration-success="state in ('submitted', 'confirmed')" decoration-danger="state == 'withdrawn'"/>''',
     '''                <field name="state" widget="badge" decoration-info="state == 'sent'" decoration-warning="state == 'reported'" decoration-success="state in ('submitted', 'confirmed')" decoration-danger="state == 'withdrawn'"/>'''),
    ('''statusbar_visible="submitted,confirmed"''', '''statusbar_visible="sent,submitted,confirmed"'''),
    ('''                    <div class="alert alert-warning" role="status" invisible="state != 'reported'">''',
     '''                    <div class="alert alert-info" role="status" invisible="state != 'sent'">This student was signed in and clicked Apply Now: they were sent to the employer's own application page. Name, e-mail and phone come from their account. Whether they finished the application there is not known - use "Confirm application" once you know.</div>
                    <div class="alert alert-warning" role="status" invisible="state != 'reported'">'''),
    ('''                <filter name="submitted" string="Received" domain="[('state', '=', 'submitted')]"/>''', '''                <filter name="sent" string="Sent to employer" domain="[('state', '=', 'sent')]"/>
                <filter name="submitted" string="Received" domain="[('state', '=', 'submitted')]"/>'''),
    ('''                <filter name="provider" string="Sent by the job provider" domain="[('channel', '=', 'provider')]"/>''', '''                <filter name="redirect" string="Employer's website (signed in)" domain="[('channel', '=', 'redirect')]"/>
                <filter name="provider" string="Sent by the job provider" domain="[('channel', '=', 'provider')]"/>'''),
])

edit('models/click.py', [
    ("            person = {'user_id': user.id, 'applicant_name': partner.name or user.name, 'email': (user.email or partner.email or '').strip().lower() or False, 'phone': partner.phone or False}\n",
     "            person = {'user_id': user.id, 'applicant_name': partner.name or user.name, 'email': (user.email or partner.email or '').strip().lower() or False, 'phone': partner.phone or False}\n"
     "            repeat = repeat or bool(self.search([('user_id', '=', user.id), ('job_key', '=', info['job_key'])], limit=1))      # the same person, also from another browser\n"),
    ("        if person and rec.status == 'clicked':\n",
     "        if person and rec.status == 'clicked' and user.share:                # a student (portal account); a staff member trying the page is no applicant\n"),
])
