export function mergeUniqueById(current, incoming, key) {
  const seen = new Set(current.map((item) => item[key]));
  return [
    ...current,
    ...incoming.filter((item) => {
      const id = item[key];
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    }),
  ];
}

export function prependUniqueById(current, incoming, key) {
  const seen = new Set();
  return [...incoming, ...current].filter((item) => {
    const id = item[key];
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

export function restorePrependScrollPosition(element, previousHeight, previousTop) {
  element.scrollTop = previousTop + (element.scrollHeight - previousHeight);
}

export function isCurrentGeneration(requestGeneration, currentGeneration) {
  return requestGeneration === currentGeneration;
}

export function canLoadMore(hasMore, loading) {
  return hasMore && !loading;
}
