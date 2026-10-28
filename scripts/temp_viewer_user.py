"""Run inside `odoo shell` on the LOCAL database: creates (or removes, with REMOVE=1) a throw-away recruiter login "llmd_viewer" so that the backend screens can be looked at in a browser.
The password is random, printed once and is gone with the user. Nothing else is touched.
"""
import os
import secrets

Users = env['res.users'].with_context(active_test=False)
existing = Users.search([('login', '=', 'llmd_viewer')])
if os.environ.get('REMOVE'):
    existing.unlink()
    env.cr.commit()
    print('removed:', bool(existing))
else:
    existing.unlink()
    password = secrets.token_urlsafe(12)
    groups = env.ref('base.group_user') | env.ref('hr_recruitment.group_hr_recruitment_manager')
    user = Users.create({'name': 'LLMD Viewer (temporary)', 'login': 'llmd_viewer', 'password': password, 'group_ids': [(6, 0, groups.ids)]})
    env.cr.commit()
    print('created user', user.id, 'PASSWORD=' + password)
