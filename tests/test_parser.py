import asyncio
import gzip
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta

import pytest
import pytz

from conftest import fixture_path, ROOT

from mlp import settings
from mlp import main as mlp_main
from mlp.main import LogImporter, build_document, build_documents, import_log, resolve_log_files, decodev2
from mlp.parser import TimestampParser, parse_postfix, parse_legacy, service_from_program, split_syslog

UTC = timezone.utc


def _import(*names, **kwargs):
    imp = LogImporter(**kwargs)
    for n in names:
        assert imp.feed_file(fixture_path(n))
    return imp.result()


@pytest.fixture(scope='module')
def rfc():
    out = _import('postfix_rfc3339.log')
    docs = {d['id']: d for d in build_documents(out, convert_time=False)}
    return out, docs


# ----------------------------------------------------------------------------------------------------------------------
# The issue #30 example
# ----------------------------------------------------------------------------------------------------------------------

def test_issue_example_fields(rfc):
    _, docs = rfc
    d = docs['mx1:25CF61E7BCF']
    assert d['queue_id'] == '25CF61E7BCF'
    assert d['host'] == 'mx1'
    assert d['client'] == {'host': 'unknown', 'ip': '192.168.140.50'}
    assert d['sasl_method'] == 'login'
    assert d['sasl_username'] == 'dms@example.com'
    assert d['service'] == 'submission'
    assert d['message_id'] == ''
    assert d['mail_from'] == 'dms@example.com'
    assert d['size'] == round(3799 / 1024, 2)
    assert d['nrcpt'] == 2
    assert d['dkim'] == {'domain': 'example.com', 'selector': 'default'}
    # message level: last delivery line
    assert d['relay'] == {'host': 'example-com.mail.protection.outlook.com', 'ip': '52.101.91.156', 'port': '25'}
    assert d['dsn'] == '2.6.0'
    assert d['delay'] == 1.9
    assert d['delays'] == '0.12/0.01/0.37/1.4'
    assert d['tls'] is True
    assert d['timestamp'] == datetime(2026, 10, 26, 6, 28, 47, 155158, tzinfo=UTC)
    assert d['first_attempt'] == d['timestamp']
    assert d['last_attempt'] == datetime(2026, 10, 26, 6, 28, 49, 82321, tzinfo=UTC)
    # opendkim line is kept in the raw lines
    assert any(l['message'].startswith('DKIM-Signature') for l in d['lines'])
    assert len(d['lines']) == 7


def test_issue_example_recipients(rfc):
    _, docs = rfc
    rc = docs['mx1:25CF61E7BCF']['recipients']
    assert [r['to'] for r in rc] == ['backup@archive.example', 'john.doe@example.com']
    lmtp, smtp = rc
    assert lmtp['relay'] == {'host': 'mail.example.com', 'ip': 'private/dovecot-lmtp', 'port': ''}
    assert lmtp['status']['code'] == 'sent'
    assert lmtp['dsn'] == '2.0.0' and lmtp['delay'] == 0.82 and lmtp['delays'] == '0.12/0.02/0.02/0.66'
    assert lmtp['orig_to'] == ''
    assert smtp['relay']['ip'] == '52.101.91.156'
    assert smtp['status']['code'] == 'sent'
    assert smtp['status']['message'].startswith('(250 2.6.0 <00000000-1111-2222')
    assert smtp['timestamp'] == datetime(2026, 10, 26, 6, 28, 49, 80848, tzinfo=UTC)


def test_multiple_recipients_get_aggregated_status(rfc):
    out, docs = rfc
    d = docs['mx1:1A2B3C4D5E6']
    assert d['status']['code'] == 'sent'
    assert d['status']['message'].startswith('2 recipients: 2 sent.')
    assert d['multiple'] is True
    assert json.loads(d['mail_to']) == ['bob@example.com', 'carol@example.com']


def test_legacy_multiple_status_setting(rfc, monkeypatch):
    from mlp import settings
    from mlp.main import build_document
    out, _ = rfc
    monkeypatch.setattr(settings, 'legacy_multiple_status', True)
    d = build_document('mx1:1A2B3C4D5E6', out['messages']['mx1:1A2B3C4D5E6'], out['multiple_recipients'])
    assert d['status'] == {'code': 'multiple', 'message': 'multiple, see log lines below'}
    assert json.loads(d['mail_to']) == ['bob@example.com', 'carol@example.com']
    assert [r['to'] for r in d['recipients']] == ['bob@example.com', 'carol@example.com']
    assert d['subject'] == 'Quarterly report'
    assert d['nrcpt'] == 2
    assert 'mx1:1A2B3C4D5E6' in out['multiple_recipients_qids']


def test_offset_is_honoured(rfc):
    _, docs = rfc
    # 07:00:00.200000+02:00
    assert docs['mx1:1A2B3C4D5E6']['timestamp'] == datetime(2026, 10, 26, 5, 0, 0, 200000, tzinfo=UTC)


# ----------------------------------------------------------------------------------------------------------------------
# Delivery variants
# ----------------------------------------------------------------------------------------------------------------------

def test_bounced_relay_none(rfc):
    _, docs = rfc
    d = docs['mx1:E45B11E09E3']
    assert d['status']['code'] == 'bounced'
    assert d['relay'] == {'host': 'none', 'ip': '', 'port': ''}
    assert d['dsn'] == '5.4.4'
    assert d['recipients'][0]['relay']['host'] == 'none'
    assert d['recipients'][0]['status']['code'] == 'bounced'


def test_deferred_latest_attempt_wins(rfc):
    _, docs = rfc
    d = docs['mx1:951791EA2D5']
    assert d['status']['code'] == 'deferred'
    assert len(d['recipients']) == 1
    r = d['recipients'][0]
    assert r['delay'] == 680.0 and r['delays'] == '544/0.01/136/0'
    assert r['timestamp'] == datetime(2026, 10, 27, 13, 15, 21, 488042, tzinfo=UTC)
    assert d['delay'] == 680.0


def test_orig_to_and_pickup(rfc):
    _, docs = rfc
    d = docs['mx1:CC4E31E7824']
    assert d['service'] == 'pickup'
    assert d['client'] == {}
    assert d['mail_to'] == 'root@example.com'
    assert d['mail_to_alias'] == {'root@example.com': 'root'}
    assert d['recipients'][0]['orig_to'] == 'root'
    assert d['tls'] is False


def test_discard(rfc):
    _, docs = rfc
    d = docs['mx1:0B2451E06C4']
    assert d['status'] == {'code': 'sent', 'message': '(example.org)'}
    assert d['relay']['host'] == 'none'
    assert d['service'] == 'smtpd'


def test_noqueue_reject_includes_host(rfc):
    out, docs = rfc
    rejects = [d for d in docs.values() if d['status']['code'] == 'reject']
    assert len(rejects) == 1
    d = rejects[0]
    assert d['id'] == 'mx1:' + d['queue_id'] and len(d['queue_id']) == 11
    assert d['mail_from'] == 'spammer@example.net'
    assert d['mail_to'] == 'victim@example.net'
    assert d['client'] == {'host': 'unknown', 'ip': '203.0.113.7'}
    assert d['status']['message'] == '554 5.7.1 <victim@example.net>: Relay access denied'
    assert d['recipients'][0]['status']['code'] == 'reject'
    assert d['service'] == 'smtpd'
    # the same line on another host gets another id
    line = ('2026-10-26T06:28:47.320000+00:00 {} postfix/smtpd[5001]: NOQUEUE: reject: RCPT from unknown[203.0.113.7]: '
            '554 5.7.1 <victim@example.net>: Relay access denied; from=<spammer@example.net> to=<victim@example.net> '
            'proto=ESMTP helo=<bad.example>')
    imp = LogImporter()
    imp.feed_line(line.format('mx1'))
    imp.feed_line(line.format('mx2'))
    keys = sorted(imp.messages)
    assert len(keys) == 2 and keys[0].startswith('mx1:') and keys[1].startswith('mx2:')
    assert keys[0].split(':')[1] != keys[1].split(':')[1]
    assert 'mx1:' + d['queue_id'] in imp.messages


def test_same_qid_on_two_hosts(rfc):
    _, docs = rfc
    a, b = docs['mx1:C544910081E'], docs['mx2:C544910081E']
    assert a['host'] == 'mx1' and b['host'] == 'mx2'
    assert a['mail_from'] == 'one@example.com' and b['mail_from'] == 'two@example.com'
    assert a['message_id'] == 'on-mx1@example.com' and b['message_id'] == 'on-mx2@example.com'
    assert [r['to'] for r in a['recipients']] == ['dest1@example.net']
    assert [r['to'] for r in b['recipients']] == ['dest2@example.net']
    assert len(a['lines']) == 5 and len(b['lines']) == 5


def test_smtps_service(rfc):
    _, docs = rfc
    d = docs['mx1:B81091E7DCD']
    assert d['service'] == 'smtps'
    assert d['sasl_method'] == 'LOGIN'
    assert d['sasl_username'] == 'printer@example.com'
    assert d['status']['code'] == 'unknown'


def test_other_programs_and_connect_lines_ignored(rfc):
    out, docs = rfc
    assert len(docs) == 10
    for d in docs.values():
        for l in d['lines']:
            assert not l['message'].startswith(('connect from', 'disconnect from', 'warning: restriction'))


# ----------------------------------------------------------------------------------------------------------------------
# BSD syslog / no host
# ----------------------------------------------------------------------------------------------------------------------

def test_bsd_format():
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    out = _import('postfix_bsd.log', now=now)
    docs = {d['id']: d for d in build_documents(out)}
    d = docs['mx3:7D3E21A0F11']
    assert d['timestamp'] == datetime(2026, 10, 26, 6, 28, 47, tzinfo=UTC)
    assert d['client'] == {'host': 'mail.example.org', 'ip': '198.51.100.20'}
    assert d['relay'] == {'host': 'local', 'ip': '', 'port': ''}
    assert d['recipients'][0]['orig_to'] == 'user'
    assert d['mail_to_alias'] == {'user@mx3.example.com': 'user'}
    # Dec 31 would be in the future -> previous year
    assert docs['mx3:9F00A1B2C3D']['timestamp'] == datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert docs['mx3:9F00A1B2C3D']['service'] == 'pickup'


def test_no_syslog_host_uses_mail_host_name():
    out = _import('postfix_nohost.log')
    assert list(out['messages']) == ['3C4D5E6F701']
    m = out['messages']['3C4D5E6F701']
    assert m.host == ''
    assert m.timestamp == datetime(2025, 2, 15, 0, 0, 3, 474000, tzinfo=UTC)
    out = _import('postfix_nohost.log', host_name='mailhost')
    assert list(out['messages']) == ['mailhost:3C4D5E6F701']
    d = build_documents(out)[0]
    assert d['host'] == 'mailhost' and d['service'] == 'smtpd'
    assert d['relay']['ip'] == '198.51.100.30' and d['client']['ip'] == '192.0.2.77'


def test_log_timezone_applies_without_offset():
    tz = pytz.timezone('Europe/Warsaw')
    out = _import('postfix_nohost.log', tz=tz)
    # 2025-02-15 00:00:03.474 in Warsaw (CET, +01:00)
    assert out['messages']['3C4D5E6F701'].timestamp == datetime(2025, 2, 14, 23, 0, 3, 474000, tzinfo=UTC)
    # an explicit offset wins over LOG_TIMEZONE
    tp = TimestampParser(tz=tz)
    dt, _, _ = tp.parse('2026-10-26T06:28:47.155158+00:00 mx1 postfix/smtpd[1]: x')
    assert dt == datetime(2026, 10, 26, 6, 28, 47, 155158, tzinfo=UTC)


# ----------------------------------------------------------------------------------------------------------------------
# Timestamp parser
# ----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('line, expected, kind', [
    ('2026-10-26T06:28:47.155158+00:00 h p: m', datetime(2026, 10, 26, 6, 28, 47, 155158, tzinfo=UTC), 'iso'),
    ('2026-10-26T08:28:47.5+02:00 h p: m', datetime(2026, 10, 26, 6, 28, 47, 500000, tzinfo=UTC), 'iso'),
    ('2026-10-26T06:28:47Z h p: m', datetime(2026, 10, 26, 6, 28, 47, tzinfo=UTC), 'iso'),
    ('2026-10-26T01:28:47-0500 h p: m', datetime(2026, 10, 26, 6, 28, 47, tzinfo=UTC), 'iso'),
    ('2025-02-15T00:00:03.474Z,192.0.2.1,', datetime(2025, 2, 15, 0, 0, 3, 474000, tzinfo=UTC), 'iso'),
    ('2025-02-15 00:00:03 1sFUlr-000rus-Io <= a', datetime(2025, 2, 15, 0, 0, 3, tzinfo=UTC), 'iso-space'),
    ('Oct 26 06:28:47 h p: m', datetime(2026, 10, 26, 6, 28, 47, tzinfo=UTC), 'bsd'),
    ('Oct  6 06:28:47 h p: m', datetime(2026, 10, 6, 6, 28, 47, tzinfo=UTC), 'bsd'),
    ('Nov 17 06:28:47 h p: m', datetime(2026, 11, 17, 6, 28, 47, tzinfo=UTC), 'bsd'),  # within the 1 day tolerance
    ('Nov 18 06:28:47 h p: m', datetime(2025, 11, 18, 6, 28, 47, tzinfo=UTC), 'bsd'),
])
def test_timestamp_fast_paths(line, expected, kind):
    tp = TimestampParser(tz=pytz.UTC, now=datetime(2026, 11, 16, 12, 0, tzinfo=UTC))
    dt, pos, k = tp.parse(line)
    assert dt == expected and k == kind


def test_timestamp_fallback_and_none():
    tp = TimestampParser(tz=pytz.UTC, input_length=30)
    dt, pos, kind = tp.parse('15.02.2025 10:00:00 something')
    assert kind == 'fallback' and dt == datetime(2025, 2, 15, 10, 0, tzinfo=UTC)
    dt, pos, kind = tp.parse('no date here at all')
    assert dt is None and kind == 'none'


def test_line_without_timestamp_is_skipped():
    imp = LogImporter()
    imp.feed_line('postfix/smtpd[1]: 3C4D5E6F701: client=unknown[192.0.2.1]')
    assert imp.messages == {} and imp.stats['no_timestamp'] == 1


def test_split_syslog():
    assert split_syslog('2026-10-26T06:28:47+00:00 mx1 postfix/submission/smtpd[110451]: QID: x', 25) == \
        ('mx1', 'postfix/submission/smtpd', '110451', 'QID: x')
    assert split_syslog('2026-10-26T06:28:47+00:00 mx1 dovecot: lmtp(x): y', 25) == ('mx1', 'dovecot', None, 'lmtp(x): y')
    # no hostname field
    assert split_syslog('2025-02-15 00:00:03.474 postfix/smtpd[101]: QID: x', 23) is None


@pytest.mark.parametrize('program, service', [
    ('postfix/submission/smtpd', 'submission'), ('postfix/smtpd', 'smtpd'), ('postfix/pickup', 'pickup'),
    ('postfix/smtps/smtpd', 'smtps'), ('postfix-out/smtpd', 'smtpd'), ('', ''),
])
def test_service_from_program(program, service):
    assert service_from_program(program) == service


# ----------------------------------------------------------------------------------------------------------------------
# Line type rules (no log forging)
# ----------------------------------------------------------------------------------------------------------------------

def test_client_regex_variants():
    assert parse_postfix('client=unknown[192.168.140.50], sasl_method=login, sasl_username=dms@example.com',
                         'postfix/submission/smtpd') == {
        'client': {'host': 'unknown', 'ip': '192.168.140.50'}, 'sasl_method': 'login', 'sasl_username': 'dms@example.com'}
    assert parse_postfix('client=[192.0.2.1]', 'postfix/smtpd')['client'] == {'host': '', 'ip': '192.0.2.1'}
    assert parse_postfix('client=mail.example.org[2001:db8::1]', 'postfix/smtpd')['client'] == \
        {'host': 'mail.example.org', 'ip': '2001:db8::1'}


def test_header_cannot_forge_fields():
    evil = ('warning: header Subject: hi to=<evil@example.net>, relay=evil.example[203.0.113.66]:25, delay=1, '
            'status=sent (ok) client=evil[203.0.113.66] message-id=<forged@example.net> from '
            'unknown[192.0.2.1]; from=<a@example.com> to=<b@example.com> proto=ESMTP helo=<x>')
    lm = parse_postfix(evil, 'postfix/cleanup')
    assert lm == {'subject': 'hi to=<evil@example.net>, relay=evil.example[203.0.113.66]:25, delay=1, status=sent (ok) '
                             'client=evil[203.0.113.66] message-id=<forged@example.net>'}
    # remote server text after status= cannot change the parsed status/relay
    lm = parse_postfix('to=<b@example.com>, relay=mx.example.com[192.0.2.25]:25, delay=1, delays=0/0/0/1, dsn=5.0.0, '
                       'status=bounced (host said: 550 status=sent relay=x[203.0.113.66]:25)', 'postfix/smtp')
    assert lm['status']['code'] == 'bounced' and lm['relay']['ip'] == '192.0.2.25'
    # delivery fields are not taken from non-delivery programs, client= only from smtpd
    assert parse_postfix('to=<b@example.com>, relay=x[192.0.2.1]:25, status=sent (ok)', 'postfix/cleanup') == {}
    assert parse_postfix('client=x[192.0.2.1]', 'postfix/qmgr') == {}
    assert parse_postfix('from=<a@example.com>, size=10, nrcpt=1 (queue active)', 'postfix/smtpd') == {}


def test_connect_to_relay_for_relay_none():
    lm = parse_postfix('to=<b@example.com>, relay=none, delay=30, delays=0/0/30/0, dsn=4.4.1, status=deferred '
                       '(connect to mx.example.com[192.0.2.25]:25: Connection timed out)', 'postfix/smtp')
    assert lm['relay'] == {'host': 'mx.example.com', 'ip': '192.0.2.25', 'port': '25'}


def test_alias_without_at_does_not_crash():
    lm = parse_postfix('to=<root>, orig_to=<admin>, relay=local, delay=0, delays=0/0/0/0, dsn=2.0.0, status=sent (ok)',
                       'postfix/local')
    assert lm['mail_to'] == 'root' and lm['mail_to_alias'] == {'root': 'admin'}


# ----------------------------------------------------------------------------------------------------------------------
# Documents
# ----------------------------------------------------------------------------------------------------------------------

def _msg(**kw):
    from mlp.objects import PostfixMessage, PostfixLog
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    m = PostfixMessage(timestamp=ts, queue_id='ABCDEF12345', **kw)
    m.lines.append(PostfixLog(timestamp=ts, queue_id='ABCDEF12345', message='x'))
    return m


def test_build_document_status_and_domains(monkeypatch):
    d = build_document('ABCDEF12345', _msg(status={'code': 'expired', 'message': ''}), {})
    assert d['status'] == {'code': 'unknown', 'message': 'no status message found'}
    d = build_document('ABCDEF12345', _msg(), {})
    assert d['status'] == {'code': 'unknown', 'message': 'no status message found'}
    # mail_from '<>' (exim bounce) no longer crashes / reuses a stale domain
    d = build_document('ABCDEF12345', _msg(mail_from='<> R=1sFUlr-000rus-Io', mail_to='a@example.com'), {})
    assert d is not None
    monkeypatch.setattr(settings, 'ignore_domains', ['localhost', 'ignored.example'])
    assert build_document('X', _msg(mail_from='a@ignored.example'), {}) is None
    assert build_document('X', _msg(mail_from='<>', mail_to='b@ignored.example'), {}) is None


def test_decodev2():
    assert decodev2('=?UTF-8?B?w7PFgg==?=') == 'ół'
    assert decodev2('Re: =?UTF-8?B?w7PFgsSZ?= x') == 'Re: ółę x'
    assert decodev2('=?utf-8?Q?Zam=C3=B3wienie?= nr 5') == 'Zamówienie nr 5'
    assert decodev2('=?windows-1250?Q?Zam=F3wienie?=') == 'Zamówienie'
    assert decodev2('=?no-such-charset?Q?x?=') == '=?no-such-charset?Q?x?='
    assert decodev2('plain subject') == 'plain subject'
    # legacy fallback decoder: base64 padding is -len % 4
    assert mlp_main._decode_legacy('=?UTF-8?B?w7PFgg?=').startswith('ół')


def test_housekeeping_days_disabled(monkeypatch):
    assert mlp_main._housekeeping_days('') is None
    assert mlp_main._housekeeping_days(0) is None
    assert mlp_main._housekeeping_days(-3) is None
    assert mlp_main._housekeeping_days(30) == 30


# ----------------------------------------------------------------------------------------------------------------------
# Log files
# ----------------------------------------------------------------------------------------------------------------------

def test_resolve_log_files(tmp_path):
    for name in ('mail.log', 'mail.log.1', 'other.log'):
        shutil.copy(fixture_path('postfix_bsd.log'), tmp_path / name)
    os.utime(tmp_path / 'mail.log.1', (1_000_000, 1_000_000))
    files = resolve_log_files(str(tmp_path), 'mail.log*, missing.log, other.log, mail.log')
    assert [os.path.basename(f) for f in files] == ['mail.log.1', 'mail.log', 'other.log']
    assert resolve_log_files(str(tmp_path), ['nothing*']) == []
    assert resolve_log_files(str(tmp_path), [str(tmp_path / 'other.log')]) == [str(tmp_path / 'other.log')]


def test_multiple_files_and_gzip(tmp_path):
    src = open(fixture_path('postfix_rfc3339.log'), 'rb').read().splitlines(keepends=True)
    with open(tmp_path / 'mail.log.1', 'wb') as f:
        f.writelines(src[:20])
    with gzip.open(tmp_path / 'mail.log.2.gz', 'wb') as f:
        f.writelines(src[20:40])
    with open(tmp_path / 'mail.log', 'wb') as f:
        f.writelines(src[40:])
    files = [str(tmp_path / n) for n in ('mail.log.1', 'mail.log.2.gz', 'mail.log', 'missing.log')]
    out = asyncio.run(import_log(files))
    assert out['stats']['files'] == 3
    full = _import('postfix_rfc3339.log')
    assert sorted(out['messages']) == sorted(full['messages'])
    # a message split across files is merged
    assert len(out['messages']['mx1:25CF61E7BCF'].lines) == len(full['messages']['mx1:25CF61E7BCF'].lines)


# ----------------------------------------------------------------------------------------------------------------------
# Other MTAs keep working (run in a subprocess: the MTA is read at import time)
# ----------------------------------------------------------------------------------------------------------------------

_SUB = '''
import asyncio, json, sys
sys.path.insert(0, {root!r})
from mlp.main import import_log, build_documents
out = asyncio.run(import_log({path!r}))
print(json.dumps(build_documents(out, convert_time=str), default=str))
'''


def _run_mta(mta, fixture):
    env = dict(os.environ, MTA=mta, PYTHONIOENCODING='utf-8')
    code = _SUB.format(root=ROOT, path=fixture_path(fixture))
    res = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, encoding='utf-8')
    assert res.returncode == 0, res.stderr
    return {d['queue_id']: d for d in json.loads(res.stdout.strip().splitlines()[-1])}


def test_exim_still_parses():
    docs = _run_mta('exim', 'exim_mainlog.log')
    a = docs['1sFUlr-000rus-Io']
    assert a['mail_from'] == 'alice@example.org' and a['mail_to'] == 'bob@example.com'
    assert a['subject'] == 'Hello there' and a['message_id'] == 'abc123@example.org'
    assert a['client'] == {'host': 'mail.example.org', 'ip': '198.51.100.20:52344'}
    assert a['host'] == '' and a['id'] == '1sFUlr-000rus-Io'
    b = docs['1sFUm0-000abc-Zz']
    assert b['status']['code'] == 'bounced'
    assert b['mail_from'].startswith('<>')


def test_sendmail_still_parses():
    docs = _run_mta('sendmail', 'sendmail.log')
    d = docs['2BDAv4xN002001']
    assert d['id'] == 'mx4:2BDAv4xN002001' and d['host'] == 'mx4'
    assert d['mail_to'] == '<bob@example.com>'
    assert d['status']['code'] == 'sent'
    assert d['message_id'] == 'sm-1@example.org'


def test_exchange_unknown_event_and_empty_size():
    import mlp.parser as p
    old = settings.mta
    settings.mta = 'exchange'
    try:
        fields = ['2025-02-15T00:00:03.474Z', '192.0.2.1', 'client', '192.0.2.2', 'server', 'ctx', 'conn', 'SMTP',
                  'AGENTINFO', '123', '<id@example.com>', 'net-id', 'bob@example.com', 'status-text', '', '1', '', '',
                  'subject', 'alice@example.com', 'ret', 'x', 'y', 'z', 'cip', 'rip', 'w']
        lm = p.parse_legacy(','.join(fields) + ',')
        assert 'status' not in lm and 'size' not in lm
        fields[8] = 'DELIVER'
        fields[14] = '2048'
        lm = p.parse_legacy(','.join(fields) + ',')
        assert lm['status']['code'] == 'sent' and lm['size'] == 2.0
    finally:
        settings.mta = old
