"""
Translation of ``/api/emails`` and ``/api/stats`` query strings into RethinkDB queries.

Filter syntax (any number of filters, AND-ed; the same key may be repeated)::

    <field>=<text>        case-insensitive "contains"
    <field>__not=<text>   does not contain
    <field>__eq=<text>    exact match (case-insensitive); comma-separated list = OR for
                          ``status.code`` and ``host``
    <date>__gt=<iso8601>  date >= value  (timestamp, first_attempt, last_attempt)
    <date>__lt=<iso8601>  date <= value

The text is always literal: it is escaped before it reaches RethinkDB's RE2 ``match()``.
Legacy ``equal=false`` turns every plain ``<field>=<text>`` filter into ``__not``.
"""
import json
import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from functools import reduce
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import moment
from rethinkdb import r

from mlp import settings


class FilterError(ValueError):
    """Invalid query parameter; reported to the client as ``400``."""

    def __init__(self, message: str, error_code: str = 'INVALID_FILTER'):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


TEXT_FIELDS = (
    'id', 'queue_id', 'host', 'mail_from', 'mail_to', 'subject', 'message_id', 'status.code', 'status.message',
    'relay', 'relay.host', 'relay.ip', 'client', 'client.host', 'client.ip', 'sasl_username', 'sasl_method',
    'service', 'dsn', 'dkim.domain', 'size', 'log_lines',
)
DATE_FIELDS = ('timestamp', 'first_attempt', 'last_attempt')
#: Boolean fields: ``<field>=true|false`` / ``<field>__eq=true|false``.
BOOL_FIELDS = ('multiple',)
#: ``__eq`` on these fields accepts a comma-separated list (OR).
LIST_EQ_FIELDS = ('status.code', 'host')
TEXT_OPS = ('', 'not', 'eq')
DATE_OPS = ('gt', 'lt')

#: Fields the list can be ordered by. Each has a secondary index (``id`` is the primary key), so
#: ordering is done lazily through the index and never loads the whole table into memory.
ORDER_FIELDS = (
    'id', 'queue_id', 'host', 'timestamp', 'first_attempt', 'last_attempt', 'mail_from', 'mail_to', 'subject',
    'size', 'service',
)

#: Pagination / ordering / misc parameters that are not filters.
COMMON_PARAMS = frozenset({'page', 'limit', 'offset', 'order', 'order_dir', 'equal', 'format', '_'})

_RE2_SPECIAL = re.compile(r'([\\.^$|?*+()\[\]{}])')


def escape_re2(text: str) -> str:
    """Escape ``text`` so RE2 treats it literally."""
    return _RE2_SPECIAL.sub(r'\\\1', text)


def parse_datetime(value: str) -> datetime:
    """
    Parse a filter date: ISO 8601 (``2026-10-26T06:28:47+02:00``, ``...Z``; naive values are taken as UTC),
    or - for 1.x clients - a value in ``DATETIME_FORMAT`` (taken as UTC, like 1.x did).
    """
    v = (value or '').strip()
    if not v:
        raise FilterError('Empty date value.', 'INVALID_DATE')
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        dt = None
        try:
            m = moment.date(v, settings.datetime_format)
            # moment is lenient ("yesterday", "1"); accept only values that round-trip exactly
            if m is not None and m.date is not None and m.format(settings.datetime_format) == v:
                dt = m.date
        except Exception:
            dt = None
        if not isinstance(dt, datetime):
            raise FilterError(f'Invalid date {value!r}: use ISO 8601, e.g. 2026-10-26T06:28:47+00:00.', 'INVALID_DATE')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --- per-field candidate strings -----------------------------------------------------------------

def _s(expr):
    """Field value as string; missing / null -> ''."""
    return expr.default('').coerce_to('string')


def _arr(expr):
    """Field value as array; missing / null / not an array -> []."""
    v = expr.default([])
    return r.branch(v.type_of().eq('ARRAY'), v, [])


def _hostip(obj, with_port: bool):
    """Format ``{host, ip, port}`` as ``host[ip]:port`` (parts that are empty are left out)."""
    o = obj.default({})
    host, ip = _s(o['host']), _s(o['ip'])
    parts = [host, r.branch(ip.ne(''), r.add('[', ip, ']'), '')]
    if with_port:
        port = _s(o['port'])
        parts.append(r.branch(port.ne(''), r.add(':', port), ''))
    return r.branch(o.type_of().eq('OBJECT'), r.add(*parts), o.coerce_to('string'))


def _recipients(row):
    return _arr(row['recipients'])


def candidates(fname: str, row):
    """ReQL array of strings a text filter on ``fname`` is matched against (any match counts)."""
    if fname == 'relay':
        return r.expr([_hostip(row['relay'], True)]).union(
            _recipients(row).map(lambda rc: _hostip(rc['relay'], True)))
    if fname in ('relay.host', 'relay.ip'):
        sub = fname.split('.')[1]
        return r.expr([_s(row['relay'][sub])]).union(_recipients(row).map(lambda rc: _s(rc['relay'][sub])))
    if fname == 'client':
        return r.expr([_hostip(row['client'], False)])
    if fname == 'mail_to':
        alias = row['mail_to_alias'].default({})
        return r.expr([_s(row['mail_to'])]).union(
            r.branch(alias.type_of().eq('OBJECT'), alias.values().map(lambda v: _s(v)), [])
        ).union(_recipients(row).concat_map(lambda rc: [_s(rc['to']), _s(rc['orig_to'])]))
    if fname == 'mail_from':
        # the original sender and, for SRS-rewritten senders, the rewritten address
        srs = _s(row['srs_from'])
        return r.expr([_s(row['mail_from'])]).union(r.branch(srs.ne(''), [srs], []))
    if fname == 'log_lines':
        return _arr(row['lines']).map(lambda line: _s(line['message']))
    if '.' in fname:
        a, b = fname.split('.', 1)
        return r.expr([_s(row[a][b])])
    return r.expr([_s(row[fname])])


def multiple_predicate(value: str) -> Callable:
    """``multiple__eq=true|false``: more than one recipient (2.0 field ``multiple``, legacy status ``multiple``)."""
    v = value.strip().lower()
    if v not in ('true', 'false', '1', '0'):
        raise FilterError("multiple accepts only 'true' or 'false'.")
    want = v in ('true', '1')

    def is_multiple(row):
        return row['multiple'].default(False).eq(True) | _s(row['status']['code']).eq('multiple')
    return (lambda row: is_multiple(row)) if want else (lambda row: is_multiple(row).not_())


def text_predicate(fname: str, op: str, value: str) -> Optional[Callable]:
    """Return ``lambda row: <bool ReQL>`` for one text filter, or None if the filter is a no-op."""
    value = value.strip('*') if op != 'eq' else value
    if op == 'eq':
        values = [v.strip() for v in value.split(',')] if fname in LIST_EQ_FIELDS else [value]
        values = [v for v in values if v != ''] or ['']
        pattern = '(?i)^(?:' + '|'.join(escape_re2(v) for v in values) + ')$'
        if fname == 'mail_to' and value != '':
            # several recipients: mail_to is a JSON-encoded list (strings or {mail_to, mail_to_alias})
            in_list = r'(?i)^\[.*"' + escape_re2(value) + '"'
            return lambda row: candidates(fname, row).contains(lambda s: s.match(pattern)) \
                | _s(row['mail_to']).match(in_list).ne(None)
        return lambda row: candidates(fname, row).contains(lambda s: s.match(pattern))
    if value == '':
        return None
    pattern = '(?i)' + escape_re2(value)
    if op == 'not':
        return lambda row: candidates(fname, row).contains(lambda s: s.match(pattern)).not_()
    return lambda row: candidates(fname, row).contains(lambda s: s.match(pattern))


# --- parsing the query string --------------------------------------------------------------------

@dataclass
class Filters:
    predicates: List[Callable] = dc_field(default_factory=list)
    #: ``{date_field: [lower or None, upper or None]}``
    ranges: Dict[str, List[Optional[datetime]]] = dc_field(default_factory=dict)
    #: True when a ``log_lines`` filter is present (scans raw lines - needs a time window).
    log_lines: bool = False

    @property
    def empty(self) -> bool:
        return not self.predicates and not self.ranges

    def row_predicate(self, skip_range: Optional[str] = None) -> Optional[Callable]:
        """Combine everything (except the range on ``skip_range``) into one ``lambda row: bool``."""
        preds = list(self.predicates)
        for f, (lo, hi) in self.ranges.items():
            if f == skip_range:
                continue
            if lo is not None:
                preds.append(lambda row, f=f, lo=lo: row[f] >= lo)
            if hi is not None:
                preds.append(lambda row, f=f, hi=hi: row[f] <= hi)
        if not preds:
            return None
        return lambda row: reduce(lambda a, b: a & b, [p(row) for p in preds])


def split_key(key: str) -> Tuple[str, str]:
    if '__' in key:
        fname, op = key.rsplit('__', 1)
        return fname, op
    return key, ''


def parse_filters(args, ignore: Iterable[str] = ()) -> Filters:
    """
    Parse a ``MultiDict`` of query parameters into :class:`Filters`. Unknown keys raise
    :class:`FilterError` (-> 400). Keys in ``ignore`` and :data:`COMMON_PARAMS` are skipped.
    """
    ignore = set(ignore) | COMMON_PARAMS
    negate_plain = str(args.get('equal', 'true')).lower() == 'false'
    flt = Filters()
    for key in args.keys():
        if key in ignore:
            continue
        fname, op = split_key(key)
        values = args.getlist(key)
        if fname in DATE_FIELDS and op in DATE_OPS:
            rng = flt.ranges.setdefault(fname, [None, None])
            for v in values:
                dt = parse_datetime(v)
                if op == 'gt':
                    rng[0] = dt if rng[0] is None or dt > rng[0] else rng[0]
                else:
                    rng[1] = dt if rng[1] is None or dt < rng[1] else rng[1]
            continue
        if fname in BOOL_FIELDS and op in ('', 'eq'):
            flt.predicates.extend(multiple_predicate(v) for v in values)
            continue
        if fname not in TEXT_FIELDS or op not in TEXT_OPS:
            raise FilterError(f'Unknown filter {key!r}. Allowed fields: '
                              f'{", ".join(TEXT_FIELDS + BOOL_FIELDS + DATE_FIELDS)}.')
        if op == '' and negate_plain:
            op = 'not'
        if fname == 'log_lines':
            flt.log_lines = True
        for v in values:
            pred = text_predicate(fname, op, v)
            if pred is not None:
                flt.predicates.append(pred)
    if flt.log_lines and not any(lo is not None or hi is not None for lo, hi in flt.ranges.values()):
        raise FilterError('The log_lines search scans raw log lines: add a time window '
                          '(e.g. timestamp__gt=...).', 'TIME_WINDOW_REQUIRED')
    return flt


def apply_filters(table, flt: Filters, indexes: Iterable[str], range_index: Optional[str] = None):
    """
    Apply ``flt`` to ``table``. One date range is evaluated through its secondary index
    (``between``) when possible: ``range_index`` if given and ranged, else the first ranged field
    that has an index. Returns ``(query, used_index)``.
    """
    indexes = set(indexes)
    used = None
    if range_index and range_index in flt.ranges and range_index in indexes:
        used = range_index
    elif range_index is None:
        used = next((f for f in flt.ranges if f in indexes), None)
    q = table
    if used:
        lo, hi = flt.ranges[used]
        q = q.between(r.minval if lo is None else lo, r.maxval if hi is None else hi,
                      index=used, left_bound='closed', right_bound='closed')
    pred = flt.row_predicate(skip_range=used)
    if pred is not None:
        q = q.filter(pred)
    return q, used


def order_key(order: str):
    """ReQL value for ordering by a (possibly nested) field without an index."""
    if '.' in order:
        a, b = order.split('.', 1)
        return lambda row: row[a][b].default(None)
    return lambda row: row[order].default(None)


def parse_order(args) -> Tuple[str, str]:
    order = str(args.get('order', 'last_attempt') or 'last_attempt')
    order_dir = str(args.get('order_dir', 'desc') or 'desc').lower()
    if order not in ORDER_FIELDS:
        raise FilterError(f'Cannot order by {order!r}. Allowed: {", ".join(ORDER_FIELDS)}.', 'INVALID_ORDER')
    if order_dir not in ('asc', 'desc'):
        raise FilterError("order_dir must be 'asc' or 'desc'.", 'INVALID_ORDER')
    return order, order_dir


def parse_json_list(value: Optional[str], name: str) -> List[str]:
    """Legacy ``filtered_top_*_excluded`` parameters: a JSON list of strings (a comma list is accepted too)."""
    if value is None or value == '':
        return []
    try:
        data = json.loads(value)
    except ValueError:
        data = value.split(',')
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise FilterError(f'{name} must be a JSON list of strings.')
    return [x.strip() for x in data]
