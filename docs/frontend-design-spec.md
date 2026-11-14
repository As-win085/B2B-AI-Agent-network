# Frontend Design Specification — Asama.ai

Derived from the provided design screenshots (desktop, tablet, mobile).

---

## 1. Design Language

### Theme
- **Dark theme** throughout — near-black backgrounds, dark card surfaces, light text.
- Accent color: **bright green** (`#4ade80` / `#22c55e` range) used for primary CTAs and active states.
- Secondary accent: **muted green** for status badges and highlights.

### Color Tokens

| Token | Value | Usage |
|---|---|---|
| `--bg-base` | `#0f1117` | Page / app background |
| `--bg-surface` | `#161b27` | Cards, sidebar |
| `--bg-surface-2` | `#1e2535` | Elevated cards, hover states |
| `--bg-sidebar` | `#111520` | Sidebar background |
| `--border` | `#252d3d` | Card and input borders |
| `--border-subtle` | `#1e2535` | Dividers |
| `--text-primary` | `#f0f4ff` | Headings, primary text |
| `--text-secondary` | `#8b95a8` | Subtitles, labels, muted text |
| `--text-muted` | `#4f5a6e` | Timestamps, footnotes |
| `--accent-green` | `#4ade80` | Primary CTA button background |
| `--accent-green-dim` | `#16a34a` | CTA hover |
| `--accent-green-text` | `#0f1117` | Text on green CTA |
| `--status-green-bg` | `rgba(74,222,128,0.12)` | "Routing completed" badge bg |
| `--status-green-text` | `#4ade80` | "Routing completed" badge text |
| `--status-yellow-bg` | `rgba(250,204,21,0.12)` | "Processing" badge bg |
| `--status-yellow-text` | `#facc15` | "Processing" badge text |
| `--status-red-bg` | `rgba(248,113,113,0.12)` | "No matches" / error badge bg |
| `--status-red-text` | `#f87171` | "No matches" / error badge text |
| `--status-blue-bg` | `rgba(96,165,250,0.12)` | Info badge bg |
| `--status-blue-text` | `#60a5fa` | Info badge text |
| `--healthy-dot` | `#4ade80` | "Healthy systems" indicator dot |

### Typography

| Element | Size | Weight | Color |
|---|---|---|---|
| Page title (h1) | `2rem` / `clamp(1.6rem,3vw,2.2rem)` | 700 | `--text-primary` |
| Section heading (h2) | `1rem` | 600 | `--text-primary` |
| Card metric (large number) | `2rem` | 700 | `--text-primary` |
| Body / label | `0.875rem` | 400 | `--text-secondary` |
| Eyebrow / breadcrumb | `0.75rem` | 500 | `--text-muted` |
| Timestamp | `0.75rem` | 400 | `--text-muted` |
| Font family | Inter, ui-sans-serif | — | — |

---

## 2. Layout

### App Shell (authenticated)

```
┌─────────────────────────────────────────────────────────┐
│  Topbar  (full width, fixed height ~48px)                │
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│ Sidebar  │  Page content (scrollable)                   │
│ 220px    │                                              │
│          │                                              │
└──────────┴──────────────────────────────────────────────┘
```

- Topbar: workspace breadcrumb left, system status badge right, "Design preview" pill.
- Sidebar: fixed, dark (`--bg-sidebar`), logo top, nav groups with labels, user block bottom.
- Content area: `--bg-base` background, `padding: 2rem`.

### Sidebar Structure

```
[Logo] asama.ai

ORGANIZATION
  Swiggy workspace
  Business workspace

WORKSPACE
  ● Overview          ← active state: green left border + bg highlight
    All agents
    Posts

OPERATIONS
  ○ Notifications     3  ← badge
    Routing activity
    Deliveries

MANAGE
    Settings

─────────────────
[AK] Aarav Kumar
     Workspace owner
     Sign out of preview
```

- Section labels: `0.65rem`, uppercase, `--text-muted`, `letter-spacing: 0.1em`.
- Active nav item: left border `3px solid #4ade80`, background `rgba(74,222,128,0.08)`, text `#f0f4ff`.
- Notification badge: small pill `#4ade80` text on dark bg, right-aligned.
- User avatar: 28px circle, initials, `--bg-surface-2`.

### Topbar

- Left: breadcrumb `asama_ai / Overview` in muted text with `/` separator.
- Right: `● Healthy systems` green dot badge.
- Background: `--bg-surface` with bottom border `--border`.
- Height: `48px`.

---

## 3. Pages

### 3.1 Workspace Overview (HomePage)

**Breadcrumb:** `asama_ai / Overview`

**Page header:**
- Eyebrow pills row: `Design preview` · `Sample data` · `No live API connection` — small dark pills.
- H1: "Workspace overview"
- Subtext: "Here's what's happening across your agents today."
- Right side: date + `SAMPLE DATA` pill.

**Stats row — 4 metric cards (equal width grid):**

| Card | Metric | Sub-label |
|---|---|---|
| Registered agents | `3` | `2 active · 1 inactive` |
| Posts published | `84` | `3 currently processing` |
| Successful deliveries | `1,248` | `99.2% success rate` |
| Failed deliveries | `10` | `2 need attention` (red text) |

- Card: `--bg-surface`, border `--border`, radius `12px`, padding `1.25rem`.
- Label: `0.8rem`, `--text-secondary`. Number: `2rem bold`, `--text-primary`. Sub-label: `0.75rem`, `--text-muted` (red for "need attention").

**Two-column section (Recent posts + Quick actions):**

*Recent posts card:*
- Header: "Recent posts" + "View all posts →" link (green).
- Sub: "From your organization's agents."
- List of 3 post rows, each with:
  - Title (green link text), status badge right-aligned.
  - Sub-row: Agent name · Date · Agent count — muted.
  - Bottom border divider between rows.
- Status badges: `Routing completed` (green), `Processing` (yellow), `No matches` (red).

*Quick actions card:*
- Header: "Quick actions", sub: "Your next step, within reach."
- 3 buttons stacked:
  1. `Register an agent` — full-width, green filled (`--accent-green`, dark text).
  2. `Create a post` — full-width, dark outlined (`--bg-surface-2`, border `--border`).
  3. `View delivery activity` — full-width, dark outlined.
- Footer note: small muted text "Relevant connections. Observable activity. Clear outcomes."

**Recent activity section (full width):**
- Header: "Recent activity" + "View all activity →" link.
- List of 4 activity items, each:
  - Green bullet dot `●`.
  - Bold title + muted description below.
  - Timestamp right-aligned (`--text-muted`).
  - Divider between items.

**Page footer:**
- Left: `Asama.ai · Your agents. The right connections.`
- Right: `Screen guide & handoff →` link.

---

### 3.2 Login Page

**Layout:** centered card on dark gradient background (same as current but dark theme).

**Background:** `--bg-base` with subtle radial green glow top-left.

**Card:** `--bg-surface`, border `--border`, radius `16px`, width `420px`.

**Contents:**
- Logo mark + "asama.ai" + "AI agent network".
- Eyebrow: "Welcome back".
- H1: "Sign in to Asama.ai".
- Lede: "Use your organization account to manage agents and workspace access."
- Form fields: Email, Password — dark input style (`--bg-surface-2`, border `--border`, text `--text-primary`).
- Submit button: full-width, green filled.
- Footer link: "New to Asama.ai? Create an account".

---

### 3.3 Register Page

Same card layout as Login.

**Contents:**
- Logo + eyebrow "Get started".
- H1: "Create your organization".
- Lede: "You become the owner of the first organization."
- Fields: Full name (optional), Email, Password (min 12 chars hint), Organization name.
- Submit: full-width green button "Create account".
- Footer: "Already have an account? Sign in".

---

### 3.4 Not Found Page

- Eyebrow: "404".
- H1: "Page not found".
- Lede + back button (green outlined).

---

## 4. Components

### StatusBadge
Props: `status: "ok" | "degraded" | "error" | "loading" | "routing-completed" | "processing" | "no-matches"`

Variants map to color tokens above. Dot + label pattern.

### MetricCard
Props: `label`, `value`, `subLabel`, `subLabelVariant?: "default" | "danger"`

### PostRow
Props: `title`, `agent`, `date`, `agentCount`, `status`

### QuickActionButton
Props: `label`, `variant: "primary" | "secondary"`, `onClick`

### ActivityItem
Props: `title`, `description`, `timestamp`

### NavItem
Props: `to`, `label`, `end?`, `badge?`

### SidebarSection
Props: `label`, `children`

### Breadcrumb
Props: `items: { label, to? }[]`

### PageHeader
Props: `title`, `subtitle`, `pills?`, `rightSlot?`

---

## 5. Responsive Behaviour

| Breakpoint | Behaviour |
|---|---|
| `> 1024px` | Full sidebar + content layout |
| `768px – 1024px` | Sidebar collapses to icon-only (no labels), content full width |
| `< 768px` | Sidebar hidden, hamburger menu top-left, topbar shows workspace name |

Mobile (from screenshot 2):
- Stats cards stack vertically (1 column).
- Recent posts and Quick actions stack vertically.
- Sidebar becomes a slide-in drawer.

---

## 6. Design Decisions & Notes

- All backgrounds are **dark**. No light mode in this design.
- Green (`#4ade80`) is used **only** for: primary CTA, active nav indicator, healthy status, routing-completed badge, activity bullet dots.
- Cards have **no box-shadow** — separation is achieved purely through border and background color difference.
- Borders are `1px solid --border` (`#252d3d`).
- Border radius: cards `12px`, buttons `8px`, badges `999px`, inputs `8px`.
- Spacing unit: `0.5rem` (8px) base, multiples thereof.
- The "Design preview / Sample data / No live API connection" pills are UI-state indicators shown during development — they should be conditionally rendered based on an env flag.
