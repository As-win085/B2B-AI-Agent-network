import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../features/auth/authContext";

const PASSWORD_MIN_LENGTH = 12;

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function validate(): string | null {
    if (!email.trim()) return "Enter your email address.";
    if (password.length < PASSWORD_MIN_LENGTH)
      return `Password must be at least ${PASSWORD_MIN_LENGTH} characters.`;
    if (!organizationName.trim()) return "Enter your organization name.";
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setError(null);
    setSubmitting(true);
    try {
      await register({
        email: email.trim(),
        password,
        full_name: fullName.trim() || undefined,
        organization_name: organizationName.trim(),
      });
      navigate("/", { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create your account.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-screen">
      <section className="auth-card">
        <div className="brand">
          <span className="brand__mark">A</span>
          <div>
            <strong>asama.ai</strong>
            <small>AI agent network</small>
          </div>
        </div>

        <div>
          <p className="auth-eyebrow">Get started</p>
          <h1>Create your organization</h1>
          <p className="auth-lede">
            You become the owner of the first organization, and can invite teammates afterwards.
          </p>
        </div>

        <form className="form" onSubmit={handleSubmit} noValidate>
          <label className="field" htmlFor="register-name">
            <span>
              Full name{" "}
              <span style={{ fontWeight: 400, color: "var(--text-muted)" }}>(optional)</span>
            </span>
            <input
              id="register-name"
              name="name"
              type="text"
              autoComplete="name"
              placeholder="Aarav Kumar"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </label>

          <label className="field" htmlFor="register-email">
            <span>Email</span>
            <input
              id="register-email"
              name="email"
              type="email"
              autoComplete="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>

          <label className="field" htmlFor="register-password">
            <span>Password</span>
            <input
              id="register-password"
              name="password"
              type="password"
              autoComplete="new-password"
              placeholder="••••••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={PASSWORD_MIN_LENGTH}
            />
            <small>At least {PASSWORD_MIN_LENGTH} characters.</small>
          </label>

          <label className="field" htmlFor="register-organization">
            <span>Organization name</span>
            <input
              id="register-organization"
              name="organization"
              type="text"
              autoComplete="organization"
              placeholder="Swiggy"
              value={organizationName}
              onChange={(e) => setOrganizationName(e.target.value)}
              required
            />
          </label>

          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}

          <button className="button button--primary" type="submit" disabled={submitting}>
            {submitting ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p className="auth-footer">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </section>
    </main>
  );
}
