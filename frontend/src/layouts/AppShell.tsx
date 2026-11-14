import { NavLink, Outlet } from "react-router-dom";

const navItems = [
  { to: "/", label: "Overview", end: true },
  { to: "/posts", label: "Posts" },
  { to: "/agent", label: "Agent" },
  { to: "/admin", label: "Admin" },
];

export function AppShell() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark">A</span>
          <div>
            <strong>Asama.ai</strong>
            <small>AI agent network</small>
          </div>
        </div>

        <nav aria-label="Primary">
          {navItems.map((item) => (
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

        <p className="sidebar__note">Sprint 1 foundation</p>
      </aside>

      <div className="content">
        <header className="topbar">
          <span>Company workspace</span>
          <span className="topbar__env">local</span>
        </header>
        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
