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

Line level parsing: syslog header (timestamp, host, program), per-MTA field extraction.

For postfix the field regexes are applied per line type (delivery agent, smtpd, qmgr, cleanup), so text
coming from outside (a Subject header, a remote server's reply) cannot set fields like ``to``/``status``/``relay``.
The other MTAs (exim, sendmail, exchange) keep their legacy regexes.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import datefinder

from mlp import settings
import logging
log = logging.getLogger(__name__)

# postfix regexp (legacy; still used when the program of a line is unknown)
#OLD!!! postf_to = re.compile(r'.*to=<([a-zA-Z0-9-+_.=]+@[a-zA-Z0-9-+_.]+)>')
#postf_to = re.compile(r'^.*to=<([^>]*)>,.*orig_to=<[^>]*>') <---- this is only for orig_to
#postf_to = re.compile(r'^.*to=<([^>]*)>,.*orig_to=<[^>]*>|^.*to=<([^>]*)>')
postf_to = re.compile(r'^.*to=<([^>]*)>,.*orig_to=<([^>]*)>|^.*to=<([^>]*)>')
postf_from = re.compile(r'.*from=<([a-zA-Z0-9-+_.=]+@[a-zA-Z0-9-+_.]+)>')
postf_subject = re.compile(r'.*header\s(?i:subject):\s(.*)\sfrom\s')
postf_size = re.compile(r'.*size=([0-9]{1,}),.*')
postf_message_id = re.compile(r'.*message-id=<(.*)>')
postf_status = re.compile(r'.*status=([a-zA-Z0-9-_.]+) (.*)?|.*(reject):\s.*:\s([0-9].*);\s')
#postf_relay = re.compile(r'.*relay=([a-zA-Z0-9-._]+)\[(.*)\]:([0-9]+)')
#postf_relay = re.compile(r'.*(?:relay|connect to).([a-zA-Z0-9-._]+)\[(.*)\]:([0-9]+)')
# relay=host[ip]:port, relay=none, relay=local, relay=host[private/dovecot-lmtp]
postf_relay = re.compile(r'(?:.*?[\s,])?relay=([^\s,\[]+)(?:\[([^\]]*)\](?::([0-9]+))?)?')
#postf_client = re.compile(r'.*client=([a-zA-Z0-9-._]+)\[(.*)\]')
#postf_client = re.compile(r'.*client.([a-zA-Z0-9-._]+)?\[(.*)\]')
# client=unknown[192.0.2.1] (first occurrence; the host part may be empty)
postf_client = re.compile(r'(?:.*?[\s,])?client=([^\s,\[]*)\[([^\]]*)\]')

# postfix, new 2.0 regexps (all applied to the message part after "QID: ")
postf_delivery = re.compile(r'to=<([^>]*)>,(?: orig_to=<([^>]*)>,)?(.*?) status=([A-Za-z0-9_.-]+)(?: (.*))?$')
"""Delivery agent line: (1) to (2) orig_to (3) relay/delay/delays/dsn part (4) status code (5) status text"""
postf_connect_to = re.compile(r'connect to ([^\s\[]+)\[([^\]]*)\]:([0-9]+)')
postf_delay = re.compile(r'(?:^|[\s,])delay=([0-9.]+)')
postf_delays = re.compile(r'(?:^|[\s,])delays=([0-9./]+)')
postf_dsn = re.compile(r'(?:^|[\s,])dsn=([0-9.]+)')
postf_sasl_method = re.compile(r',\ssasl_method=([^,\s]+)')
postf_sasl_username = re.compile(r',\ssasl_username=([^,\s]+)')
postf_nrcpt = re.compile(r',\snrcpt=([0-9]+)')
postf_reject_client = re.compile(r'(?:milter-)?reject:\s\S+\sfrom\s([^\s\[]*)\[([^\]]*)\]')
# the postfix-generated tail of reject/warning/info lines; greedy .* takes the last one
postf_reject_tail = re.compile(r'.*;\sfrom=<([^>]*)>\sto=<([^>]*)>(?:\sproto=|\s*$)')
opendkim_signed = re.compile(r'DKIM-Signature field added \(s=([^,\s]+), d=([^)\s]+)\)')
tls_established = re.compile(r'.*TLS connection established (?:from|to) [^\[\s]*\[([^\]]*)\]')

POSTFIX_DELIVERY_AGENTS = frozenset(('smtp', 'lmtp', 'local', 'virtual', 'pipe', 'discard', 'error', 'retry', 'bounce'))
POSTFIX_SMTPD_AGENTS = frozenset(('smtpd', 'qmqpd'))

# exim regexp
#exim_to = re.compile(r'.*>.(.*).R=')
#exim_to = re.compile(r'.*[>|\*].(.*).R=')
#exim_to = re.compile(r'.*[>|\*]\s?(.*)\s<?([a-zA-Z0-9-+_.=]+@[a-zA-Z0-9-+_.]+).*[R|F]=(?:dnslookup|localuser)?|.*DATA:.*for.([a-zA-Z0-9-+_.=]+@[a-zA-Z0-9-+_.]+)')
exim_to = re.compile(r'.*[>|\*|=]\s?(.*)\s<?([a-zA-Z0-9-+_.=]+@[a-zA-Z0-9-+_.]+).*[R|F]=(?:dnslookup|localuser)?|.*DATA:.*for.([a-zA-Z0-9-+_.=]+@[a-zA-Z0-9-+_.]+)')
#exim_from = re.compile(r'.*<=.(.*).[U|H]=|.*F=<(.*)>')
exim_from = re.compile(r'.*<=.(.*).[U|H]=|.*F=<?([a-zA-Z0-9-+_.=]+@[a-zA-Z0-9-+_.]+)>?')
#exim_subject = re.compile(r'.*Subject:\s(.*)')
exim_subject = re.compile(r'.*[T]="(.*)".from')
#exim_size = re.compile(r'.*S=([0-9]{1,}).*')
exim_size = re.compile(r'.*\sS=([0-9]{1,}).*')
#exim_message_id = re.compile(r'.*<=.*id=(.*)')
exim_message_id = re.compile(r'.*<=.*id=(.*)\s(?:T=)')
#exim_client = re.compile(r'.*<=.*H=([a-zA-Z0-9-._]+).*\[([a-zA-Z0-9.:]+)')
#exim_client = re.compile(r'.*<=.*H=([a-zA-Z0-9-._)(]+).*\[([a-zA-Z0-9.:]+)')
#exim_client = re.compile(r'.*H=\(?\[?([a-zA-Z0-9-._]+)\]?\)?.\[?([a-zA-Z0-9.:]+)\]?.([0-9]{3,6}).[I=]')
#exim_client = re.compile(r'.*H=\[?([a-zA-Z0-9-\s()._]+)\]?\s\[?([a-zA-Z0-9.:]+)\]?.([0-9]{3,6}).[I=]')
exim_client = re.compile(r'.*H=\[?([a-zA-Z0-9-\s()._]+)\]?\s\(?\[?([a-zA-Z0-9.\s()\[\]]+)\]?\)?:([0-9]{3,6}).[I=]')
#exim_relay = re.compile(r'.*=>.*T=(dovecot)|.*T=remote_smtp.*H=([a-zA-Z0-9-._]+).\[([a-zA-Z0-9.:]+)')
#exim_relay = re.compile(r'.*=>.*T=(dovecot)|.*T=remote_smtp.*H=([a-zA-Z0-9-._]+).\[?([a-zA-Z0-9.:]+)\]?.([0-9]*)?')
#exim_relay = re.compile(r'.*(?:T=remote_smtp)?\d+\s[?:H|I]=(\(?[a-zA-Z0-9-._]+\)?)?.\[?([a-zA-Z0-9.:]+)\]?.([0-9]{2,3})\s')
exim_relay = re.compile(r'.*(?:T=remote_smtp)?[?:H|I]=(\(?[a-zA-Z0-9-._]+\)?)?.\[?([a-zA-Z0-9.:]+)\]?.([0-9]{2,3})\s')

#exim_status = re.compile(r'.*(rejected).(.*)|(.>{1}).*T=(.*)|.*(\*\*).(.*)|.*(==).*T.*:.(.*)')
exim_status = re.compile(r'.*(rejected).(.*)|(.>{1}).*\s(?:T|C)="?(.*)(?:"|S)|.*(\*\*).(.*)|.*(==).*(?:T=).*:\s(.*)')


# sendmail regexp
sendm_to = re.compile(r'.*to=(.*), ctladdr')
sendm_from = re.compile(r'.*from=(.*), size')
sendm_subject = re.compile(r'.*\(Subject:\s(.*)')
sendm_size = re.compile(r'.*size=([0-9]{1,}),.*')
sendm_message_id = re.compile(r'.*msgid=<(.*)>')
sendm_status = re.compile(r'.*stat=([a-zA-Z0-9-_.]+)(.*)?|.*(reject)=([0-9].*)')
sendm_relay = re.compile(r'.*to=.*relay=(.*)\[(.*)\], dsn|.*to=.*relay=(.*), dsn')
sendm_client = re.compile(r'.*from=.*relay=(.*)\[(.*)\]|.*from=.*relay=(.*)')

# exchange regexp
# TODO: these regexes ignore CSV quoting, a comma inside a quoted field (e.g. the subject) shifts columns
exch_to = re.compile(r'^[^#]([^,]*,){13}')
exch_from = re.compile(r'^[^#]([^,]*,){20}')
exch_subject = re.compile(r'^[^#]([^,]*,){19}')
exch_size = re.compile(r'^[^#]([^,]*,){15}')
exch_message_id = re.compile(r'^[^#]([^,]*,){11}')
#exch_status = re.compile(r'^[^#]([^,]*,){10}')
exch_status = re.compile(r'^[^#]([^,]*,){9}([^,]*,){13}')
#exch_relay = re.compile(r'^[^#]([^,]*,){26}')
exch_relay = re.compile(r'^[^#]([^,]*,){5}([^,]*,){21}')
#exch_client = re.compile(r'^[^#]([^,]*,){25}')
exch_client = re.compile(r'^[^#]([^,]*,){3}([^,]*,){22}')

# (to, from, subject, size, client, relay, status, message_id) per MTA
_REGEXES = {
    'postfix': (postf_to, postf_from, postf_subject, postf_size, postf_client, postf_relay, postf_status, postf_message_id),
    'exim': (exim_to, exim_from, exim_subject, exim_size, exim_client, exim_relay, exim_status, exim_message_id),
    'sendmail': (sendm_to, sendm_from, sendm_subject, sendm_size, sendm_client, sendm_relay, sendm_status, sendm_message_id),
    'exchange': (exch_to, exch_from, exch_subject, exch_size, exch_client, exch_relay, exch_status, exch_message_id),
}

if settings.mta == '':
    settings.mta = 'postfix'
if settings.mta not in _REGEXES:
    log.error('Incorrect value of MTA env variable: %s. Check example and set the correct one!', settings.mta)
    exit(1)

# kept for backwards compatibility (module level names used by older code)
find_to, find_from, find_subject, find_size, find_client, find_relay, find_status, find_message_id = _REGEXES[settings.mta]


########################################################################################################################
# Syslog header and timestamps
########################################################################################################################

_ts_iso = re.compile(
    r'(\d{4})-(\d{2})-(\d{2})([T ])(\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,9}))?(Z|[+-]\d{2}:?\d{2})?(?=[\s,]|$)'
)
"""RFC 3339 / ISO 8601 timestamp at the line start: 2026-10-26T06:28:47.155158+00:00, 2025-02-15 00:00:03.474"""
_ts_bsd = re.compile(r'([A-Z][a-z]{2})\s{1,2}(\d{1,2})\s(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(?=\s)')
"""BSD syslog timestamp at the line start: Oct 26 06:28:47"""
_MONTHS = {m: i for i, m in enumerate(('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), 1)}

_syslog_header = re.compile(r'\s+([^\s\[]+)\s+([\w./-]+)(?:\[([0-9]+)\])?:\s(.*)')
"""After a syslog timestamp: (1) hostname (2) program, e.g. postfix/submission/smtpd (3) pid (4) message"""


def _usec(frac: Optional[str]) -> int:
    if not frac:
        return 0
    return int((frac + '000000')[:6])


class TimestampParser:
    """
    Extract the timestamp at the start of a log line and return it as an aware UTC ``datetime``.

    Fast paths: RFC 3339 / ISO 8601 (offset honoured; :attr:`.tz` applied when there is none) and BSD syslog
    (no year: the current year is used, or the previous one if the result would be in the future).
    Fallback: ``datefinder`` on the first ``input_length`` characters (``DATETIME_INPUT_LENGTH``).
    """

    def __init__(self, tz=None, now: datetime = None, input_length: int = None):
        self.tz = tz if tz is not None else settings.log_timezone
        self.now = now if now is not None else datetime.now(timezone.utc)
        self.input_length = input_length if input_length is not None else settings.datetime_input_length
        self._offsets = {}
        self._local = {}
        self._bsd = {}

    def _localize(self, naive: datetime) -> datetime:
        if hasattr(self.tz, 'localize'):
            return self.tz.localize(naive).astimezone(timezone.utc)
        return naive.replace(tzinfo=self.tz).astimezone(timezone.utc)

    def _offset(self, off: str) -> timezone:
        tz = self._offsets.get(off)
        if tz is None:
            if off == 'Z':
                tz = timezone.utc
            else:
                sign = -1 if off[0] == '-' else 1
                digits = off[1:].replace(':', '')
                tz = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4])))
            self._offsets[off] = tz
        return tz

    def parse(self, line: str) -> Tuple[Optional[datetime], int, str]:
        """
        :return tuple: ``(timestamp or None, index right after the timestamp, kind)`` where kind is
                       ``iso`` (``T`` separator), ``iso-space``, ``bsd``, ``fallback`` or ``none``.
        """
        m = _ts_iso.match(line)
        if m is not None:
            y, mo, d, sep, hh, mi, ss, frac, off = m.groups()
            try:
                if off is not None:
                    dt = datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss), _usec(frac),
                                  tzinfo=self._offset(off)).astimezone(timezone.utc)
                else:
                    key = line[:19]
                    base = self._local.get(key)
                    if base is None:
                        base = self._localize(datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss)))
                        self._local[key] = base
                    dt = base + timedelta(microseconds=_usec(frac)) if frac else base
                return dt, m.end(), 'iso' if sep == 'T' else 'iso-space'
            except ValueError:
                pass
        m = _ts_bsd.match(line)
        if m is not None:
            key = m.group(0) if m.group(6) is None else line[:m.start(6) - 1]
            dt = self._bsd.get(key)
            if dt is None:
                dt = self._parse_bsd(*m.groups()[:5])
                if dt is not None:
                    self._bsd[key] = dt
            if dt is not None:
                if m.group(6):
                    dt = dt + timedelta(microseconds=_usec(m.group(6)))
                return dt, m.end(), 'bsd'
        dt = self.parse_fallback(line)
        return dt, 0, 'fallback' if dt is not None else 'none'

    def _parse_bsd(self, mon, day, hh, mi, ss) -> Optional[datetime]:
        month = _MONTHS.get(mon)
        if month is None:
            return None
        now = self.now
        for year in (now.year, now.year - 1):
            try:
                dt = self._localize(datetime(year, month, int(day), int(hh), int(mi), int(ss)))
            except ValueError:
                # Feb 29 in a non-leap year -> try the previous year
                continue
            if dt <= now + timedelta(days=1):
                return dt
        return None

    def parse_fallback(self, line: str) -> Optional[datetime]:
        try:
            for dt in datefinder.find_dates(line[:self.input_length]):
                if dt.tzinfo is None:
                    return self._localize(dt)
                return dt.astimezone(timezone.utc)
        except Exception:
            log.debug('datefinder failed on line %r', line[:self.input_length])
        return None


def split_syslog(line: str, pos: int):
    """
    Split ``hostname program[pid]: message`` starting at ``pos`` (right after the timestamp).

    :return: ``(host, program, pid, message)`` or ``None``
    """
    m = _syslog_header.match(line, pos)
    if m is None:
        return None
    return m.groups()


def service_from_program(program: str) -> str:
    """``postfix/submission/smtpd`` -> ``submission``, ``postfix/smtpd`` -> ``smtpd``, ``postfix/pickup`` -> ``pickup``"""
    if not program:
        return ''
    parts = program.split('/')
    if len(parts) >= 3:
        return parts[-2]
    return parts[-1]


########################################################################################################################
# Field extraction
########################################################################################################################

def _legacy_mail_to(lm: dict, to: Optional[str], orig_to: Optional[str]):
    """Legacy ``mail_to`` / ``mail_to_alias`` rules for a ``to=<..>[, orig_to=<..>]`` pair (postfix and exim)."""
    if orig_to is None:
        lm['mail_to'] = to
        return
    if to:
        # check if it is true alias
        if '@' not in to:
            to_check = to + '@' + orig_to.split('@', 1)[1] if '@' in orig_to else to
        else:
            to_check = to
        if orig_to != to_check:
            lm['mail_to_alias'] = {to_check: orig_to}
        lm['mail_to'] = to_check
    else:
        lm['mail_to'] = orig_to


def _postfix_relay(spec: str, status_text: str = '') -> dict:
    m = postf_relay.match(spec)
    if m is None:
        return dict(host='', ip='', port='')
    host, ip, port = m.groups()
    if host == 'none' and status_text and 'connect to ' in status_text:
        # relay=none after a failed connection: the attempted host is more useful (legacy behaviour)
        c = postf_connect_to.search(status_text)
        if c is not None:
            return dict(host=c.group(1), ip=c.group(2), port=c.group(3))
    return dict(host=host, ip=ip or '', port=port or '')


def parse_postfix(mline: str, program: Optional[str] = None) -> dict:
    """
    Parse the message part of a postfix line (the text after ``QID: ``).

    :param program: syslog program, e.g. ``postfix/smtp``. Selects which fields may be taken from the line.
                    When ``None`` every field regex is tried (legacy behaviour).
    :return dict: fields to merge into the message. ``_rcpt`` (if present) is a per-recipient delivery result.
    """
    lm = {}
    agent = program.rsplit('/', 1)[-1] if program else None
    anything = agent is None

    if mline.startswith('to=<') and (anything or agent in POSTFIX_DELIVERY_AGENTS):
        d = postf_delivery.match(mline)
        if d is not None:
            to, orig_to, mid, code, text = d.groups()
            text = text or ''
            _legacy_mail_to(lm, to, orig_to)
            relay = _postfix_relay(mid, text)
            lm['relay'] = relay
            lm['status'] = dict(code=code, message=text)
            rc = dict(to=to, orig_to=orig_to or '', status=dict(code=code, message=text), relay=dict(relay),
                      dsn='', delay=None, delays='', timestamp=None)
            m = postf_dsn.search(mid)
            if m is not None:
                lm['dsn'] = rc['dsn'] = m.group(1)
            m = postf_delay.search(mid)
            if m is not None:
                try:
                    lm['delay'] = rc['delay'] = float(m.group(1))
                except ValueError:
                    pass
            m = postf_delays.search(mid)
            if m is not None:
                lm['delays'] = rc['delays'] = m.group(1)
            lm['_rcpt'] = rc
        return lm

    if mline.startswith('client=') and (anything or agent in POSTFIX_SMTPD_AGENTS):
        m = postf_client.match(mline)
        if m is not None:
            lm['client'] = dict(host=m.group(1), ip=m.group(2))
        if 'sasl_' in mline:
            m = postf_sasl_method.search(mline)
            if m is not None:
                lm['sasl_method'] = m.group(1)
            m = postf_sasl_username.search(mline)
            if m is not None:
                lm['sasl_username'] = m.group(1)
        return lm

    if mline.startswith('from=<') and (anything or agent == 'qmgr'):
        m = postf_from.match(mline)
        if m is not None:
            lm['mail_from'] = m.group(1)
        m = postf_size.match(mline)
        if m is not None:
            lm['size'] = round(float(m.group(1)) / 1024, 2)
        m = postf_nrcpt.search(mline)
        if m is not None:
            lm['nrcpt'] = int(m.group(1))
        if 'status=' in mline:
            # qmgr: from=<..>, status=expired, returned to sender
            m = postf_status.match(mline)
            if m is not None and m.group(1) is not None:
                lm['status'] = dict(code=m.group(1), message=m.group(2) or '')
        return lm

    if mline.startswith('message-id=') and (anything or agent == 'cleanup'):
        m = postf_message_id.match(mline)
        if m is not None:
            lm['message_id'] = m.group(1)
        return lm

    if mline.startswith('reject:') or mline.startswith('milter-reject:'):
        m = postf_status.match(mline)
        if m is not None and m.group(3) is not None:
            lm['status'] = dict(code=m.group(3), message=m.group(4) or '')
        t = postf_reject_tail.match(mline)
        if t is not None:
            if '@' in t.group(1):
                lm['mail_from'] = t.group(1)
            lm['mail_to'] = t.group(2)
            if 'status' in lm and t.group(2):
                lm['_rcpt'] = dict(to=t.group(2), orig_to='', status=dict(lm['status']),
                                   relay=dict(host='', ip='', port=''), dsn='', delay=None, delays='', timestamp=None)
        if anything or agent in POSTFIX_SMTPD_AGENTS:
            c = postf_reject_client.match(mline)
            if c is not None:
                lm['client'] = dict(host=c.group(1), ip=c.group(2))
        # fall through: a rejected header line may also carry the subject

    if (anything or agent == 'cleanup') and 'header ' in mline:
        m = postf_subject.match(mline)
        if m is not None:
            lm['subject'] = m.group(1)
    return lm


def parse_opendkim(mline: str) -> Optional[dict]:
    """``DKIM-Signature field added (s=default, d=example.com)`` -> ``{domain, selector}``"""
    if not mline.startswith('DKIM-Signature'):
        return None
    m = opendkim_signed.match(mline)
    if m is None:
        return None
    return dict(domain=m.group(2), selector=m.group(1))


def _kib(value: str) -> Optional[float]:
    try:
        return round(float(value) / 1024, 2)
    except ValueError:
        return None


def parse_legacy(mline: str) -> dict:
    """Legacy field extraction for exim, sendmail and exchange (and postfix lines of an unknown program)."""
    mta = settings.mta
    find_to, find_from, find_subject, find_size, find_client, find_relay, find_status, find_message_id = _REGEXES[mta]
    lm = {}

    _to = find_to.match(mline)
    _from = find_from.match(mline)
    _subject = find_subject.match(mline)
    _size = find_size.match(mline)
    _client = find_client.match(mline)
    _relay = find_relay.match(mline)
    _status = find_status.match(mline)

    if _to is not None:
        if mta == 'exchange':
            lm['mail_to'] = _to.group(1)[:-1]
        elif mta == 'exim' or mta == 'postfix':
            if _to.group(3) is not None:
                lm['mail_to'] = _to.group(3)
            elif _to.group(1):
                _legacy_mail_to(lm, _to.group(1), _to.group(2))
            else:
                lm['mail_to'] = _to.group(2)
        else:
            # sendmail: the regex has a single group (the legacy code raised IndexError here)
            if _to.re.groups >= 2 and _to.group(2) is not None:
                lm['mail_to'] = _to.group(2)
            else:
                lm['mail_to'] = _to.group(1)

    if _subject is not None:
        if mta == 'exchange':
            lm['subject'] = _subject.group(1)[:-1]
        else:
            lm['subject'] = _subject.group(1)
    if _size is not None:
        size = _kib(_size.group(1)[:-1] if mta == 'exchange' else _size.group(1))
        if size is not None:
            lm['size'] = size

    if mta == 'exim':
        if _relay is not None:
            lm['relay'] = dict(host=_relay.group(1), ip=_relay.group(2), port=_relay.group(3))
        if _client is not None:
            # clear _client.group(1) and _client.group(2) from brackets if any
            if _client.group(3):
                lm['client'] = dict(host=re.sub('[^A-Za-z0-9 .]+', '', _client.group(1)), ip=re.sub('[^A-Za-z0-9 .]+', '', _client.group(2))+":"+_client.group(3))
            else:
                lm['client'] = dict(host=re.sub('[^A-Za-z0-9 .]+', '', _client.group(1)), ip=re.sub('[^A-Za-z0-9 .]+', '', _client.group(2)))
        if _from is not None:
            if _from.group(1) is not None:
                lm['mail_from'] = _from.group(1)
            if _from.group(2) is not None:
                lm['mail_from'] = _from.group(2)
        if _status is not None:
            status = None
            for code_group in (1, 3, 5, 7):
                if _status.group(code_group) is not None:
                    status = dict(code=_status.group(code_group), message="")
            if status is not None:
                code = status['code']
                if code == '=>' or code == '->':
                    status['code'] = 'sent'
                elif code == 'rejected':
                    status['code'] = 'reject'
                elif code == '**':
                    status['code'] = 'bounced'
                elif code == '==':
                    status['code'] = 'deferred'
                for msg_group in (2, 4, 6, 8):
                    if _status.group(msg_group) is not None:
                        status['message'] = _status.group(msg_group)
                lm['status'] = status

    elif mta == 'exchange':
        if _from is not None: lm['mail_from'] = _from.group(1)[:-1]
        if _relay is not None: lm['relay'] = dict(host=_relay.group(1)[:-1], ip=_relay.group(2)[:-1])
        if _client is not None: lm['client'] = dict(host=_client.group(1)[:-1], ip=_client.group(2)[:-1])
        if _status is not None and _status.group(1) is not None:
            event = _status.group(1)[:-1].lower()
            code = None
            if 'deliver' in event or event in ('process', 'receive', 'redirect', 'send', 'submit'):
                code = 'sent'
            elif 'fail' in event or 'discard' in event or 'reject' in event or event in ('suppressed', 'drop'):
                code = 'reject'
            elif 'redirect' in event or event == 'dsn':
                code = 'bounced'
            elif 'defer' in event:
                code = 'deferred'
            # other events (AGENTINFO, EXPAND, RESOLVE, TRANSFER, ...) do not change the status
            if code is not None:
                lm['status'] = dict(code=code, message="")
                if _status.group(2) is not None and _status.group(2)[:-1] != "":
                    lm['status']['message'] = _status.group(2)[:-1]

    elif mta == 'postfix':
        if _relay is not None: lm['relay'] = dict(host=_relay.group(1), ip=_relay.group(2) or '', port=_relay.group(3) or '')
        if _client is not None: lm['client'] = dict(host=_client.group(1), ip=_client.group(2))
        if _from is not None: lm['mail_from'] = _from.group(1)
        if _status is not None:
            if _status.group(1) is not None: lm['status'] = dict(code=_status.group(1), message=_status.group(2) or "")
            if _status.group(3) is not None: lm['status'] = dict(code=_status.group(3), message=_status.group(4) or "")

    elif mta == 'sendmail':
        if _from is not None: lm['mail_from'] = _from.group(1)
        if _client is not None:
            if _client.group(3) is not None:
                lm['client'] = dict(host=_client.group(3), ip="unknown")
            else:
                lm['client'] = dict(host=_client.group(1), ip=_client.group(2))
        if _relay is not None:
            if _relay.group(3) is not None:
                lm['relay'] = dict(host=_relay.group(3), ip="unknown")
            else:
                lm['relay'] = dict(host=_relay.group(1), ip=_relay.group(2))
        if _status is not None:
            if _status.group(1) is not None: lm['status'] = dict(code=_status.group(1).lower(), message="")
            if _status.group(3) is not None: lm['status'] = dict(code=_status.group(3).lower(), message="")
            if 'status' in lm:
                if _status.group(2) is not None: lm['status']['message'] = _status.group(2)
                if _status.group(4) is not None: lm['status']['message'] = _status.group(4)

    _message_id = find_message_id.match(mline)
    if _message_id is not None:
        if mta == 'exchange':
            lm['message_id'] = _message_id.group(1)[:-1]
        else:
            lm['message_id'] = _message_id.group(1)
    return lm


def parse_message(mline: str, program: Optional[str] = None) -> dict:
    """Parse the message part of one log line (sync). See :func:`parse_postfix` for ``program``."""
    if settings.mta == 'postfix':
        if program is None:
            # unknown line type: legacy extraction, but with the fixed relay/client regexes
            lm = parse_legacy(mline)
            d = parse_postfix(mline, None)
            lm.update(d)
            return lm
        return parse_postfix(mline, program)
    return parse_legacy(mline)


async def parse_line(mline, program: Optional[str] = None) -> dict:
    """Backwards compatible async wrapper around :func:`parse_message`."""
    return parse_message(mline, program)
