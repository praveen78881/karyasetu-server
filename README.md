# KaryaSetu — Team Task Manager & Communication PWA

**The bridge between your team and its work.**

A responsive, installable Progressive Web App for teams: a manager assigns
tasks, team members work on them, everyone communicates in task-linked
threads — and all of it keeps working offline, syncing automatically the
moment connectivity returns.

## Features

- **Roles** — Manager (create/assign/monitor) and Team Member (view/update/complete).
- **Team-wide visibility** — everyone sees the whole team's tasks and task
  discussions (with a one-tap "My tasks" filter), so the team can coordinate;
  only the assignee, creator or a manager can change a task's status, and
  direct messages stay private between their two participants.
- **Tasks** — title, description, priority (Low → Urgent), due date & time,
  status flow *Pending → In Progress → Completed*, automatic *Overdue*
  detection, full activity history.
- **Messaging** — task-linked conversation threads plus direct messages,
  timestamps, delivery/sync ticks.
- **Real-time** — Socket.IO pushes task assignments, status changes, messages
  and presence to online devices instantly.
- **Offline-first** — the service worker caches the whole app shell; data is
  mirrored in IndexedDB; every action goes into an outbox and syncs
  automatically when the connection returns (visible states: Online /
  Offline / Syncing / Synced / Pending Sync).
- **Notifications** — in-app notification centre + optional device (browser)
  notifications for assignments, replies, completions, due-soon and overdue.
- **PWA** — installable on Android, iOS, Windows and macOS from the browser.
- **Design** — clean corporate identity: deep indigo, marigold and peacock
  accents on flat warm-neutral surfaces; Poppins + Mukta + Rozha One
  typography (self-hosted, works offline). All interface copy is neutral,
  professional English suitable for international teams.

## Quick start

```bash
cd karyasetu
pip install -r requirements.txt
python fetch_fonts.py     # one-time: self-host fonts (already done if static/fonts is populated)
python gen_icons.py       # one-time: generate PWA icons (already done if static/icons is populated)
python app.py             # → http://localhost:5000
```

### First run

On first visit the app shows a **Set up your workspace** page: create your own
manager account (name, email, password). After that, add your real team
members from the **Team** page (name, email, temporary password, role); share
each person's credentials with them and they sign in at the same address.
There are no built-in or demo accounts.

## Installing it as an app

- **Desktop (Chrome/Edge):** open `http://localhost:5000`, click the
  **Install** icon in the address bar (or avatar menu → *Install app*).
- **Android (Chrome):** browser menu → *Add to Home screen / Install app*.
- **iOS (Safari):** Share → *Add to Home Screen*.

> **Note on phones:** PWA installation and offline mode require a *secure
> context*. `http://localhost` qualifies, but a LAN IP like
> `http://192.168.x.x:5000` does not. To install on a phone, expose the app
> over HTTPS — easiest is a tunnel, e.g. `cloudflared tunnel --url
> http://localhost:5000` or `ngrok http 5000` — or deploy it behind any
> HTTPS reverse proxy.

## Trying offline mode

1. Sign in and browse around once (this fills the cache and IndexedDB).
2. In DevTools → Network, switch to **Offline** (or turn off Wi-Fi).
3. Keep using the app: read tasks/messages, change statuses, mark tasks
   completed, send messages — everything is saved locally and marked
   **Pending sync**.
4. Go back online: the outbox syncs automatically, the pill shows
   **Syncing… → Synced**, and the other party receives the updates.

Two fully offline devices cannot exchange messages directly — actions are
stored locally and relayed through the server as soon as either device
reconnects (this is by design; see the sync model below).

## Sync model

Every user action (create task, change status, send message, mark
notifications read) goes through one path: it is written to an **outbox** in
IndexedDB with a client-generated UUID, applied optimistically to the UI,
then posted to `/api/sync`. The server applies each action **idempotently**
(a ledger of processed UUIDs makes retries safe), generates notifications,
nudges affected online clients over Socket.IO, and returns a fresh snapshot
that replaces the local mirror. Online or offline is the same code path —
offline just means the post waits for connectivity.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///karyasetu.db` | Set to `mysql+pymysql://user:pass@host/db` for MySQL (install `pymysql`) |
| `SECRET_KEY` | dev value | **Set a real secret in production** |
| `PORT` | `5000` | HTTP port |
| `FLASK_DEBUG` | off | `1` enables debug mode |

## Security notes

- Passwords hashed (Werkzeug PBKDF2), session cookies HttpOnly + SameSite=Lax.
- Role-based authorization on every endpoint; members can only see and act on
  their own tasks and conversations.
- JSON POSTs require a custom `X-KS` header (CSRF mitigation).
- Server-side validation of all sync actions.
- For production: serve over HTTPS, set `SECRET_KEY`, and use a production
  WSGI server (e.g. `gunicorn -k eventlet` or waitress) behind a reverse proxy.

## Project layout

```
app.py            Flask app, REST + sync API, Socket.IO
models.py         SQLAlchemy models (SQLite/MySQL)
gen_icons.py      PWA icon generator (Pillow)
fetch_fonts.py    Self-host Google Fonts for offline use
templates/        index.html (app shell) · login.html · setup.html
static/css/       app.css (design system) · fonts.css
static/js/        app.js (SPA) · db.js (IndexedDB) · vendor/socket.io
static/sw.js      Service worker (offline shell)
static/manifest.webmanifest
```
