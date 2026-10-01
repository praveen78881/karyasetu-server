"""KaryaSetu — Team Task Manager & Communication PWA.

Run:  python app.py   →  http://localhost:5000
"""
import base64
import json
import os
import secrets
from datetime import timedelta
from functools import wraps

from flask import (Flask, g, jsonify, redirect, render_template, request,
                   send_from_directory, session)
try:
    # Real-time push. On hosts without flask-socketio the app still works:
    # clients detect the missing socket and poll for updates instead.
    from flask_socketio import SocketIO, join_room
except ImportError:
    SocketIO = None
try:
    # Web Push (VAPID). Optional: without it the app runs and clients still get
    # in-app + realtime notifications, just no OS-level push.
    from pywebpush import WebPushException, webpush
except ImportError:
    webpush = None
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from sqlalchemy import or_, text

from models import (PRIORITIES, ROLES, STATUSES, Company, Message, Notification,
                    ProcessedAction, PushSubscription, Setting, StatusHistory,
                    Task, User, db, utcnow)

app = Flask(__name__)
os.makedirs(app.instance_path, exist_ok=True)


def _load_or_create_secret():
    """Persist a strong random session key so cookies can't be forged with a
    known default. SECRET_KEY in the environment always wins (rotate there)."""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    path = os.path.join(app.instance_path, "secret_key")
    if os.path.exists(path):
        with open(path) as fh:
            saved = fh.read().strip()
        if saved:
            return saved
    key = secrets.token_hex(32)
    with open(path, "w") as fh:
        fh.write(key)
    return key


app.config["SECRET_KEY"] = _load_or_create_secret()
_db_url = os.environ.get("DATABASE_URL", "sqlite:///karyasetu.db")
# SQLAlchemy dropped the bare "postgres://" scheme; Supabase/Heroku still hand it
# out, so normalise to the "postgresql://" form their drivers expect.
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
# Managed Postgres (Supabase) and its pooler close idle connections; pre-ping
# checks a connection is alive before use and recycles it instead of erroring.
if not _db_url.startswith("sqlite"):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Set HTTPS=1 in the hosting environment so session cookies are HTTPS-only.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("HTTPS") == "1"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=14)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # cap request bodies at 2 MB

# Trust one hop of X-Forwarded-* so HTTPS is detected behind the tunnel/proxy.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

db.init_app(app)
socketio = SocketIO(app, async_mode="threading") if SocketIO else None

# In-memory presence registry: user_id -> set of socket sids.
ONLINE = {}

DUE_SOON_WINDOW = timedelta(hours=24)

# Login throttling (company-standard brute-force protection):
# 5 failed attempts per email in 15 minutes → temporarily locked.
FAILED_LOGINS = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_WINDOW = timedelta(minutes=15)

# Join-code guessing protection: 10 wrong codes per IP per 15 minutes.
JOIN_ATTEMPTS = {}
JOIN_MAX_ATTEMPTS = 10

# Company-creation throttle: 5 new companies per IP per 15 minutes (open sign-up).
SETUP_ATTEMPTS = {}
SETUP_MAX_ATTEMPTS = 5

# Unambiguous alphabet for team codes (no O/0, I/1 confusion).
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# ---------------------------------------------------------------- web push (VAPID)

VAPID_SUB = "mailto:" + os.environ.get("VAPID_SUB", "admin@karyasetu.app")


def _load_or_create_vapid():
    """Load (or generate + persist) the VAPID EC P-256 keypair used to sign web
    push messages. Returns (private_pem_path, public_key_b64url) or (None, None)
    if the crypto/pywebpush stack is unavailable."""
    if webpush is None:
        return None, None
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError:
        return None, None
    priv_path = os.path.join(app.instance_path, "vapid_private.pem")
    if os.path.exists(priv_path):
        with open(priv_path, "rb") as fh:
            priv = serialization.load_pem_private_key(fh.read(), password=None)
    else:
        priv = ec.generate_private_key(ec.SECP256R1())
        with open(priv_path, "wb") as fh:
            fh.write(priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
    raw_pub = priv.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)
    pub_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode("ascii")
    return priv_path, pub_b64


VAPID_PRIVATE_PATH, VAPID_PUBLIC_KEY = _load_or_create_vapid()
PUSH_ENABLED = bool(webpush and VAPID_PRIVATE_PATH and VAPID_PUBLIC_KEY)


def queue_push(user_id, title, body, url="/"):
    """Record a push to be delivered after the request commits (see after_request)."""
    if not PUSH_ENABLED:
        return
    pending = getattr(g, "_pushes", None)
    if pending is None:
        pending = g._pushes = []
    pending.append({"user_id": user_id, "title": title, "body": body, "url": url})


PUSH_TITLES = {
    "task_assigned": "New task assigned",
    "status_changed": "Task updated",
    "task_completed": "Task completed",
    "message": "New message",
    "due_soon": "Task due soon",
    "overdue": "Task overdue",
    "team": "Team update",
}


def deliver_pushes(pushes):
    """Send queued pushes; prune subscriptions the push service has retired."""
    if not (PUSH_ENABLED and pushes):
        return
    stale = []
    for p in pushes:
        subs = PushSubscription.query.filter_by(user_id=p["user_id"]).all()
        payload = json.dumps({"title": p["title"], "body": p["body"], "url": p["url"]})
        for s in subs:
            try:
                webpush(
                    {"endpoint": s.endpoint,
                     "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_PATH,
                    vapid_claims={"sub": VAPID_SUB},
                    timeout=10,
                )
            except WebPushException as exc:
                code = getattr(getattr(exc, "response", None), "status_code", None)
                if code in (404, 410):
                    stale.append(s.id)
            except Exception:
                pass  # never let a push failure break the request
    if stale:
        PushSubscription.query.filter(PushSubscription.id.in_(stale)).delete(
            synchronize_session=False)
        db.session.commit()


def new_join_code():
    # Retried until unique across all companies (collisions are astronomically
    # unlikely, but the code is a tenant selector so it must be unique).
    while True:
        code = "WH-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
        if not Company.query.filter_by(join_code=code).first():
            return code


def company_code(user):
    """The self-registration code for this user's company."""
    return user.company.join_code if user and user.company else ""


# ---------------------------------------------------------------- helpers

def current_user():
    uid = session.get("uid")
    return db.session.get(User, uid) if uid else None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "auth_required"}), 401
        # An account awaiting (or denied) manager approval has no access, even
        # if it somehow holds a session. NULL = legacy/approved.
        if user.approved is False:
            session.clear()
            return jsonify({"error": "pending_approval"}), 403
        return fn(user, *args, **kwargs)
    return wrapper


def manager_required(fn):
    @wraps(fn)
    def wrapper(user, *args, **kwargs):
        if user.role != "manager":
            return jsonify({"error": "forbidden"}), 403
        return fn(user, *args, **kwargs)
    return wrapper


def api_post_guard():
    # Cheap CSRF mitigation: same-site fetch() sets this header; cross-site
    # form posts cannot.
    if request.headers.get("X-KS") != "1":
        return jsonify({"error": "bad_request"}), 400
    return None


# ---------------------------------------------------------------- security / request hooks

@app.before_request
def _assign_csp_nonce():
    # Fresh per-request nonce so inline template scripts run under a strict CSP.
    g.csp_nonce = secrets.token_urlsafe(16)


@app.context_processor
def _inject_nonce():
    return {"csp_nonce": getattr(g, "csp_nonce", "")}


@app.after_request
def _security_and_push(resp):
    nonce = getattr(g, "csp_nonce", "")
    resp.headers.setdefault("Content-Security-Policy",
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "connect-src 'self' ws: wss:; "
        "manifest-src 'self'; "
        "worker-src 'self'")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy",
                            "geolocation=(), microphone=(), camera=()")
    if request.is_secure:
        resp.headers.setdefault("Strict-Transport-Security",
                                "max-age=31536000; includeSubDomains")
    # Deliver any pushes queued during the request, now that it has committed.
    pushes = getattr(g, "_pushes", None)
    if pushes:
        try:
            deliver_pushes(pushes)
        except Exception:
            pass
    return resp


def iso(dt):
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def task_dict(t, now):
    overdue = t.status != "completed" and t.due_at is not None and t.due_at < now
    due_soon = (t.status != "completed" and t.due_at is not None
                and now <= t.due_at <= now + DUE_SOON_WINDOW)
    return {
        "id": t.id,
        "client_id": t.client_id,
        "title": t.title,
        "description": t.description or "",
        "priority": t.priority,
        "status": t.status,
        "overdue": overdue,
        "due_soon": due_soon,
        "created_by": t.created_by,
        "assigned_to": t.assigned_to,
        "due_at": iso(t.due_at),
        "created_at": iso(t.created_at),
        "updated_at": iso(t.updated_at),
        "completed_at": iso(t.completed_at),
        "history": [{
            "user_id": h.user_id,
            "from": h.from_status,
            "to": h.to_status,
            "note": h.note or "",
            "at": iso(h.created_at),
        } for h in t.history],
    }


def message_dict(m):
    return {
        "id": m.id,
        "client_id": m.client_id,
        "task_id": m.task_id,
        "sender_id": m.sender_id,
        "recipient_id": m.recipient_id,
        "body": m.body,
        "created_at": iso(m.created_at),
    }


def notification_dict(n):
    return {
        "id": n.id,
        "kind": n.kind,
        "text": n.text,
        "task_id": n.task_id,
        "read": n.read,
        "created_at": iso(n.created_at),
    }


def notify(user_id, kind, text, task_id=None):
    db.session.add(Notification(user_id=user_id, kind=kind, text=text, task_id=task_id))
    # Mirror every in-app notification to the user's devices via web push.
    url = f"/#/tasks/{task_id}" if task_id else "/#/notifications"
    queue_push(user_id, PUSH_TITLES.get(kind, "KaryaSetu"), text, url)


def visible_tasks(user):
    # Whole-team visibility *within the company*: everyone in the company sees
    # every company task so the team can coordinate. Editing rights stay with
    # the assignee/creator/manager.
    return (Task.query.filter_by(company_id=user.company_id)
            .order_by(Task.created_at.desc()).all())


def visible_messages(user):
    # Everything is company-scoped, and beyond that both kinds of message are
    # private to the people involved (WhatsApp-style):
    #   - a task thread is visible only to that task's creator or assignee;
    #   - a direct message is visible only to its sender or recipient.
    involved_tasks = (db.session.query(Task.id).filter(
        Task.company_id == user.company_id,
        or_(Task.created_by == user.id, Task.assigned_to == user.id)))
    return (Message.query.filter(
        Message.company_id == user.company_id,
        or_(
            Message.task_id.in_(involved_tasks),
            Message.sender_id == user.id,
            Message.recipient_id == user.id,
        )
    ).order_by(Message.created_at.asc()).all())


def generate_due_notifications(user, now):
    """Create one-time due-soon / overdue notifications for this user's tasks."""
    tasks = (Task.query.filter(Task.company_id == user.company_id,
                               Task.assigned_to == user.id, Task.status != "completed",
                               Task.due_at.isnot(None)).all())
    if user.role == "manager":
        tasks += (Task.query.filter(Task.company_id == user.company_id,
                                    Task.created_by == user.id, Task.status != "completed",
                                    Task.due_at.isnot(None),
                                    Task.assigned_to != user.id).all())
    changed = False
    for t in tasks:
        kind = None
        if t.due_at < now:
            kind, text = "overdue", f'Task overdue: "{t.title}"'
        elif t.due_at <= now + DUE_SOON_WINDOW:
            kind, text = "due_soon", f'Due soon: "{t.title}"'
        if not kind:
            continue
        exists = Notification.query.filter_by(user_id=user.id, kind=kind, task_id=t.id).first()
        if not exists:
            notify(user.id, kind, text, t.id)
            changed = True
    if changed:
        db.session.commit()


def snapshot(user):
    now = utcnow()
    generate_due_notifications(user, now)
    online_ids = {uid for uid, sids in ONLINE.items() if sids}
    extra = {"company_name": user.company.name if user.company else ""}
    if user.role == "manager":
        extra["team_code"] = company_code(user)
        # Employees awaiting this manager's approval.
        extra["pending_members"] = [
            u.pending_dict() for u in
            User.query.filter(User.company_id == user.company_id,
                              User.approved.is_(False))
            .order_by(User.created_at.asc()).all()]
    return {
        **extra,
        "server_time": iso(now),
        "me": user.to_dict(online_ids),
        # Team roster shows approved members only; pending requests are surfaced
        # to managers separately (pending_members above).
        "users": [u.to_dict(online_ids) for u in
                  User.query.filter(User.company_id == user.company_id,
                                    User.approved.isnot(False))
                  .order_by(User.name).all()],
        "tasks": [task_dict(t, now) for t in visible_tasks(user)],
        "messages": [message_dict(m) for m in visible_messages(user)],
        "notifications": [notification_dict(n) for n in
                          Notification.query.filter_by(user_id=user.id)
                          .order_by(Notification.created_at.desc()).limit(200).all()],
    }


def ping_users(user_ids, reason):
    """Nudge connected clients to pull a fresh snapshot."""
    if not socketio:
        return  # no realtime layer — clients poll every 30s instead
    for uid in set(user_ids):
        socketio.emit("refresh", {"reason": reason}, room=f"user:{uid}")


# ---------------------------------------------------------------- sync engine

def resolve_task(user, ref):
    """A task reference is a server id (int) or 'local-<client_id>' for tasks
    created offline on the same device."""
    if ref is None:
        return None
    if isinstance(ref, str) and ref.startswith("local-"):
        t = Task.query.filter_by(client_id=ref[len("local-"):]).first()
    else:
        try:
            t = db.session.get(Task, int(ref))
        except (TypeError, ValueError):
            return None
    # Never resolve a task belonging to another company.
    if t and t.company_id != user.company_id:
        return None
    return t


def apply_action(user, action):
    """Apply one outbox action. Returns (status, detail). Idempotent via
    ProcessedAction ledger."""
    cid = action.get("client_id")
    typ = action.get("type")
    payload = action.get("payload") or {}
    if not cid or not typ:
        return "rejected", "malformed"
    if ProcessedAction.query.filter_by(client_id=cid).first():
        return "duplicate", None

    touched = set()

    if typ == "create_task":
        if user.role != "manager":
            return "rejected", "forbidden"
        assignee = db.session.get(User, payload.get("assigned_to"))
        title = (payload.get("title") or "").strip()
        if not assignee or assignee.company_id != user.company_id or not title:
            return "rejected", "invalid"
        priority = payload.get("priority") if payload.get("priority") in PRIORITIES else "medium"
        due_at = None
        if payload.get("due_at"):
            try:
                from datetime import datetime
                due_at = datetime.fromisoformat(payload["due_at"].replace("Z", ""))
            except ValueError:
                due_at = None
        t = Task(client_id=cid, company_id=user.company_id, title=title[:250],
                 description=(payload.get("description") or "")[:5000],
                 priority=priority, status="pending", created_by=user.id,
                 assigned_to=assignee.id, due_at=due_at)
        db.session.add(t)
        db.session.flush()
        db.session.add(StatusHistory(task_id=t.id, user_id=user.id,
                                     from_status=None, to_status="pending",
                                     note="Task created"))
        if assignee.id != user.id:
            notify(assignee.id, "task_assigned",
                   f'New task assigned by {user.name}: "{t.title}"', t.id)
        touched.update([assignee.id, user.id])

    elif typ == "update_status":
        t = resolve_task(user, payload.get("task_id"))
        new_status = payload.get("status")
        if not t or new_status not in STATUSES:
            return "rejected", "invalid"
        if user.id not in (t.assigned_to, t.created_by) and user.role != "manager":
            return "rejected", "forbidden"
        if t.status != new_status:
            old = t.status
            t.status = new_status
            t.completed_at = utcnow() if new_status == "completed" else None
            db.session.add(StatusHistory(task_id=t.id, user_id=user.id,
                                         from_status=old, to_status=new_status,
                                         note=(payload.get("note") or "")[:300]))
            other = t.created_by if user.id == t.assigned_to else t.assigned_to
            if other != user.id:
                if new_status == "completed":
                    notify(other, "task_completed",
                           f'{user.name} completed "{t.title}"', t.id)
                else:
                    label = "In Progress" if new_status == "in_progress" else new_status.title()
                    notify(other, "status_changed",
                           f'{user.name} moved "{t.title}" to {label}', t.id)
            touched.update([t.assigned_to, t.created_by])

    elif typ == "send_message":
        body = (payload.get("body") or "").strip()
        if not body:
            return "rejected", "invalid"
        task = resolve_task(user, payload.get("task_id")) if payload.get("task_id") else None
        recipient_id = payload.get("recipient_id")
        if task:
            # A task thread is private to the task's creator and assignee.
            if user.id not in (task.created_by, task.assigned_to):
                return "rejected", "forbidden"
            m = Message(client_id=cid, company_id=user.company_id, task_id=task.id,
                        sender_id=user.id, body=body[:5000])
            for other in {task.assigned_to, task.created_by} - {user.id}:
                notify(other, "message",
                       f'{user.name} on "{task.title}": {body[:80]}', task.id)
            touched.update([task.assigned_to, task.created_by, user.id])
        elif recipient_id:
            recipient = db.session.get(User, recipient_id)
            if not recipient or recipient.company_id != user.company_id:
                return "rejected", "invalid"
            m = Message(client_id=cid, company_id=user.company_id, sender_id=user.id,
                        recipient_id=recipient.id, body=body[:5000])
            notify(recipient.id, "message", f"{user.name}: {body[:80]}")
            touched.update([recipient.id, user.id])
        else:
            return "rejected", "invalid"
        db.session.add(m)

    elif typ == "mark_read":
        q = Notification.query.filter_by(user_id=user.id, read=False)
        ids = payload.get("notification_ids")
        if ids:
            q = q.filter(Notification.id.in_(ids))
        for n in q.all():
            n.read = True
        touched.add(user.id)

    else:
        return "rejected", "unknown_type"

    db.session.add(ProcessedAction(client_id=cid, user_id=user.id, action_type=typ))
    return "applied", touched


# ---------------------------------------------------------------- pages

@app.route("/")
def index():
    if not current_user():
        return redirect("/login")
    return render_template("index.html")


@app.route("/login")
def login_page():
    if current_user():
        return redirect("/")
    return render_template("login.html")


@app.route("/setup")
def setup_page():
    # Open sign-up: anyone may create a new company and become its manager.
    if current_user():
        return redirect("/")
    return render_template("setup.html")


@app.route("/shell")
def shell():
    # App shell for the service-worker cache: always the SPA skeleton,
    # never a redirect, and contains no data (the SPA enforces auth).
    return render_template("index.html")


@app.route("/login-shell")
def login_shell():
    return render_template("login.html")


@app.route("/sw.js")
def service_worker():
    # Served from root scope so the SW can control "/".
    return send_from_directory(os.path.join(app.root_path, "static"), "sw.js",
                               mimetype="application/javascript")


@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(os.path.join(app.root_path, "static"),
                               "manifest.webmanifest",
                               mimetype="application/manifest+json")


# ---------------------------------------------------------------- auth api

@app.route("/api/setup", methods=["POST"])
def api_setup():
    """Open sign-up: create a new company plus its first manager account."""
    guard = api_post_guard()
    if guard:
        return guard
    ip = request.remote_addr or "?"
    now = utcnow()
    recent = [t for t in SETUP_ATTEMPTS.get(ip, []) if now - t < LOGIN_LOCKOUT_WINDOW]
    SETUP_ATTEMPTS[ip] = recent
    if len(recent) >= SETUP_MAX_ATTEMPTS:
        return jsonify({"error": "too_many_attempts",
                        "detail": "Too many new companies from this network. "
                                  "Please try again later."}), 429
    SETUP_ATTEMPTS[ip].append(now)
    data = request.get_json(silent=True) or {}
    company_name = (data.get("company") or "").strip()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not company_name or not name or "@" not in email or len(password) < 6:
        return jsonify({"error": "invalid", "detail":
                        "Company name, your name, a valid email and a 6+ character "
                        "password are required."}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "exists", "detail":
                        "That email is already registered — try signing in."}), 409
    company = Company(name=company_name[:160], join_code=new_join_code())
    db.session.add(company)
    db.session.flush()
    admin = User(company_id=company.id, name=name[:120], email=email,
                 password_hash=generate_password_hash(password),
                 role="manager", title=(data.get("title") or "")[:120])
    db.session.add(admin)
    db.session.commit()
    session.permanent = True
    session["uid"] = admin.id
    return jsonify({"ok": True, "user": admin.to_dict(),
                    "company": company.name, "team_code": company.join_code})


@app.route("/api/join", methods=["POST"])
def api_join():
    """Self-registration with a company's join code: creates a member account
    in whichever company owns that code."""
    guard = api_post_guard()
    if guard:
        return guard

    ip = request.remote_addr or "?"
    now = utcnow()
    attempts = [t for t in JOIN_ATTEMPTS.get(ip, []) if now - t < LOGIN_LOCKOUT_WINDOW]
    JOIN_ATTEMPTS[ip] = attempts
    if len(attempts) >= JOIN_MAX_ATTEMPTS:
        return jsonify({"error": "too_many_attempts"}), 429

    data = request.get_json(silent=True) or {}
    typed = "".join((data.get("code") or "").upper().split()).replace("-", "")
    company = None
    if typed:
        # Match against every company's code (normalized the same way).
        for c in Company.query.all():
            if c.join_code.upper().replace("-", "") == typed:
                company = c
                break
    if not company:
        JOIN_ATTEMPTS[ip].append(now)
        return jsonify({"error": "bad_code"}), 403

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not name or "@" not in email or len(password) < 6:
        return jsonify({"error": "invalid", "detail":
                        "Name, valid email and a 6+ character password are required."}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "exists", "detail":
                        "That email is already registered — try signing in."}), 409

    # The role picked on the form is only a REQUEST — never granted here. The
    # account is created as an unprivileged "member", pending, and not logged in.
    requested = data.get("role") if data.get("role") in ROLES else "member"
    member = User(company_id=company.id, name=name[:120], email=email,
                  password_hash=generate_password_hash(password),
                  role="member", title=(data.get("title") or "")[:120],
                  approved=False, requested_role=requested)
    db.session.add(member)
    db.session.flush()
    want = "manager access" if requested == "manager" else "employee access"
    for mgr in User.query.filter_by(company_id=company.id, role="manager").all():
        notify(mgr.id, "team",
               f"{member.name} requested to join ({want}) — approve on the Team page")
    db.session.commit()
    # Nudge managers so the request appears without waiting for a poll.
    ping_users([m.id for m in User.query.filter_by(
        company_id=company.id, role="manager").with_entities(User.id)],
        "team_update")
    return jsonify({"ok": True, "pending": True, "company": company.name})


@app.route("/api/team-code/rotate", methods=["POST"])
@login_required
@manager_required
def api_rotate_code(user):
    guard = api_post_guard()
    if guard:
        return guard
    user.company.join_code = new_join_code()
    db.session.commit()
    return jsonify({"ok": True, "team_code": user.company.join_code})


@app.route("/api/login", methods=["POST"])
def api_login():
    guard = api_post_guard()
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    now = utcnow()
    attempts = [t for t in FAILED_LOGINS.get(email, [])
                if now - t < LOGIN_LOCKOUT_WINDOW]
    FAILED_LOGINS[email] = attempts
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        return jsonify({"error": "too_many_attempts"}), 429

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, data.get("password") or ""):
        FAILED_LOGINS.setdefault(email, []).append(now)
        return jsonify({"error": "invalid_credentials"}), 401
    FAILED_LOGINS.pop(email, None)
    # Credentials are right, but a self-registered account stays locked out
    # until a manager approves it.
    if user.approved is False:
        return jsonify({"error": "pending_approval", "detail":
                        "Your account is waiting for a manager to approve it. "
                        "You'll be able to sign in once they do."}), 403
    # The role field is free text — any role name is accepted (companies have
    # many). Access rights always come from the account's registered role.
    session.permanent = True
    session["uid"] = user.id
    return jsonify({"ok": True, "user": user.to_dict()})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/ping")
def api_ping():
    return jsonify({"ok": True, "authed": bool(session.get("uid"))})


# ---------------------------------------------------------------- web push api

@app.route("/api/push/key")
@login_required
def api_push_key(user):
    # The VAPID public key is the browser's applicationServerKey. Empty when
    # push isn't configured on this host, so the client skips subscribing.
    return jsonify({"key": VAPID_PUBLIC_KEY or "", "enabled": PUSH_ENABLED})


@app.route("/api/push/subscribe", methods=["POST"])
@login_required
def api_push_subscribe(user):
    guard = api_post_guard()
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    keys = data.get("keys") or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth or len(endpoint) > 512:
        return jsonify({"error": "invalid"}), 400
    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if sub:
        # Re-bind an existing endpoint to this user (e.g. shared device).
        sub.user_id = user.id
        sub.p256dh, sub.auth = p256dh, auth
    else:
        db.session.add(PushSubscription(user_id=user.id, endpoint=endpoint,
                                        p256dh=p256dh, auth=auth))
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/push/unsubscribe", methods=["POST"])
@login_required
def api_push_unsubscribe(user):
    guard = api_post_guard()
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    if endpoint:
        PushSubscription.query.filter_by(endpoint=endpoint, user_id=user.id).delete()
        db.session.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- data api

@app.route("/api/bootstrap")
@login_required
def api_bootstrap(user):
    return jsonify(snapshot(user))


@app.route("/api/sync", methods=["POST"])
@login_required
def api_sync(user):
    guard = api_post_guard()
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    actions = data.get("actions") or []
    results = []
    touched_all = set()
    for action in actions[:200]:
        try:
            status, detail = apply_action(user, action)
        except Exception:
            db.session.rollback()
            results.append({"client_id": action.get("client_id"), "status": "error"})
            continue
        if status == "applied":
            touched_all.update(detail)
            db.session.commit()
            results.append({"client_id": action.get("client_id"), "status": "applied"})
        else:
            db.session.rollback()
            results.append({"client_id": action.get("client_id"),
                            "status": status, "detail": detail})
    body = snapshot(user)
    body["results"] = results
    touched_all.discard(user.id)
    if touched_all:
        ping_users(touched_all, "peer_update")
    return jsonify(body)


@app.route("/api/members", methods=["POST"])
@login_required
@manager_required
def api_add_member(user):
    guard = api_post_guard()
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = data.get("role") if data.get("role") in ROLES else "member"
    if not name or "@" not in email or len(password) < 6:
        return jsonify({"error": "invalid", "detail":
                        "Name, valid email and a 6+ character password are required."}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "exists", "detail": "That email is already registered."}), 409
    member = User(company_id=user.company_id, name=name[:120], email=email,
                  password_hash=generate_password_hash(password),
                  role=role, title=(data.get("title") or "")[:120])
    db.session.add(member)
    db.session.commit()
    ping_users([u.id for u in User.query.filter_by(company_id=user.company_id)
                .with_entities(User.id)], "team_update")
    return jsonify({"ok": True, "user": member.to_dict()})


def _pending_in_company(manager, uid):
    """Fetch a pending (unapproved) user in the manager's own company, or None.
    Company-scoped so a manager can never touch another company's requests."""
    target = db.session.get(User, uid)
    if (not target or target.company_id != manager.company_id
            or target.approved is not False):
        return None
    return target


@app.route("/api/members/<int:uid>/approve", methods=["POST"])
@login_required
@manager_required
def api_approve_member(user, uid):
    guard = api_post_guard()
    if guard:
        return guard
    target = _pending_in_company(user, uid)
    if not target:
        return jsonify({"error": "not_found"}), 404
    # Grant the role the manager confirms in the request body; default to what
    # the person asked for; fall back to the safe "member".
    data = request.get_json(silent=True) or {}
    grant = data.get("role")
    if grant not in ROLES:
        grant = target.requested_role if target.requested_role in ROLES else "member"
    target.role = grant
    target.approved = True
    role_label = "a manager" if grant == "manager" else "a team member"
    notify(target.id, "team",
           f"Your request to join {user.company.name} was approved "
           f"as {role_label}. Welcome!")
    for mgr in User.query.filter_by(company_id=user.company_id, role="manager").all():
        if mgr.id != user.id:
            notify(mgr.id, "team", f"{user.name} approved {target.name}")
    db.session.commit()
    ping_users([u.id for u in User.query.filter(
        User.company_id == user.company_id, User.approved.isnot(False))
        .with_entities(User.id)], "team_update")
    return jsonify({"ok": True, "user": target.to_dict()})


@app.route("/api/members/<int:uid>/reject", methods=["POST"])
@login_required
@manager_required
def api_reject_member(user, uid):
    guard = api_post_guard()
    if guard:
        return guard
    target = _pending_in_company(user, uid)
    if not target:
        return jsonify({"error": "not_found"}), 404
    name = target.name
    # Deleting the pending row frees the email so the person can be re-invited.
    db.session.delete(target)
    for mgr in User.query.filter_by(company_id=user.company_id, role="manager").all():
        if mgr.id != user.id:
            notify(mgr.id, "team", f"{user.name} declined {name}'s request to join")
    db.session.commit()
    ping_users([m.id for m in User.query.filter_by(
        company_id=user.company_id, role="manager").with_entities(User.id)],
        "team_update")
    return jsonify({"ok": True})


# ---------------------------------------------------------------- socket.io

if socketio:
    @socketio.on("connect")
    def on_connect():
        uid = session.get("uid")
        if not uid:
            return False  # reject unauthenticated sockets
        join_room(f"user:{uid}")
        ONLINE.setdefault(uid, set()).add(request.sid)
        socketio.emit("refresh", {"reason": "presence"})

    @socketio.on("disconnect")
    def on_disconnect():
        uid = session.get("uid")
        if uid and uid in ONLINE:
            ONLINE[uid].discard(request.sid)
            if not ONLINE[uid]:
                del ONLINE[uid]
            socketio.emit("refresh", {"reason": "presence"})


# ---------------------------------------------------------------- schema / migration

def _sqlite_add_column(table, column, coltype):
    """Add a column to an existing SQLite table if it is missing.
    db.create_all() creates missing *tables* but never alters existing ones."""
    rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
    existing = {r[1] for r in rows}
    if column not in existing:
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
        db.session.commit()


def ensure_schema():
    """Create tables and migrate a pre-multi-tenant database in place.

    Existing users/tasks/messages predate the company_id column and the
    companies table; we add the column, then fold all existing rows into one
    default company (keeping the old global join code) so live data survives.
    """
    db.create_all()
    if db.engine.url.get_backend_name() == "sqlite":
        _sqlite_add_column("users", "company_id", "INTEGER")
        _sqlite_add_column("tasks", "company_id", "INTEGER")
        _sqlite_add_column("messages", "company_id", "INTEGER")
        # Everyone who already had an account predates approval → keep them in.
        _sqlite_add_column("users", "approved", "BOOLEAN")
        _sqlite_add_column("users", "requested_role", "VARCHAR(20)")
        db.session.execute(text("UPDATE users SET approved=1 WHERE approved IS NULL"))
        db.session.commit()

    orphans = (User.query.filter(User.company_id.is_(None)).count()
               or Task.query.filter(Task.company_id.is_(None)).count()
               or Message.query.filter(Message.company_id.is_(None)).count())
    if not orphans:
        return

    default = Company.query.order_by(Company.id).first()
    if not default:
        old = db.session.get(Setting, "team_code")
        code = old.value if old else new_join_code()
        mgr = User.query.filter_by(role="manager").order_by(User.id).first()
        cname = (f"{mgr.name.split()[0]}'s Company" if mgr else "My Company")
        default = Company(name=cname[:160], join_code=code)
        db.session.add(default)
        db.session.flush()
    cid = default.id
    for u in User.query.filter(User.company_id.is_(None)).all():
        u.company_id = cid
    for t in Task.query.filter(Task.company_id.is_(None)).all():
        t.company_id = cid
    for m in Message.query.filter(Message.company_id.is_(None)).all():
        m.company_id = cid
    db.session.commit()


# ---------------------------------------------------------------- entrypoint

with app.app_context():
    ensure_schema()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"\n  KaryaSetu running at  http://localhost:{port}\n")
    debug = os.environ.get("FLASK_DEBUG") == "1"
    if socketio:
        socketio.run(app, host="0.0.0.0", port=port, debug=debug,
                     allow_unsafe_werkzeug=True)
    else:
        app.run(host="0.0.0.0", port=port, debug=debug)
