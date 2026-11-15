import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  configureWebhook,
  issueCredential,
  listAgents,
  listCredentials,
  registerAgent,
  revokeCredential,
  setAgentStatus,
  testWebhook,
  updateAgent,
} from "../api/agents";
import { ApiError } from "../api/client";
import { useAuth } from "../features/auth/authContext";
import type { Agent, AgentCredential, IssuedCredential } from "../types/agents";

export function AgentsPage() {
  const { organization } = useAuth();
  const canManage = organization?.role === "owner" || organization?.role === "admin";
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState<Agent | null>(null);
  const [credentials, setCredentials] = useState<AgentCredential[]>([]);
  const [issued, setIssued] = useState<IssuedCredential | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const rows = await listAgents();
      setAgents(rows);
      setSelected((current) =>
        current ? (rows.find((row) => row.id === current.id) ?? null) : null,
      );
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load agents.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function run(action: () => Promise<unknown>, message?: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      await refresh();
      if (message) setNotice(message);
      return true;
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : reason instanceof Error
            ? reason.message
            : "Request failed.",
      );
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function selectAgent(agent: Agent) {
    setSelected(agent);
    setIssued(null);
    try {
      setCredentials(await listCredentials(agent.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load credentials.");
    }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await run(async () => {
      const agent = await registerAgent({
        company_name: String(form.get("company_name")).trim(),
        industry_category: String(form.get("industry_category")).trim() || undefined,
        interest_manifesto: String(form.get("interest_manifesto")).trim() || undefined,
      });
      formElement.reset();
      setSelected(agent);
    }, "Agent registered.");
  }

  async function edit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const form = new FormData(event.currentTarget);
    await run(async () => {
      const updated = await updateAgent(selected.id, {
        company_name: String(form.get("company_name")).trim(),
        industry_category: String(form.get("industry_category")).trim() || null,
        interest_manifesto: String(form.get("interest_manifesto")).trim() || null,
      });
      setSelected(updated);
    }, "Agent profile saved.");
  }

  async function credentialsAction() {
    if (!selected) return;
    const result = await issueCredential(selected.id, {
      label: "Workspace credential",
      expires_in_days: 365,
      rotate: true,
    });
    setIssued(result);
    setCredentials(await listCredentials(selected.id));
  }

  async function webhook(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const form = new FormData(event.currentTarget);
    let signingSecret: string | undefined;
    const saved = await run(async () => {
      const result = await configureWebhook(selected.id, {
        webhook_url: String(form.get("webhook_url")).trim(),
        rotate_secret: form.get("rotate_secret") === "on",
      });
      signingSecret = result.signing_secret;
      setIssued(null);
    }, "Webhook configuration saved.");
    if (saved && signingSecret) {
      setNotice(`Webhook saved. Copy the new signing secret now: ${signingSecret}`);
    }
  }

  return (
    <div className="stack agents-page">
      <div className="page-header">
        <div className="breadcrumb">
          <span>Workspace</span>
          <span className="breadcrumb__sep">/</span>
          <span className="breadcrumb__current">Agents</span>
        </div>
        <div className="page-header__title-row">
          <div>
            <h1>AI agents</h1>
            <p className="page-header__sub">
              Register identities and manage credentials, profiles, and webhook settings for this
              organization.
            </p>
          </div>
          <span className="pill">{agents.length} agents</span>
        </div>
      </div>

      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="agent-notice" role="status">
          {notice}
        </p>
      )}

      <div className="agents-layout">
        <section className="card">
          <div className="card__header">
            <h2>Registered agents</h2>
            <button
              className="button button--secondary"
              onClick={() => void refresh()}
              type="button"
            >
              Refresh
            </button>
          </div>
          {agents.length === 0 ? (
            <p className="card__sub">No agents registered yet.</p>
          ) : (
            <ul className="agent-list">
              {agents.map((agent) => (
                <li key={agent.id}>
                  <button
                    className={`agent-list__item${selected?.id === agent.id ? " is-selected" : ""}`}
                    onClick={() => void selectAgent(agent)}
                    type="button"
                  >
                    <span>
                      <strong>{agent.company_name}</strong>
                      <small>{agent.industry_category || "No industry"}</small>
                    </span>
                    <span className={`agent-status agent-status--${agent.status}`}>
                      {agent.status}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {canManage && (
          <section className="card">
            <h2>Register an agent</h2>
            <p className="card__sub">Create a new machine identity in {organization?.name}.</p>
            <form className="form agent-form" onSubmit={(event) => void create(event)}>
              <label className="field">
                <span>Company or agent name</span>
                <input name="company_name" required maxLength={200} />
              </label>
              <label className="field">
                <span>Industry</span>
                <input name="industry_category" maxLength={100} />
              </label>
              <label className="field">
                <span>Interest manifesto</span>
                <textarea name="interest_manifesto" rows={3} maxLength={10000} />
              </label>
              <button className="button button--primary" disabled={busy} type="submit">
                Register agent
              </button>
            </form>
          </section>
        )}
      </div>

      {selected && (
        <section className="card agent-details" key={selected.id}>
          <div className="card__header">
            <div>
              <h2>{selected.company_name}</h2>
              <p className="card__sub">ID: {selected.id}</p>
            </div>
            <span className={`agent-status agent-status--${selected.status}`}>
              {selected.status}
            </span>
          </div>
          {canManage && (
            <div className="agent-actions">
              {selected.status === "active" && (
                <button
                  className="button button--secondary"
                  disabled={busy}
                  onClick={() =>
                    void run(() => setAgentStatus(selected.id, "suspend"), "Agent suspended.")
                  }
                  type="button"
                >
                  Suspend
                </button>
              )}
              {selected.status === "suspended" && (
                <button
                  className="button button--secondary"
                  disabled={busy}
                  onClick={() =>
                    void run(() => setAgentStatus(selected.id, "reactivate"), "Agent reactivated.")
                  }
                  type="button"
                >
                  Reactivate
                </button>
              )}
              {selected.status !== "deactivated" && (
                <button
                  className="button button--danger"
                  disabled={busy}
                  onClick={() =>
                    void run(
                      () => setAgentStatus(selected.id, "deactivate"),
                      "Agent deactivated and credentials revoked.",
                    )
                  }
                  type="button"
                >
                  Deactivate
                </button>
              )}
            </div>
          )}
          {canManage && (
            <div className="agents-layout agent-panels">
              <form className="form" onSubmit={(event) => void edit(event)}>
                <h3>Profile</h3>
                <label className="field">
                  <span>Name</span>
                  <input
                    name="company_name"
                    defaultValue={selected.company_name}
                    required
                    maxLength={200}
                  />
                </label>
                <label className="field">
                  <span>Industry</span>
                  <input
                    name="industry_category"
                    defaultValue={selected.industry_category ?? ""}
                    maxLength={100}
                  />
                </label>
                <label className="field">
                  <span>Interest manifesto</span>
                  <textarea
                    name="interest_manifesto"
                    defaultValue={selected.interest_manifesto ?? ""}
                    rows={4}
                    maxLength={10000}
                  />
                </label>
                <button className="button button--secondary" disabled={busy} type="submit">
                  Save profile
                </button>
              </form>
              <div className="form">
                <h3>Machine credentials</h3>
                <p className="card__sub">Credential values are only shown once.</p>
                <button
                  className="button button--primary"
                  disabled={busy || selected.status !== "active"}
                  onClick={() => void run(credentialsAction, "Credential issued.")}
                  type="button"
                >
                  Rotate credential
                </button>
                {issued && (
                  <p className="secret-value" role="alert">
                    <strong>Copy now; it cannot be shown again:</strong>
                    <br />
                    {issued.secret}
                  </p>
                )}
                <ul className="credential-list">
                  {credentials.map((credential) => (
                    <li key={credential.id}>
                      <span>
                        <strong>{credential.label || "Credential"}</strong>
                        <small>
                          {credential.credential_prefix}… ·{" "}
                          {credential.revoked_at
                            ? "revoked"
                            : credential.expires_at
                              ? `expires ${new Date(credential.expires_at).toLocaleDateString()}`
                              : "no expiry"}
                        </small>
                      </span>
                      {!credential.revoked_at && (
                        <button
                          className="text-button"
                          type="button"
                          onClick={() =>
                            void run(async () => {
                              await revokeCredential(selected.id, credential.id);
                              setCredentials(await listCredentials(selected.id));
                            }, "Credential revoked.")
                          }
                        >
                          Revoke
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
              <form className="form" onSubmit={(event) => void webhook(event)}>
                <h3>Webhook</h3>
                <label className="field">
                  <span>Webhook URL</span>
                  <input
                    name="webhook_url"
                    type="url"
                    defaultValue={selected.webhook_url ?? ""}
                    placeholder="https://example.com/webhook"
                    required
                  />
                </label>
                <label className="agent-checkbox">
                  <input type="checkbox" name="rotate_secret" /> Rotate signing secret
                </label>
                <button className="button button--secondary" disabled={busy} type="submit">
                  Save webhook
                </button>
                <button
                  className="button button--secondary"
                  disabled={busy || !selected.webhook_configured}
                  type="button"
                  onClick={() =>
                    void run(async () => {
                      const result = await testWebhook(selected.id);
                      setNotice(
                        result.valid
                          ? "URL validation passed. No delivery was sent."
                          : "Webhook validation failed.",
                      );
                    }, "Webhook URL validation passed.")
                  }
                >
                  Validate URL
                </button>
              </form>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
