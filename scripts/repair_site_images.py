"""Run inside `odoo shell` on the LOCAL database only: puts Odoo's stock logo and favicon back on the website when their files are missing from the filestore
(the Jobs page header then shows a broken image and every page load logs a 500 for /web/image/website/1/favicon).

  cat scripts/repair_site_images.py | docker compose --env-file .env -f docker/docker-compose.yml exec -T -e DBN=llmd_local odoo sh -c 'odoo shell -d "$DBN" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'

It only touches a field whose stored file cannot be read; a logo or favicon that works is left alone.
"""
import base64
import os

from odoo import tools

Website = env['website']
for website in Website.search([]):
    for field, loader in (('logo', Website._default_logo), ('favicon', Website._default_favicon)):
        att = env['ir.attachment'].sudo().search([('res_model', '=', 'website'), ('res_field', '=', field), ('res_id', '=', website.id)], limit=1)
        if not att:
            continue
        path = att._full_path(att.store_fname) if att.store_fname else None
        if path and os.path.exists(path):
            print('website %s: %s is fine' % (website.id, field))
            continue
        website.write({field: loader()})
        print('website %s: %s was missing from the filestore - the stock image was put back' % (website.id, field))
env.cr.commit()
