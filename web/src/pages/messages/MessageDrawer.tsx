import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronUp, Copy, Link2, Lock, LockOpen, WrapText, X } from 'lucide-react';
import { useEmail } from '../../api/hooks';
import type { Email } from '../../api/types';
import { copyText } from '../../lib/clipboard';
import { formatClient, formatDelay, formatRelay, formatSize, formatTime, recipientsOf, tzLabel } from '../../lib/format';
import { toSearchParams, type ListState } from '../../lib/filters';
import { usePrefs } from '../../lib/prefs';
import { errorText } from '../../lib/errors';
import { Button, cx, Empty, Spinner } from '../../ui/primitives';
import { Drawer } from '../../ui/overlays';
import { StatusBadge, StatusIcon, statusKey } from '../../ui/StatusBadge';
import { toast } from '../../ui/toast';

interface Props {
  id: string | undefined;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  state: ListState;
}

async function copy(text: string, ok: string, fail: string) {
  if (await copyText(text)) toast('success', ok);
  else toast('warning', fail, { detail: text.length < 2000 ? text : undefined, ms: 15000 });
}

export function MessageDrawer({ id, onClose, onPrev, onNext, state }: Props) {
  const { t } = useTranslation();
  const q = useEmail(id);

  useEffect(() => {
    if (!id) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest('input, textarea, select, [contenteditable]')) return;
      if ((e.key === 'ArrowDown' || e.key === 'j') && onNext) {
        e.preventDefault();
        onNext();
      } else if ((e.key === 'ArrowUp' || e.key === 'k') && onPrev) {
        e.preventDefault();
        onPrev();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [id, onNext, onPrev]);

  const { defaultRange } = usePrefs();
  const deepLink = () => {
    const qs = toSearchParams({ ...state, msg: id }, { defaultRange, absolute: true }).toString();
    return `${window.location.origin}${window.location.pathname}?${qs}`;
  };

  return (
    <Drawer open={!!id} onClose={onClose} label={t('detail.title')}>
      <header className="drawer-head">
        <div className="drawer-title">
          {q.data ? <StatusBadge code={q.data.status?.code} /> : <span className="badge st-unknown">…</span>}
          <h2 className="mono drawer-id" title={id}>
            {q.data?.queue_id ?? id}
          </h2>
          {q.data?.host && <span className="drawer-host mono">{q.data.host}</span>}
        </div>
        <div className="drawer-actions">
          <Button size="sm" variant="ghost" icon={<ChevronUp size={16} />} disabled={!onPrev} onClick={onPrev} aria-label={t('detail.prev')} title={`${t('detail.prev')} (↑ / k)`} />
          <Button size="sm" variant="ghost" icon={<ChevronDown size={16} />} disabled={!onNext} onClick={onNext} aria-label={t('detail.next')} title={`${t('detail.next')} (↓ / j)`} />
          <Button size="sm" variant="ghost" icon={<Link2 size={15} />} onClick={() => void copy(deepLink(), t('share.copied'), t('share.manual'))} aria-label={t('detail.copyLink')} title={t('detail.copyLink')} />
          <Button size="sm" variant="ghost" icon={<X size={17} />} onClick={onClose} aria-label={t('common.close')} title={`${t('common.close')} (Esc)`} />
        </div>
      </header>
      <div className="drawer-body">
        {q.isPending && (
          <div className="drawer-loading">
            <Spinner size={18} label={t('common.loading')} />
          </div>
        )}
        {q.isError && <Empty title={t('detail.notFound')}>{errorText(q.error, t)}</Empty>}
        {q.data && <Detail e={q.data} />}
      </div>
    </Drawer>
  );
}

function Row({ label, children, mono }: { label: string; children: ReactNode; mono?: boolean }) {
  if (children === null || children === undefined || children === '') return null;
  return (
    <div className="kv-row">
      <dt>{label}</dt>
      <dd className={mono ? 'mono' : undefined}>{children}</dd>
    </div>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="dgroup">
      <h3>{title}</h3>
      <dl className="kv">{children}</dl>
    </section>
  );
}

function Detail({ e }: { e: Email }) {
  const { t } = useTranslation();
  const { timeZone } = usePrefs();
  const [wrap, setWrap] = useState(true);
  const recips = recipientsOf(e);
  const allRecips = recipientsOf(e, true);
  const tm = (iso?: string | null) => (iso ? formatTime(iso, timeZone) : null);
  const logText = (e.lines ?? []).map((l) => `${l.timestamp} ${l.message}`).join('\n');
  const st = statusKey(e.status?.code);

  return (
    <>
      <section className="dsummary">
        <div className="dsummary-route">
          <span className="dsummary-from">{e.mail_from || <span className="muted-3">{t('detail.noSender')}</span>}</span>
          <span className="dsummary-arrow" aria-hidden="true">→</span>
          <span className="dsummary-to">
            {recips[0]?.to ?? '—'}
            {recips.length > 1 && <span className="more">+{recips.length - 1}</span>}
          </span>
        </div>
        {e.subject ? <div className="dsummary-subject">{e.subject}</div> : <div className="dsummary-subject muted-3">{t('detail.noSubject')}</div>}
        {e.status?.message && (
          <div className={cx('dsummary-status', `st-${st}`)}>
            <StatusIcon code={st} size={14} />
            <code>{e.status.message}</code>
          </div>
        )}
      </section>

      <div className="dgrid">
        <Group title={t('detail.envelope')}>
          <Row label={t('col.from')}>{e.mail_from}</Row>
          <Row label={t('detail.srsFrom')} mono>
            {e.srs_from}
          </Row>
          <Row label={t('col.to')}>{recips.map((r) => r.to).join(', ')}</Row>
          <Row label={t('col.subject')}>{e.subject}</Row>
          <Row label={t('col.message_id')} mono>
            {e.message_id}
          </Row>
          <Row label={t('col.size')}>{e.size !== null && e.size !== undefined && e.size !== '' ? `${formatSize(e.size)} KiB` : null}</Row>
          <Row label={t('col.nrcpt')}>{e.nrcpt ?? null}</Row>
        </Group>

        <Group title={t('detail.server')}>
          <Row label={t('col.host')} mono>
            {e.host}
          </Row>
          <Row label={t('col.service')} mono>
            {e.service}
          </Row>
          <Row label={t('col.queue_id')} mono>
            {e.queue_id}
          </Row>
          <Row label={t('detail.id')} mono>
            {e.id}
          </Row>
          <Row label={`${t('col.time')} (${tzLabel(timeZone)})`} mono>
            {tm(e.timestamp)}
          </Row>
          <Row label={t('col.first_attempt')} mono>
            {tm(e.first_attempt)}
          </Row>
          <Row label={t('col.last_attempt')} mono>
            {tm(e.last_attempt)}
          </Row>
        </Group>

        <Group title={t('detail.client')}>
          <Row label={t('col.client')} mono>
            {formatClient(e.client) || null}
          </Row>
          <Row label={t('detail.saslMethod')} mono>
            {e.sasl_method}
          </Row>
          <Row label={t('col.sasl')}>{e.sasl_username}</Row>
          <Row label={t('col.tls')}>
            {e.tls === true ? (
              <span className="tls tls-on">
                <Lock size={13} aria-hidden="true" /> {t('detail.tlsYes')}
              </span>
            ) : e.tls === false ? (
              <span className="tls tls-off">
                <LockOpen size={13} aria-hidden="true" /> {t('detail.tlsNo')}
              </span>
            ) : null}
          </Row>
        </Group>

        <Group title={t('detail.delivery')}>
          <Row label={t('col.status')}>
            <StatusBadge code={e.status?.code} compact />
          </Row>
          <Row label={t('col.relay')} mono>
            {formatRelay(e.relay) || null}
          </Row>
          <Row label={t('col.dsn')} mono>
            {e.dsn}
          </Row>
          <Row label={t('col.delay')}>{e.delay !== null && e.delay !== undefined ? `${formatDelay(e.delay)} (${e.delay} s)` : null}</Row>
          <Row label={t('detail.dkim')} mono>
            {e.dkim?.domain ? `d=${e.dkim.domain}${e.dkim.selector ? `  s=${e.dkim.selector}` : ''}` : null}
          </Row>
        </Group>
      </div>

      <section className="dsection">
        <h3>
          {t('detail.recipients')} <span className="count">{allRecips.length}</span>
        </h3>
        {allRecips.length === 0 ? (
          <p className="muted-3">—</p>
        ) : (
          <div className="rtable-wrap">
            <table className="rtable">
              <thead>
                <tr>
                  <th>{t('detail.rcptTo')}</th>
                  <th>{t('col.status')}</th>
                  <th>{t('col.relay')}</th>
                  <th>{t('col.dsn')}</th>
                  <th className="is-right">{t('col.delay')}</th>
                  <th>{t('detail.rcptTime')}</th>
                </tr>
              </thead>
              <tbody>
                {allRecips.map((r, i) => (
                  <tr key={`${r.to}-${i}`} className={r.hidden ? 'is-hidden-rcpt' : undefined}>
                    <td>
                      <div>
                        {r.to}
                        {r.hidden && (
                          <span className="tag-hidden" title={t('detail.hiddenRecipientHint')}>
                            {t('detail.hiddenRecipient')}
                          </span>
                        )}
                      </div>
                      {r.orig_to && r.orig_to !== r.to && (
                        <div className="muted-3 small">
                          {t('detail.rcptOrigTo')}: {r.orig_to}
                        </div>
                      )}
                    </td>
                    <td title={r.status?.message ?? undefined}>{r.status ? <StatusBadge code={r.status.code} compact title={r.status.message ?? undefined} /> : <span className="muted-3">—</span>}</td>
                    <td className="mono small">{formatRelay(r.relay)}</td>
                    <td className="mono small">{r.dsn}</td>
                    <td className="is-right small">{formatDelay(r.delay)}</td>
                    <td className="mono small">{tm(r.timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {allRecips.some((r) => r.status?.message) && allRecips.length > 1 && (
          <ul className="rmessages">
            {allRecips
              .filter((r) => r.status?.message)
              .map((r, i) => (
                <li key={i}>
                  <StatusIcon code={r.status?.code ?? 'unknown'} size={13} />
                  <span className="rmessages-to">{r.to}</span>
                  <code>{r.status?.message}</code>
                </li>
              ))}
          </ul>
        )}
      </section>

      <section className="dsection">
        <div className="dsection-head">
          <h3>
            {t('detail.logLines')} <span className="count">{e.lines?.length ?? 0}</span>
          </h3>
          <div className="dsection-tools">
            <Button size="sm" variant="ghost" icon={<WrapText size={14} />} pressed={wrap} onClick={() => setWrap((w) => !w)} title={t('detail.wrap')} aria-label={t('detail.wrap')} />
            <Button size="sm" icon={<Copy size={14} />} disabled={!logText} onClick={() => void copy(logText, t('detail.copied'), t('detail.copyFailed'))}>
              {t('detail.copy')}
            </Button>
          </div>
        </div>
        {logText ? (
          <pre className={cx('loglines', wrap && 'is-wrapped')}>
            {(e.lines ?? []).map((l, i) => (
              <div key={i} className="logline">
                <span className="logline-time">{formatTime(l.timestamp, timeZone)}</span>
                <span className="logline-msg">{l.message}</span>
              </div>
            ))}
          </pre>
        ) : (
          <p className="muted-3">{t('detail.noLines')}</p>
        )}
      </section>
    </>
  );
}
