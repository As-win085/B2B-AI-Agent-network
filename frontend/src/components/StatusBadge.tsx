type Status =
  | "ok"
  | "degraded"
  | "error"
  | "loading"
  | "routing-completed"
  | "processing"
  | "no-matches";

interface StatusBadgeProps {
  status: Status;
  label?: string;
}

const defaultLabels: Record<Status, string> = {
  ok: "Operational",
  degraded: "Degraded",
  error: "Unreachable",
  loading: "Checking…",
  "routing-completed": "Routing completed",
  processing: "Processing",
  "no-matches": "No matches",
};

export function StatusBadge({ status, label }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-badge--${status}`} role="status">
      <span className="status-badge__dot" aria-hidden="true" />
      {label ?? defaultLabels[status]}
    </span>
  );
}
