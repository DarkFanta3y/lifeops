const DEFAULT_BOTTOM_THRESHOLD = 80;

export function isNearBottom(element, threshold = DEFAULT_BOTTOM_THRESHOLD) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold;
}
