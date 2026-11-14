import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section className="stack">
      <p className="eyebrow">404</p>
      <h1>Page not found</h1>
      <p className="lede">The screen you requested does not exist in this workspace.</p>
      <Link className="button" to="/">
        Back to overview
      </Link>
    </section>
  );
}
