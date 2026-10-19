import { stackLabel } from "../format";
import { useStack } from "../stack";

const CLOUD_NAMES: Record<string, string> = { aws: "AWS", gcp: "GCP", azure: "Azure" };

/**
 * Shows which stack served this page, then the latest API response, so traffic can be watched. On
 * modern it adds the cloud and region that served the page.
 */
export function StackBadge() {
  const { stack, cloud, region } = useStack();
  const where = cloud === null ? null : [CLOUD_NAMES[cloud] ?? cloud, region].filter(Boolean).join(" ");
  return (
    <span className="stack-badge" data-stack={stack ?? "unknown"} data-cloud={cloud ?? undefined}>
      Served by: {stack === null ? "—" : stackLabel(stack)}
      {where !== null && ` · ${where}`}
    </span>
  );
}
