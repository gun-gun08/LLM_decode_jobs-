"""LOCAL ONLY - the website test account for tests/click_user_test.py: a portal user "LLMD Test User" with a test e-mail and phone in its profile.
Login and password come from .env (LLMD_TEST_USER_LOGIN / LLMD_TEST_USER_PASSWORD, made by hand for the local database); nothing is printed.
Run it in the odoo shell of the LOCAL database with those two variables passed in (docker compose exec -e LLMD_TEST_USER_LOGIN -e LLMD_TEST_USER_PASSWORD ...).
Running it again only resets the password and the profile."""
import os

assert env.cr.dbname == 'llmd_local', 'local_test_user.py is for the local test database only'          # noqa: F821 (env is the odoo shell's)
login, password = os.environ['LLMD_TEST_USER_LOGIN'], os.environ['LLMD_TEST_USER_PASSWORD']
Users = env['res.users'].sudo().with_context(active_test=False, no_reset_password=True)                    # noqa: F821
user = Users.search([('login', '=', login)], limit=1)
profile = {'name': 'LLMD Test User', 'email': login, 'phone': '+91 90000 00001'}
if not user:
    user = Users.create(dict(profile, login=login, group_ids=[(6, 0, [env.ref('base.group_portal').id])]))    # noqa: F821
user.write({'active': True, 'password': password})
user.partner_id.write(profile)
env.cr.commit()                                                                                             # noqa: F821
print('test user ready: id %d, portal %s' % (user.id, user.has_group('base.group_portal')))
