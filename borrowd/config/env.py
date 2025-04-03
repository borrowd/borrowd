"""
For background, see `here`_, although we deviate from that structure
in order to accommodate per-env configs for third-party integrations,
and because I'm less concerned that "everything must be in base
config"; I can deal with certain envs having settings which are
specific only to them.

.. _here: https://github.com/HackSoftware/Django-Styleguide?tab=readme-ov-file#settings
"""

from pathlib import Path
from environ import Env

env = Env()

env.read_env(
    Path(__file__).resolve().parent.parent.parent / ".env", parse_comments=True
)
