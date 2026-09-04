export default function Logo({ size = 30, tone = "dark" }) {
  const light = tone !== "dark";
  // On a dark chrome the tile inverts: the plate goes white and every mark on
  // it goes dark, so the rising line stays visible in both. Keeping the marks
  // white on a white plate is the classic way a logo silently disappears.
  const fg = light ? "#ffffff" : "#0f3d36";
  const accent = light ? "#2f7d6b" : "#2f7d6b";
  const mark = light ? "#0f3d36" : "#ffffff";
  return (
    <span className="inline-flex items-center gap-2.5">
      {/* Three visits, one rising line. The mark is the product's argument:
          nobody looks at the sequence, so the sequence is the logo. */}
      <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="AIRA">
        <rect width="32" height="32" rx="9" fill={fg} />
        <circle cx="9" cy="21" r="2.1" fill={accent} />
        <circle cx="16" cy="18" r="2.1" fill={accent} />
        <circle cx="23" cy="9" r="2.6" fill={mark} />
        <path
          d="M9 21 L16 18 L23 9"
          stroke={mark}
          strokeWidth="1.6"
          strokeLinecap="round"
          fill="none"
          opacity=".55"
        />
      </svg>
      <span
        className="font-extrabold tracking-tight"
        style={{ color: fg, fontSize: size * 0.62 }}
      >
        AIRA
      </span>
    </span>
  );
}
