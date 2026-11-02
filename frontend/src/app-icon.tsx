import type { SVGProps } from "react";

const paths = {
  overview: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  accounts: "M3 6h18v14H3zM3 6V4h15v2M16 11h5v5h-5z",
  journal: "M5 3h14v18H5zM9 7h6M9 12h6M9 17h4",
  reports: "M4 20V10h4v10M10 20V4h4v16M16 20v-7h4v7M2 20h20",
  investments: "M3 20h18M5 16l5-6 4 3 6-9M15 4h5v5",
  investmentReports: "M12 3v9h9M8 4a9 9 0 1 0 12 12M16 3a8 8 0 0 1 5 5",
  data: "M4 4h16v16H4zM4 9h16M4 14h16M8 6h1M8 11h1M8 16h1",
  plan: "M6 3v18M6 4h13l-3 4 3 4H6",
  book: "M4 4h12a4 4 0 0 1 4 4v13H8a4 4 0 0 1-4-4V4zM8 4v17M11 9h5M11 13h5",
} as const;

export function AppIcon({
  name,
  ...props
}: SVGProps<SVGSVGElement> & { name: keyof typeof paths }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d={paths[name]} />
    </svg>
  );
}
