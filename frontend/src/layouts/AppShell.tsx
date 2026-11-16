import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "../features/auth/authContext";

const workspaceNav = [
  { to: "/", label: "Overview", end: true },
  { to: "/agents", label: "All agents" },
  { to: "/posts", label: "Posts" },
];

const operationsNav = [
  { to: "/notifications", label: "Notifications", badge: 3 },
  { to: "/routing", label: "Routing activity" },
  { to: "/deliveries", label: "Deliveries" },
];

const manageNav = [{ to: "/settings", label: "Settings" }];

function initials(name: string | null | undefined, email: string | null | undefined): string {
  if (name) {
    const parts = name.trim().split(" ");
    return parts.length >= 2
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : parts[0].slice(0, 2).toUpperCase();
  }
  return (email ?? "?")[0].toUpperCase();
}

export function AppShell() {
  const { user, organization, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  const userInitials = initials(user?.full_name, user?.email);

  return (
    <div className="app-shell">
      {/* Topbar */}
      <header className="topbar">
        <div className="topbar__left">
          <span className="topbar__workspace">{organization?.name ?? "asama_ai"}</span>
          <span className="topbar__sep">/</span>
          <span className="topbar__page">Agent network</span>
        </div>
        <div className="topbar__right">
          <span className="topbar__health">
            <span className="topbar__health-dot" />
            Healthy systems
          </span>
        </div>
      </header>

      {/* Sidebar */}
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark">A</span>
          <div>
            <strong>asama.ai</strong>
            <small>AI agent network</small>
          </div>
        </div>

        {organization && (
          <div className="sidebar__org">
            <p className="sidebar__org-name">{organization.name}</p>
            <p className="sidebar__org-role">Business workspace</p>
          </div>
        )}

        <nav className="sidebar__section" aria-label="Workspace">
          <span className="sidebar__section-label">Workspace</span>
          {workspaceNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "nav-link nav-link--active" : "nav-link")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <nav className="sidebar__section" aria-label="Operations">
          <span className="sidebar__section-label">Operations</span>
          {operationsNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? "nav-link nav-link--active" : "nav-link")}
            >
              {item.label}
              {item.badge ? <span className="nav-link__badge">{item.badge}</span> : null}
            </NavLink>
          ))}
        </nav>

        <nav className="sidebar__section" aria-label="Manage">
          <span className="sidebar__section-label">Manage</span>
          {manageNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? "nav-link nav-link--active" : "nav-link")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__footer">
          <div className="sidebar__user">
            <span className="sidebar__avatar">{userInitials}</span>
            <div className="sidebar__user-info">
              <p className="sidebar__user-name">{user?.full_name ?? user?.email}</p>
              <p className="sidebar__user-role">Workspace owner</p>
            </div>
          </div>
          <button className="sidebar__signout" type="button" onClick={handleLogout}>
            Sign out of preview
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="content">
        <main className="page">
          <Outlet />
        </main>
        <footer className="page-footer">
          <span>Asama.ai · Your agents. The right connections.</span>
          <a className="page-footer__link" href="#">
            Screen guide &amp; handoff →
          </a>
        </footer>
      </div>
    </div>
  );
}
