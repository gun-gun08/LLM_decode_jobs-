"""v19.0.72: a second website (the job board's own domain) gets the header of the main website - its logo, header template and header text
(learn.llmdecode.com: the rounded box, no phone). Only what that website has not customised itself: its own header views and its own logo stay."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    websites = env['website'].search([], order='id')
    if len(websites) < 2:
        return
    main, others = websites[0], websites[1:]
    View = env['ir.ui.view'].with_context(active_test=False)
    header = View.search([('website_id', '=', main.id), ('key', '=like', 'website.%header%')])
    default_logo = env['website']._default_logo()
    for site in others:
        if main.logo and (not site.logo or site.logo == default_logo):
            site.logo = main.logo
        for view in header:
            if View.search_count([('key', '=', view.key), ('website_id', '=', site.id)]):
                continue
            generic = View.search([('key', '=', view.key), ('website_id', '=', False)], limit=1)
            if generic:
                generic.with_context(website_id=site.id).write({'active': view.active, 'arch_db': view.arch_db})   # Odoo's copy-on-write: a copy for that website only
            else:
                view.copy({'website_id': site.id, 'key': view.key})
