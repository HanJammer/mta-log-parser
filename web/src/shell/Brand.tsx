import { useId } from 'react';

/** Air-mail envelope: the app's only decorative element. */
export function BrandMark({ size = 26 }: { size?: number }) {
  const id = useId().replace(/:/g, '');
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="brand-mark">
      <defs>
        <clipPath id={`c${id}`}>
          <rect x="2" y="6" width="28" height="20" rx="3" />
        </clipPath>
        <pattern id={`p${id}`} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="3.4" height="8" fill="var(--airmail-red)" />
          <rect x="4" width="3.4" height="8" fill="var(--airmail-blue)" />
        </pattern>
      </defs>
      <g clipPath={`url(#c${id})`}>
        <rect x="2" y="6" width="28" height="20" fill={`url(#p${id})`} />
        <rect x="4.6" y="8.6" width="22.8" height="14.8" rx="1" fill="var(--surface)" />
      </g>
      <path d="M7.5 12l8.5 5.6 8.5-5.6" fill="none" stroke="var(--ink)" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
