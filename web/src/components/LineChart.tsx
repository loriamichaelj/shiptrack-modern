/** A small line chart in SVG, drawn with presentation attributes only (the CSP allows no inline style). */
export interface Series {
  label: string;
  values: number[];
  className: string;
}

const W = 520;
const H = 150;
const PAD = { left: 34, right: 8, top: 10, bottom: 18 };

export function LineChart({ series, unit, caption }: { series: Series[]; unit: string; caption: string }) {
  const length = Math.max(2, ...series.map((s) => s.values.length));
  const peak = Math.max(1, ...series.flatMap((s) => s.values));
  const top = niceCeil(peak);
  const x = (i: number) => PAD.left + (i / (length - 1)) * (W - PAD.left - PAD.right);
  const y = (v: number) => H - PAD.bottom - (v / top) * (H - PAD.top - PAD.bottom);
  const points = (values: number[]) => values.map((v, i) => `${x(i + (length - values.length))},${y(v)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="linechart" role="img" aria-label={caption}>
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={PAD.left} x2={W - PAD.right} y1={y(top * f)} y2={y(top * f)} className="grid-line" />
          <text x={PAD.left - 6} y={y(top * f) + 4} textAnchor="end" className="axis">
            {Math.round(top * f)}
          </text>
        </g>
      ))}
      <text x={W - PAD.right} y={H - 4} textAnchor="end" className="axis">
        last {length} s · {unit}
      </text>
      {series.map((s) => (
        <polyline key={s.label} points={points(s.values)} fill="none" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" className={s.className} />
      ))}
    </svg>
  );
}

function niceCeil(v: number): number {
  if (v <= 5) return 5;
  const magnitude = 10 ** Math.floor(Math.log10(v));
  const n = v / magnitude;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * magnitude;
}
