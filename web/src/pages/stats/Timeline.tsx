import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TimelinePoint } from '../../api/types';
import { usePrefs } from '../../lib/prefs';
import { StatusIcon } from '../../ui/StatusBadge';

const STACK = ['sent', 'deferred', 'bounced', 'reject', 'other'] as const;

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * exp >= v) return m * exp;
  return 10 * exp;
}

function bucketLabel(iso: string, bucket: 'hour' | 'day', utc: boolean, lng: string, long = false): string {
  const d = new Date(iso);
  const opts: Intl.DateTimeFormatOptions =
    bucket === 'hour'
      ? long
        ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
        : { hour: '2-digit', minute: '2-digit' }
      : { month: 'short', day: 'numeric', ...(long ? { weekday: 'short' } : {}) };
  return d.toLocaleString(lng, { ...opts, timeZone: utc ? 'UTC' : undefined });
}

/** Stacked columns per hour/day, one y-axis, hover tooltip with the breakdown. */
export function Timeline({ points, bucket }: { points: TimelinePoint[]; bucket: 'hour' | 'day' }) {
  const { t, i18n } = useTranslation();
  const { timeZone } = usePrefs();
  const [hover, setHover] = useState<number | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const nf = new Intl.NumberFormat(i18n.language);
  const utc = timeZone === 'utc';

  const data = useMemo(() => points.map((p) => ({ ...p, total: p.sent + p.deferred + p.bounced + p.reject + p.other })), [points]);
  if (!data.length) return <p className="muted-3 panel-empty">{t('stats.noData')}</p>;

  const W = 1000;
  const H = 220;
  const padL = 44;
  const padB = 24;
  const padT = 8;
  const plotW = W - padL - 8;
  const plotH = H - padB - padT;
  const max = niceMax(Math.max(...data.map((d) => d.total)));
  const step = plotW / data.length;
  const barW = Math.max(2, Math.min(28, step - 2));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const labelEvery = Math.max(1, Math.ceil(data.length / 10));
  const y = (v: number) => padT + plotH - (v / max) * plotH;
  const hp = hover !== null ? data[hover] : null;

  return (
    <div className="timeline" ref={wrap} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="timeline-svg" role="img" aria-label={t('stats.timeline')}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={padL} x2={W - 8} y1={y(v)} y2={y(v)} className="grid-line" />
          </g>
        ))}
        {data.map((d, i) => {
          const x = padL + i * step + (step - barW) / 2;
          let acc = 0;
          return (
            <g key={d.t} onMouseEnter={() => setHover(i)}>
              <rect x={padL + i * step} y={padT} width={step} height={plotH} className={hover === i ? 'hover-col is-on' : 'hover-col'} />
              {STACK.map((s) => {
                const v = d[s];
                if (!v) return null;
                const y0 = y(acc);
                acc += v;
                const y1 = y(acc);
                const h = Math.max(0, y0 - y1 - (acc < d.total ? 1 : 0));
                return <rect key={s} x={x} y={y1} width={barW} height={h} className={`seg-${s}`} rx={acc === d.total ? 1.5 : 0} />;
              })}
            </g>
          );
        })}
        <line x1={padL} x2={W - 8} y1={y(0)} y2={y(0)} className="axis-line" />
      </svg>
      {/* HTML labels: crisp text regardless of the SVG's horizontal stretch */}
      <div className="timeline-y" style={{ height: plotH, top: padT }}>
        {ticks
          .slice()
          .reverse()
          .map((v) => (
            <span key={v}>{nf.format(v)}</span>
          ))}
      </div>
      <div className="timeline-x" style={{ left: `${(padL / W) * 100}%`, right: `${(8 / W) * 100}%` }}>
        {data.map((d, i) =>
          i % labelEvery === 0 ? (
            <span key={d.t} style={{ left: `${((i + 0.5) / data.length) * 100}%` }}>
              {bucketLabel(d.t, bucket, utc, i18n.language)}
            </span>
          ) : null,
        )}
      </div>
      {hp && hover !== null && (
        <div
          className="chart-tip"
          style={{
            left: `${((padL + (hover + 0.5) * step) / W) * 100}%`,
            transform: hover > data.length / 2 ? 'translateX(calc(-100% - 12px))' : 'translateX(12px)',
          }}
        >
          <div className="chart-tip-title">{bucketLabel(hp.t, bucket, utc, i18n.language, true)}</div>
          {STACK.map((s) => (
            <div key={s} className="chart-tip-row">
              <span className={`legend-swatch seg-${s}`} aria-hidden="true" />
              {s !== 'other' && <StatusIcon code={s} size={12} />}
              <span>{s === 'other' ? t('stats.other') : t(`status.${s}`)}</span>
              <span className="chart-tip-val">{nf.format(hp[s])}</span>
            </div>
          ))}
          <div className="chart-tip-row chart-tip-total">
            <span>{t('stats.total')}</span>
            <span className="chart-tip-val">{nf.format(hp.total)}</span>
          </div>
        </div>
      )}
      <ul className="legend legend-inline">
        {STACK.map((s) => (
          <li key={s}>
            <span className={`legend-swatch seg-${s}`} aria-hidden="true" />
            <span className="legend-label">{s === 'other' ? t('stats.other') : t(`status.${s}`)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
