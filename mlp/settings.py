"""

Copyright::
    +===================================================+
    |                 © 2019 Privex Inc.                |
    |               https://www.privex.io               |
    +===================================================+
    |                                                   |
    |        Postfix Log Parser / Web UI                |
    |                                                   |
    |        Core Developer(s):                         |
    |                                                   |
    |          (+)  Chris (@someguy123) [Privex]        |
    |                                                   |
    +===================================================+

"""
from collections import namedtuple
from typing import List, Dict

import pytz

from os import getenv as env, path as path
from dotenv import load_dotenv
from privex.helpers import env_bool, env_csv, env_int

load_dotenv()

DEBUG = env_bool('DEBUG', False)

vue_debug = env_bool('VUE_DEBUG', False)
"""
If True, the development version of Vue (with devtools support and logging) will be used instead of the 
production minified version.
"""

rethink_host = env('RETHINK_HOST', 'localhost')
rethink_port = int(env('RETHINK_PORT', 28015))
rethink_db = env('RETHINK_DB', 'maildata')
rethink_arr_limit = int(env('RETHINK_ARR_LIMIT', 100000))

rethink_tables = [
    ('sent_mail', 'auth', ['status_code', 'mail_from', 'mail_to', 'mail_to_alias', 'timestamp', 'first_attempt', 'last_attempt', 'host']),
]

# add ldap vars from env
ldap_connect = env('LDAP_CONNECT','')
ldap_version = int(env('LDAP_VERSION',3))
ldap_bind_dn = env('LDAP_BIND_DN', '')
ldap_bind_dn_pwd = env('LDAP_BIND_DN_PWD', '')
ldap_searchbase = env('LDAP_SEARCHBASE' ,'')
ldap_searchfilter = env('LDAP_SEARCHFILTER', '(%s=%s)')
ldap_username_attr = env('LDAP_USERNAME_ATTR', '')
ldap_username_domain_part = env('LDAP_USERNAME_DOMAIN_PART', '')

# --- Web auth / session / secret key (2.0) ---------------------------------------------------
# SECRET_KEY values that must never be used: when SECRET_KEY is empty or one of these, a random
# key is generated once and persisted in ``<instance_path>/secret_key`` (see mlp/security.py).
insecure_secret_keys = ('', 'SetThis!InYourEnv', 'ChangeMe', 'changeme', 'secret')
instance_path = env('INSTANCE_PATH', path.join(path.dirname(path.dirname(path.abspath(__file__))), 'instance'))
session_cookie_secure = env_bool('SESSION_COOKIE_SECURE', False)
session_lifetime_hours = env_int('SESSION_LIFETIME_HOURS', 12)
# Login throttling (in memory, per worker): failures allowed per (IP, login) and per IP in the window.
login_max_failures = env_int('LOGIN_MAX_FAILURES', 5)
login_max_failures_ip = env_int('LOGIN_MAX_FAILURES_IP', 50)
login_throttle_window = env_int('LOGIN_THROTTLE_WINDOW', 900)
# Optional RethinkDB account (RethinkDB's default "admin" user has no password).
rethink_user = env('RETHINK_USER', '')
rethink_password = env('RETHINK_PASSWORD', '')
# Client-side timeout (seconds) of one API query; 0 disables it.
query_timeout = env_int('QUERY_TIMEOUT', 60)
# Network / operation timeout (seconds) for LDAP calls.
ldap_timeout = env_int('LDAP_TIMEOUT', 10)
# ----------------------------------------------------------------------------------------------

mail_domain = env('MAIL_DOMAIN', '')

mail_log_path = env('MAIL_LOG_PATH', '/var/log')
mail_log_filename = env('MAIL_LOG_FILENAME', 'mail.log')
mail_log_filenames = [f.strip() for f in mail_log_filename.split(',') if f.strip()]
"""
``MAIL_LOG_FILENAME`` may be a comma separated list of file names and/or glob patterns (``mail.log,mail.log.1``,
``hosts/*/mail.log``), relative to ``MAIL_LOG_PATH`` (absolute paths are used as they are). Matching files are
parsed oldest first (by modification time); ``.gz`` files are read transparently.
"""

mail_log = mail_log_path+'/'+mail_log_filename
"""Legacy: the single log file path (only meaningful when ``MAIL_LOG_FILENAME`` is one plain file name)"""

mail_host_name = env('MAIL_HOST_NAME', '')
"""Host name stored for lines without a syslog hostname field (e.g. a log written without a syslog header)"""

legacy_multiple_status = env_bool('LEGACY_MULTIPLE_STATUS', False)
"""If True, messages with several recipients get the 1.x catch-all status ``multiple`` instead of their worst delivery status"""

hidden_recipients = [p.strip().lower() for p in env_csv('HIDDEN_RECIPIENTS', []) if p.strip()]
"""
Recipients the server adds to (nearly) every message, e.g. an ``always_bcc`` archive copy: addresses or shell patterns
(``backup@archive.local``, ``*@archive.local``), case-insensitive. Their deliveries stay in ``recipients`` (flagged
``hidden``) but do not count for ``mail_to``, ``multiple``, the message status or the relay - unless a message has no
other recipient.
"""

decode_srs = env_bool('DECODE_SRS', True)
"""Show the original sender of SRS-rewritten envelope senders (``SRS0=...``) in ``mail_from``; the rewritten address is kept in ``srs_from``"""

import_batch_size = max(1, env_int('IMPORT_BATCH_SIZE', 500))
"""Number of messages per RethinkDB ``insert(..., conflict='update')`` call when importing"""

lock_file = path.abspath(env('LOCK_FILE', path.join(path.dirname(path.abspath(path.dirname(__file__))), 'processing.lock')))
"""Lock file created while the importer runs (the web UI reports \"processing\" while it exists)"""

#admin_pass = env('ADMIN_PASS', 'SetThis!InYourEnv')
secret_key = env('SECRET_KEY', 'SetThis!InYourEnv')

# add prefix var from env
path_prefix = env('PATH_PREFIX', '')

# add housekeeping_days var from env ('' / unset = disabled; values <= 0 are treated as disabled too)
housekeeping_days = env_int('HOUSEKEEPING_DAYS', '')

# add datetime_format var from env
datetime_format = env('DATETIME_FORMAT', 'HH:mm:ss, DD.MM.YYYY')

# add datetime_input_length var from env
datetime_input_length = env_int('DATETIME_INPUT_LENGTH', 20)

# add mail_log_timestamp_convert var from env
mail_log_timestamp_convert = env_bool('MAIL_LOG_TIMESTAMP_CONVERT', False)

# add gui_refresh_block var from env
gui_refresh_block = env_bool('GUI_REFRESH_BLOCK', True)

# add gui_max_log_period var from env
gui_max_log_period = env_int('GUI_MAX_LOG_PERIOD', 4320)

# add mta var from env
mta = env('MTA', '').strip().lower() or 'postfix'

# add exclude from top senders
exclude_from_top_senders = env('EXCLUDE_FROM_TOP_SENDERS', '')

# add exclude from top recipients
exclude_from_top_recipients = env('EXCLUDE_FROM_TOP_RECIPIENTS', '')

log_timezone = pytz.timezone(env('LOG_TIMEZONE', 'UTC'))
"""
If your mail.log isn't in UTC, set the LOG_TIMEZONE env var to a pytz compatible timezone
"""

ignore_domains = env_csv('IGNORE_DOMAINS', ['localhost', '127.0.0.1'])

default_limit = env_int('DEFAULT_LIMIT', 50)
max_limit = env_int('MAX_LIMIT', 1000)

AppError = namedtuple('AppError', 'code message status', defaults=['', 500])
_ERRORS: List[AppError] = [
    AppError('UNKNOWN_ERROR', "An unknown error has occurred. Please contact the administrator of this site.", 500),
    AppError('NOT_FOUND', "The requested resource or URL was not found. You may wish to check the URL for typos.", 404),
    AppError('METHOD_NOT_ALLOWED', "This API endpoint does not allow the requested HTTP method (GET/POST/PUT etc.)", 405),
]
ERRORS: Dict[str, AppError] = {err.code: err for err in _ERRORS}
DEFAULT_ERR: AppError = ERRORS['UNKNOWN_ERROR']
