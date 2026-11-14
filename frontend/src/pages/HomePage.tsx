import { useEffect, useState } from "react";

import { API_BASE_URL, getHealth } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import type { HealthResponse } from "../types/health";

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; health: HealthResponse }
  | { kind: "error"; message: string };

export function HomePage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    getHealth(controller.signal)
      .then((health) => setState({ kind: "loaded", health }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof Error ? error.message : "Unknown error";
        setState({ kind: "error", message });
      });

    return () => controller.abort();
  }, []);

  return (
    <section className="stack">
      <header>
        <p className="eyebrow">Platform status</p>
        <h1>Asama.ai foundation is running</h1>
        <p className="lede">
          Sprint 1 connects the React workspace to the FastAPI service, Supabase PostgreSQL, Redis
          Streams and RabbitMQ.
        </p>
      </header>

      <div className="grid">
        <article className="card">
          <div className="card__header">
            <h2>API</h2>
            {state.kind === "loading" && <StatusBadge status="loading" />}
            {state.kind === "loaded" && <StatusBadge status={state.health.status} />}
            {state.kind === "error" && <StatusBadge status="error" />}
          </div>

          {state.kind === "loaded" && (
            <dl className="facts">
              <div>
                <dt>Service</dt>
                <dd>{state.health.service}</dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{state.health.version}</dd>
              </div>
              <div>
                <dt>Environment</dt>
                <dd>{state.health.environment}</dd>
              </div>
              <div>
                <dt>Checked</dt>
                <dd>{new Date(state.health.timestamp).toLocaleString()}</dd>
              </div>
            </dl>
          )}

          {state.kind === "error" && (
            <p className="error-text">
              Could not reach the API at <code>{API_BASE_URL}</code>. {state.message}
            </p>
          )}

          {state.kind === "loading" && <p className="muted">Contacting the API…</p>}
        </article>

        <article className="card">
          <div className="card__header">
            <h2>Integration checklist</h2>
          </div>
          <ul className="checklist">
            <li>FastAPI health endpoint</li>
            <li>Supabase PostgreSQL + pgvector</li>
            <li>Redis Streams connectivity</li>
            <li>RabbitMQ / Celery connectivity</li>
            <li>JWT auth and tenant isolation (Phase 2–3)</li>
          </ul>
        </article>
      </div>
    </section>
  );
}
