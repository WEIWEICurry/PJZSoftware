"use client";

import type { InputHTMLAttributes } from "react";
import { localDay } from "./money";

type Props = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "type" | "value" | "onChange"
> & {
  value: string;
  onValueChange: (value: string) => void;
  stepLabel: string;
  inlineArrows?: boolean;
};

/** Calendar days, independent of timezone and daylight saving transitions. */
export function DateStepper({
  value,
  onValueChange,
  stepLabel,
  inlineArrows = false,
  ...props
}: Props) {
  const shifted = (direction: number) => {
    if (!value) return localDay();
    const day = new Date(value + "T00:00:00Z");
    day.setUTCDate(day.getUTCDate() + direction);
    return day.toISOString().slice(0, 10);
  };
  const bounded = (day: string) =>
    (typeof props.min !== "string" || day >= props.min) &&
    (typeof props.max !== "string" || day <= props.max);
  function stepButton(direction: -1 | 1, symbol: string) {
    const day = shifted(direction);
    const label = `${stepLabel}${direction === -1 ? "前一天" : "后一天"}`;
    return (
      <button
        type="button"
        className="secondary"
        aria-label={label}
        title={inlineArrows ? label : undefined}
        disabled={props.disabled || !bounded(day)}
        onClick={(e) => {
          e.preventDefault();
          onValueChange(day);
        }}
      >
        {symbol}
      </button>
    );
  }
  return (
    <span
      className={
        inlineArrows ? "date-stepper date-stepper-inline" : "date-stepper"
      }
    >
      {!inlineArrows && stepButton(-1, "‹")}
      <input
        aria-label={props["aria-label"] ?? stepLabel}
        {...props}
        type="date"
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
      />
      {inlineArrows ? (
        <span className="date-stepper-arrows">
          {stepButton(1, "▴")}
          {stepButton(-1, "▾")}
        </span>
      ) : (
        stepButton(1, "›")
      )}
    </span>
  );
}
