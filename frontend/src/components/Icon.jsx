// Minimal inline-SVG icon set. 1.75 stroke, 24x24 grid, currentColor.
const PATHS = {
  overview: <><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>,
  activity: <path d="M3 12h4l3 8 4-16 3 8h4" />,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
  shield: <path d="M12 3l7 3v5c0 4.5-3 8-7 9-4-1-7-4.5-7-9V6l7-3z" />,
  check: <path d="M20 6 9 17l-5-5" />,
  refresh: <><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 5v6h-6" /></>,
  swap: <><path d="M7 4 3 8l4 4" /><path d="M3 8h13" /><path d="m17 20 4-4-4-4" /><path d="M21 16H8" /></>,
  stop: <><path d="M8 3h8l5 5v8l-5 5H8l-5-5V8z" /><path d="M12 8v5" /><path d="M12 16h.01" /></>,
  alert: <><path d="M12 3 2 20h20L12 3z" /><path d="M12 9v5" /><path d="M12 17h.01" /></>,
  dot: <circle cx="12" cy="12" r="3.5" />,
  chevron: <path d="m9 6 6 6-6 6" />,
  arrowLeft: <path d="M19 12H5M12 19l-7-7 7-7" />,
  spark: <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  lock: <><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
  bolt: <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z" />,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" /></>,
  device: <><rect x="6" y="3" width="12" height="18" rx="2" /><path d="M11 18h2" /></>,
  layers: <><path d="m12 3 9 5-9 5-9-5 9-5z" /><path d="m3 13 9 5 9-5" /></>,
  sparkles: <><path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6L12 4z" /><path d="M18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8L18 15z" /></>,
}

export function Icon({ name, size = 18, className, strokeWidth = 1.75, style }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
    >
      {PATHS[name] || PATHS.dot}
    </svg>
  )
}
