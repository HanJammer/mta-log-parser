"""
``/api/stats`` modes. Every mode accepts the ``/api/emails`` filters (see :mod:`mlp.queries`).
"""
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, List

from rethinkdb import r

from mlp import settings
from mlp.core import run
from mlp.queries import FilterError, Filters, _arr, _hostip, _s, apply_filters, parse_json_list

TOP_N = 10
STATUS_COLUMNS = ('sent', 'deferred', 'bounced', 'reject')
#: Query parameters consumed by the stats modes themselves (not filters).
STATS_PARAMS = frozenset({
    'statuses', 'top_senders', 'top_recipients', 'top_relays', 'by_host', 'timeline', 'bucket', 'tz', 'limit',
    'filtered_top_senders_excluded', 'filtered_top_recipients_excluded',
})
_TZ_RE = re.compile(r'^[+-](\d\d):(\d\d)$')


def _excludes(args, param: str, configured: str) -> List[str]:
    excl = parse_json_list(args.get(param), param)
    if configured:
        excl += [x.strip() for x in configured.split(',')]
    if '' in excl:
        excl.append('<>')       # exim's null sender
    return excl


def _top_n(args) -> int:
    try:
        n = int(args.get('limit', TOP_N))
    except ValueError:
        raise FilterError('limit must be an integer.')
    return max(1, min(n, 100))


async def status_count(table, conn, flt: Filters, indexes, code: str) -> dict:
    if flt.empty:
        cnt = await run(table.get_all(code, index='status_code').count(), conn)
    else:
        q, _ = apply_filters(table, flt, indexes)
        cnt = await run(q.filter(lambda row: row['status']['code'].default('') == code).count(), conn)
    return {code: cnt}


async def top_senders(table, conn, flt: Filters, indexes, args) -> list:
    excl = _excludes(args, 'filtered_top_senders_excluded', settings.exclude_from_top_senders)
    q, _ = apply_filters(table, flt, indexes)
    if excl:
        q = q.filter(lambda row: r.expr(excl).contains(_s(row['mail_from'])).not_())
    res = await run(q.group(lambda row: _s(row['mail_from'])).count().ungroup()
                    .order_by(r.desc('reduction'), 'group').limit(_top_n(args)), conn)
    return [{'mail_from': x['group'], 'count': x['reduction']} for x in res]


def _legacy_recipients(mail_to: str) -> List[str]:
    """1.x stored several recipients as a JSON list (strings or ``{mail_to, mail_to_alias}``)."""
    try:
        items = json.loads(mail_to)
    except ValueError:
        items = mail_to.strip('[]').split(',')
    if not isinstance(items, list):
        items = [items]
    out = []
    for it in items:
        if isinstance(it, dict):
            v = it.get('mail_to')
        else:
            v = str(it).strip().strip('"')
        if v and v not in out:
            out.append(v)
    return out


async def top_recipients(table, conn, flt: Filters, indexes, args) -> list:
    excl = set(_excludes(args, 'filtered_top_recipients_excluded', settings.exclude_from_top_recipients))
    q, _ = apply_filters(table, flt, indexes)

    def has_rc(row):
        return _arr(row['recipients']).count().gt(0)

    def is_legacy_list(row):
        return has_rc(row).not_() & _s(row['mail_to']).match(r'^\[')

    def per_doc(row):
        return r.branch(
            has_rc(row), _arr(row['recipients']).map(lambda x: _s(x['to'])).distinct(),
            is_legacy_list(row), [],
            [_s(row['mail_to'])],
        )

    grouped = await run(q.concat_map(per_doc).group(lambda x: x).count().ungroup(), conn)
    counts = Counter({x['group']: x['reduction'] for x in grouped})
    legacy = await run(q.filter(is_legacy_list).pluck('mail_to'), conn)
    for doc in legacy:
        for rc in _legacy_recipients(doc.get('mail_to', '')):
            counts[rc] += 1
    rows = [(k, v) for k, v in counts.items() if k not in excl and k != '']
    rows.sort(key=lambda kv: (-kv[1], kv[0]))
    return [{'mail_to': k, 'count': v} for k, v in rows[:_top_n(args)]]


async def top_relays(table, conn, flt: Filters, indexes, args) -> list:
    q, _ = apply_filters(table, flt, indexes)

    def per_doc(row):
        rc = _arr(row['recipients'])
        return r.branch(rc.count().gt(0), rc.map(lambda x: _hostip(x['relay'], True)).distinct(),
                        [_hostip(row['relay'], True)])

    res = await run(q.concat_map(per_doc).filter(lambda x: x.ne('')).group(lambda x: x).count().ungroup()
                    .order_by(r.desc('reduction'), 'group').limit(_top_n(args)), conn)
    return [{'relay': x['group'], 'count': x['reduction']} for x in res]


async def by_host(table, conn, flt: Filters, indexes, args) -> list:
    q, _ = apply_filters(table, flt, indexes)
    res = await run(q.group(lambda row: [_s(row['host']), _s(row['status']['code'])]).count().ungroup(), conn)
    hosts = defaultdict(lambda: {'count': 0, **{c: 0 for c in STATUS_COLUMNS}})
    for x in res:
        host, code = x['group']
        h = hosts[host]
        h['count'] += x['reduction']
        if code in STATUS_COLUMNS:
            h[code] += x['reduction']
    out = [{'host': k, **v} for k, v in hosts.items()]
    out.sort(key=lambda d: (-d['count'], d['host']))
    return out


def _parse_tz(value: str):
    """``tz=+02:00`` (default ``+00:00``) -> (ReQL timezone string, tzinfo)."""
    value = (value or '+00:00').strip()
    if value in ('Z', 'UTC'):
        value = '+00:00'
    m = _TZ_RE.match(value)
    if not m or int(m.group(1)) > 14 or int(m.group(2)) > 59:
        raise FilterError("tz must look like '+02:00'.")
    delta = timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))
    return value, timezone(-delta if value[0] == '-' else delta)


async def timeline(table, conn, flt: Filters, indexes, args) -> list:
    bucket = str(args.get('bucket', 'hour')).lower()
    if bucket not in ('hour', 'day'):
        raise FilterError("bucket must be 'hour' or 'day'.")
    tz_str, tzinfo = _parse_tz(args.get('tz'))
    q, _ = apply_filters(table, flt, indexes)

    def key(row):
        t = row['timestamp'].in_timezone(tz_str)
        parts = [t.year(), t.month(), t.day()]
        if bucket == 'hour':
            parts.append(t.hours())
        return r.expr(parts).append(_s(row['status']['code']))

    q = q.filter(lambda row: row['timestamp'].default(None).type_of().eq('PTYPE<TIME>'))
    res = await run(q.group(key).count().ungroup(), conn)
    buckets = defaultdict(lambda: {**{c: 0 for c in STATUS_COLUMNS}, 'other': 0})
    for x in res:
        *parts, code = x['group']
        t = datetime(*parts, tzinfo=tzinfo) if bucket == 'hour' else datetime(*parts[:3], tzinfo=tzinfo)
        b = buckets[t]
        b[code if code in STATUS_COLUMNS else 'other'] += x['reduction']
    return [{'t': t.isoformat(), **v} for t, v in sorted(buckets.items())]
