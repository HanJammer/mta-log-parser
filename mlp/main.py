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

Log importer: reads the configured log files, groups lines into messages and saves them into RethinkDB.
"""
import base64
from email.header import decode_header, make_header
import glob
import gzip
import hashlib
import json
import logging
import os
import quopri
import re
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, Iterable, List, Optional, Union

import rethinkdb.query

from mlp import settings
from mlp.core import get_rethink
from mlp.objects import PostfixLog, PostfixMessage
from mlp.parser import (
    TimestampParser, parse_message, parse_opendkim, service_from_program, split_syslog, tls_established,
)

log = logging.getLogger(__name__)

# !!! change version upon update !!!
global VERSION
VERSION = "1.8.5"

lockfile = settings.lock_file
"""Absolute path of the lock file that exists while the importer runs (read by the web UI)"""

postf_match = r'.*postfix.*\[.+\]\:[ \t](?!statistics|warning)([A-Za-z0-9]{8,15}|NOQUEUE)\:[ \t]+?(.*)'
"""Legacy regex (used when a line has no syslog header) to match the (1) Queue ID and the (2) Log Message"""

# exim regexp (for syslog and separate mainlog)
exim_match = r'([0-9A-Za-z]{6}-[0-9A-Za-z]{6,11}-[0-9A-Za-z]{2,4})\s(.+)'
"""Regex to match the (1) Message ID and the (2) Log Message"""

# sendmail regexp
sendm_match = r'.*\:\s([0-9A-Za-z]+)\:[ \t]+?(.*)'
"""Regex to match the (1) Queue ID and the (2) Log Message"""

# exchange regexp
exch_match = r'([^#]([^,]*,){12}.+)'
"""Regex to match the (2) message ID and the (1) Log Message"""

if settings.mta == '': settings.mta = 'postfix'

_MATCHES = {'postfix': postf_match, 'exim': exim_match, 'sendmail': sendm_match, 'exchange': exch_match}
if settings.mta not in _MATCHES:
    log.error('Incorrect value of MTA env variable: %s. Check example and set the correct one!', settings.mta)
    exit(1)

match = re.compile(_MATCHES[settings.mta])

_postf_qid = re.compile(r'(?!statistics|warning)([A-Za-z0-9]{8,15}|NOQUEUE):[ \t]+(.*)')
"""Postfix: (1) queue id (2) message, applied to the text after ``program[pid]: ``"""
_postf_program = re.compile(r'(\S*postfix\S*?)\[([0-9]+)\]:')

_MAX_LOGGED_BAD_LINES = 10


class ObjectExists(BaseException):
    pass


class OnConflict(Enum):
    QUIET = "quiet"
    EXCEPT = "except"
    UPDATE = "update"


async def save_obj(table, data, primary=None, onconflict: OnConflict = OnConflict.EXCEPT):
    """Save a single object (kept for compatibility; the importer uses :func:`save_documents`)."""
    r, conn, _ = await get_rethink()
    _data = dict(data)
    if primary is not None:
        if 'id' not in _data: _data['id'] = _data[primary]
        g = await r.table(table).get(data[primary]).run(conn, array_limit=settings.rethink_arr_limit)

        if g is not None:
            if onconflict == OnConflict.QUIET:
                return None
            if onconflict == OnConflict.EXCEPT:
                raise ObjectExists(f"Table '{table}' entry with '{primary} = {data[primary]}' already exists!")
            if onconflict == OnConflict.UPDATE:
                return await r.table(table).get(data[primary]).update(_data).run(conn, array_limit=settings.rethink_arr_limit)
            raise AttributeError("'saveobj' onconflict must be either 'quiet', 'except', or 'update'")
    return await r.table(table).insert(_data).run(conn, array_limit=settings.rethink_arr_limit)


def _housekeeping_days(value=None) -> Optional[int]:
    """Return the configured housekeeping period in days, or ``None`` when housekeeping is disabled."""
    value = settings.housekeeping_days if value is None else value
    if value is None or value == '':
        return None
    try:
        days = int(value)
    except (TypeError, ValueError):
        log.warning('Invalid HOUSEKEEPING_DAYS value %r - housekeeping disabled', value)
        return None
    if days <= 0:
        log.warning('HOUSEKEEPING_DAYS=%d is <= 0 - housekeeping disabled (it would delete everything)', days)
        return None
    return days


""" samoilov housekeeping function"""
async def housekeeping(housekeeping_days):
    a = datetime.now(timezone.utc) - timedelta(days=housekeeping_days)
    log.info('According to the configured housekeeping days variable there will be deleted all logs before %s', a)
    result = {}
    log.info('Making DB cleanup query')
    r, conn, r_q = await get_rethink()
    r_q: rethinkdb.query
    _sm = r.table('sent_mail')
    # optimized cleanup query using between
    _sm = _sm.between(r_q.minval, a, right_bound='closed', index='timestamp').delete()
    _sm = await _sm.run(conn, array_limit=settings.rethink_arr_limit)
    result['deleted'] = _sm['deleted']
    result['status'] = 'true' if result['deleted'] != 0 else 'false'
    return result


########################################################################################################################
# Log files
########################################################################################################################

def _has_magic(pattern: str) -> bool:
    return any(c in pattern for c in '*?[')


def resolve_log_files(log_path: str = None, patterns: Iterable[str] = None) -> List[str]:
    """
    Expand ``MAIL_LOG_FILENAME`` (comma separated names / glob patterns, relative to ``MAIL_LOG_PATH``) into the list
    of existing files, oldest first (modification time), without duplicates.
    """
    log_path = settings.mail_log_path if log_path is None else log_path
    if patterns is None:
        patterns = settings.mail_log_filenames
    elif isinstance(patterns, str):
        patterns = [p.strip() for p in patterns.split(',') if p.strip()]
    found = []
    for pat in patterns:
        full = pat if os.path.isabs(pat) else os.path.join(log_path, pat)
        if _has_magic(full):
            matches = sorted(f for f in glob.glob(full) if os.path.isfile(f))
            if not matches:
                log.warning('No log files match %s', full)
        elif os.path.isfile(full):
            matches = [full]
        else:
            log.warning('Log file %s does not exist - skipping it', full)
            matches = []
        for f in matches:
            f = os.path.abspath(f)
            if f not in found:
                found.append(f)

    def _mtime(f):
        try:
            return os.path.getmtime(f)
        except OSError:
            return 0
    found.sort(key=_mtime)
    return found


def _open_log(path: str):
    if path.endswith('.gz'):
        return gzip.open(path, 'rb')
    return open(path, 'rb')


########################################################################################################################
# Import
########################################################################################################################

class LogImporter:
    """
    Groups log lines into :class:`.PostfixMessage` objects keyed by ``"<host>:<queue_id>"`` (``queue_id`` when the
    host is unknown). One instance can be fed several files; their messages are merged.
    """

    def __init__(self, mta: str = None, host_name: str = None, now: datetime = None, tz=None):
        self.mta = mta or settings.mta
        self.host_name = settings.mail_host_name if host_name is None else host_name
        self.ts = TimestampParser(tz=tz, now=now)
        self._match = match if self.mta == settings.mta else re.compile(_MATCHES[self.mta])
        self.messages: Dict[str, PostfixMessage] = {}
        # legacy multiple recipients detection
        self.multiple_recipients_qids = []
        self.multiple_recipients = defaultdict(list)
        self.counter = 0
        self.same_qid = ''
        # (host, program, pid) -> peer ip of the last "TLS connection established" line
        self._tls = {}
        self.stats = Counter()

    # ------------------------------------------------------------------------------------------------------------
    def feed_file(self, path: str) -> bool:
        log.info('Opening log file %s', path)
        try:
            with _open_log(path) as f:
                for raw in f:
                    self.feed_line(raw.decode(errors='replace'))
        except OSError as e:
            log.warning('Cannot read log file %s (%s) - skipping it', path, e)
            return False
        finally:
            self._flush_multiple()
        self.stats['files'] += 1
        log.info('Finished parsing log file %s', path)
        return True

    def feed_line(self, line: str):
        line = line.rstrip('\r\n')
        if not line:
            return
        self.stats['lines'] += 1
        try:
            if self.mta == 'postfix':
                self._feed_postfix(line)
            else:
                self._feed_other(line)
        except Exception:
            self.stats['errors'] += 1
            if self.stats['errors'] <= _MAX_LOGGED_BAD_LINES:
                log.exception('Error while parsing log line, skipping it: %r', line[:500])

    def _no_timestamp(self, line: str):
        self.stats['no_timestamp'] += 1
        if self.stats['no_timestamp'] <= _MAX_LOGGED_BAD_LINES:
            log.warning('No date/time found in log line, skipping it: %r', line[:200])

    # ------------------------------------------------------------------------------------------------------------
    def _feed_postfix(self, line: str):
        if 'postfix' not in line and 'opendkim' not in line:
            return
        dtime, pos, kind = self.ts.parse(line)
        hdr = split_syslog(line, pos) if kind == 'iso' or kind == 'bsd' else None
        if hdr is not None:
            host, program, pid, rest = hdr
            is_dkim = program == 'opendkim'
            if not is_dkim and 'postfix' not in program:
                return
            m = _postf_qid.match(rest)
            if m is None:
                if not is_dkim:
                    self._track_tls(host, program, pid, rest)
                return
            qid, msg = m.groups()
        else:
            # no syslog header (or an unknown one): legacy regex, host from MAIL_HOST_NAME
            m = self._match.match(line)
            if m is None:
                return
            qid, msg = m.groups()
            pm = _postf_program.search(line)
            program, pid = pm.groups() if pm is not None else (None, None)
            host = self.host_name
            is_dkim = False
        if dtime is None:
            self._no_timestamp(line)
            return

        noqueue = qid == 'NOQUEUE'
        if noqueue:
            # process postfix NOQUEUE, generate new qid based on host, msg and timestamp
            qid = hashlib.md5(((host or '') + str(dtime) + msg).encode('utf-8')).hexdigest().upper()[0:11]
        key = f'{host}:{qid}' if host else qid
        message = self.messages.get(key)
        if message is None:
            message = self.messages[key] = PostfixMessage(timestamp=dtime, queue_id=qid, host=host or '')

        if is_dkim:
            dkim = parse_opendkim(msg)
            if dkim is not None:
                message.dkim = dkim
            message.lines.append(PostfixLog(timestamp=dtime, queue_id=qid, message=msg))
            return

        lm = parse_message(msg, program)
        rcpt = lm.pop('_rcpt', None)
        message.merge(lm)
        if rcpt is not None:
            rcpt['timestamp'] = dtime
            message.add_recipient(rcpt)
        if not message.service and program and (noqueue or msg.startswith('client=') or msg.startswith('uid=')):
            message.service = service_from_program(program)
        if pid is not None and program:
            self._message_tls(message, host, program, pid, msg, lm)

        if not noqueue:
            self._legacy_multiple(key, message, msg)
        message.lines.append(PostfixLog(timestamp=dtime, queue_id=qid, message=msg))

    def _track_tls(self, host, program, pid, rest: str):
        if pid is None:
            return
        if 'TLS connection established' in rest:
            m = tls_established.match(rest)
            if m is not None:
                self._tls[(host, program, pid)] = m.group(1)
        elif rest.startswith('disconnect from'):
            self._tls.pop((host, program, pid), None)

    def _message_tls(self, message: PostfixMessage, host, program, pid, msg: str, lm: dict):
        if msg.startswith('client='):
            peer = lm.get('client', {}).get('ip')
        elif msg.startswith('to=<') and program.rsplit('/', 1)[-1] == 'smtp':
            peer = lm.get('relay', {}).get('ip')
        else:
            return
        tls_peer = self._tls.get((host, program, pid))
        if tls_peer is not None and tls_peer == peer:
            message.tls = True
        elif message.tls is None:
            message.tls = False

    # ------------------------------------------------------------------------------------------------------------
    def _feed_other(self, line: str):
        mta = self.mta
        m = self._match.search(line) if mta == 'exim' else self._match.match(line)
        if not m:
            return
        dtime, pos, kind = self.ts.parse(line)
        if dtime is None:
            self._no_timestamp(line)
            return
        host = None
        if kind == 'iso' or kind == 'bsd':
            hdr = split_syslog(line, pos)
            if hdr is not None:
                host = hdr[0]
        if not host:
            host = self.host_name

        if mta == 'exchange':
            msg, qid = m.groups()
            qid = qid[:-1]
        else:
            qid, msg = m.groups()
        key = f'{host}:{qid}' if host else qid
        message = self.messages.get(key)
        if message is None:
            message = self.messages[key] = PostfixMessage(timestamp=dtime, queue_id=qid, host=host or '')
        message.merge(parse_message(msg))
        # remove commas for ms exchange log
        if mta == 'exchange' and message.mail_to:
            message.mail_to = message.mail_to.replace(",", "")
        self._legacy_multiple(key, message, msg)
        message.lines.append(PostfixLog(timestamp=dtime, queue_id=qid, message=msg))

    # ------------------------------------------------------------------------------------------------------------
    def _legacy_multiple(self, key: str, message: PostfixMessage, msg: str):
        """
        Legacy detection of messages with several recipients (``mail_to`` becomes a JSON list, status ``multiple``).

        It only sees consecutive lines of the same message (as in the original code); ``recipients`` is the reliable
        per-recipient data.
        """
        checking_mailto_alias = {}
        if self.mta in ('postfix', 'exim') and message.mail_to_alias:
            alias = message.mail_to_alias.get(message.mail_to)
            if alias is not None:
                # samoilov test append mail_to_alias into every mail_to
                checking_mailto_alias[key] = dict(mail_to=message.mail_to, mail_to_alias=alias)

        checking_mailto = message.mail_to
        if key == self.same_qid or self.same_qid == '':
            if message.status.get('code') is not None:
                # check if there are already recipients in message and there are recipients parsed
                if checking_mailto != '' and checking_mailto is not None:
                    if checking_mailto in msg or checking_mailto.split('@')[0] in msg:
                        # don't add email duplicates
                        if checking_mailto not in self.multiple_recipients[self.same_qid]:
                            self.same_qid = key
                            self.counter += 1
                            # add alias dict if any
                            if checking_mailto_alias:
                                checking_mailto = checking_mailto_alias[key]
                            self.multiple_recipients[self.same_qid].append(checking_mailto)
        else:
            if self.counter > 1:
                self.multiple_recipients_qids.append(self.same_qid)
            self.counter = 0
            self.same_qid = ''

    def _flush_multiple(self):
        # fix for the last log line if multiple
        if self.counter > 1:
            self.multiple_recipients_qids.append(self.same_qid)
        self.counter = 0
        self.same_qid = ''

    def result(self) -> dict:
        qids = set(self.multiple_recipients_qids)
        multiple_recipients = defaultdict(list, {k: v for k, v in self.multiple_recipients.items() if k in qids})
        return dict(
            messages=self.messages,
            multiple_recipients_qids=self.multiple_recipients_qids,
            multiple_recipients=multiple_recipients,
            stats=dict(self.stats),
        )


async def import_log(logfile: Union[str, Iterable[str]], **kwargs) -> dict:
    """
    Parse one log file or a list of log files.

    :return dict: ``messages`` (``{id: PostfixMessage}``), ``multiple_recipients_qids``, ``multiple_recipients``,
                  ``stats``
    """
    files = [logfile] if isinstance(logfile, str) else list(logfile)
    importer = LogImporter(**kwargs)
    for f in files:
        importer.feed_file(f)
    out = importer.result()
    st = out['stats']
    log.info('Parsed %d file(s), %d lines, %d messages (%d lines without timestamp, %d lines with errors)',
             st.get('files', 0), st.get('lines', 0), len(out['messages']), st.get('no_timestamp', 0), st.get('errors', 0))
    return out


""" samoilov subject decoder fixed"""
pat2 = re.compile(r'(([^=]*)=\?([^\?]*)\?([BbQq])\?([^\?]*)([^=]*))', re.IGNORECASE)


def decodev2(a):
    """Decode RFC 2047 encoded words in a subject (``=?UTF-8?B?...?=``)."""
    if not a or '=?' not in a:
        return a
    try:
        return str(make_header(decode_header(a)))
    except Exception:
        # e.g. an unknown charset or an encoded word truncated by the MTA
        try:
            return _decode_legacy(a)
        except Exception:
            return a


def _decode_legacy(a):
    data = pat2.findall(a)
    line = []
    if data:
        for g in data:
            (raw, extra1, encoding, method, string, extra) = g
            extra1 = extra1.replace('\r', '').replace('\n', '').strip()
            if len(extra1) > 0:
                line.append(extra1)
            if method.lower() == 'q':
                string = quopri.decodestring(string)
            if method.lower() == 'b':
                # samoilov fix of padding errors
                string = f"{string}{'=' * (-len(string) % 4)}"
                string = base64.b64decode(string)
            line.append(string.decode(encoding, errors='ignore'))
            extra = extra.replace('\r', '').replace('\n', '').strip()
            if len(extra) > 0:
                line.append(extra)
        return "".join(line)
    else:
        return a


def _domain(addr) -> str:
    if not addr or '@' not in addr:
        return ''
    return addr.split('@')[1]


_KNOWN_STATUSES = ('sent', 'reject', 'deferred', 'bounced', 'multiple')


def build_document(key: str, msg: PostfixMessage, multiple_recipients: dict, convert_time=False) -> Optional[dict]:
    """Turn a parsed message into the ``sent_mail`` document, or ``None`` if it is ignored (``IGNORE_DOMAINS``)."""
    m = {"id": key, **msg.clean_dict(convert_time=convert_time)}
    # check and process status
    status = dict(m.get('status') or {})
    if status:
        if status.get('code') not in _KNOWN_STATUSES:
            if not status.get('message'):
                status['message'] = 'no status message found'
            else:
                status['message'] = str(status.get('code')) + status['message']
            status['code'] = "unknown"
    else:
        status = dict(code="unknown", message="no status message found")
    m['status'] = status
    """subject decoder"""
    try:
        m['subject'] = decodev2(m.get('subject'))
    except Exception:
        m['subject'] = m.get('subject')

    if _domain(m.get('mail_from')) in settings.ignore_domains or _domain(m.get('mail_to')) in settings.ignore_domains:
        return None
    recipients = [r for r in (m.get('recipients') or []) if r.get('to')]
    if settings.legacy_multiple_status or not recipients:
        # check if there are many recipients (legacy detection, consecutive delivery lines only)
        if key in multiple_recipients:
            m['mail_to'] = json.dumps(multiple_recipients[key])
            m['status']['code'] = 'multiple'
            m['status']['message'] = 'multiple, see log lines below'
        return m
    _aggregate_recipients(m, recipients, multiple_recipients.get(key))
    return m


# Worst first: the message status is the status of its worst recipient delivery.
_RCPT_SEVERITY = {'bounced': 5, 'expired': 5, 'reject': 4, 'deferred': 3, 'sent': 1}


def _rcpt_rank(r: dict) -> int:
    return _RCPT_SEVERITY.get((r.get('status') or {}).get('code'), 2)


def _network_relay(r: dict) -> bool:
    rel = r.get('relay') or {}
    ip = str(rel.get('ip') or '')
    return bool(ip) and not ip.startswith('private/') and rel.get('host') not in ('', 'none', 'local')


def _aggregate_recipients(m: dict, recipients: list, legacy_list: list = None):
    """
    Derive message level ``status``, ``relay`` and ``mail_to`` from the per recipient deliveries.

    A message to several recipients (e.g. an always_bcc archive copy plus the real recipient) gets the status of its
    worst delivery (bounced > reject > deferred > sent) instead of the legacy catch-all ``multiple`` (set
    ``LEGACY_MULTIPLE_STATUS=true`` to keep the old behaviour); ``multiple`` is then a separate boolean field.
    The message ``relay`` prefers a network relay over local/LMTP hand-offs.
    """
    worst = max(recipients, key=_rcpt_rank)
    rank = _rcpt_rank(worst)
    code = (worst.get('status') or {}).get('code')
    if code == 'expired':
        code = 'bounced'
    if code in _KNOWN_STATUSES:
        m['status'] = dict(code=code, message=(worst.get('status') or {}).get('message') or '')
    # the delivery that represents the message: the worst one if something failed, else the last network delivery
    net = [r for r in recipients if _network_relay(r)]
    if rank > 1:
        primary = worst
    else:
        primary = net[-1] if net else recipients[-1]
    for k in ('dsn', 'delay', 'delays'):
        if primary.get(k) not in (None, ''):
            m[k] = primary[k]
    if _network_relay(primary):
        m['relay'] = dict(primary.get('relay'))
    elif net:
        m['relay'] = dict(net[-1].get('relay'))

    addresses = []
    for r in recipients:
        if r['to'] not in addresses:
            addresses.append(r['to'])
    m['multiple'] = len(addresses) > 1
    if m['multiple']:
        if len(addresses) > 1 and m['status']['code'] != 'unknown':
            counts = defaultdict(int)
            for r in recipients:
                counts[(r.get('status') or {}).get('code') or 'unknown'] += 1
            summary = ', '.join(f'{v} {k}' for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
            m['status']['message'] = f'{len(addresses)} recipients: {summary}. ' + (m['status'].get('message') or '')
        # legacy JSON list (aliases kept when the legacy detection found them)
        m['mail_to'] = json.dumps(legacy_list if legacy_list and len(legacy_list) >= len(addresses) else addresses)
    else:
        m['mail_to'] = addresses[0]


def build_documents(import_output: dict, convert_time=False) -> List[dict]:
    """Build all ``sent_mail`` documents; a message that fails is logged and skipped."""
    multiple_recipients = import_output['multiple_recipients']
    docs = []
    for key, msg in import_output['messages'].items():
        try:
            d = build_document(key, msg, multiple_recipients, convert_time=convert_time)
        except Exception:
            log.exception('Error while preparing message %s - skipping it', key)
            continue
        if d is not None:
            docs.append(d)
    return docs


async def save_documents(docs: List[dict], batch_size: int = None) -> Counter:
    """Upsert documents into ``sent_mail`` with batched ``insert(..., conflict='update')``."""
    r, conn, _ = await get_rethink()
    batch_size = batch_size or settings.import_batch_size
    totals = Counter()
    table = r.table('sent_mail')

    async def _insert(chunk):
        res = await table.insert(chunk, conflict='update').run(conn, array_limit=settings.rethink_arr_limit)
        for k in ('inserted', 'replaced', 'unchanged', 'errors'):
            totals[k] += res.get(k, 0)
        if res.get('errors'):
            log.error('RethinkDB reported %d error(s) while saving messages, first: %s', res['errors'], res.get('first_error'))

    for i in range(0, len(docs), batch_size):
        chunk = docs[i:i + batch_size]
        try:
            await _insert(chunk)
        except Exception:
            log.exception('Batch insert of %d messages failed - retrying them one by one', len(chunk))
            for d in chunk:
                try:
                    await _insert([d])
                except Exception:
                    totals['errors'] += 1
                    log.exception('Could not save message %s - skipping it', d.get('id'))
    return totals


async def main():
    lock_created = False
    try:
        if settings.gui_refresh_block:
            log.info('Blocking GUI updates while processing')
            os.makedirs(os.path.dirname(lockfile), exist_ok=True)
            with open(lockfile, "w"):
                pass
            lock_created = True

        r, conn, r_q = await get_rethink()

        """housekeeping from old logs"""
        housekeeping_days = _housekeeping_days()
        if housekeeping_days is not None:
            log.info('Start housekeeping')
            try:
                hk_result = await housekeeping(housekeeping_days)
                log.info('Finished housekeeping')
                if hk_result['status'] == 'true':
                    log.info('Housekeeping has successfully deleted %d messages older then %d day(s)', hk_result['deleted'], housekeeping_days)
                else:
                    log.info('Housekeeping has deleted NOTHING. There are no emails %d day(s) ago or something went wrong.', housekeeping_days)
            except Exception:
                log.exception('Housekeeping failed - continuing with the import')
        else:
            log.info('Housekeeping is not configured so there will be no deletion of old data! Pay attention to the disk space!')

        files = resolve_log_files()
        if not files:
            log.error('No log files found (MAIL_LOG_PATH=%s, MAIL_LOG_FILENAME=%s)', settings.mail_log_path, settings.mail_log_filename)
            return
        log.info('Importing %s log file(s): %s', settings.mta, ', '.join(files))
        import_output = await import_log(files)

        log.info('Converting %s log data into documents', settings.mta)
        docs = build_documents(import_output, convert_time=False)
        log.info('Total of %d message entries, saving in batches of %d', len(docs), settings.import_batch_size)
        totals = await save_documents(docs)
        log.info('Saved: %d inserted, %d replaced, %d unchanged, %d errors',
                 totals['inserted'], totals['replaced'], totals['unchanged'], totals['errors'])
        log.info('Finished!')
    finally:
        if lock_created:
            log.info('Unblocking GUI updates')
            try:
                os.remove(lockfile)
            except FileNotFoundError:
                pass
