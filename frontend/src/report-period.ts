/** UTC calendar conversion for native ISO week pickers; no financial arithmetic. */
function utcDate(year: number, month: number, day: number): Date {
  const result = new Date(0);
  result.setUTCFullYear(year, month, day);
  result.setUTCHours(0, 0, 0, 0);
  return result;
}

export function isoWeekValue(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  const thursday = utcDate(year, month - 1, date);
  thursday.setUTCDate(
    thursday.getUTCDate() + 3 - ((thursday.getUTCDay() + 6) % 7),
  );
  const weekYear = thursday.getUTCFullYear();
  const first = utcDate(weekYear, 0, 1);
  const week = Math.ceil(
    ((thursday.getTime() - first.getTime()) / 86400000 + 1) / 7,
  );
  return `${String(weekYear).padStart(4, "0")}-W${String(week).padStart(2, "0")}`;
}

export function weekMonday(value: string): string | null {
  const match = /^(\d{4})-W(\d{2})$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const week = Number(match[2]);
  if (year < 1 || week < 1 || week > 53) return null;
  const monday = utcDate(year, 0, 4);
  monday.setUTCDate(
    monday.getUTCDate() - ((monday.getUTCDay() + 6) % 7) + (week - 1) * 7,
  );
  const day = monday.toISOString().slice(0, 10);
  return isoWeekValue(day) === value ? day : null;
}
