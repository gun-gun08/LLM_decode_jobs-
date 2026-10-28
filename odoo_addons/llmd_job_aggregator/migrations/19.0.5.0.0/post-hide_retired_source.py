"""Himalayas was removed from the job integration. The jobs that were stored from it earlier are all "remote, worldwide" jobs: they are hidden (not deleted) so that the Jobs page
does not show only remote jobs. To bring them back: set `active` of the listings with source "Himalayas" again (Recruitment > Job board > Job board listings > Archived)."""


def migrate(cr, version):
    cr.execute("UPDATE llmd_job_listing SET active = false WHERE source = 'Himalayas' AND active")
