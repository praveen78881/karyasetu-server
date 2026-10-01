"""KaryaSetu database models.

Works against SQLite out of the box; point DATABASE_URL at MySQL
(mysql+pymysql://user:pass@host/dbname) for production.
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

PRIORITIES = ("low", "medium", "high", "urgent")
STATUSES = ("pending", "in_progress", "completed")
ROLES = ("manager", "member")


def utcnow():
    # Stored naive-UTC; serialized with a trailing "Z" so clients render local time.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Company(db.Model):
    """A tenant. Every user/task/message belongs to exactly one company, and
    no query ever crosses the company boundary."""
    __tablename__ = "companies"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    # Per-company self-registration code (managers can rotate it).
    join_code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"),
                           nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    # Email is globally unique: one account belongs to one company, so signing
    # in by email alone resolves the company unambiguously.
    email = db.Column(db.String(190), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="member")
    title = db.Column(db.String(120), default="")
    # Employees who self-register with a join code start unapproved: a manager
    # must approve them before they can sign in or see anything. Accounts a
    # manager creates directly (and the founding manager) are approved on
    # creation. NULL is treated as approved (legacy rows pre-dating this column).
    approved = db.Column(db.Boolean, default=True, nullable=False)
    # The role a self-registering person asked for on the sign-up form. It is
    # NOT granted automatically — a manager sees it and chooses what to grant
    # when approving. The live `role` above stays "member" until then.
    requested_role = db.Column(db.String(20), default="member")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    company = db.relationship("Company", foreign_keys=[company_id])

    def to_dict(self, online_ids=None):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "title": self.title or "",
            "online": self.id in (online_ids or ()),
        }

    def pending_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "title": self.title or "",
            "requested_role": self.requested_role or "member",
            "requested_at": self.created_at.isoformat(timespec="seconds") + "Z"
            if self.created_at else None,
        }


class Task(db.Model):
    __tablename__ = "tasks"
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"),
                           nullable=False, index=True)
    # Client-generated UUID when the task was created offline; used for sync dedupe.
    client_id = db.Column(db.String(64), unique=True, nullable=True, index=True)
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text, default="")
    priority = db.Column(db.String(20), nullable=False, default="medium")
    status = db.Column(db.String(30), nullable=False, default="pending", index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    due_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship("User", foreign_keys=[created_by])
    assignee = db.relationship("User", foreign_keys=[assigned_to])
    history = db.relationship(
        "StatusHistory", backref="task", order_by="StatusHistory.created_at",
        cascade="all, delete-orphan",
    )


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"),
                           nullable=False, index=True)
    client_id = db.Column(db.String(64), unique=True, nullable=True, index=True)
    # Either linked to a task thread (task_id set) or a direct message (recipient_id set).
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=True, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    sender = db.relationship("User", foreign_keys=[sender_id])


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    kind = db.Column(db.String(40), nullable=False)  # task_assigned | status_changed | task_completed | message | due_soon | overdue
    text = db.Column(db.String(400), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=True)
    read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)


class StatusHistory(db.Model):
    __tablename__ = "status_history"
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    from_status = db.Column(db.String(30), nullable=True)
    to_status = db.Column(db.String(30), nullable=False)
    note = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    actor = db.relationship("User", foreign_keys=[user_id])


class Setting(db.Model):
    """Small key-value store for workspace settings (e.g. the team join code)."""
    __tablename__ = "settings"
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.String(300), nullable=False)


class PushSubscription(db.Model):
    """A browser Web Push subscription for one user's device. A user may have
    several (phone, laptop, …). Stale ones (410/404 from the push service) are
    pruned automatically."""
    __tablename__ = "push_subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    endpoint = db.Column(db.String(512), unique=True, nullable=False)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class ProcessedAction(db.Model):
    """Offline-sync ledger: every applied outbox action's client_id lands here,
    so a retried sync batch is idempotent."""
    __tablename__ = "processed_actions"
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action_type = db.Column(db.String(40), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
