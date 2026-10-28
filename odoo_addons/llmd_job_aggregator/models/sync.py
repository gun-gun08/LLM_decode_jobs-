"""One line for every run of the job synchronization (scheduled or by hand): what was created, updated, hidden, which sources worked, what could not be saved."""
from odoo import fields, models


class LlmdJobSync(models.Model):
    _name = 'llmd.job.sync'
    _description = 'Job synchronization run'
    _order = 'started desc, id desc'

    started = fields.Datetime(required=True, default=fields.Datetime.now)
    finished = fields.Datetime()
    trigger = fields.Selection([('cron', 'Scheduled action'), ('manual', 'By hand')], default='manual')
    state = fields.Selection([('ok', 'OK'), ('partial', 'Some problems'), ('idle', 'Nothing delivered')], default='ok')
    created = fields.Integer(string='New jobs')
    updated = fields.Integer(string='Updated jobs')
    hidden = fields.Integer(string='Hidden jobs')
    duplicates = fields.Integer(string='Duplicates removed')
    errors = fields.Integer(string='Jobs that could not be saved')
    visible = fields.Integer(string='Jobs on the website after the run')
    details = fields.Text()
