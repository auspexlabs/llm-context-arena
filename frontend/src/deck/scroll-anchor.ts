/** Ephemeral scroll target for expand/collapse without jumping to top. */
let anchor: string | null = null;

export function setScrollAnchor(id: string | null) {
  anchor = id;
}

export function consumeScrollAnchor(): string | null {
  const id = anchor;
  anchor = null;
  return id;
}

function findAnchor(container: HTMLElement, id: string): HTMLElement | null {
  return container.querySelector(`[data-scroll-anchor="${CSS.escape(id)}"]`) as HTMLElement | null;
}

/** Offset of anchor from top of scroll container's visible area (before DOM swap). */
export function anchorOffsetIn(container: HTMLElement, id: string): number | null {
  const el = findAnchor(container, id);
  if (!el) return null;
  return el.getBoundingClientRect().top - container.getBoundingClientRect().top;
}

/** Restore scroll after viewport innerHTML swap — keeps anchor row at same visual position. */
export function restoreViewportScroll(
  container: HTMLElement,
  fallbackScrollTop: number,
  anchorId: string | null,
  anchorRelTop: number | null
) {
  if (anchorId != null && anchorRelTop != null) {
    const el = findAnchor(container, anchorId);
    if (el) {
      const newRelTop = el.getBoundingClientRect().top - container.getBoundingClientRect().top;
      container.scrollTop += newRelTop - anchorRelTop;
      return;
    }
  }
  container.scrollTop = fallbackScrollTop;
}

/** Buttons steal focus on click and browsers scroll them into view — block that. */
export function preventFocusScroll(el: Element) {
  el.addEventListener('mousedown', (e) => e.preventDefault());
}