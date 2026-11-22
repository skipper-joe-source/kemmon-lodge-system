// Position a confirmation by its trigger while keeping every edge on screen.
export function confirmationPosition(anchor, size, viewport) {
  const margin = Math.min(16, viewport.width / 4, viewport.height / 4);
  const width = Math.min(size.width, viewport.width - 2 * margin);
  const height = Math.min(size.height, viewport.height - 2 * margin);
  const clamp = (n, min, max) => Math.max(min, Math.min(n, max));
  const visible = anchor && anchor.bottom > 0 && anchor.top < viewport.height && anchor.right > 0 && anchor.left < viewport.width;
  if (!visible) return {left:(viewport.width-width)/2, top:(viewport.height-height)/2};
  const below = anchor.bottom + 10;
  const above = anchor.top - height - 10;
  const top = below + height <= viewport.height-margin ? below : above >= margin ? above : (anchor.top + anchor.bottom - height)/2;
  return {left:clamp(anchor.left,margin,viewport.width-width-margin), top:clamp(top,margin,viewport.height-height-margin)};
}
