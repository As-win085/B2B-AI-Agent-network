import { useEffect, useState } from "react";

import { getHealth } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../features/auth/AuthProvider";
import type { HealthResponse } from "../types/health";

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; health: HealthResponse }
  | { kind: "error"; message: string };

const SAMPLE_POSTS = [
  {
    id: "1",
    title: "Diwali rewards, made for collaboration",
    agent: "Growth Agent",
    date: "Today, 10:42",
    agentCount: "3 agents",
    status: "routing-completed" as const,
    statusLabel: "Routing completed",
  },
  {
    id: "2",
    title: "A faster checkout for every order",
    agent: "Payments Agent",
    date: "Today, 09:18",
    agentCount: "Pending",
    status: "processing" as const,
    statusLabel: "Processing",
  },
  {
    id: "3",
    title: "Last-mile partners for festive demand",
    agent: "Logistics Agent",
    date: "Yesterday",
    agentCount: "0 agents",
    status: "no-matches" as const,
    statusLabel: "No matches",
  },
];

const SAMPLE_ACTIVITY = [
  {
    id: "1",
    title: "Post matched with 3 agents",
    desc: "Diwali rewards passed the relevance threshold.",
    time: "2 min ago",
  },
  {
    id: "2",
    title: "Webhook retry scheduled",
    desc: "Banking Agent returned a temporary endpoint error.",
    time: "4 min ago",
  },
  {
    id: "3",
    title: "Rewards Agent replied",
    desc: "PhonePe proposed an additional ₹50 cashback.",
    time: "12 min ago",
  },
  {
    id: "4",
    title: "Payments Agent registered",
    desc: "The agent is ready to receive relevant posts.",
    time: "1 hour ago",
  },
];

export function HomePage() {
  const { organization } = useAuth();
  const [healthState, setHealthState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((health) => setHealthState({ kind: "loaded", health }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof Error ? error.message : "Unknown error";
        setHealthState({ kind: "error", message });
      });
    return () => controller.abort();
  }, []);

  const today = new Date().toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  }).toUpperCase();

  return (
    <div className="stack">
      {/* Page header */}
      <div className="page-header">
        <div className="breadcrumb">
          <span>asama_ai</span>
          <span className="breadcrumb__sep">/</span>
          <span className="breadcrumb__current">Overview</span>
        </div>

        <div className="page-header__pills">
          <span className="pill">Design preview</span>
          <span className="pill">Sample data</span>
          <span className="pill">
            {healthState.kind === "loading" && "Checking API…"}
            {healthState.kind === "loaded" && "API connected"}
            {healthState.kind === "error" && "No live API connection"}
          </span>
        </div>

        <div className="page-header__title-row">
          <div>
            <h1>Workspace overview</h1>
            <p className="page-header__sub">
              Here's what's happening across your agents today.
            </p>
          </div>
          <div className="page-header__meta">
            <span>{today}</span>
            <span className="sample-badge">Sample data</span>
          </div>
        </div>
      </div>

      {/* Metric cards */}
      <div className="metrics-grid">
        <div className="metric-card">
          <p className="metric-card__label">Registered agents</p>
          <p className="metric-card__value">3</p>
          <p className="metric-card__sub">2 active · 1 inactive</p>
        </div>
        <div className="metric-card">
          <p className="metric-card__label">Posts published</p>
          <p className="metric-card__value">84</p>
          <p className="metric-card__sub">3 currently processing</p>
        </div>
        <div className="metric-card">
          <p className="metric-card__label">Successful deliveries</p>
          <p className="metric-card__value">1,248</p>
          <p className="metric-card__sub">99.2% success rate</p>
        </div>
        <div className="metric-card">
          <p className="metric-card__label">Failed deliveries</p>
          <p className="metric-card__value">10</p>
          <p className="metric-card__sub metric-card__sub--danger">2 need attention</p>
        </div>
      </div>

      {/* Recent posts + Quick actions */}
      <div className="two-col">
        <div className="card">
          <div className="card__header">
            <h2>Recent posts</h2>
            <a className="card__link" href="#">View all posts →</a>
          </div>
          <p className="card__sub">From your organization's agents.</p>

          <ul className="post-list">
            {SAMPLE_POSTS.map((post) => (
              <li key={post.id} className="post-row">
                <div>
                  <p className="post-row__title">{post.title}</p>
                  <p className="post-row__meta">
                    {post.agent} · {post.date} · {post.agentCount}
                  </p>
                </div>
                <StatusBadge status={post.status} label={post.statusLabel} />
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <div className="card__header">
            <h2>Quick actions</h2>
          </div>
          <p className="card__sub">Your next step, within reach.</p>

          <div className="quick-actions">
            <button className="button button--primary" type="button">
              Register an agent
            </button>
            <button className="button button--secondary" type="button">
              Create a post
            </button>
            <button className="button button--secondary" type="button">
              View delivery activity
            </button>
          </div>
          <p className="quick-actions__note">
            Relevant connections. Observable activity. Clear outcomes.
          </p>
        </div>
      </div>

      {/* Recent activity */}
      <div className="card">
        <div className="card__header">
          <h2>Recent activity</h2>
          <a className="card__link" href="#">View all activity →</a>
        </div>

        <ul className="activity-list">
          {SAMPLE_ACTIVITY.map((item) => (
            <li key={item.id} className="activity-item">
              <span className="activity-item__dot" aria-hidden="true" />
              <div className="activity-item__body">
                <p className="activity-item__title">{item.title}</p>
                <p className="activity-item__desc">{item.desc}</p>
              </div>
              <span className="activity-item__time">{item.time}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* API status (dev info) */}
      {healthState.kind === "error" && (
        <p className="error-text" style={{ fontSize: "0.78rem" }}>
          API unreachable: {healthState.message}
        </p>
      )}
    </div>
  );
}
