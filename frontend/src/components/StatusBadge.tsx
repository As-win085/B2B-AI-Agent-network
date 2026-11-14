import type { HealthResponse } from "../types/health";

interface StatusBadgeProps {
  status: HealthResponse["status"] | "loading" | "error";
}

const labels: Record<StatusBadgeProps["status"], string> = {
  ok: "Operational",
  degraded: "Degraded",
  loading: "Checking…",
  error: "Unreachable",
};

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-badge--${status}`} role="status">
      <span className="status-badge__dot" aria-hidden="true" />
      {labels[status]}
    </span>
  );
}
