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

# Load .env file if available
# Some hosting environments may not require or expect a .env file
# for platform.sh, we could remove the env.platform and instead set environment variables via the CLI/UI and
# its possible this may be the preferred approach down the road, so adding this check to prevent issues later
env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if env_file.exists():
    env.read_env(env_file, parse_comments=True)
