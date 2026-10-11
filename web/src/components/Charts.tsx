/** Charts drawn as SVG with presentation attributes only, so the strict CSP needs no allowance. */

export interface Segment {
  label: string;
  value: number;
  /** A CSS class that sets `stroke` or `fill`, such as `seg-in-transit`. */
  className: string;
}

const RADIUS = 52;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function DonutChart({ segments, centre, caption }: { segments: Segment[]; centre: string; caption: string }) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  let offset = 0;
  return (
    <div className="donut">
      <svg viewBox="0 0 140 140" width="168" height="168" role="img" aria-label={`${caption}: ${centre}`}>
        <circle cx="70" cy="70" r={RADIUS} fill="none" strokeWidth="16" className="donut-track" />
        {total > 0 &&
          segments
            .filter((s) => s.value > 0)
            .map((s) => {
              const length = (s.value / total) * CIRCUMFERENCE;
              const circle = (
                <circle
                  key={s.label}
                  cx="70"
                  cy="70"
                  r={RADIUS}
                  fill="none"
                  strokeWidth="16"
                  className={s.className}
                  strokeDasharray={`${length} ${CIRCUMFERENCE - length}`}
                  strokeDashoffset={-offset}
                  transform="rotate(-90 70 70)"
                />
              );
              offset += length;
              return circle;
            })}
        <text x="70" y="68" textAnchor="middle" className="donut-centre">
          {centre}
        </text>
        <text x="70" y="86" textAnchor="middle" className="donut-caption">
          {caption}
        </text>
      </svg>
      <div className="legend">
        {segments.map((s) => (
          <div key={s.label} className="legend-row">
            <span className={`legend-swatch ${s.className}`} />
            <span>{s.label}</span>
            <strong>{s.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BarChart({ items, caption }: { items: { label: string; value: number }[]; caption: string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  const rowHeight = 30;
  const labelWidth = 74;
  const barMax = 220;
  return (
    <svg
      viewBox={`0 0 ${labelWidth + barMax + 44} ${Math.max(1, items.length) * rowHeight}`}
      className="bars"
      role="img"
      aria-label={caption}
    >
      {items.map((item, i) => {
        const width = Math.max(2, (item.value / max) * barMax);
        const y = i * rowHeight;
        return (
          <g key={item.label}>
            <text x="0" y={y + 19} className="bar-label">
              {item.label}
            </text>
            <rect x={labelWidth} y={y + 6} width={width} height="16" rx="5" className={`bar bar-${i % 6}`} />
            <text x={labelWidth + width + 6} y={y + 19} className="bar-value">
              {item.value}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
