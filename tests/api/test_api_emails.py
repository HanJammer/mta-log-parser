"""/api/emails list + detail, every filter operator, /api/facets and /api/stats."""
import re
from urllib.parse import urlencode

import pytest

from mlp import settings
from mlp.queries import escape_re2

pytestmark = pytest.mark.asyncio

ISO_RE = re.compile(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$')
ALL_IDS = {'AAA111', 'BBB222', 'filterek08:25CF61E7BCF', 'filterek09:99AA', 'filterek08:CC33'}


async def ids(client, query) -> set:
    q = query if isinstance(query, str) else urlencode(query, doseq=True)
    res = await client.get('/api/emails?' + q)
    body = await res.get_json()
    assert res.status_code == 200, body
    assert body['count'] == len(body['result'])
    return {d['id'] for d in body['result']}


async def status_of(client, query):
    res = await client.get('/api/emails?' + query)
    return res.status_code, await res.get_json()


# --- list & detail ---------------------------------------------------------------------------

async def test_list_shape_without_lines(authed):
    res = await authed.get('/api/emails')
    assert res.status_code == 200
    body = await res.get_json()
    assert body['error'] is False
    assert body['count'] == 5 and body['page'] == 1 and body['total_pages'] == 1 and body['remaining'] == 5
    assert {d['id'] for d in body['result']} == ALL_IDS
    for doc in body['result']:
        assert 'lines' not in doc
        for f in ('timestamp', 'first_attempt', 'last_attempt'):
            assert ISO_RE.match(doc[f]), doc[f]
    # default order: last_attempt desc
    lasts = [d['last_attempt'] for d in body['result']]
    assert body['result'][0]['id'] == 'filterek08:CC33'
    assert lasts == sorted(lasts, reverse=True)


async def test_pagination(authed):
    body = await (await authed.get('/api/emails?limit=2&page=2&order=timestamp&order_dir=asc')).get_json()
    assert body['count'] == 5 and body['total_pages'] == 3 and body['page'] == 2 and body['remaining'] == 3
    assert [d['id'] for d in body['result']] == ['filterek08:25CF61E7BCF', 'filterek09:99AA']
    body = await (await authed.get('/api/emails?limit=2&page=99')).get_json()
    assert body['page'] == 3 and len(body['result']) == 1
    body = await (await authed.get(f'/api/emails?limit={settings.max_limit + 500}')).get_json()
    assert len(body['result']) == 5


@pytest.mark.parametrize('order', ['timestamp', 'first_attempt', 'last_attempt', 'mail_from', 'id', 'host', 'size',
                                   'subject', 'queue_id', 'mail_to', 'service'])
async def test_order_fields(authed, order):
    body = await (await authed.get(f'/api/emails?order={order}&order_dir=asc&limit=100')).get_json()
    assert body['count'] == 5
    vals = [d.get(order) for d in body['result'] if d.get(order) is not None]
    assert vals == sorted(vals)


@pytest.mark.parametrize('query', ['order=lines', 'order=status.message', 'order=__proto__', 'order_dir=sideways',
                                   'limit=ten', 'page=1.5', 'offset=x'])
async def test_bad_paging_or_order_is_400(authed, query):
    code, body = await status_of(authed, query)
    assert code == 400 and body['error'] is True


async def test_detail_with_lines(authed):
    res = await authed.get('/api/emails/filterek08:25CF61E7BCF')
    assert res.status_code == 200
    doc = await res.get_json()
    assert doc['id'] == 'filterek08:25CF61E7BCF' and doc['host'] == 'filterek08'
    assert len(doc['lines']) == 2 and ISO_RE.match(doc['lines'][0]['timestamp'])
    assert doc['recipients'][1]['to'] == 'frank@example.com'
    # +02:00 in the source is stored and returned as UTC
    doc = await (await authed.get('/api/emails/filterek09:99AA')).get_json()
    assert doc['timestamp'] == '2026-10-27T10:30:00+00:00'


async def test_detail_404(authed):
    res = await authed.get('/api/emails/filterek08:NOPE')
    assert res.status_code == 404 and (await res.get_json())['error_code'] == 'NOT_FOUND'


# --- text filters ----------------------------------------------------------------------------

async def test_contains_not_eq(authed):
    assert await ids(authed, 'mail_from=ALICE@') == {'AAA111', 'filterek09:99AA'}
    assert await ids(authed, 'mail_from__not=alice') == ALL_IDS - {'AAA111', 'filterek09:99AA'}
    assert await ids(authed, 'mail_from__eq=alice@example.com') == {'AAA111', 'filterek09:99AA'}
    assert await ids(authed, 'mail_from__eq=alice@example') == set()
    assert await ids(authed, 'queue_id__eq=25cf61e7bcf') == {'filterek08:25CF61E7BCF'}


async def test_filters_are_anded_and_repeatable(authed):
    assert await ids(authed, 'mail_from=alice&host=filterek09') == {'filterek09:99AA'}
    assert await ids(authed, [('subject', 'a'), ('subject', 'test')]) == {'filterek08:25CF61E7BCF'}
    assert await ids(authed, 'status.code__eq=sent&mail_from__not=alice') == set()


async def test_comma_or_for_status_and_host(authed):
    assert await ids(authed, 'status.code__eq=sent,deferred') == {'AAA111', 'filterek08:25CF61E7BCF'}
    assert await ids(authed, 'status.code__eq=bounced, reject') == {'filterek09:99AA', 'filterek08:CC33'}
    assert await ids(authed, 'host__eq=filterek08,filterek09') == ALL_IDS - {'AAA111', 'BBB222'}
    assert await ids(authed, 'host__eq=filterek09') == {'filterek09:99AA'}
    # comma is literal for other fields
    assert await ids(authed, 'mail_from__eq=alice@example.com,carol@example.net') == set()


async def test_status_message_and_id(authed):
    assert await ids(authed, 'status.message=relay access') == {'filterek08:CC33'}
    assert await ids(authed, 'id=filterek08:') == {'filterek08:25CF61E7BCF', 'filterek08:CC33'}


async def test_relay_and_client_strings(authed):
    assert await ids(authed, 'relay=mx1.example.com[203.0.113.5]:25') == {'filterek08:25CF61E7BCF'}
    assert await ids(authed, 'relay=mx.example.org[192.0.2.10]:25') == {'AAA111', 'filterek09:99AA'}
    assert await ids(authed, 'relay__eq=none') == {'filterek08:CC33'}
    assert await ids(authed, 'relay.host=mx2') == {'filterek08:25CF61E7BCF'}
    assert await ids(authed, 'relay.ip__eq=203.0.113.5') == {'filterek08:25CF61E7BCF'}
    assert await ids(authed, 'client__eq=unknown[198.51.100.7]') == {'AAA111'}
    assert await ids(authed, 'client=[192.168.140.50]') == {'filterek08:25CF61E7BCF'}
    assert await ids(authed, 'client.host__eq=localhost') == {'filterek09:99AA'}
    assert await ids(authed, 'client.ip=198.51.100') == {'AAA111', 'filterek08:CC33'}


async def test_mail_to_matches_alias_and_recipients(authed):
    assert await ids(authed, 'mail_to=robert@') == {'AAA111'}                      # mail_to_alias
    assert await ids(authed, 'mail_to=frank@') == {'filterek08:25CF61E7BCF'}       # recipients[].to
    assert await ids(authed, 'mail_to__eq=info@example.com') == {'filterek08:25CF61E7BCF'}   # orig_to
    assert await ids(authed, 'mail_to=dave@') == {'BBB222'}                        # legacy JSON list
    assert await ids(authed, 'mail_to__not=bob@') == ALL_IDS - {'AAA111', 'filterek08:CC33'}


async def test_new_fields_and_missing_fields(authed):
    assert await ids(authed, 'sasl_username=dms@') == {'filterek08:25CF61E7BCF'}
    assert await ids(authed, 'sasl_method__eq=login') == {'filterek08:25CF61E7BCF'}
    assert await ids(authed, 'service__eq=pickup') == {'filterek09:99AA'}
    assert await ids(authed, 'dsn=5.1') == {'filterek09:99AA'}
    assert await ids(authed, 'dkim.domain__eq=example.com') == {'filterek08:25CF61E7BCF'}
    assert await ids(authed, 'size__eq=12.5') == {'AAA111'}
    # legacy documents lack these fields: "not" keeps them, "eq ''" finds them, nothing crashes
    assert await ids(authed, 'sasl_username__not=dms') == ALL_IDS - {'filterek08:25CF61E7BCF'}
    assert await ids(authed, 'host__eq=') == {'AAA111', 'BBB222'}
    assert await ids(authed, 'dkim.domain__not=example') == ALL_IDS - {'filterek08:25CF61E7BCF'}


async def test_regex_is_escaped(authed):
    assert escape_re2('a.b(c)') == r'a\.b\(c\)'
    assert await ids(authed, 'subject=a.b') == {'AAA111'}                          # must not match "axb test"
    assert await ids(authed, 'subject=[Q3] (draft)') == {'filterek09:99AA'}
    assert await ids(authed, 'subject=.+') == set()
    assert await ids(authed, {'subject': '(?i)'}) == set()
    assert await ids(authed, {'subject': 'a|x'}) == set()
    assert await ids(authed, {'subject': '\\'}) == set()


async def test_legacy_equal_false(authed):
    assert await ids(authed, 'equal=false&mail_from=alice') == ALL_IDS - {'AAA111', 'filterek09:99AA'}
    # order of parameters does not matter
    assert await ids(authed, 'mail_from=alice&equal=false') == ALL_IDS - {'AAA111', 'filterek09:99AA'}
    assert await ids(authed, 'equal=true&mail_from=alice') == {'AAA111', 'filterek09:99AA'}


@pytest.mark.parametrize('query', ['foo=bar', 'lines=x', 'a.b.c=x', 'status.code.x=1', 'mail_from__gt=a',
                                   'mail_from__regex=a', 'timestamp=2026', 'timestamp__eq=2026-10-26',
                                   'password=x', 'status__eq=sent'])
async def test_field_whitelist(authed, query):
    code, body = await status_of(authed, query)
    assert code == 400 and body['error'] is True and body['error_code'] == 'INVALID_FILTER'


# --- dates -----------------------------------------------------------------------------------

async def test_iso_date_filters(authed):
    assert await ids(authed, {'timestamp__gt': '2026-10-27T00:00:00+00:00'}) == \
        {'filterek08:25CF61E7BCF', 'filterek09:99AA', 'filterek08:CC33'}
    assert await ids(authed, {'timestamp__gt': '2026-10-27T12:00:00+02:00', 'timestamp__lt': '2026-10-27T12:30:00+02:00'}) == \
        {'filterek09:99AA'}                                                       # inclusive bounds
    assert await ids(authed, 'timestamp__lt=2026-10-26T06:30:00Z') == {'AAA111'}
    assert await ids(authed, 'last_attempt__gt=2026-10-27T08:30:00') == \
        {'filterek08:25CF61E7BCF', 'filterek09:99AA', 'filterek08:CC33'}          # naive = UTC
    assert await ids(authed, 'first_attempt__gt=2026-10-26T06:30:00Z&first_attempt__lt=2026-10-27T09:00:00Z') == \
        {'BBB222', 'filterek08:25CF61E7BCF'}
    # range on one field combined with ordering by another indexed field
    body = await (await authed.get('/api/emails?timestamp__gt=2026-10-27T00:00:00Z&order=mail_from&order_dir=asc')).get_json()
    assert [d['id'] for d in body['result']] == ['filterek09:99AA', 'filterek08:25CF61E7BCF', 'filterek08:CC33']


async def test_legacy_datetime_format(authed):
    # DATETIME_FORMAT default 'HH:mm:ss, DD.MM.YYYY'
    assert await ids(authed, {'timestamp__gt': '12:00:00, 27.10.2026'}) == {'filterek08:CC33'}


@pytest.mark.parametrize('value', ['yesterday', '2026-13-45T00:00:00', ''])
async def test_bad_date_is_400(authed, value):
    code, body = await status_of(authed, urlencode({'timestamp__gt': value}))
    assert code == 400 and body['error_code'] == 'INVALID_DATE'


# --- log lines ---------------------------------------------------------------------------------

async def test_log_lines_search(authed):
    window = 'timestamp__gt=2026-10-01T00:00:00Z'
    assert await ids(authed, f'log_lines=queued as XYZ123&{window}') == {'filterek08:25CF61E7BCF'}
    assert await ids(authed, f'log_lines=CLIENT=unknown[&{window}') == {'AAA111', 'filterek08:25CF61E7BCF'}
    assert await ids(authed, f'log_lines__not=client=&{window}') == ALL_IDS - {'AAA111', 'filterek08:25CF61E7BCF'}
    assert await ids(authed, f'log_lines=nrcpt=2&mail_from=carol&{window}') == {'BBB222'}
    assert await ids(authed, f'log_lines=to=<bob@example.org>, status=sent (250&{window}') == {'AAA111'}


async def test_log_lines_requires_time_window(authed):
    code, body = await status_of(authed, 'log_lines=queued')
    assert code == 400 and body['error_code'] == 'TIME_WINDOW_REQUIRED'


# --- facets ----------------------------------------------------------------------------------

async def test_facets(authed):
    res = await authed.get('/api/facets')
    assert res.status_code == 200
    assert await res.get_json() == {
        'hosts': ['filterek08', 'filterek09'],
        'statuses': ['bounced', 'deferred', 'multiple', 'reject', 'sent'],
        'services': ['pickup', 'smtpd', 'submission'],
    }


# --- stats -----------------------------------------------------------------------------------

async def stats(client, query):
    res = await client.get('/api/stats?' + query)
    body = await res.get_json()
    assert res.status_code == 200, body
    return body


async def test_stats_statuses(authed):
    assert await stats(authed, 'statuses=sent') == {'sent': 1}
    assert await stats(authed, 'statuses=deferred') == {'deferred': 1}
    assert await stats(authed, 'statuses=reject&host__eq=filterek09') == {'reject': 0}
    assert await stats(authed, 'statuses=bounced&timestamp__gt=2026-10-27T00:00:00Z') == {'bounced': 1}


async def test_stats_top_senders(authed):
    assert await stats(authed, 'top_senders=1') == [
        {'mail_from': 'alice@example.com', 'count': 2}, {'mail_from': 'carol@example.net', 'count': 1},
        {'mail_from': 'dms@example.com', 'count': 1}, {'mail_from': 'spam@bad.example', 'count': 1}]
    assert await stats(authed, 'top_senders=1&host__eq=filterek08') == [
        {'mail_from': 'dms@example.com', 'count': 1}, {'mail_from': 'spam@bad.example', 'count': 1}]
    excl = urlencode({'filtered_top_senders_excluded': '["alice@example.com", "spam@bad.example"]'})
    assert await stats(authed, 'top_senders=1&' + excl) == [
        {'mail_from': 'carol@example.net', 'count': 1}, {'mail_from': 'dms@example.com', 'count': 1}]
    res = await authed.get('/api/stats?top_senders=1&filtered_top_senders_excluded=' + '{"a": 1}')
    assert res.status_code == 400


async def test_stats_top_recipients(authed):
    rows = await stats(authed, 'top_recipients=1')
    assert {r['mail_to']: r['count'] for r in rows} == {
        'bob@example.org': 2, 'erin@example.com': 2,      # legacy JSON list + recipients[]
        'dave@example.net': 1, 'frank@example.com': 1, 'gina@example.org': 1}
    assert rows[0]['count'] == 2
    rows = await stats(authed, 'top_recipients=1&status.code__eq=multiple')
    assert {r['mail_to'] for r in rows} == {'dave@example.net', 'erin@example.com'}


async def test_stats_top_relays(authed):
    rows = await stats(authed, 'top_relays=1')
    assert {r['relay']: r['count'] for r in rows} == {
        'mx.example.org[192.0.2.10]:25': 2, 'mx1.example.com[203.0.113.5]:25': 1,
        'mx2.example.com[203.0.113.6]:25': 1, 'none': 1}
    assert rows[0] == {'relay': 'mx.example.org[192.0.2.10]:25', 'count': 2}


async def test_stats_by_host(authed):
    assert await stats(authed, 'by_host=1') == [
        {'host': '', 'count': 2, 'sent': 1, 'deferred': 0, 'bounced': 0, 'reject': 0},
        {'host': 'filterek08', 'count': 2, 'sent': 0, 'deferred': 1, 'bounced': 0, 'reject': 1},
        {'host': 'filterek09', 'count': 1, 'sent': 0, 'deferred': 0, 'bounced': 1, 'reject': 0},
    ]


async def test_stats_timeline(authed):
    rows = await stats(authed, 'timeline=1&bucket=day')
    assert rows == [
        {'t': '2026-10-26T00:00:00+00:00', 'sent': 1, 'deferred': 0, 'bounced': 0, 'reject': 0, 'other': 1},
        {'t': '2026-10-27T00:00:00+00:00', 'sent': 0, 'deferred': 1, 'bounced': 1, 'reject': 1, 'other': 0},
    ]
    rows = await stats(authed, 'timeline=1&bucket=hour&host__eq=filterek08')
    assert [r['t'] for r in rows] == ['2026-10-27T08:00:00+00:00', '2026-10-27T20:00:00+00:00']
    # buckets in another timezone: 20:00Z is already 28 Oct in +05:00
    rows = await stats(authed, 'timeline=1&bucket=day&tz=%2B05:00&timestamp__gt=2026-10-27T00:00:00Z')
    assert [r['t'] for r in rows] == ['2026-10-27T00:00:00+05:00', '2026-10-28T00:00:00+05:00']


@pytest.mark.parametrize('query', ['', 'nonsense=1', 'timeline=1&bucket=week', 'timeline=1&tz=Europe/Warsaw',
                                   'top_senders=1&bogus__eq=1', 'top_senders=1&limit=x'])
async def test_stats_bad_requests(authed, query):
    res = await authed.get('/api/stats?' + query)
    assert res.status_code == 400
    assert (await res.get_json())['error'] is True
