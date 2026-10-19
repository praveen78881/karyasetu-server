# Deploying KaryaSetu to the cloud (free, on Render)

After this, the app runs 24/7 at your own address like
`https://karyasetu.onrender.com` — **your laptop can stay off**. Teammates use
it from anywhere, install it on their phones, and full offline mode works
(HTTPS enables it).

KaryaSetu runs on [Render](https://render.com)'s free tier: a free **web
service** runs the Flask app and a free **Postgres** database stores your data.
Both are created from the `render.yaml` blueprint in this repo, so the whole
setup is one step.

> This project's live instance was deployed straight from the Render connector,
> so the service and database already exist. The steps below are how to
> reproduce it from scratch (new account, fork, or re-deploy).

---

## One-click deploy (Blueprint)

1. **Push this project to GitHub** (public or private). The Flask backend lives
   at `github.com/praveen78881/karyasetu-server`.

2. **Sign up** at https://render.com (free, no card) — "Sign in with GitHub" is
   easiest so Render can read your repo.

3. In the Render dashboard: **New → Blueprint**, pick the `karyasetu-server`
   repo, and confirm. Render reads [`render.yaml`](render.yaml) and creates:
   - a **web service** `karyasetu` (Python, free plan) running
     `gunicorn wsgi:application`;
   - a free **Postgres** `karyasetu-db`, with its connection string wired into
     the service as `DATABASE_URL`;
   - a generated `SECRET_KEY` and `HTTPS=1`.

4. Wait for the first deploy (2–4 min). Open the service URL
   (`https://karyasetu.onrender.com`) — you'll see the **Set up your workspace**
   page. Create your manager account and add your team from the Team page.

That's it. Tables are created automatically on first boot (`ensure_schema()`),
so there's nothing to migrate.

## Manual setup (without the blueprint)

If you'd rather wire it by hand in the dashboard:

1. **New → PostgreSQL** → Name `karyasetu-db`, Plan **Free**, Region
   **Singapore** → *Create*. Copy its **Internal Database URL**.
2. **New → Web Service** → connect the `karyasetu-server` repo →
   - Runtime: **Python**
   - Build command: `pip install -r requirements.txt`
   - Start command:
     `gunicorn wsgi:application --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120`
   - Plan: **Free**
3. On the web service, add **Environment** variables:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | *(paste the Postgres Internal Database URL)* |
   | `SECRET_KEY` | *(any long random string — keep it private)* |
   | `HTTPS` | `1` |
   | `PYTHON_VERSION` | `3.13` |

4. **Create Web Service** and wait for the deploy.

## Give it to your team

- **Phones/laptops (recommended):** send them the URL. On Android Chrome:
  menu → *Add to Home screen*. On iPhone Safari: Share → *Add to Home Screen*.
  On desktop: the install icon in the address bar. This is a full install with
  the KaryaSetu icon **and complete offline support**.
- **The APK:** anyone using `KaryaSetu.apk` opens it, presses Back →
  *Change server address*, and enters `https://karyasetu.onrender.com`. (Once
  you know your final URL, the APK can be rebuilt with it as the built-in
  default.)

## Free-plan notes (important)

- **Spin-down:** a free web service sleeps after ~15 minutes with no traffic;
  the next visit takes ~30–50 s to wake it, then it's fast again. Upgrade to a
  paid instance (from $7/mo) to keep it always-on. The app's 30-second
  auto-refresh is unaffected once awake.
- **Free Postgres expiry:** Render's free Postgres is deleted after its trial
  window (shown on the database's page). Before it lapses, either upgrade the
  database, or point `DATABASE_URL` at another free Postgres (e.g. Supabase) —
  the app reads whatever `DATABASE_URL` you give it. **Back up first** from the
  database's dashboard (or `pg_dump "$DATABASE_URL"`).
- **WebSockets:** instant Socket.IO push is replaced by an automatic refresh
  every 30 seconds — the client detects this by itself; nothing to configure.
- **Updates:** push to the repo's default branch; Render auto-deploys
  (`autoDeploy: true`).

## Web Push notifications (optional)

OS-level Web Push needs VAPID keys in the environment. Generate a pair and add
them to the service's Environment:

| Key | Value |
|---|---|
| `VAPID_PUBLIC` | *(public key)* |
| `VAPID_PRIVATE` | *(private key)* |
| `VAPID_SUB` | `you@example.com` |

Without them, in-app notifications still work; only OS push is off. Push also
requires an HTTPS origin (Render provides one) and, on iPhone, the PWA installed
to the Home Screen first.

## Using the existing Supabase Postgres instead

This project already has a Supabase Postgres with migrated data. To run the
Render Flask app against it instead of Render's own database, set `DATABASE_URL`
to the Supabase **connection string** (Supabase dashboard → *Connect* → use the
**Session pooler** URI, which includes your DB password). The app normalises the
`postgres://` scheme and enables `pool_pre_ping`, so it works as-is.

## Alternative hosts

Any host that runs Flask works. The `Procfile` and `wsgi.py` are standard:
- A VPS: `pip install -r requirements.txt && gunicorn wsgi:application` behind
  an HTTPS reverse proxy.
- Railway / Fly.io / Heroku-likes: they read the `Procfile` directly.
