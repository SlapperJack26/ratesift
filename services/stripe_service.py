"""
Stripe Billing & Subscription Management Service for Quotelytics Inc.
Supports Canadian CAD pricing, B2B tax ID collection, Stripe Customer Portal,
signed webhook processing, and graceful zero-configuration local test mode.
"""
import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional
import uuid

logger = logging.getLogger(__name__)

# Plan Catalog (CAD) matching GTM §4.3
PLANS = {
    "PRO": {
        "id": "PRO",
        "name": "Broker Pro",
        "amount_cad": 79.0,
        "amount_cents": 7900,
        "max_sheets": 10,
        "max_quotes_per_month": 2500,
        "seats": 1,
    },
    "TEAM": {
        "id": "TEAM",
        "name": "Broker Team",
        "amount_cad": 199.0,
        "amount_cents": 19900,
        "max_sheets": -1,
        "max_quotes_per_month": 15000,
        "seats": 5,
        "seat_addon_cad": 25.0,
    },
    "BUSINESS": {
        "id": "BUSINESS",
        "name": "Business / Enterprise",
        "amount_cad": -1.0,
        "max_sheets": -1,
        "max_quotes_per_month": -1,
        "seats": -1,
    }
}

# Promotional Coupons & Founding Beta Discounts (CAD)
PROMO_COUPONS = {
    "BETA50": {
        "code": "BETA50",
        "percent_off": 50.0,
        "duration": "repeating",
        "duration_in_months": 12,
        "description": "Founding Beta Cohort Reward — 50% Off for 12 Months",
    },
    "FOUNDING25": {
        "code": "FOUNDING25",
        "percent_off": 30.0,
        "duration": "repeating",
        "duration_in_months": 12,
        "description": "Founding 25 Brokerage Partner — 30% Off for 12 Months",
    },
}


def _get_base_url() -> str:
    from services.email_service import get_base_url
    return get_base_url()


def is_stripe_configured() -> bool:
    """Returns True only when a valid, non-mock Stripe secret key is present in environment."""
    key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    return bool(key and not key.startswith("mock_") and key.startswith("sk_"))


def create_checkout_session(
    user_id: str,
    email: str,
    plan: str,
    interval: str = "month",
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
    promo_code: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a Stripe Checkout Session for subscription checkout.
    Supports optional promotional codes (BETA50, FOUNDING25) and customer-entered promotion codes.
    When running in test/mock mode without live keys, returns a functional mock session URL.
    """
    target_plan = (plan or "PRO").strip().upper()
    if target_plan not in ("PRO", "TEAM"):
        raise ValueError(f"Invalid subscription plan '{plan}'. Must be 'PRO' or 'TEAM'.")

    coupon_info = None
    if promo_code and str(promo_code).strip():
        clean_code = str(promo_code).strip().upper()
        if clean_code not in PROMO_COUPONS:
            raise ValueError(f"Invalid or expired promotional code '{promo_code}'.")
        coupon_info = PROMO_COUPONS[clean_code]

    plan_info = PLANS[target_plan]
    base_amount_cad = plan_info["amount_cad"]
    discounted_amount_cad = (
        round(base_amount_cad * (1.0 - coupon_info["percent_off"] / 100.0), 2)
        if coupon_info
        else base_amount_cad
    )

    base_url = _get_base_url()
    effective_success = success_url or f"{base_url}/console/account?billing=success&plan={target_plan}"
    effective_cancel = cancel_url or f"{base_url}/pricing?billing=canceled"

    # 1. Real Stripe API Path
    if is_stripe_configured():
        try:
            import stripe
            stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

            price_id_env = os.getenv(f"STRIPE_{target_plan}_PRICE_ID", "").strip()
            line_items = []
            if price_id_env:
                line_items.append({"price": price_id_env, "quantity": 1})
            else:
                # Dynamic line item fallback in test mode
                line_items.append({
                    "price_data": {
                        "currency": "cad",
                        "product_data": {
                            "name": f"Quotelytics {plan_info['name']}",
                            "description": f"{plan_info['max_sheets']} sheets, {plan_info['max_quotes_per_month']} quotes/mo",
                        },
                        "unit_amount": plan_info["amount_cents"],
                        "recurring": {"interval": interval.lower()},
                    },
                    "quantity": 1,
                })

            metadata = {"user_id": user_id, "plan": target_plan}
            session_kwargs: Dict[str, Any] = {
                "mode": "subscription",
                "customer_email": email,
                "line_items": line_items,
                "client_reference_id": user_id,
                "metadata": metadata,
                "automatic_tax": {"enabled": True},
                "tax_id_collection": {"enabled": True},
                "success_url": effective_success + "&session_id={CHECKOUT_SESSION_ID}",
                "cancel_url": effective_cancel,
            }

            if coupon_info:
                metadata["promo_code"] = coupon_info["code"]
                metadata["percent_off"] = str(coupon_info["percent_off"])
                coupon_env_id = os.getenv(f"STRIPE_COUPON_{coupon_info['code']}", coupon_info["code"]).strip()
                session_kwargs["discounts"] = [{"coupon": coupon_env_id}]
            else:
                session_kwargs["allow_promotion_codes"] = True

            session = stripe.checkout.Session.create(**session_kwargs)
            return {
                "checkout_url": session.url,
                "session_id": session.id,
                "plan": target_plan,
                "promo_code": coupon_info["code"] if coupon_info else None,
                "percent_off": coupon_info["percent_off"] if coupon_info else 0.0,
                "effective_monthly_cad": discounted_amount_cad,
                "mode": "stripe",
            }
        except Exception as exc:
            logger.error(f"Stripe checkout creation error: {exc}")
            raise

    # 2. Local Development / $0 Mock Mode Path
    mock_session_id = f"mock_cs_{uuid.uuid4().hex[:16]}"
    promo_suffix = f"&promo={coupon_info['code']}" if coupon_info else ""
    mock_url = f"{effective_success}{promo_suffix}&session_id={mock_session_id}"
    return {
        "checkout_url": mock_url,
        "session_id": mock_session_id,
        "plan": target_plan,
        "promo_code": coupon_info["code"] if coupon_info else None,
        "percent_off": coupon_info["percent_off"] if coupon_info else 0.0,
        "effective_monthly_cad": discounted_amount_cad,
        "mode": "mock",
        "message": "Stripe mock test checkout initialized."
    }


def create_customer_portal_session(user_id: str, return_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Creates a Stripe Customer Portal session URL for managing cards, invoices, and cancellations.
    """
    from services.db_service import get_user_billing_info
    billing = get_user_billing_info(user_id)
    cust_id = billing.get("stripe_customer_id")

    base_url = _get_base_url()
    effective_return = return_url or f"{base_url}/console/account"

    if is_stripe_configured() and cust_id:
        try:
            import stripe
            stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
            session = stripe.billing_portal.Session.create(
                customer=cust_id,
                return_url=effective_return,
            )
            return {"portal_url": session.url, "mode": "stripe"}
        except Exception as exc:
            logger.error(f"Stripe portal session creation error: {exc}")
            raise

    # Local Mock Mode
    return {
        "portal_url": f"{effective_return}?portal=mock_active",
        "mode": "mock",
        "message": "Mock billing portal active."
    }


def process_stripe_webhook(payload_bytes: bytes, sig_header: Optional[str] = None) -> Dict[str, Any]:
    """
    Parses and verifies raw webhook payload, executing plan changes and recording subscription status.
    """
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

    event = None
    if webhook_secret and sig_header and is_stripe_configured():
        import stripe
        try:
            event = stripe.Webhook.construct_event(payload_bytes, sig_header, webhook_secret)
        except Exception as exc:
            logger.error(f"Stripe webhook signature verification failed: {exc}")
            raise ValueError(f"Webhook signature verification failed: {exc}")
    else:
        # Development / test unverified payload parse
        try:
            event = json.loads(payload_bytes.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"Invalid JSON webhook payload: {exc}")

    event_type = event.get("type", "")
    data_obj = event.get("data", {}).get("object", {})

    from services.db_service import (
        update_user_billing_subscription,
        get_user_by_stripe_customer_id,
    )

    handled = False
    details = {}

    if event_type == "checkout.session.completed":
        # Subscription purchased via hosted checkout
        user_id = data_obj.get("client_reference_id") or data_obj.get("metadata", {}).get("user_id")
        plan = data_obj.get("metadata", {}).get("plan", "PRO")
        cust_id = data_obj.get("customer")
        sub_id = data_obj.get("subscription")

        if user_id:
            update_user_billing_subscription(
                user_id=user_id,
                plan=plan,
                stripe_customer_id=cust_id,
                stripe_subscription_id=sub_id,
                subscription_status="active",
                cancel_at_period_end=0,
            )
            handled = True
            details = {"user_id": user_id, "plan": plan, "action": "activated"}

    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        cust_id = data_obj.get("customer")
        sub_id = data_obj.get("id")
        status = data_obj.get("status", "active")
        cancel_at_period_end = 1 if data_obj.get("cancel_at_period_end") else 0
        current_period_end_ts = data_obj.get("current_period_end")
        period_end_iso = (
            datetime.utcfromtimestamp(current_period_end_ts).isoformat() + "Z"
            if current_period_end_ts
            else None
        )

        user = get_user_by_stripe_customer_id(cust_id)
        if user:
            # Check metadata for plan upgrade/downgrade
            meta_plan = data_obj.get("metadata", {}).get("plan")
            update_user_billing_subscription(
                user_id=user["id"],
                plan=meta_plan,
                stripe_subscription_id=sub_id,
                subscription_status=status,
                current_period_end=period_end_iso,
                cancel_at_period_end=cancel_at_period_end,
            )
            handled = True
            details = {"user_id": user["id"], "status": status, "action": "updated"}

    elif event_type == "customer.subscription.deleted":
        # Subscription ended or cancelled -> downgrade to FREE (no data deleted per GTM Rule)
        cust_id = data_obj.get("customer")
        user = get_user_by_stripe_customer_id(cust_id)
        if user:
            update_user_billing_subscription(
                user_id=user["id"],
                plan="FREE",
                subscription_status="canceled",
                cancel_at_period_end=0,
            )
            handled = True
            details = {"user_id": user["id"], "action": "downgraded_to_free"}

    elif event_type == "invoice.payment_failed":
        # Payment failure -> mark past_due for 7-day grace period
        cust_id = data_obj.get("customer")
        user = get_user_by_stripe_customer_id(cust_id)
        if user:
            update_user_billing_subscription(
                user_id=user["id"],
                subscription_status="past_due",
            )
            handled = True
            details = {"user_id": user["id"], "action": "grace_period_marked_past_due"}

    elif event_type == "invoice.paid":
        cust_id = data_obj.get("customer")
        user = get_user_by_stripe_customer_id(cust_id)
        if user:
            update_user_billing_subscription(
                user_id=user["id"],
                subscription_status="active",
            )
            handled = True
            details = {"user_id": user["id"], "action": "invoice_paid_active"}

    return {
        "status": "success",
        "event_id": event.get("id"),
        "event_type": event_type,
        "handled": handled,
        "details": details,
    }
