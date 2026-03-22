from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Literal


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


PaymentStatus = Literal["created", "pending", "paid", "expired", "failed", "cancelled"]


@dataclass(frozen=True)
class Payment:
    payment_id: str
    user_id: int
    provider: str
    plan_id: str
    amount_cents: int
    currency: str
    status: PaymentStatus
    checkout_url: str
    provider_ref: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Subscription:
    user_id: int
    plan_id: str
    active_until: datetime
    updated_at: datetime
    active: bool


@dataclass(frozen=True)
class PlanRecord:
    plan_id: str
    name: str
    price_cents: int
    duration_days: int


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        sub_cols = {r[1] for r in conn.execute("PRAGMA table_info(subscriptions)").fetchall()}
        if sub_cols and "active" not in sub_cols:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN active INTEGER NOT NULL DEFAULT 1")

        pay_indexes = {
            str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='payments'").fetchall()
        }
        if "idx_payments_provider_ref_unique" not in pay_indexes:
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_provider_ref_unique
                ON payments(provider_ref) WHERE provider_ref IS NOT NULL
                """
            )

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                  user_id INTEGER PRIMARY KEY,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS payments (
                  payment_id TEXT PRIMARY KEY,
                  user_id INTEGER NOT NULL,
                  provider TEXT NOT NULL,
                  plan_id TEXT NOT NULL,
                  amount_cents INTEGER NOT NULL,
                  currency TEXT NOT NULL,
                  status TEXT NOT NULL,
                  checkout_url TEXT NOT NULL,
                  provider_ref TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
                CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);

                CREATE TABLE IF NOT EXISTS subscriptions (
                  user_id INTEGER PRIMARY KEY,
                  plan_id TEXT NOT NULL,
                  active_until TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  active INTEGER NOT NULL DEFAULT 1,
                  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS plans (
                  plan_id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  price_cents INTEGER NOT NULL,
                  duration_days INTEGER NOT NULL
                );
                """
            )
            self._migrate(conn)

    def ensure_user(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?)",
                (user_id, utcnow().isoformat()),
            )

    def create_payment(
        self,
        *,
        payment_id: str,
        user_id: int,
        provider: str,
        plan_id: str,
        amount_cents: int,
        currency: str,
        status: PaymentStatus,
        checkout_url: str,
        provider_ref: str | None,
    ) -> None:
        self.ensure_user(user_id)
        now = utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO payments(
                  payment_id, user_id, provider, plan_id, amount_cents, currency,
                  status, checkout_url, provider_ref, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payment_id,
                    user_id,
                    provider,
                    plan_id,
                    amount_cents,
                    currency,
                    status,
                    checkout_url,
                    provider_ref,
                    now,
                    now,
                ),
            )

    def update_payment_status(self, payment_id: str, status: PaymentStatus, provider_ref: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE payments SET status=?, provider_ref=COALESCE(?, provider_ref), updated_at=? WHERE payment_id=?",
                (status, provider_ref, utcnow().isoformat(), payment_id),
            )

    def get_payment(self, payment_id: str) -> Payment | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM payments WHERE payment_id=?", (payment_id,)).fetchone()
        return self._row_to_payment(row) if row else None

    def get_payment_by_provider_ref(self, *, provider: str, provider_ref: str) -> Payment | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE provider=? AND provider_ref=?",
                (provider, provider_ref),
            ).fetchone()
        return self._row_to_payment(row) if row else None

    def list_payments_by_status(self, statuses: Iterable[PaymentStatus], limit: int = 50) -> list[Payment]:
        qs = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM payments WHERE status IN ({qs}) ORDER BY created_at ASC LIMIT ?",
                (*statuses, limit),
            ).fetchall()
        return [self._row_to_payment(r) for r in rows]

    def upsert_subscription(self, user_id: int, plan_id: str, active_until: datetime, *, active: bool = True) -> None:
        self.ensure_user(user_id)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO subscriptions(user_id, plan_id, active_until, updated_at, active)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                  plan_id=excluded.plan_id,
                  active_until=excluded.active_until,
                  updated_at=excluded.updated_at,
                  active=excluded.active
                """,
                (user_id, plan_id, active_until.isoformat(), utcnow().isoformat(), 1 if active else 0),
            )

    def deactivate_subscription(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE subscriptions SET active=0, updated_at=? WHERE user_id=?",
                (utcnow().isoformat(), user_id),
            )

    def revoke_subscription(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM subscriptions WHERE user_id=?", (user_id,))

    def get_subscription(self, user_id: int) -> Subscription | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        return self._row_to_subscription(row)

    def list_expired_active_subscriptions(self) -> list[Subscription]:
        now = utcnow().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM subscriptions
                WHERE active = 1 AND active_until < ?
                """,
                (now,),
            ).fetchall()
        return [self._row_to_subscription(r) for r in rows]

    def list_plans(self) -> list[PlanRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM plans ORDER BY plan_id ASC").fetchall()
        return [self._row_to_plan(r) for r in rows]

    def get_plan_record(self, plan_id: str) -> PlanRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        return self._row_to_plan(row) if row else None

    def upsert_plan_record(self, plan: PlanRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO plans(plan_id, name, price_cents, duration_days)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                  name=excluded.name,
                  price_cents=excluded.price_cents,
                  duration_days=excluded.duration_days
                """,
                (plan.plan_id, plan.name, plan.price_cents, plan.duration_days),
            )

    def add_days(self, user_id: int, plan_id: str, days: int) -> Subscription:
        now = utcnow()
        existing = self.get_subscription(user_id)
        base = existing.active_until if existing and existing.active_until > now else now
        new_until = base + timedelta(days=days)
        self.upsert_subscription(user_id, plan_id, new_until, active=True)
        return self.get_subscription(user_id)  # type: ignore[return-value]

    @staticmethod
    def _row_to_payment(row: sqlite3.Row) -> Payment:
        return Payment(
            payment_id=str(row["payment_id"]),
            user_id=int(row["user_id"]),
            provider=str(row["provider"]),
            plan_id=str(row["plan_id"]),
            amount_cents=int(row["amount_cents"]),
            currency=str(row["currency"]),
            status=str(row["status"]),  # type: ignore[assignment]
            checkout_url=str(row["checkout_url"]),
            provider_ref=row["provider_ref"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_subscription(row: sqlite3.Row) -> Subscription:
        active = row["active"] if "active" in row.keys() else 1
        return Subscription(
            user_id=int(row["user_id"]),
            plan_id=str(row["plan_id"]),
            active_until=datetime.fromisoformat(row["active_until"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            active=bool(active),
        )

    @staticmethod
    def _row_to_plan(row: sqlite3.Row) -> PlanRecord:
        return PlanRecord(
            plan_id=str(row["plan_id"]),
            name=str(row["name"]),
            price_cents=int(row["price_cents"]),
            duration_days=int(row["duration_days"]),
        )
