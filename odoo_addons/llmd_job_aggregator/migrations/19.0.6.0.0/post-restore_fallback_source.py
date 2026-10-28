"""Himalayas is the temporary keyless fallback source again (until Adzuna / JSearch / Jooble have keys): the jobs that migration 19.0.5.0.0 had hidden are shown again.
They are all remote jobs; the next fetch refreshes them and hides the ones Himalayas no longer lists."""


def migrate(cr, version):
    cr.execute("UPDATE llmd_job_listing SET active = true WHERE source = 'Himalayas' AND NOT active")
