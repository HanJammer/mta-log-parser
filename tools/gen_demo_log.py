#!/usr/bin/env python3
"""
Generate a synthetic postfix log (RFC 3339 syslog format, several servers) for demos, screenshots and
load tests. Only reserved example domains and documentation IP ranges are used.

    python tools/gen_demo_log.py --messages 2000 --hours 48 > demo/mail.log
    MAIL_LOG_PATH=demo MAIL_LOG_FILENAME=mail.log python manage.py parse
"""
import argparse
import random
import sys
from datetime import datetime, timedelta, timezone

HOSTS = ['mx01', 'mx02', 'relay03']
LOCAL_DOMAINS = ['example.com', 'corp.example.com']
LOCAL_USERS = ['alice', 'bob', 'carol', 'dave', 'erin', 'frank', 'grace', 'heidi', 'ivan', 'judy',
               'billing', 'noreply', 'helpdesk', 'reports', 'scanner', 'monitoring']
REMOTE = [
    ('customer.example', 'customer-example.mail.protection.example.net', '198.51.100.21'),
    ('partner.example.org', 'mx1.partner.example.org', '198.51.100.35'),
    ('supplier.example.net', 'mail.supplier.example.net', '203.0.113.40'),
    ('shop.example', 'mx.shop.example', '203.0.113.88'),
    ('agency.example.org', 'agency-example-org.mail.protection.example.net', '198.51.100.22'),
]
SUBJECTS = ['Invoice {n}', 'Weekly backup summary', 'Re: contract renewal', 'Meeting notes - infrastructure sync',
            'Purchase order PO-{n}', 'Your password will expire in 7 days', 'Scan from MFP-{n}', 'Ticket OPS-{n} updated',
            'Fwd: price list', 'Monitoring alert: disk usage {n}%', 'Newsletter: what changed in November',
            'Re: lunch?', 'Delivery delayed: order {n}', 'Quarterly report draft']
INTERNAL_CLIENTS = [('app01.example.com', '192.0.2.11'), ('app02.example.com', '192.0.2.12'),
                    ('unknown', '192.0.2.50'), ('scanner.example.com', '192.0.2.77')]
EXTERNAL_CLIENTS = [('mail.partner.example.org', '198.51.100.35'), ('unknown', '203.0.113.77'),
                    ('out.shop.example', '203.0.113.88'), ('mta.supplier.example.net', '203.0.113.40')]
ARCHIVE = 'archive@archive.example.com'


def qid(rnd):
    return ''.join(rnd.choice('0123456789ABCDEF') for _ in range(11))


class Writer:
    def __init__(self):
        self.lines = []

    def add(self, ts, host, prog, text):
        self.lines.append((ts, f'{ts.isoformat(timespec="microseconds")} {host} {prog}: {text}'))


def message(w, rnd, ts, host, n):
    q = qid(rnd)
    pid = lambda: rnd.randint(1000, 99999)  # noqa: E731
    kind = rnd.choices(['submission', 'inbound', 'internal', 'pickup', 'reject'], [35, 35, 18, 5, 7])[0]
    t = ts

    def step(sec=0.05):
        nonlocal t
        t = t + timedelta(seconds=rnd.uniform(sec * 0.5, sec * 1.5))
        return t

    if kind == 'reject':
        ch, ci = rnd.choice(EXTERNAL_CLIENTS)
        p = pid()
        w.add(step(), host, f'postfix/smtpd[{p}]', f'connect from {ch}[{ci}]')
        rcpt = f'{rnd.choice(LOCAL_USERS)}@{rnd.choice(LOCAL_DOMAINS)}'
        reason = rnd.choice(['554 5.7.1 Service unavailable; Client host [{ci}] blocked using zen.spamhaus.example',
                             '450 4.7.1 Client host rejected: cannot find your reverse hostname, [{ci}]',
                             '550 5.1.1 <{rcpt}>: Recipient address rejected: User unknown in virtual mailbox table'])
        w.add(step(), host, f'postfix/smtpd[{p}]',
              f'NOQUEUE: reject: RCPT from {ch}[{ci}]: ' + reason.format(ci=ci, rcpt=rcpt) +
              f'; from=<bulk{n}@{rnd.choice(REMOTE)[0]}> to=<{rcpt}> proto=ESMTP helo=<{ch}>')
        w.add(step(), host, f'postfix/smtpd[{p}]', f'disconnect from {ch}[{ci}] ehlo=1 mail=1 rcpt=0/1 commands=2/3')
        return

    if kind == 'submission':
        ch, ci = rnd.choice(INTERNAL_CLIENTS)
        user = rnd.choice(LOCAL_USERS)
        sender = f'{user}@{rnd.choice(LOCAL_DOMAINS)}'
        p = pid()
        w.add(step(), host, f'postfix/submission/smtpd[{p}]', f'connect from {ch}[{ci}]')
        w.add(step(), host, f'postfix/submission/smtpd[{p}]',
              f'Anonymous TLS connection established from {ch}[{ci}]: TLSv1.3 with cipher TLS_AES_256_GCM_SHA384 (256/256 bits)')
        w.add(step(), host, f'postfix/submission/smtpd[{p}]', f'{q}: client={ch}[{ci}], sasl_method=login, sasl_username={sender}')
        rcpts = [f'{rnd.choice(["sales", "office", "info", "j.smith", "a.nowak"])}@{rnd.choice(REMOTE)[0]}'
                 for _ in range(rnd.choice([1, 1, 1, 2, 3]))]
    elif kind == 'inbound':
        ch, ci = rnd.choice(EXTERNAL_CLIENTS)
        sender = f'{rnd.choice(["sales", "office", "info", "noreply", "news"])}@{rnd.choice(REMOTE)[0]}'
        p = pid()
        w.add(step(), host, f'postfix/smtpd[{p}]', f'connect from {ch}[{ci}]')
        if rnd.random() < 0.85:
            w.add(step(), host, f'postfix/smtpd[{p}]',
                  f'Anonymous TLS connection established from {ch}[{ci}]: TLSv1.2 with cipher ECDHE-RSA-AES256-GCM-SHA384 (256/256 bits)')
        w.add(step(), host, f'postfix/smtpd[{p}]', f'{q}: client={ch}[{ci}]')
        rcpts = list({f'{rnd.choice(LOCAL_USERS)}@{rnd.choice(LOCAL_DOMAINS)}' for _ in range(rnd.choice([1, 1, 2]))})
    elif kind == 'internal':
        ch, ci = rnd.choice(INTERNAL_CLIENTS)
        sender = f'{rnd.choice(["monitoring", "reports", "scanner", "noreply"])}@{LOCAL_DOMAINS[0]}'
        p = pid()
        w.add(step(), host, f'postfix/smtpd[{p}]', f'connect from {ch}[{ci}]')
        w.add(step(), host, f'postfix/smtpd[{p}]', f'{q}: client={ch}[{ci}]')
        rcpts = [f'{rnd.choice(LOCAL_USERS)}@{LOCAL_DOMAINS[0]}']
    else:  # pickup (local cron mail)
        sender = f'root@{host}.example.com'
        w.add(step(), host, f'postfix/pickup[{pid()}]', f'{q}: uid=0 from=<root>')
        rcpts = [f'admins@{LOCAL_DOMAINS[0]}']

    subject = rnd.choice(SUBJECTS).format(n=rnd.randint(100, 9999))
    cp = pid()
    w.add(step(), host, f'postfix/cleanup[{cp}]',
          f'{q}: warning: header Subject: {subject} from localhost[127.0.0.1]; from=<{sender}> to=<{rcpts[0]}> proto=ESMTP')
    w.add(step(), host, f'postfix/cleanup[{cp}]', f'{q}: message-id=<{q.lower()}.{n}@{sender.split("@")[1]}>')
    if sender.split('@')[1] in LOCAL_DOMAINS:
        w.add(step(), host, f'opendkim[{pid()}]', f'{q}: DKIM-Signature field added (s=default, d={sender.split("@")[1]})')
    size = rnd.choice([rnd.randint(900, 9000), rnd.randint(9000, 90000), rnd.randint(90000, 4000000)])
    all_rcpts = rcpts + [ARCHIVE]
    qm = 2391 if host == 'mx01' else 3120
    w.add(step(), host, f'postfix/qmgr[{qm}]', f'{q}: from=<{sender}>, size={size}, nrcpt={len(all_rcpts)} (queue active)')
    start = t

    for r in all_rcpts:
        if r == ARCHIVE:
            d = step(0.3)
            dl = (d - start).total_seconds() + 0.1
            w.add(d, host, f'postfix/lmtp[{pid()}]',
                  f'{q}: to=<{r}>, relay=mail.example.com[private/dovecot-lmtp], delay={dl:.2f}, '
                  f'delays=0.1/0.01/0.02/{dl - 0.13:.2f}, dsn=2.0.0, status=sent (250 2.0.0 <{r}> {qid(rnd)} Saved)')
            continue
        dom = r.split('@')[1]
        if dom in LOCAL_DOMAINS:
            d = step(0.2)
            w.add(d, host, f'postfix/lmtp[{pid()}]',
                  f'{q}: to=<{r}>, relay=mail.example.com[private/dovecot-lmtp], delay=0.2, delays=0.1/0.01/0.02/0.07, '
                  f'dsn=2.0.0, status=sent (250 2.0.0 <{r}> {qid(rnd)} Saved)')
            continue
        _, rh, ri = next(x for x in REMOTE if x[0] == dom)
        fate = rnd.choices(['sent', 'deferred-sent', 'deferred', 'bounced', 'nohost'], [86, 5, 3, 4, 2])[0]
        sp = pid()
        if fate == 'nohost':
            d = step(0.3)
            w.add(d, host, f'postfix/smtp[{sp}]',
                  f'{q}: to=<{r}>, relay=none, delay=0.3, delays=0.2/0.05/0.05/0, dsn=5.4.4, status=bounced '
                  f'(Host or domain name not found. Name service error for name={dom} type=A: Host not found)')
            continue
        w.add(step(0.4), host, f'postfix/smtp[{sp}]',
              f'Trusted TLS connection established to {rh}[{ri}]:25: TLSv1.3 with cipher TLS_AES_256_GCM_SHA384 (256/256 bits)')
        if fate.startswith('deferred'):
            d = step(30)
            w.add(d, host, f'postfix/smtp[{sp}]',
                  f'{q}: to=<{r}>, relay={rh}[{ri}]:25, delay={(d - start).total_seconds():.0f}, delays=0.1/0.01/30/0, '
                  f'dsn=4.4.2, status=deferred (lost connection with {rh}[{ri}] while receiving the initial server greeting)')
            if fate == 'deferred':
                continue
            d = step(900)
            w.add(d, host, f'postfix/smtp[{sp}]',
                  f'{q}: to=<{r}>, relay={rh}[{ri}]:25, delay={(d - start).total_seconds():.0f}, delays=900/0.01/0.3/0.5, '
                  f'dsn=2.0.0, status=sent (250 2.0.0 OK queued as {qid(rnd)})')
            continue
        d = step(1.2)
        dl = (d - start).total_seconds()
        if fate == 'bounced':
            w.add(d, host, f'postfix/smtp[{sp}]',
                  f'{q}: to=<{r}>, relay={rh}[{ri}]:25, delay={dl:.1f}, delays=0.1/0.02/0.4/{dl - 0.52:.2f}, dsn=5.1.1, '
                  f'status=bounced (host {rh}[{ri}] said: 550 5.1.1 <{r}>: Recipient address rejected: User unknown (in reply to RCPT TO command))')
        else:
            w.add(d, host, f'postfix/smtp[{sp}]',
                  f'{q}: to=<{r}>, relay={rh}[{ri}]:25, delay={dl:.1f}, delays=0.1/0.02/0.4/{dl - 0.52:.2f}, dsn=2.6.0, '
                  f'status=sent (250 2.6.0 <{q.lower()}@{rh}> Queued mail for delivery)')
    w.add(step(), host, f'postfix/qmgr[{qm}]', f'{q}: removed')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--messages', type=int, default=1500)
    ap.add_argument('--hours', type=float, default=48)
    ap.add_argument('--seed', type=int, default=30)
    ap.add_argument('--end', help='ISO timestamp of the last message (default: now)')
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    end = datetime.fromisoformat(a.end) if a.end else datetime.now(timezone.utc)
    start = end - timedelta(hours=a.hours)
    w = Writer()
    for n in range(a.messages):
        # busier during the working day
        while True:
            ts = start + timedelta(seconds=rnd.uniform(0, a.hours * 3600))
            if rnd.random() < (1.0 if 7 <= ts.hour <= 17 else 0.35):
                break
        message(w, rnd, ts, rnd.choices(HOSTS, [55, 35, 10])[0], n)
    for _, line in sorted(w.lines, key=lambda x: x[0]):
        sys.stdout.write(line + '\n')


if __name__ == '__main__':
    main()
