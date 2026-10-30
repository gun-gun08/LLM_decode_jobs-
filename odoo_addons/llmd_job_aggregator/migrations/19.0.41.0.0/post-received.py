"""19.0.41.0.0: every record of Job Applications is an application that reached us, so its status is "Received" - also the ones a signed-in Apply Now made, which
19.0.35 kept as "Redirected to External Site" / "Apply Clicked". Their channel stays "Apply Now (signed in)" (and their Application Type "External Apply Click"), so
they are still told apart from an application sent through a form. Only the status changes; nothing is deleted, no other value is touched."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("UPDATE llmd_job_application SET state = 'submitted' WHERE state IN ('clicked', 'redirected')")
    _logger.info('19.0.41: %d Apply Now records set to "Received"', cr.rowcount)
