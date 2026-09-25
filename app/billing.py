"""One fixed-price subscription per bot. Stripe is authoritative; redirects grant nothing."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import stripe
from fastapi import HTTPException

from app.config import settings
from app.db import one, transaction

log = logging.getLogger("coastworks.billing")
TERMINAL = {"canceled", "incomplete_expired"}
EVENTS = {
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.resumed",
    "invoice.paid",
    "invoice.payment_failed",
    "invoice.payment_action_required",
    "invoice.marked_uncollectible",
    "invoice.voided",
}


@lru_cache
def client():
    return stripe.StripeClient(
        settings.STRIPE_API_KEY,
        stripe_version="2026-08-26.dahlia",
        max_network_retries=1,
        http_client=stripe.HTTPXClient(timeout=8),
    )


class BillingContractError(Exception):
    """Safe machine-readable configuration/reconciliation failure."""


def resource(value):
    """Normalize current Stripe SDK resources at the provider boundary."""
    return value.to_dict() if isinstance(value, stripe.StripeObject) else value


def require_configured():
    if not settings.BILLING_ENABLED:
        raise HTTPException(503, "Betalningen är inte tillgänglig ännu.")


def entitled(row):
    return bool(
        row
        and row["status"] in {"active", "past_due"}
        and row.get("paid_until")
        and row["paid_until"] > datetime.now(timezone.utc)
    )


async def require_paid(db, bot_id):
    if settings.BILLING_ENABLED:
        row = await one(db, "SELECT * FROM bot_billing WHERE bot_id=%s", (bot_id,))
        if not entitled(row):
            raise HTTPException(402, "Ett betalt abonnemang krävs för att aktivera assistenten.")


def valid_price(price):
    price = resource(price)
    recurring = price.get("recurring") or {}
    return (
        price.get("id") == settings.STRIPE_PRICE_ID
        and price.get("currency") == "sek"
        and price.get("unit_amount") == 39900
        and recurring.get("interval") == "month"
        and recurring.get("interval_count") == 1
        and price.get("tax_behavior") == settings.STRIPE_TAX_BEHAVIOR
        and price.get("livemode") == settings.STRIPE_LIVEMODE
    )


async def validate_catalog():
    price = await client().v1.prices.retrieve_async(settings.STRIPE_PRICE_ID)
    price = resource(price)
    if not price.get("active") or not valid_price(price):
        raise BillingContractError("STRIPE_PRICE_CONTRACT")
    portal_config = resource(
        await client().v1.billing_portal.configurations.retrieve_async(
            settings.STRIPE_PORTAL_CONFIGURATION_ID
        )
    )
    features = portal_config.get("features", {})
    cancel = features.get("subscription_cancel", {})
    if (
        not portal_config.get("active")
        or portal_config.get("livemode") != settings.STRIPE_LIVEMODE
        or features.get("subscription_update", {}).get("enabled")
        or not cancel.get("enabled")
        or cancel.get("mode") != "at_period_end"
        or not features.get("payment_method_update", {}).get("enabled")
        or not features.get("invoice_history", {}).get("enabled")
    ):
        raise BillingContractError("STRIPE_PORTAL_CONTRACT")
    if settings.STRIPE_AUTOMATIC_TAX:
        registrations = await client().v1.tax.registrations.list_async({"status": "active", "limit": 1})
        if not registrations["data"]:
            raise BillingContractError("STRIPE_TAX_REGISTRATION_REQUIRED")


async def locked_row(db, bot_id):
    await db.execute("INSERT INTO bot_billing(bot_id) VALUES(%s) ON CONFLICT DO NOTHING", (bot_id,))
    return await one(db, "SELECT * FROM bot_billing WHERE bot_id=%s FOR UPDATE", (bot_id,))


async def apply_subscription(db, row, sub):
    """Called under the bot's row lock after fetching current Stripe state, never event snapshots."""
    sub = resource(sub)
    items = sub.get("items", {}).get("data", [])
    if (
        sub.get("customer") != row["customer_id"]
        or sub.get("metadata", {}).get("bot_id") != str(row["bot_id"])
        or sub.get("livemode") != settings.STRIPE_LIVEMODE
    ):
        raise BillingContractError("STRIPE_SUBSCRIPTION_IDENTITY")
    valid = len(items) == 1 and items[0].get("quantity") == 1 and valid_price(items[0]["price"])
    status = sub["status"] if valid and not sub.get("pause_collection") else "invalid"
    invoice = sub.get("latest_invoice") or {}
    paid_until = row["paid_until"] if row["subscription_id"] == sub["id"] else None
    if (
        status == "active"
        and isinstance(invoice, dict)
        and invoice.get("status") == "paid"
        and invoice.get("billing_reason") in {"subscription_create", "subscription_cycle"}
    ):
        # Grant only the service period actually covered by the paid invoice.
        periods = [
            line["period"]["end"]
            for line in invoice.get("lines", {}).get("data", [])
            if (line.get("parent") or {}).get("type") == "subscription_item_details"
            and (line.get("pricing") or {}).get("price_details", {}).get("price") == settings.STRIPE_PRICE_ID
            and line.get("quantity") == 1
        ]
        if periods:
            paid_until = datetime.fromtimestamp(
                min(max(periods), items[0]["current_period_end"]), timezone.utc
            )
    if status not in {"active", "past_due"}:
        paid_until = None
    await db.execute(
        """UPDATE bot_billing SET subscription_id=%s,status=%s,paid_until=%s,
        cancel_at_period_end=%s,checked_at=now() WHERE bot_id=%s""",
        (sub["id"], status, paid_until, bool(sub.get("cancel_at_period_end")), row["bot_id"]),
    )
    return await one(db, "SELECT * FROM bot_billing WHERE bot_id=%s", (row["bot_id"],))


async def reconcile_locked(db, row):
    if not row["customer_id"]:
        return row
    # Listing also recovers a completed Checkout whose webhook has not arrived yet.
    found = await client().v1.subscriptions.list_async(
        {
            "customer": row["customer_id"],
            "status": "all",
            "limit": 100,
            "expand": ["data.latest_invoice"],
        }
    )
    found = resource(found)
    if found.get("has_more"):
        raise BillingContractError("STRIPE_SUBSCRIPTION_REVIEW_REQUIRED")
    subscriptions = [
        resource(s)
        for s in found["data"]
        if resource(s).get("metadata", {}).get("bot_id") == str(row["bot_id"])
    ]
    active = [s for s in subscriptions if s["status"] not in TERMINAL]
    if len(active) > 1:
        raise BillingContractError("STRIPE_DUPLICATE_SUBSCRIPTIONS")
    selected = active or [s for s in subscriptions if s["id"] == row["subscription_id"]]
    if selected:
        return await apply_subscription(db, row, selected[0])
    await db.execute("UPDATE bot_billing SET checked_at=now() WHERE bot_id=%s", (row["bot_id"],))
    return row


async def checkout(bot):
    require_configured()
    await validate_catalog()
    bot_id = bot["id"]
    # Persist identity and attempt before creating any chargeable object remotely.
    async with transaction() as db:
        row = await locked_row(db, bot_id)
        if not row["customer_id"]:
            customer = await client().v1.customers.create_async(
                {"email": bot["owner_email"], "metadata": {"bot_id": str(bot_id)}},
                {"idempotency_key": f"cw-customer-{bot_id}"},
            )
            await db.execute(
                "UPDATE bot_billing SET customer_id=%s WHERE bot_id=%s", (customer["id"], bot_id)
            )
        if not row["checkout_expires_at"] or row["checkout_expires_at"] <= datetime.now(timezone.utc):
            await db.execute(
                """UPDATE bot_billing SET checkout_attempt=%s,
                checkout_expires_at=now()+interval '1 hour' WHERE bot_id=%s""",
                (uuid.uuid4(), bot_id),
            )
    async with transaction() as db:
        row = await locked_row(db, bot_id)
        row = await reconcile_locked(db, row)
        if row["subscription_id"] and row["status"] not in TERMINAL:
            raise HTTPException(409, "Assistenten har redan ett abonnemang. Använd Hantera abonnemang.")
        # Reuse open sessions, including ones whose successful API response was lost.
        sessions = await client().v1.checkout.sessions.list_async(
            {
                "customer": row["customer_id"],
                "status": "open",
                "limit": 100,
            }
        )
        sessions = resource(sessions)
        if sessions.get("has_more"):
            raise BillingContractError("STRIPE_CHECKOUT_REVIEW_REQUIRED")
        for session in sessions["data"]:
            if session.get("client_reference_id") == str(bot_id):
                return {"url": session["url"]}
        attempt = str(row["checkout_attempt"])
        # If a request failed ambiguously too close to expiry, wait for expiry before a new attempt.
        if row["checkout_expires_at"] < datetime.now(timezone.utc) + timedelta(minutes=31):
            raise HTTPException(409, "Betalningen behöver återställas. Försök igen om en stund.")
        params = {
            "mode": "subscription",
            "customer": row["customer_id"],
            "client_reference_id": str(bot_id),
            "line_items": [{"price": settings.STRIPE_PRICE_ID, "quantity": 1}],
            "subscription_data": {"metadata": {"bot_id": str(bot_id)}},
            "metadata": {"bot_id": str(bot_id)},
            "expires_at": int(row["checkout_expires_at"].timestamp()),
            "success_url": settings.APP_ORIGIN + f"/?billing=return&bot={bot_id}",
            "cancel_url": settings.APP_ORIGIN + f"/?billing=cancel&bot={bot_id}",
            "integration_identifier": "coastworks_"
            + "".join(chr(97 + int(c, 16)) for c in attempt.replace("-", "")[:8]),
            "tax_id_collection": {"enabled": True},
        }
        if settings.STRIPE_AUTOMATIC_TAX:
            params.update(
                {
                    "automatic_tax": {"enabled": True},
                    "customer_update": {"address": "auto"},
                    "billing_address_collection": "required",
                }
            )
        session = await client().v1.checkout.sessions.create_async(
            params, {"idempotency_key": f"cw-checkout-{attempt}"}
        )
        return {"url": session["url"]}


async def status(bot_id, refresh=False):
    async with transaction() as db:
        row = await one(db, "SELECT * FROM bot_billing WHERE bot_id=%s FOR UPDATE", (bot_id,))
        if row and refresh and settings.BILLING_ENABLED:
            row = await reconcile_locked(db, row)
    return {
        "enabled": settings.BILLING_ENABLED,
        "active": entitled(row),
        "status": row["status"] if row else "none",
        "amount": 39900,
        "currency": "sek",
        "tax_behavior": settings.STRIPE_TAX_BEHAVIOR,
        "paid_until": row["paid_until"].isoformat() if row and row["paid_until"] else None,
        "cancel_at_period_end": bool(row and row["cancel_at_period_end"]),
        "can_manage": bool(row and row["customer_id"]),
    }


async def portal(bot_id):
    require_configured()
    async with transaction() as db:
        row = await one(db, "SELECT customer_id FROM bot_billing WHERE bot_id=%s", (bot_id,))
    if not row or not row["customer_id"]:
        raise HTTPException(409, "Det finns inget abonnemang att hantera ännu.")
    session = await client().v1.billing_portal.sessions.create_async(
        {
            "customer": row["customer_id"],
            "configuration": settings.STRIPE_PORTAL_CONFIGURATION_ID,
            "return_url": settings.APP_ORIGIN + f"/?billing=return&bot={bot_id}",
        }
    )
    return {"url": session["url"]}


async def prepare_delete(db, bot_id):
    row = await one(db, "SELECT * FROM bot_billing WHERE bot_id=%s FOR UPDATE", (bot_id,))
    if not row:
        return
    require_configured()
    if row["customer_id"]:
        sessions = resource(
            await client().v1.checkout.sessions.list_async(
                {"customer": row["customer_id"], "status": "open", "limit": 100}
            )
        )
        if sessions.get("has_more"):
            raise BillingContractError("STRIPE_CHECKOUT_REVIEW_REQUIRED")
        # Close pending Checkout before the final subscription read: no payment may race deletion.
        for session in sessions["data"]:
            if session.get("client_reference_id") == str(bot_id):
                await client().v1.checkout.sessions.expire_async(session["id"])
        row = await reconcile_locked(db, row)
        if row["subscription_id"] and row["status"] not in TERMINAL:
            raise HTTPException(
                409, "Säg upp abonnemanget i kundportalen och invänta periodens slut före radering."
            )
    await db.execute("DELETE FROM bot_billing WHERE bot_id=%s", (bot_id,))


async def receive_event(payload, signature):
    require_configured()
    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Ogiltig Stripe-signatur.")
    event = event.to_dict()
    if event.get("livemode") != settings.STRIPE_LIVEMODE:
        raise HTTPException(400, "Fel Stripe-miljö.")
    if event["type"] not in EVENTS:
        return
    customer = event["data"]["object"].get("customer")
    if not isinstance(customer, str):
        return
    async with transaction() as db:
        await db.execute(
            """INSERT INTO billing_events(event_id,customer_id)
            SELECT %s,customer_id FROM bot_billing WHERE customer_id=%s ON CONFLICT DO NOTHING""",
            (event["id"], customer),
        )


async def reconcile_pending():
    if not settings.BILLING_ENABLED:
        return
    async with transaction() as db:
        rows = await (
            await db.execute("""SELECT b.bot_id FROM bot_billing b WHERE b.customer_id IS NOT NULL
            AND (b.checked_at IS NULL OR b.checked_at<now()-interval '6 hours'
            OR EXISTS(SELECT 1 FROM billing_events e WHERE e.customer_id=b.customer_id
                AND e.processed_at IS NULL AND e.retry_at<=now()))
            ORDER BY b.checked_at NULLS FIRST LIMIT 20""")
        ).fetchall()
    for item in rows:
        try:
            async with transaction() as db:
                row = await one(
                    db, "SELECT * FROM bot_billing WHERE bot_id=%s FOR UPDATE SKIP LOCKED", (item["bot_id"],)
                )
                if not row:
                    continue
                # Only acknowledge events received before this reconciliation started.
                cutoff = datetime.now(timezone.utc)
                await reconcile_locked(db, row)
                await db.execute(
                    """UPDATE billing_events SET processed_at=now() WHERE customer_id=%s
                    AND received_at<=%s AND processed_at IS NULL""",
                    (row["customer_id"], cutoff),
                )
        except Exception as exc:
            log.warning("billing_reconcile_failed bot=%s type=%s", item["bot_id"], type(exc).__name__)
            async with transaction() as db:
                await db.execute(
                    """UPDATE billing_events SET attempts=attempts+1,retry_at=now()+interval '5 minutes'
                    WHERE customer_id=(SELECT customer_id FROM bot_billing WHERE bot_id=%s)
                    AND processed_at IS NULL""",
                    (item["bot_id"],),
                )
    async with transaction() as db:
        await db.execute("DELETE FROM billing_events WHERE processed_at<now()-interval '30 days'")


async def run_loop():
    while True:
        try:
            await reconcile_pending()
        except Exception as exc:
            log.warning("billing_loop_failed type=%s", type(exc).__name__)
        await asyncio.sleep(30)
