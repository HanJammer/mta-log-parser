/** Minimal toast queue. Text only — never HTML. */
import { useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react';

export type ToastKind = 'info' | 'success' | 'warning' | 'error';
export interface ToastItem {
  id: number;
  kind: ToastKind;
  text: string;
  /** optional second line, e.g. text to copy by hand */
  detail?: string;
}

let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function dismissToast(id: number) {
  items = items.filter((t) => t.id !== id);
  emit();
}

export function toast(kind: ToastKind, text: string, opts: { detail?: string; ms?: number } = {}) {
  const id = nextId++;
  items = [...items.slice(-3), { id, kind, text, detail: opts.detail }];
  emit();
  const ms = opts.ms ?? (kind === 'error' || opts.detail ? 9000 : 4000);
  window.setTimeout(() => dismissToast(id), ms);
  return id;
}

const ICONS = { info: Info, success: CheckCircle2, warning: AlertTriangle, error: XCircle };

export function Toaster({ closeLabel }: { closeLabel: string }) {
  const list = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => items,
  );
  return createPortal(
    <div className="toaster" role="status" aria-live="polite">
      {list.map((t) => {
        const Icon = ICONS[t.kind];
        return (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            <Icon size={16} aria-hidden="true" className="toast-icon" />
            <div className="toast-text">
              <div>{t.text}</div>
              {t.detail && (
                <input
                  className="input toast-detail mono"
                  readOnly
                  value={t.detail}
                  onFocus={(e) => e.currentTarget.select()}
                  aria-label={t.text}
                />
              )}
            </div>
            <button type="button" className="toast-close" onClick={() => dismissToast(t.id)} aria-label={closeLabel}>
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>,
    document.body,
  );
}
