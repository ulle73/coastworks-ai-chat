import asyncio
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import stripe
from fastapi import HTTPException

from app import billing
from app.config import settings
from app.db import one, transaction
from app.main import app
from app.security import digest, signer


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(settings, "BILLING_ENABLED", True)
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID", "price_monthly")
    monkeypatch.setattr(settings, "STRIPE_LIVEMODE", False)
    monkeypatch.setattr(settings, "STRIPE_TAX_BEHAVIOR", "inclusive")
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "unit-test-signing-value")
    monkeypatch.setattr(settings, "STRIPE_AUTOMATIC_TAX", False)
    price = {
        "id": "price_monthly",
        "currency": "sek",
        "unit_amount": 39900,
        "active": True,
        "livemode": False,
        "tax_behavior": "inclusive",
        "recurring": {"interval": "month", "interval_count": 1},
    }
    fake = SimpleNamespace(
        v1=SimpleNamespace(
            prices=SimpleNamespace(retrieve_async=AsyncMock(return_value=price)),
            customers=SimpleNamespace(create_async=AsyncMock(return_value={"id": "cus_unit"})),
            subscriptions=SimpleNamespace(list_async=AsyncMock(return_value={"data": [], "has_more": False})),
            checkout=SimpleNamespace(
                sessions=SimpleNamespace(
                    list_async=AsyncMock(return_value={"data": [], "has_more": False}),
                    create_async=AsyncMock(
                        return_value={"id": "cs_unit", "url": "https://checkout.stripe.com/unit"}
                    ),
                )
            ),
            billing_portal=SimpleNamespace(
                configurations=SimpleNamespace(
                    retrieve_async=AsyncMock(
                        return_value={
                            "active": True,
                            "livemode": False,
                            "features": {
                                "subscription_update": {"enabled": False},
                                "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
                                "payment_method_update": {"enabled": True},
                                "invoice_history": {"enabled": True},
                            },
                        }
                    )
                ),
                sessions=SimpleNamespace(
                    create_async=AsyncMock(return_value={"url": "https://billing.stripe.com/unit"})
                ),
            ),
        )
    )
    monkeypatch.setattr(billing, "client", lambda: fake)
    return fake


async def seed():
    bot_id = uuid.uuid4()
    async with transaction() as db:
        await db.execute(
            """INSERT INTO bots(id,url,origin,preview_hash,owner_email,active_version,
            state,install_nonce,published,expires_at) VALUES(%s,'https://company.example/',
            'https://company.example',%s,'owner@example.com',%s,'ready','install',true,now()+interval '1 day')""",
            (bot_id, digest("preview"), uuid.uuid4()),
        )
        await db.execute("INSERT INTO bot_billing(bot_id,customer_id) VALUES(%s,'cus_unit')", (bot_id,))
        return await one(db, "SELECT * FROM bots WHERE id=%s", (bot_id,))


def subscription(bot, provider, **overrides):
    value = {
        "id": "sub_unit",
        "customer": "cus_unit",
        "metadata": {"bot_id": str(bot["id"])},
        "status": "active",
        "livemode": False,
        "cancel_at_period_end": False,
        "items": {
            "data": [
                {
                    "quantity": 1,
                    "price": provider.v1.prices.retrieve_async.return_value,
                    "current_period_end": int(time.time()) + 86400,
                }
            ]
        },
        "latest_invoice": {
            "status": "paid",
            "billing_reason": "subscription_cycle",
            "lines": {
                "data": [
                    {
                        "quantity": 1,
                        "parent": {"type": "subscription_item_details"},
                        "pricing": {"price_details": {"price": "price_monthly"}},
                        "period": {"end": int(time.time()) + 86400},
                    }
                ]
            },
        },
    }
    value.update(overrides)
    # Real SDK objects deliberately used: StripeObject is not a dict in current SDKs.
    return stripe.StripeObject.construct_from(value, None)


def webclient(email="owner@example.com"):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=settings.APP_ORIGIN,
        headers={"Origin": settings.APP_ORIGIN},
        cookies={"cw_owner": signer.dumps({"email": email}, salt="owner-v1")},
    )


def signed(event):
    payload = json.dumps(event).encode()
    timestamp = int(time.time())
    signature = hmac.new(
        settings.STRIPE_WEBHOOK_SECRET.encode(), str(timestamp).encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    return payload, f"t={timestamp},v1={signature}"


@pytest.mark.usefixtures("database")
async def test_paid_invoice_and_expiry_enforced_on_widget_and_publication(provider):
    bot = await seed()
    async with webclient() as c:
        assert (await c.post(f"/api/bots/{bot['id']}/publish")).status_code == 402
        assert (
            await c.post(f"/api/widget/{bot['id']}/session", headers={"Origin": bot["origin"]})
        ).status_code == 402
        async with transaction() as db:
            row = await billing.locked_row(db, bot["id"])
            await billing.apply_subscription(db, row, subscription(bot, provider))
        response = await c.post(f"/api/widget/{bot['id']}/session", headers={"Origin": bot["origin"]})
        assert response.status_code == 200
        token = response.json()["token"]
        async with transaction() as db:
            await db.execute("UPDATE bot_billing SET paid_until=now()-interval '1 second'")
        assert (
            await c.post(
                f"/api/widget/{bot['id']}/chat",
                json={"message": "Hej"},
                headers={"Authorization": "Bearer " + token},
            )
        ).status_code == 402


@pytest.mark.usefixtures("database")
async def test_paid_period_cancellation_failed_renewal_and_wrong_price(provider):
    bot = await seed()
    async with transaction() as db:
        row = await billing.locked_row(db, bot["id"])
        unpaid = subscription(bot, provider, latest_invoice={"status": "open"})
        row = await billing.apply_subscription(db, row, unpaid)
        assert not billing.entitled(row)
        row = await billing.apply_subscription(
            db, row, subscription(bot, provider, cancel_at_period_end=True)
        )
        assert billing.entitled(row) and row["cancel_at_period_end"]
        end = row["paid_until"]
        row = await billing.apply_subscription(
            db, row, subscription(bot, provider, status="past_due", latest_invoice={"status": "open"})
        )
        assert row["paid_until"] == end
        row = await billing.apply_subscription(db, row, subscription(bot, provider, status="canceled"))
        assert not billing.entitled(row)
        invalid = subscription(bot, provider)
        invalid["items"]["data"][0]["quantity"] = 2
        row = await billing.apply_subscription(db, row, invalid)
        assert not billing.entitled(row) and row["status"] == "invalid"


@pytest.mark.usefixtures("database")
async def test_checkout_race_reuses_session_and_server_price(provider):
    bot = await seed()

    async def create(params, options):
        assert params["line_items"] == [{"price": "price_monthly", "quantity": 1}]
        assert "payment_method_types" not in params
        assert options["idempotency_key"].startswith("cw-checkout-")
        provider.v1.checkout.sessions.list_async.return_value = {
            "data": [{"client_reference_id": str(bot["id"]), "url": "https://checkout.stripe.com/unit"}]
        }
        return {"url": "https://checkout.stripe.com/unit"}

    provider.v1.checkout.sessions.create_async.side_effect = create
    results = await asyncio.gather(billing.checkout(bot), billing.checkout(bot))
    assert results[0] == results[1]
    assert provider.v1.checkout.sessions.create_async.await_count == 1


@pytest.mark.usefixtures("database")
async def test_checkout_recovers_subscription_before_webhook_and_no_duplicate_charge(provider):
    bot = await seed()
    provider.v1.subscriptions.list_async.return_value = {"data": [subscription(bot, provider)]}
    with pytest.raises(HTTPException) as exc:
        await billing.checkout(bot)
    assert exc.value.status_code == 409
    provider.v1.checkout.sessions.create_async.assert_not_awaited()


@pytest.mark.usefixtures("database")
async def test_webhook_signature_duplicates_out_of_order_and_retry(provider):
    bot = await seed()
    event = {
        "id": "evt_unit",
        "type": "invoice.paid",
        "livemode": False,
        "data": {"object": {"customer": "cus_unit", "status": "paid"}},
    }
    payload, sig = signed(event)
    async with webclient() as c:
        assert (await c.post("/api/billing/webhook", content=payload)).status_code == 400
        for _ in range(2):
            assert (
                await c.post("/api/billing/webhook", content=payload, headers={"Stripe-Signature": sig})
            ).status_code == 200
    async with transaction() as db:
        assert (await one(db, "SELECT count(*) AS n FROM billing_events"))["n"] == 1
    provider.v1.subscriptions.list_async.side_effect = RuntimeError("transient")
    await billing.reconcile_pending()
    async with transaction() as db:
        assert (await one(db, "SELECT processed_at FROM billing_events"))["processed_at"] is None
        await db.execute("UPDATE billing_events SET retry_at=now()")
    provider.v1.subscriptions.list_async.side_effect = None
    # Old paid event must observe current cancellation, not reactivate the bot.
    provider.v1.subscriptions.list_async.return_value = {
        "data": [subscription(bot, provider, status="canceled")]
    }
    async with transaction() as db:
        await db.execute("UPDATE bot_billing SET subscription_id='sub_unit'")
    await billing.reconcile_pending()
    async with transaction() as db:
        row = await one(db, "SELECT * FROM bot_billing")
        assert row["status"] == "canceled" and not billing.entitled(row)
        assert (await one(db, "SELECT processed_at FROM billing_events"))["processed_at"] is not None


@pytest.mark.usefixtures("database")
async def test_billing_tenant_csrf_and_redirect_cannot_grant_access(provider):
    bot = await seed()
    async with webclient("attacker@example.com") as c:
        assert (await c.get(f"/api/bots/{bot['id']}/billing")).status_code == 404
        assert (await c.post(f"/api/bots/{bot['id']}/billing/portal")).status_code == 404
    async with webclient() as c:
        assert (
            await c.post(
                f"/api/bots/{bot['id']}/billing/checkout", headers={"Origin": "https://evil.example"}
            )
        ).status_code == 403
        assert not (await c.get(f"/api/bots/{bot['id']}/billing?session_id=forged")).json()["active"]
        provider.v1.subscriptions.list_async.return_value = {"data": [subscription(bot, provider)]}
        assert (await c.delete(f"/api/bots/{bot['id']}")).status_code == 409


def test_entitlement_fails_closed():
    assert not billing.entitled(None)
    for status in ["trialing", "unpaid", "incomplete", "paused", "canceled", "invalid"]:
        assert not billing.entitled(
            {"status": status, "paid_until": datetime.now(timezone.utc) + timedelta(days=1)}
        )


async def test_catalog_rejects_wrong_price_and_portal_quantity_changes(provider):
    provider.v1.prices.retrieve_async.return_value["unit_amount"] = 399
    with pytest.raises(billing.BillingContractError, match="PRICE_CONTRACT"):
        await billing.validate_catalog()
    provider.v1.prices.retrieve_async.return_value["unit_amount"] = 39900
    provider.v1.billing_portal.configurations.retrieve_async.return_value["features"]["subscription_update"][
        "enabled"
    ] = True
    with pytest.raises(billing.BillingContractError, match="PORTAL_CONTRACT"):
        await billing.validate_catalog()


@pytest.mark.usefixtures("database")
async def test_paid_invoice_never_grants_unpaid_future_period(provider):
    bot = await seed()
    sub = subscription(bot, provider)
    sub["items"]["data"][0]["current_period_end"] = int(time.time()) + 90 * 86400
    async with transaction() as db:
        row = await billing.locked_row(db, bot["id"])
        row = await billing.apply_subscription(db, row, sub)
    assert row["paid_until"] < datetime.now(timezone.utc) + timedelta(days=2)


@pytest.mark.usefixtures("database")
async def test_signed_foreign_mode_and_customer_never_affect_tenant(provider):
    await seed()
    event = {
        "id": "evt_other",
        "type": "invoice.paid",
        "livemode": True,
        "data": {"object": {"customer": "cus_unit"}},
    }
    payload, signature = signed(event)
    with pytest.raises(HTTPException) as exc:
        await billing.receive_event(payload, signature)
    assert exc.value.status_code == 400
    event["livemode"] = False
    event["data"]["object"]["customer"] = "cus_other_project"
    await billing.receive_event(*signed(event))
    async with transaction() as db:
        assert (await one(db, "SELECT count(*) AS n FROM billing_events"))["n"] == 0
