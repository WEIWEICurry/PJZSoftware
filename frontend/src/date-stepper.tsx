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
};

/** Calendar days, independent of timezone and daylight saving transitions. */
export function DateStepper({
  value,
  onValueChange,
  stepLabel,
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
  return (
    <span className="date-stepper">
      <button
        type="button"
        className="secondary"
        aria-label={`${stepLabel}前一天`}
        disabled={props.disabled || !bounded(shifted(-1))}
        onClick={(e) => {
          e.preventDefault();
          onValueChange(shifted(-1));
        }}
      >
        ‹
      </button>
      <input
        aria-label={props["aria-label"] ?? stepLabel}
        {...props}
        type="date"
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
      />
      <button
        type="button"
        className="secondary"
        aria-label={`${stepLabel}后一天`}
        disabled={props.disabled || !bounded(shifted(1))}
        onClick={(e) => {
          e.preventDefault();
          onValueChange(shifted(1));
        }}
      >
        ›
      </button>
    </span>
  );
}
