export interface HealthComponent {
  name: string;
  ok: boolean;
  detail?: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  service: string;
  version: string;
  environment: string;
  timestamp: string;
  components?: HealthComponent[];
}
