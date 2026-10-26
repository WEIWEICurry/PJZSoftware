/** Money stays decimal text / BigInt, including display. */
export function yuanToFen(value: string): string {
  const normalized = value.trim();
  if (!/^-?\d+(\.\d{1,2})?$/.test(normalized))
    throw new Error("金额最多保留两位小数。");
  const negative = normalized.startsWith("-");
  const [whole, fraction = ""] = normalized.replace(/^-/, "").split(".");
  const result = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (result > 1000000000000n) throw new Error("金额超出支持范围。");
  return ((negative ? -1n : 1n) * result).toString();
}
export function fenToYuan(value: string): string {
  const negative = value.startsWith("-");
  const digits = value.replace(/^-/, "").padStart(3, "0");
  return (negative ? "-" : "") + digits.slice(0, -2) + "." + digits.slice(-2);
}
export function money(value: string): string {
  const [whole, fraction] = fenToYuan(value).split(".");
  return "¥" + whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "." + fraction;
}
export function localDay(): string {
  const day = new Date();
  return [
    day.getFullYear(),
    String(day.getMonth() + 1).padStart(2, "0"),
    String(day.getDate()).padStart(2, "0"),
  ].join("-");
}
