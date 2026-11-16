"""Shared data and helpers for the web API tests (imported by conftest and the test modules)."""
from datetime import datetime, timezone

CSRF = {'X-Requested-With': 'mlp'}
UTC = timezone.utc


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def line(t: str, qid: str, msg: str) -> dict:
    return {'timestamp': ts(t), 'queue_id': qid, 'message': msg}


#: Documents shaped like the 2.0 data model: two legacy (1.x) documents without the new fields
#: and three new ones with host-prefixed ids.
FIXTURE_DOCS = [
    {   # legacy, single recipient, alias
        'id': 'AAA111', 'queue_id': 'AAA111',
        'timestamp': ts('2026-10-26T06:00:00+00:00'),
        'first_attempt': ts('2026-10-26T06:00:00+00:00'), 'last_attempt': ts('2026-10-26T06:00:05+00:00'),
        'mail_from': 'alice@example.com', 'mail_to': 'bob@example.org',
        'mail_to_alias': {'bob@example.org': 'robert@example.org'},
        'subject': 'Hello a.b world', 'size': 12.5, 'message_id': '<m1@example.com>',
        'status': {'code': 'sent', 'message': '250 2.0.0 Ok'},
        'relay': {'host': 'mx.example.org', 'ip': '192.0.2.10', 'port': '25'},
        'client': {'host': 'unknown', 'ip': '198.51.100.7'},
        'lines': [line('2026-10-26T06:00:00+00:00', 'AAA111', 'client=unknown[198.51.100.7]'),
                  line('2026-10-26T06:00:05+00:00', 'AAA111', 'to=<bob@example.org>, status=sent (250 2.0.0 Ok)')],
    },
    {   # legacy, several recipients stored as a JSON string
        'id': 'BBB222', 'queue_id': 'BBB222',
        'timestamp': ts('2026-10-26T07:00:00+00:00'),
        'first_attempt': ts('2026-10-26T07:00:00+00:00'), 'last_attempt': ts('2026-10-26T07:10:00+00:00'),
        'mail_from': 'carol@example.net',
        'mail_to': '["dave@example.net", "erin@example.com"]', 'mail_to_alias': {},
        'subject': 'Weekly', 'size': 3, 'message_id': '<m2@example.net>',
        'status': {'code': 'multiple', 'message': ''},
        'relay': {}, 'client': {'host': 'mail.example.net', 'ip': '203.0.113.9'},
        'lines': [line('2026-10-26T07:00:00+00:00', 'BBB222', 'from=<carol@example.net>, size=3072, nrcpt=2')],
    },
    {   # 2.0: host-prefixed id, recipients, SASL, DKIM
        'id': 'filterek08:25CF61E7BCF', 'queue_id': '25CF61E7BCF', 'host': 'filterek08',
        'timestamp': ts('2026-10-27T08:00:00+00:00'),
        'first_attempt': ts('2026-10-27T08:00:00+00:00'), 'last_attempt': ts('2026-10-27T08:30:00+00:00'),
        'mail_from': 'dms@example.com', 'mail_to': 'erin@example.com', 'mail_to_alias': {},
        'recipients': [
            {'to': 'erin@example.com', 'orig_to': 'info@example.com', 'status': {'code': 'sent', 'message': 'ok'},
             'relay': {'host': 'mx1.example.com', 'ip': '203.0.113.5', 'port': 25}, 'dsn': '2.0.0', 'delay': 1.9},
            {'to': 'frank@example.com', 'orig_to': '', 'status': {'code': 'deferred', 'message': 'timeout'},
             'relay': {'host': 'mx2.example.com', 'ip': '203.0.113.6', 'port': 25}, 'dsn': '4.4.1', 'delay': 30.0},
        ],
        'subject': 'axb test', 'size': 40, 'message_id': '<m3@example.com>',
        'status': {'code': 'deferred', 'message': 'timeout'},
        'relay': {'host': 'mx2.example.com', 'ip': '203.0.113.6', 'port': 25},
        'client': {'host': 'unknown', 'ip': '192.168.140.50'},
        'sasl_method': 'login', 'sasl_username': 'dms@example.com', 'service': 'submission',
        'dsn': '4.4.1', 'delay': 30.0, 'nrcpt': 2, 'dkim': {'domain': 'example.com', 'selector': 'default'},
        'tls': True,
        'lines': [line('2026-10-27T08:00:00+00:00', '25CF61E7BCF',
                       'client=unknown[192.168.140.50], sasl_method=login, sasl_username=dms@example.com'),
                  line('2026-10-27T08:00:01+00:00', '25CF61E7BCF', 'status=sent (250 2.0.0 Ok: queued as XYZ123)')],
    },
    {   # 2.0, other host, offset in the original log line (+02:00)
        'id': 'filterek09:99AA', 'queue_id': '99AA', 'host': 'filterek09',
        'timestamp': ts('2026-10-27T12:30:00+02:00'),
        'first_attempt': ts('2026-10-27T12:30:00+02:00'), 'last_attempt': ts('2026-10-27T12:31:00+02:00'),
        'mail_from': 'alice@example.com', 'mail_to': 'gina@example.org', 'mail_to_alias': {},
        'recipients': [{'to': 'gina@example.org', 'orig_to': '', 'status': {'code': 'bounced', 'message': 'no such user'},
                        'relay': {'host': 'mx.example.org', 'ip': '192.0.2.10', 'port': 25}, 'dsn': '5.1.1'}],
        'subject': 'Report [Q3] (draft)', 'size': 7, 'message_id': '<m4@example.com>',
        'status': {'code': 'bounced', 'message': 'no such user'},
        'relay': {'host': 'mx.example.org', 'ip': '192.0.2.10', 'port': 25},
        'client': {'host': 'localhost', 'ip': '127.0.0.1'}, 'service': 'pickup', 'dsn': '5.1.1', 'nrcpt': 1,
        'lines': [line('2026-10-27T12:30:00+02:00', '99AA', 'uid=0 from=<alice@example.com>')],
    },
    {   # 2.0, rejected, relay=none
        'id': 'filterek08:CC33', 'queue_id': 'CC33', 'host': 'filterek08',
        'timestamp': ts('2026-10-27T20:00:00+00:00'),
        'first_attempt': ts('2026-10-27T20:00:00+00:00'), 'last_attempt': ts('2026-10-27T20:00:00+00:00'),
        'mail_from': 'spam@bad.example', 'mail_to': 'bob@example.org', 'mail_to_alias': {},
        'recipients': [], 'subject': '', 'size': 0, 'message_id': '',
        'status': {'code': 'reject', 'message': '554 Relay access denied'},
        'relay': {'host': 'none'}, 'client': {'host': 'bad.example', 'ip': '198.51.100.66'}, 'service': 'smtpd',
        'lines': [line('2026-10-27T20:00:00+00:00', 'CC33', 'NOQUEUE: reject: RCPT from bad.example')],
    },
]


async def post(client, url, body=None, method='POST', headers=None):
    h = dict(CSRF)
    h.update(headers or {})
    return await client.open(url, method=method, json=body if body is not None else {}, headers=h)


async def login(client, user='admin', password='password123'):
    return await post(client, '/api/login', {'login': user, 'password': password})
