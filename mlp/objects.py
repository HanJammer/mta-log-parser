from dataclasses import dataclass, field
from datetime import datetime
# TODO dayjs? as moment is deprecated
import moment
from typing import List, Optional

from dateutil.parser import parse
from privex.helpers import Dictable, is_false

from mlp.settings import log_timezone
from mlp import settings

import logging
log = logging.getLogger(__name__)


def _convert(value, convert_time):
    if value is None or is_false(convert_time):
        return value
    return convert_time(value)


@dataclass
class PostfixLog(Dictable):
    timestamp: datetime
    queue_id: str
    message: str

    def __post_init__(self):
        if type(self.timestamp) is not datetime:
            self.timestamp = log_timezone.localize(parse(self.timestamp))
        self.message = self.message.strip()
        self.queue_id = self.queue_id.strip()

    def __repr__(self):
        return f'<PostfixLog timestamp="{self.timestamp}" queue_id="{self.queue_id}" message="{self.message}" />'

    def __str__(self):
        return self.__repr__()

    def clean_dict(self, convert_time=str) -> dict:
        data = dict(self)
        # log lines timestamp convert before append (for message related log view)
        # this data conversion uses only one thread and takes too long so do it according to mail_log_timestamp_convert variable value
        if settings.mail_log_timestamp_convert:
            data['timestamp'] = moment.date(str(self.timestamp)).format(settings.datetime_format)
        else:
            data['timestamp'] = _convert(self.timestamp, convert_time)
        return data


@dataclass
class PostfixMessage(Dictable):
    """
    One mail message (all log lines of one queue id on one host). See ``docs/DESIGN-v2.md`` (table ``sent_mail``).
    """
    timestamp: datetime
    queue_id: str
    lines: List[PostfixLog] = field(default_factory=list)
    mail_to: str = ""
    mail_to_alias: dict = field(default_factory=dict)
    mail_from: str = ""
    subject: str = ""
    size: float = 0
    message_id: str = ""
    status: dict = field(default_factory=dict)
    relay: dict = field(default_factory=dict)
    client: dict = field(default_factory=dict)
    # --- new in 2.0 ---
    host: str = ""
    service: str = ""
    sasl_method: str = ""
    sasl_username: str = ""
    dsn: str = ""
    delay: Optional[float] = None
    delays: str = ""
    nrcpt: Optional[int] = None
    recipients: List[dict] = field(default_factory=list)
    dkim: dict = field(default_factory=dict)
    tls: Optional[bool] = None

    def __post_init__(self):
        if type(self.timestamp) is not datetime:
            self.timestamp = log_timezone.localize(parse(self.timestamp))
        self.queue_id = self.queue_id.strip()

    def __repr__(self):
        return f'<PostfixMessage host="{self.host}" timestamp="{self.timestamp}" queue_id="{self.queue_id}" status="{self.status}" />'

    def __str__(self):
        return self.__repr__()

    @property
    def id(self) -> str:
        """``"<host>:<queue_id>"`` when the host is known, else ``queue_id``"""
        return f'{self.host}:{self.queue_id}' if self.host else self.queue_id

    @property
    def first_attempt(self) -> datetime:
        return self.lines[0].timestamp if self.lines else self.timestamp

    @property
    def last_attempt(self) -> datetime:
        return self.lines[-1].timestamp if self.lines else self.timestamp

    def merge(self, dicdata: dict):
        for k, v in dicdata.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def add_recipient(self, rcpt: dict):
        """Add a per-recipient delivery result; the latest attempt for the same address wins."""
        to = rcpt.get('to')
        for i, old in enumerate(self.recipients):
            if old.get('to') == to:
                old_ts, new_ts = old.get('timestamp'), rcpt.get('timestamp')
                if old_ts is None or new_ts is None or new_ts >= old_ts:
                    self.recipients[i] = rcpt
                return
        self.recipients.append(rcpt)

    def clean_dict(self, convert_time=str) -> dict:
        data = dict(self)
        data['timestamp'] = _convert(self.timestamp, convert_time)
        data['first_attempt'] = _convert(self.first_attempt, convert_time)
        data['last_attempt'] = _convert(self.last_attempt, convert_time)
        data['lines'] = [s.clean_dict(convert_time=convert_time) for s in self.lines]
        data['recipients'] = [dict(r, timestamp=_convert(r.get('timestamp'), convert_time)) for r in self.recipients]
        return data
