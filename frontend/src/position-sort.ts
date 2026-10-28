/** Compare exact integer fen; missing values stay last in either direction. */
export type PositionSortKey = "cost_fen" | "value_fen" | "unrealized_fen";
export type PositionSort = {
  key: PositionSortKey;
  direction: "ascending" | "descending";
};

export function sortPositions<T extends Record<PositionSortKey, string | null>>(
  positions: readonly T[],
  sort: PositionSort | null,
): T[] {
  if (!sort) return [...positions];
  return [...positions].sort((left, right) => {
    const a = left[sort.key];
    const b = right[sort.key];
    if (a === null) return b === null ? 0 : 1;
    if (b === null) return -1;
    const first = BigInt(a);
    const second = BigInt(b);
    const order = first < second ? -1 : first > second ? 1 : 0;
    return sort.direction === "ascending" ? order : -order;
  });
}
