/**
 * Deterministic fake mail log data for `VITE_MOCK=1` (development and screenshots only).
 * Only reserved example domains and documentation IP ranges are used.
 */
import type { Email, LogLine, Recipient, Relay, StatusCode } from '../types';

let seed = 20261116;
function rnd(): number {
  // mulberry32
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
const pick = <T,>(arr: readonly T[]): T => arr[Math.floor(rnd() * arr.length)];
const hex = (n: number) =>
  Array.from({ length: n }, () => '0123456789ABCDEF'[Math.floor(rnd() * 16)]).join('');

const HOSTS = ['mx01', 'mx02'];
const USERS = ['alice', 'bob', 'carol', 'dave', 'erin', 'frank', 'grace', 'heidi', 'ivan', 'judy', 'mallory', 'oscar'];
const SYSTEM_SENDERS = ['noreply@example.com', 'alerts@monitoring.example.com', 'billing@example.com', 'jira@tracker.example.com'];
const EXT_DOMAINS = ['example.org', 'example.net', 'mail.example.org', 'partner.example.net', 'customer.example'];
const SUBJECTS = [
  'Invoice 2026/11/0412',
  'Re: Quarterly report draft',
  'Delivery delayed: order #55120',
  '[ALERT] disk usage on db02 above 90%',
  'Meeting notes — infrastructure sync',
  'Your password will expire in 7 days',
  'Fwd: contract renewal',
  'Weekly backup summary',
  'Re: Re: VPN access for the new contractor',
  'Price list December',
  'Out of office: back on Monday',
  'Ticket OPS-2817 updated',
  'Newsletter: what changed in November',
  'Scan from MFP-2F',
  'Re: lunch?',
  'Purchase order PO-77813',
  'Certificate for www.example.com expires soon',
  '',
];
const RELAYS_EXT: Relay[] = [
  { host: 'mx.example.org', ip: '198.51.100.25', port: 25 },
  { host: 'mx1.example.net', ip: '203.0.113.10', port: 25 },
  { host: 'mx2.example.net', ip: '203.0.113.11', port: 25 },
  { host: 'smtp.partner.example.net', ip: '198.51.100.80', port: 25 },
  { host: 'inbound.customer.example', ip: '192.0.2.200', port: 25 },
];
const RELAY_LOCAL: Relay = { host: 'lmtp.example.com', ip: '10.20.0.15', port: 24 };
const RELAY_ARCHIVE: Relay = { host: 'mail.example.com', ip: 'private/dovecot-lmtp', port: '' };
const CLIENTS = [
  { host: 'web01.example.com', ip: '10.20.1.11' },
  { host: 'web02.example.com', ip: '10.20.1.12' },
  { host: 'unknown', ip: '192.0.2.44' },
  { host: 'mail-out.example.org', ip: '198.51.100.31' },
  { host: 'localhost', ip: '127.0.0.1' },
  { host: 'unknown', ip: '203.0.113.77' },
];

const MSG_SENT = (r: Relay) =>
  r.port === 24
    ? `250 2.0.0 <${hex(6).toLowerCase()}> Saved`
    : `250 2.0.0 OK ${Math.floor(rnd() * 1e9)} ${hex(10).toLowerCase()} - accepted`;
const MSG_DEFERRED = (r: Relay) =>
  pick([
    `connect to ${r.host}[${r.ip}]:25: Connection timed out`,
    `host ${r.host}[${r.ip}] said: 451 4.7.1 Greylisted, please try again later (in reply to RCPT TO command)`,
    `host ${r.host}[${r.ip}] said: 452 4.2.2 Mailbox full (in reply to RCPT TO command)`,
  ]);
const MSG_BOUNCED = (r: Relay, to: string) =>
  pick([
    `host ${r.host}[${r.ip}] said: 550 5.1.1 <${to}>: Recipient address rejected: User unknown (in reply to RCPT TO command)`,
    `host ${r.host}[${r.ip}] said: 554 5.7.1 Message rejected as spam (in reply to end of DATA command)`,
  ]);

function addrLocal(): string {
  return `${pick(USERS)}@example.com`;
}
function addrExt(): string {
  return `${pick(['info', 'sales', 'office', 'kontakt', 'j.smith', 'a.kowalska', 'support', 'hr'])}@${pick(EXT_DOMAINS)}`;
}

function iso(ms: number): string {
  return new Date(ms).toISOString().replace('Z', '+00:00');
}

function syslogLine(host: string, ms: number, proc: string, text: string, qid: string | null): LogLine {
  return { timestamp: iso(ms), queue_id: qid, message: `${host} postfix/${proc}: ${text}` };
}

function makeEmail(i: number, now: number): Email {
  const host = rnd() < 0.62 ? HOSTS[0] : HOSTS[1];
  // denser traffic in the recent past
  const ageMs = Math.pow(rnd(), 1.8) * 8 * 24 * 3600e3;
  const t0 = now - ageMs - i * 7;
  const qid = hex(rnd() < 0.5 ? 10 : 11);
  const roll = rnd();
  const submission = rnd() < 0.28;
  const outgoing = submission || rnd() < 0.55;
  const client = submission ? pick(CLIENTS.slice(0, 2)) : outgoing ? pick(CLIENTS) : pick(CLIENTS.slice(2));
  const from = submission ? addrLocal() : outgoing ? pick([...SYSTEM_SENDERS, addrLocal()]) : addrExt();
  const nrcpt = rnd() < 0.12 ? 2 + Math.floor(rnd() * 4) : 1;
  const legacyMultiple = nrcpt > 1 && rnd() < 0.25;
  const size = Math.round((1 + rnd() * rnd() * 900) * 100) / 100;

  let code: StatusCode =
    roll < 0.74 ? 'sent' : roll < 0.85 ? 'deferred' : roll < 0.92 ? 'bounced' : roll < 0.97 ? 'reject' : 'unknown';

  const recipients: Recipient[] = [];
  const lines: LogLine[] = [];
  const service = submission ? 'submission' : client.host === 'localhost' ? 'pickup' : 'smtpd';
  const smtpdProc = submission ? 'submission/smtpd' : 'smtpd';
  const pid = 1000 + Math.floor(rnd() * 60000);
  const tls = client.host !== 'localhost' && rnd() < 0.8;

  if (code === 'reject') {
    const to = outgoing ? addrExt() : addrLocal();
    const msg = `554 5.7.1 Service unavailable; Client host [${client.ip}] blocked using dnsbl.example.org`;
    lines.push(syslogLine(host, t0, `smtpd[${pid}]`, `connect from ${client.host}[${client.ip}]`, null));
    lines.push(
      syslogLine(host, t0 + 300, `smtpd[${pid}]`, `NOQUEUE: reject: RCPT from ${client.host}[${client.ip}]: ${msg}; from=<${from}> to=<${to}> proto=ESMTP helo=<${client.host}>`, null),
    );
    return {
      id: `${host}:${qid}`,
      queue_id: qid,
      host,
      timestamp: iso(t0),
      first_attempt: iso(t0),
      last_attempt: iso(t0 + 300),
      mail_from: from,
      mail_to: to,
      recipients: [{ to, status: { code: 'reject', message: msg }, timestamp: iso(t0 + 300) }],
      subject: '',
      size: null,
      message_id: null,
      status: { code: 'reject', message: msg },
      relay: null,
      client,
      service: 'smtpd',
      nrcpt: null,
      tls: null,
      lines,
    };
  }

  if (tls) lines.push(syslogLine(host, t0 - 40, `${smtpdProc}[${pid}]`, `Anonymous TLS connection established from ${client.host}[${client.ip}]: TLSv1.3 with cipher TLS_AES_256_GCM_SHA384 (256/256 bits)`, null));
  lines.push(
    syslogLine(
      host,
      t0,
      `${smtpdProc}[${pid}]`,
      `${qid}: client=${client.host}[${client.ip}]${submission ? `, sasl_method=login, sasl_username=${from}` : ''}`,
      qid,
    ),
  );
  const msgId = `<${hex(8).toLowerCase()}.${hex(6).toLowerCase()}@${from.split('@')[1]}>`;
  lines.push(syslogLine(host, t0 + 20, `cleanup[${pid + 3}]`, `${qid}: message-id=${msgId}`, qid));
  const dkim = outgoing && rnd() < 0.85 ? { domain: from.split('@')[1], selector: 'default' } : null;
  if (dkim) {
    lines.push({
      timestamp: iso(t0 + 30),
      queue_id: qid,
      message: `${host} opendkim[812]: ${qid}: DKIM-Signature field added (s=${dkim.selector}, d=${dkim.domain})`,
    });
  }
  lines.push(syslogLine(host, t0 + 40, 'qmgr[1201]', `${qid}: from=<${from}>, size=${Math.round(size * 1024)}, nrcpt=${nrcpt} (queue active)`, qid));

  let tLast = t0 + 40;
  const counts: Record<string, number> = {};
  // most messages also get an archive copy handed over LMTP (as on the real servers)
  const archive = !legacyMultiple && code !== 'unknown' && rnd() < 0.8;
  const total = nrcpt + (archive ? 1 : 0);
  for (let r = 0; r < total; r++) {
    const isArchive = archive && r === total - 1;
    const to = isArchive ? 'archive@example.com' : outgoing ? addrExt() : addrLocal();
    const relay = isArchive ? RELAY_ARCHIVE : outgoing ? pick(RELAYS_EXT) : RELAY_LOCAL;
    let rc: StatusCode = isArchive ? 'sent' : code;
    if (!isArchive && nrcpt > 1 && r > 0 && rnd() < 0.35) rc = pick(['sent', 'deferred', 'bounced'] as const);
    if (code === 'unknown') rc = 'unknown';
    counts[rc] = (counts[rc] ?? 0) + 1;
    const delay = Math.round((rc === 'deferred' ? 30 + rnd() * 3000 : 0.2 + rnd() * 4) * 10) / 10;
    const dsn = rc === 'sent' ? '2.0.0' : rc === 'deferred' ? pick(['4.4.1', '4.7.1', '4.2.2']) : rc === 'bounced' ? pick(['5.1.1', '5.7.1']) : '';
    const message =
      rc === 'sent' ? MSG_SENT(relay) : rc === 'deferred' ? MSG_DEFERRED(relay) : rc === 'bounced' ? MSG_BOUNCED(relay, to) : 'status not found in log';
    tLast = t0 + 40 + delay * 1000;
    const orig_to = !outgoing && rnd() < 0.2 ? `team@example.com` : null;
    const delays = `0.${Math.floor(rnd() * 9)}/0.0${Math.floor(rnd() * 9)}/0.${Math.floor(rnd() * 9)}/${(delay / 3).toFixed(1)}`;
    recipients.push({
      to,
      orig_to,
      status: { code: rc, message },
      relay,
      dsn,
      delay,
      delays,
      timestamp: iso(tLast),
    });
    if (rc !== 'unknown') {
      lines.push(
        syslogLine(
          host,
          tLast,
          `${relay.port === 24 || isArchive ? 'lmtp' : 'smtp'}[${pid + 10 + r}]`,
          `${qid}: to=<${to}>,${orig_to ? ` orig_to=<${orig_to}>,` : ''} relay=${relay.host}[${relay.ip}]${relay.port ? `:${relay.port}` : ''}, delay=${delay}, delays=${delays}, dsn=${dsn}, status=${rc} (${message})`,
          qid,
        ),
      );
    }
  }
  if (code === 'bounced' || Object.keys(counts).includes('bounced')) {
    lines.push(syslogLine(host, tLast + 10, `bounce[${pid + 40}]`, `${qid}: sender non-delivery notification: ${hex(10)}`, qid));
  }
  if (code !== 'deferred') lines.push(syslogLine(host, tLast + 20, 'qmgr[1201]', `${qid}: removed`, qid));

  // overall status: worst recipient delivery (bounced > reject > deferred > sent)
  const multiple = recipients.length > 1;
  if (multiple && code !== 'unknown') code = counts.bounced ? 'bounced' : counts.deferred ? 'deferred' : 'sent';
  if (legacyMultiple) code = 'multiple';
  // representative delivery: the worst failure, else the last network (non-LMTP archive) hand-off
  const failed = recipients.filter((r) => r.status?.code === code && code !== 'sent');
  const network = recipients.filter((r) => r.relay !== RELAY_ARCHIVE);
  const last = failed[failed.length - 1] ?? network[network.length - 1] ?? recipients[recipients.length - 1];
  const summary = multiple
    ? `${recipients.length} recipients: ${Object.entries(counts)
        .map(([k, n]) => `${n} ${k}`)
        .join(', ')}. `
    : '';
  const legacyTo = legacyMultiple
    ? JSON.stringify(recipients.map((r) => (r.orig_to ? { mail_to: r.to, mail_to_alias: r.orig_to } : r.to)))
    : recipients[0].to;

  return {
    id: `${host}:${qid}`,
    queue_id: qid,
    host,
    timestamp: iso(t0),
    first_attempt: iso(t0),
    last_attempt: iso(tLast),
    mail_from: from,
    mail_to: legacyTo,
    mail_to_alias: recipients[0].orig_to ? { [recipients[0].to]: recipients[0].orig_to } : {},
    // legacy rows (status `multiple`) come from the old parser without per-recipient data
    recipients: legacyMultiple ? null : recipients,
    subject: pick(SUBJECTS),
    size,
    message_id: msgId,
    status: { code, message: legacyMultiple ? '' : summary + (last.status?.message ?? '') },
    multiple: legacyMultiple ? null : multiple,
    relay: last.relay,
    client,
    sasl_method: submission ? 'login' : null,
    sasl_username: submission ? from : null,
    service,
    dsn: legacyMultiple ? null : last.dsn,
    delay: legacyMultiple ? null : last.delay,
    nrcpt: recipients.length,
    dkim,
    tls,
    lines,
  };
}

let cache: Email[] | null = null;

export function mockEmails(): Email[] {
  if (cache) return cache;
  const now = Date.now();
  const list: Email[] = [];
  for (let i = 0; i < 1400; i++) list.push(makeEmail(i, now));
  list.sort((a, b) => (b.timestamp ?? '').localeCompare(a.timestamp ?? ''));
  cache = list;
  return list;
}
