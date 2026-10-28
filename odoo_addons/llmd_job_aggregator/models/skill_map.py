"""How the skills found in a job's text are put into Odoo's skill system (hr.skill), in three separate kinds - pure Python, no Odoo imports.

- Technical Skills: the technical names of the parser's own vocabulary (vocab.SKILLS: programming languages, frameworks, databases, cloud, data, machine
  learning, testing, mobile, IT). They go into one skill type of their own, "Technical Skills", created from the first one a job really mentions.
- Soft Skills and Languages: Odoo's own records (hr_skills) are matched by name, never created: a job skill named like an Odoo soft skill ("Communication",
  "Problem Solving" = "Problem-Solving"), a language the job asks for (llmd.job.listing.languages: "Mandarin" = "Mandarin Chinese").
- Everything else a job mentions (sales, marketing, design, HR, finance skills, and the free lines of a job's own skills section) stays on the website only:
  it is no technical skill, and inventing a soft skill or language for it would be wrong.
Only skills a job's own text mentions are ever linked; nothing is assumed from a title or a category."""
import re

try:
    from .vocab import SKILLS
except ImportError:                                                     # imported on its own (the unit tests)
    from vocab import SKILLS

TECHNICAL_TYPE = 'Technical Skills'
# the levels of the new skill type (Odoo wants at least one): the usual scale, the first one the default
TECHNICAL_LEVELS = [('Beginner', 25, True), ('Intermediate', 50, False), ('Advanced', 75, False), ('Expert', 100, False)]

# the technical part of the vocabulary, by its own names (the rest of vocab.SKILLS is design, marketing, sales, project, HR, finance or soft skills)
_TECHNICAL_NAMES = (
    'Python', 'JavaScript', 'TypeScript', 'React', 'Node.js', 'Express.js', 'MongoDB', 'SQL', 'NoSQL', 'Django', 'Flask', 'FastAPI', 'Java', 'Spring Boot', 'C#',
    'Go', 'Next.js', 'Angular', 'Vue.js', 'HTML', 'CSS', 'Tailwind CSS', 'Redux', 'REST APIs', 'GraphQL', 'Microservices', 'AWS', 'Azure', 'Google Cloud',
    'Docker', 'Kubernetes', 'CI/CD', 'Terraform', 'Linux', 'Git', 'Machine Learning', 'Deep Learning', 'NLP', 'LLMs', 'Generative AI', 'Prompt Engineering',
    'RAG', 'TensorFlow', 'PyTorch', 'scikit-learn', 'Pandas', 'NumPy', 'MLOps', 'Computer Vision', 'Data Analysis', 'Data Visualization', 'Statistics',
    'A/B Testing', 'Tableau', 'Power BI', 'Excel', 'Looker', 'ETL', 'Spark', 'Airflow', 'Snowflake', 'Databricks', 'BigQuery', 'Test Automation', 'Selenium',
    'Cypress', 'API Testing', 'Manual Testing', 'Swift', 'Kotlin', 'Flutter', 'React Native', 'Android', 'iOS', 'Network Security', 'Troubleshooting',
    'Active Directory', 'Windows Server')
_VOCAB = {name for name, _rx in SKILLS}
assert set(_TECHNICAL_NAMES) <= _VOCAB, set(_TECHNICAL_NAMES) - _VOCAB             # every technical name is one the parser really finds
# a language as the job text names it -> the name of Odoo's language skill (only where they differ)
LANGUAGE_NAMES = {'Mandarin': 'Mandarin Chinese'}


def norm(name):
    """A name for comparing: lower case, punctuation between words as one space ("Problem-Solving" = "problem solving"); + and # stay (C#, C++)."""
    return re.sub(r'[^a-z0-9+#]+', ' ', (name or '').lower()).strip()


def skill_key(name):
    """The stored form of a skill on a listing (job_facets.skill_key)."""
    return re.sub(r'[\s,]+', ' ', (name or '').strip().lower())


TECHNICAL_BY_KEY = {skill_key(name): name for name in _TECHNICAL_NAMES}


def technical_name(key):
    """The vocabulary name of a technical skill for a listing's skill key, or ''."""
    return TECHNICAL_BY_KEY.get(key, '')


def language_skill_name(language):
    """The name of Odoo's language skill for a language a job asks for."""
    return LANGUAGE_NAMES.get(language, language)
