import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="not-found">
      <p className="not-found__code">404</p>
      <h1>Page not found</h1>
      <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", margin: 0 }}>
        The screen you requested does not exist in this workspace.
      </p>
      <Link className="not-found__btn" to="/">
        ← Back to overview
      </Link>
    </div>
  );
}
