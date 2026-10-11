import { Icon, type IconName } from "../icons";

export function StatCard({
  icon,
  label,
  value,
  hint,
  tone = "blue",
}: {
  icon: IconName;
  label: string;
  value: string | number;
  hint?: string;
  tone?: "blue" | "green" | "amber" | "red" | "violet" | "slate";
}) {
  return (
    <div className={`stat stat-${tone}`}>
      <span className="stat-icon">
        <Icon name={icon} size={22} />
      </span>
      <div>
        <div className="stat-value">{value}</div>
        <div className="stat-label">{label}</div>
        {hint !== undefined && <div className="stat-hint">{hint}</div>}
      </div>
    </div>
  );
}
