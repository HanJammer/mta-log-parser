import { useEffect, useMemo, useRef, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cx } from './primitives';
import { trapTab, useFocusReturn, useOutsidePointer, usePopoverPosition } from './overlay';

export function Popover({
  open,
  onClose,
  anchor,
  children,
  align = 'start',
  label,
  className,
}: {
  open: boolean;
  onClose: () => void;
  anchor: RefObject<HTMLElement | null>;
  children: ReactNode;
  align?: 'start' | 'end';
  label: string;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const pos = usePopoverPosition(open, anchor, ref, align);
  const refs = useMemo(() => [ref, anchor], [anchor]);
  useOutsidePointer(open, refs, onClose);
  useFocusReturn(open, ref);
  if (!open) return null;
  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-label={label}
      tabIndex={-1}
      className={cx('popover', className)}
      style={{
        top: pos?.top ?? -9999,
        left: pos?.left ?? -9999,
        minWidth: pos?.minWidth,
        maxHeight: pos?.maxHeight,
        visibility: pos ? 'visible' : 'hidden',
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      {children}
    </div>,
    document.body,
  );
}

let modalCount = 0;

export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  width = 520,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
  className?: string;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  useFocusReturn(open, ref);
  useEffect(() => {
    if (!open) return;
    const root = document.getElementById('root');
    modalCount += 1;
    root?.setAttribute('inert', '');
    document.body.classList.add('no-scroll');
    return () => {
      modalCount -= 1;
      if (modalCount === 0) {
        root?.removeAttribute('inert');
        document.body.classList.remove('no-scroll');
      }
    };
  }, [open]);
  if (!open) return null;
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        tabIndex={-1}
        className={cx('dialog', className)}
        style={{ width: `min(${width}px, calc(100vw - 24px))` }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            onClose();
          }
          trapTab(e, ref.current);
        }}
      >
        <header className="dialog-head">
          <h2 id="dialog-title">{title}</h2>
          <button type="button" className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label={t('common.close')}>
            <X size={16} />
          </button>
        </header>
        <div className="dialog-body">{children}</div>
        {footer && <footer className="dialog-foot">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

/** Right-hand side panel. Not modal on wide screens: the table stays usable behind it. */
export function Drawer({
  open,
  onClose,
  label,
  children,
}: {
  open: boolean;
  onClose: () => void;
  label: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);
  useFocusReturn(open, ref);
  if (!open) return null;
  return createPortal(
    <aside
      ref={ref}
      className="drawer"
      role="dialog"
      aria-modal="false"
      aria-label={label}
      tabIndex={-1}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && !e.defaultPrevented) {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      {children}
    </aside>,
    document.body,
  );
}
