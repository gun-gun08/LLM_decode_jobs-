"""The courses the Jobs page offers: read from the LLM Decode course data of this Odoo site (eLearning: slide.channel, published courses of type "training"), never typed in.

Only when the Odoo database has no eLearning module at all (the local test database) the four courses of board_config.COURSES are used instead, so that page can still be tried;
their text (subtitle, roadmap, outcomes, curriculum lessons) then comes from course_snapshot.json, a copy of the public course pages.

Which jobs a course leads to is decided as before (its role profiles, from its name, tags and description). Its full text - modules / lessons and outcomes included -
gives its course terms (board_config.COURSE_TERMS), which rank those jobs and say why each one matches.
"""
import json
import os
import re

from odoo import api, models

from . import board_config as C

_SNAPSHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'course_snapshot.json')


def _plain(html, limit=600):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(html or ''))).strip()[:limit]


def _snapshot():
    try:
        with open(_SNAPSHOT, encoding='utf-8') as fh:
            return {c['code']: c for c in json.load(fh).get('courses') or []}
    except (OSError, ValueError):
        return {}


class LlmdCourseCatalog(models.AbstractModel):
    _name = 'llmd.course.catalog'
    _description = 'Courses offered on the Jobs page (from the eLearning course data)'

    @api.model
    def has_course_data(self):
        return 'slide.channel' in self.env

    @api.model
    def courses(self):
        """[{'code', 'name', 'profiles', 'words', 'dynamic', 'subtitle', 'terms', 'url'}] in the order of the course list on the site."""
        if not self.has_course_data():
            snap = _snapshot()
            out = []
            for code, name in C.COURSES:
                page = snap.get(code) or {}
                text = ' '.join([name, page.get('subtitle') or '', page.get('content') or ''])
                out.append({'code': code, 'name': name, 'profiles': [code], 'words': [], 'dynamic': False, 'subtitle': page.get('subtitle') or '',
                            'terms': C.course_terms(text), 'url': ''})
            return out
        Channel = self.env['slide.channel'].sudo()
        domain = []
        if 'channel_type' in Channel._fields:
            domain.append(('channel_type', '=', 'training'))                 # "documentation" channels (like the SOP library) are not courses
        for flag in ('is_published', 'website_published'):
            if flag in Channel._fields:
                domain.append((flag, '=', True))
                break
        out = []
        for channel in Channel.search(domain, order='sequence, id'):
            tags = ' '.join(channel.tag_ids.mapped('name')) if 'tag_ids' in Channel._fields else ''
            text = ' '.join([channel.name or '', tags, _plain(channel.description) if 'description' in Channel._fields else ''])
            profiles = C.course_profiles(text)
            # the whole course for its course terms: the full description, the short one, and the names of its sections and lessons (its modules)
            lessons = ' '.join(channel.slide_ids.mapped('name')) if 'slide_ids' in Channel._fields else ''
            full = ' '.join([text, _plain(channel.description, 20000) if 'description' in Channel._fields else '',
                             _plain(channel.description_short, 4000) if 'description_short' in Channel._fields else '', lessons])
            subtitle = _plain(channel.description_short, 160) if 'description_short' in Channel._fields else ''
            out.append({'code': 'c%d' % channel.id, 'name': channel.name, 'profiles': profiles, 'words': [] if profiles else C.course_words(channel.name), 'dynamic': True,
                        'subtitle': subtitle, 'terms': C.course_terms(full), 'url': getattr(channel, 'website_url', '') or ''})
        return out

    @api.model
    def resolve(self, code, courses=None):
        """The course for a ?course= value: its own code, or an older code (sell-ai ...) that points to the first course with that profile."""
        courses = self.courses() if courses is None else courses
        for course in courses:
            if course['code'] == code:
                return course
        if code in C.COURSE_LABELS:
            for course in courses:
                if code in course['profiles']:
                    return course
        return None
