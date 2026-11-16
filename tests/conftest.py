import os
import sys

# Settings are read from the environment at import time: set the test environment before anything imports mlp.
os.environ['MTA'] = 'postfix'
os.environ['LOG_TIMEZONE'] = 'UTC'
os.environ['MAIL_HOST_NAME'] = ''
os.environ['GUI_REFRESH_BLOCK'] = 'false'
os.environ.setdefault('RETHINK_DB', 'mlp_test_parser')
os.environ.setdefault('RETHINK_HOST', 'localhost')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def fixture_path(name: str) -> str:
    return os.path.join(FIXTURES, name)
