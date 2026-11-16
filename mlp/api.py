"""
JSON response helpers and the JSON provider of the web app.

Every error answer has the shape ``{"error": true, "error_code": "...", "message": "..."}``.
"""
from datetime import date, datetime, timezone
from typing import Union

from quart import jsonify
from quart.json.provider import DefaultJSONProvider

import logging

log = logging.getLogger(__name__)


def error_dict(error_code: str, msg: str, extra: dict = None) -> dict:
    extra = {} if not extra else dict(extra)
    return dict(error=True, error_code=error_code, message=msg, **extra)


def error(error_code: str, msg: str, code: int = 400, extra: dict = None, headers: dict = None):
    """
    Generate a JSON error response.

        >>> def my_view():
        ...     return api.error('NOT_FOUND', 'No object found with that ID', code=404)
    """
    res = jsonify(error_dict(error_code, msg, extra=extra))
    res.status_code = code
    for k, v in (headers or {}).items():
        res.headers[k] = v
    return res


def result_dict(res: Union[dict, list, str, int], count: int = None, total: int = None, extra: dict = None):
    extra = {} if not extra else dict(extra)
    _res = dict(error=False)
    if count is None and isinstance(res, (list, set, tuple)):
        _res['count'] = len(res)
    elif count is not None:
        _res['count'] = int(count)
    if total is not None:
        _res['total'] = int(total)
    return {**_res, 'result': res, **extra}


def result(res: Union[dict, list, str, int], code: int = 200, count: int = None, total: int = None, extra: dict = None):
    """Generate a JSON ``{error: false, result: ...}`` response."""
    return jsonify(result_dict(res, count=count, total=total, extra=extra)), code


def _json_default(o):
    # RethinkDB returns aware datetimes (RqlTzinfo, keeping the stored offset); always emit
    # ISO 8601 in UTC with an explicit offset. Naive values are taken as UTC.
    if isinstance(o, datetime):
        if o.tzinfo is None:
            o = o.replace(tzinfo=timezone.utc)
        return o.astimezone(timezone.utc).isoformat()
    if isinstance(o, date):
        return o.isoformat()
    return DefaultJSONProvider.default(o)


class MLPJSONProvider(DefaultJSONProvider):
    """Like Quart's default provider, but datetimes become ISO 8601 strings instead of RFC 822."""
    default = staticmethod(_json_default)
    ensure_ascii = False
