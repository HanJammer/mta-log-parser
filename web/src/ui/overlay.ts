import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function focusableIn(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.getClientRects().length > 0);
}

/** Keeps Tab inside a modal container. */
export function trapTab(event: KeyboardEvent, root: HTMLElement | null): void {
  if (event.key !== 'Tab' || !root) return;
  const items = focusableIn(root);
  const first = items[0];
  const last = items[items.length - 1];
  if (!first || !last) {
    event.preventDefault();
    return;
  }
  const active = document.activeElement;
  if (event.shiftKey && (active === first || !root.contains(active))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (active === last || !root.contains(active))) {
    event.preventDefault();
    first.focus();
  }
}

/** Moves focus into the overlay when it opens and gives it back when it closes. */
export function useFocusReturn(open: boolean, root: RefObject<HTMLElement | null>) {
  const previous = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);
  if (open && !wasOpen.current) previous.current = document.activeElement as HTMLElement | null;
  wasOpen.current = open;

  useEffect(() => {
    if (!open) return;
    const container = root.current;
    if (container && !container.contains(document.activeElement)) {
      const auto = container.querySelector<HTMLElement>('[data-autofocus]');
      (auto ?? container).focus({ preventScroll: true });
    }
    return () => {
      const prev = previous.current;
      if (prev && document.contains(prev)) prev.focus({ preventScroll: true });
    };
  }, [open, root]);
}

export interface PopoverPosition {
  top: number;
  left: number;
  minWidth: number;
  maxHeight: number;
}

/** Fixed position under (or above) an anchor; follows scrolling and resizing. */
export function usePopoverPosition(
  open: boolean,
  anchor: RefObject<HTMLElement | null>,
  popover: RefObject<HTMLElement | null>,
  align: 'start' | 'end' = 'start',
): PopoverPosition | null {
  const [pos, setPos] = useState<PopoverPosition | null>(null);
  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const update = () => {
      const a = anchor.current?.getBoundingClientRect();
      if (!a) return;
      const p = popover.current;
      const height = p?.offsetHeight ?? 0;
      const width = Math.max(p?.offsetWidth ?? 0, a.width);
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const below = vh - a.bottom - 12;
      const above = a.top - 12;
      const placeAbove = height > below && above > below;
      const maxHeight = Math.max(160, placeAbove ? above : below);
      const top = placeAbove ? Math.max(8, a.top - 4 - Math.min(height, maxHeight)) : a.bottom + 4;
      let left = align === 'end' ? a.right - width : a.left;
      left = Math.min(Math.max(8, left), Math.max(8, vw - width - 8));
      setPos({ top, left, minWidth: a.width, maxHeight });
    };
    update();
    const frame = requestAnimationFrame(update);
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [open, anchor, popover, align]);
  return pos;
}

/** Calls `onOutside` on a pointer press outside all given elements. */
export function useOutsidePointer(open: boolean, refs: Array<RefObject<HTMLElement | null>>, onOutside: () => void) {
  const handler = useRef(onOutside);
  useEffect(() => {
    handler.current = onOutside;
  });
  useEffect(() => {
    if (!open) return;
    const listener = (event: PointerEvent) => {
      const target = event.target as Node;
      if (refs.some((r) => r.current?.contains(target))) return;
      handler.current();
    };
    document.addEventListener('pointerdown', listener, true);
    return () => document.removeEventListener('pointerdown', listener, true);
  }, [open, refs]);
}
