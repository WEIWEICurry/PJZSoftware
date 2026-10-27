import type { components } from "./api-schema";
import { localDay } from "./money";
import { isoWeekValue, weekMonday } from "./report-period";

export function ReportPeriodPicker({
  period,
  anchor,
  disabled,
  choose,
}: {
  period: components["schemas"]["ReportOutput"]["period"];
  anchor: string;
  disabled: boolean;
  choose: (day: string) => void;
}) {
  const today = localDay();
  if (period === "year") {
    const year = Number(today.slice(0, 4));
    return (
      <label>
        选择年份
        <select
          aria-label="选择年份"
          value={anchor.slice(0, 4)}
          disabled={disabled}
          onChange={(e) => choose(e.target.value + "-01-01")}
        >
          {Array.from({ length: year }, (_, index) => year - index).map(
            (value) => (
              <option key={value} value={String(value).padStart(4, "0")}>
                {value}年
              </option>
            ),
          )}
        </select>
      </label>
    );
  }
  if (period === "month")
    return (
      <label>
        选择月份
        <input
          aria-label="选择月份"
          type="month"
          value={anchor.slice(0, 7)}
          max={today.slice(0, 7)}
          disabled={disabled}
          onChange={(e) => {
            if (e.target.value && e.target.value <= today.slice(0, 7))
              choose(e.target.value + "-01");
          }}
        />
      </label>
    );
  if (period === "week")
    return (
      <label>
        选择周
        <input
          aria-label="选择周"
          type="week"
          value={isoWeekValue(anchor)}
          max={isoWeekValue(today)}
          disabled={disabled}
          onChange={(e) => {
            const monday = weekMonday(e.target.value);
            if (monday && monday <= today) choose(monday);
          }}
        />
      </label>
    );
  return (
    <label>
      选择日期
      <input
        aria-label="选择日期"
        type="date"
        value={anchor}
        max={today}
        disabled={disabled}
        onChange={(e) => {
          if (e.target.value && e.target.value <= today) choose(e.target.value);
        }}
      />
    </label>
  );
}
