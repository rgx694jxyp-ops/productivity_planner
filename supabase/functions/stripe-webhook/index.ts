// Stripe Webhook Handler — Supabase Edge Function
// Handles subscription lifecycle events from Stripe
//
// Deploy: supabase functions deploy stripe-webhook
// Set secrets:
//   supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_xxx
//   supabase secrets set STRIPE_SECRET_KEY=sk_xxx

import { createClient } from "npm:@supabase/supabase-js@2";

const STRIPE_WEBHOOK_SECRET = Deno.env.get("STRIPE_WEBHOOK_SECRET")!;
const STRIPE_SECRET_KEY = Deno.env.get("STRIPE_SECRET_KEY")!;
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY =
  Deno.env.get("SERVICE_ROLE_KEY") ||
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";

// Plan metadata mapping
const PLAN_LIMITS: Record<string, number> = {
  starter: 25,
  pro: 100,
  business: -1, // unlimited
};

// Price ID → plan name mapping (set via: supabase secrets set STRIPE_PRICE_STARTER=price_xxx etc.)
const PRICE_PLAN_MAP: Record<string, string> = {};
const _ps = Deno.env.get("STRIPE_PRICE_STARTER");
const _pp = Deno.env.get("STRIPE_PRICE_PRO");
const _pb = Deno.env.get("STRIPE_PRICE_BUSINESS");
if (_ps) PRICE_PLAN_MAP[_ps] = "starter";
if (_pp) PRICE_PLAN_MAP[_pp] = "pro";
if (_pb) PRICE_PLAN_MAP[_pb] = "business";

function resolvePlan(sub: any): string {
  // 1. Subscription-level metadata
  const metaPlan = sub.metadata?.plan?.toLowerCase?.();
  if (metaPlan && PLAN_LIMITS[metaPlan] !== undefined) return metaPlan;
  // 2. Price-level metadata
  const priceMetaPlan = sub.items?.data?.[0]?.price?.metadata?.plan?.toLowerCase?.();
  if (priceMetaPlan && PLAN_LIMITS[priceMetaPlan] !== undefined) return priceMetaPlan;
  // 3. Match price ID against known secrets
  const priceId = sub.items?.data?.[0]?.price?.id;
  if (priceId && PRICE_PLAN_MAP[priceId]) return PRICE_PLAN_MAP[priceId];
  return "starter";
}

async function verifyStripeSignature(
  body: string,
  signature: string
): Promise<any> {
  // Stripe signature verification using Web Crypto API.
  // Supports multiple v1 signatures and a safer timestamp tolerance.
  const encoder = new TextEncoder();
  const parts = signature
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);
  const timestamp = parts.find((p) => p.startsWith("t="))?.split("=")[1];
  const v1Sigs = parts
    .filter((p) => p.startsWith("v1="))
    .map((p) => p.split("=")[1])
    .filter(Boolean) as string[];

  if (!timestamp || v1Sigs.length === 0) {
    throw new Error("Invalid signature format");
  }

  const payload = `${timestamp}.${body}`;
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(STRIPE_WEBHOOK_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const expected = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  const expectedHex = Array.from(new Uint8Array(expected))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  const sigMatch = v1Sigs.some((candidate) => candidate === expectedHex);
  if (!sigMatch) throw new Error("Signature mismatch");

  // Check timestamp tolerance. Keep strict, but allow mild clock skew.
  // Stripe default tolerance is 5 minutes; 10 minutes is more resilient in
  // edge environments with occasional clock/network drift.
  const now = Math.floor(Date.now() / 1000);
  const ts = parseInt(timestamp, 10);
  if (!Number.isFinite(ts)) throw new Error("Invalid signature timestamp");
  if (Math.abs(now - ts) > 600) throw new Error("Timestamp outside tolerance");

  return JSON.parse(body);
}

async function getSubscriptionDetails(subscriptionId: string) {
  const resp = await fetch(
    `https://api.stripe.com/v1/subscriptions/${subscriptionId}`,
    {
      headers: { Authorization: `Bearer ${STRIPE_SECRET_KEY}` },
    }
  );
  return resp.json();
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const body = await req.text();
  const signature = req.headers.get("stripe-signature") || "";

  let event: any;
  try {
    event = await verifyStripeSignature(body, signature);
  } catch (err) {
    console.error("Signature verification failed:", err);
    return new Response(`Webhook Error: ${err.message}`, { status: 400 });
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const session = event.data.object;
        const tenantId =
          session.metadata?.tenant_id ||
          session.subscription_details?.metadata?.tenant_id ||
          session.client_reference_id;
        const userId =
          session.metadata?.user_id ||
          session.subscription_details?.metadata?.user_id ||
          session.client_reference_id ||
          null;
        const customerId = session.customer;
        const subscriptionId = session.subscription;

        if (!tenantId || !subscriptionId) {
          console.error("Missing tenant or subscription ID in checkout.session.completed", {
            tenantId,
            userId,
            subscriptionId,
          });
          break;
        }

        // Fetch full subscription from Stripe
        const sub = await getSubscriptionDetails(subscriptionId);
        const plan = resolvePlan(sub);
        const limit = PLAN_LIMITS[plan] ?? 25;

        // Upsert subscription
        await supabase.from("subscriptions").upsert(
          {
            tenant_id: tenantId,
            stripe_customer_id: customerId,
            stripe_subscription_id: subscriptionId,
            plan: plan,
            status: "active",
            employee_limit: limit,
            current_period_end: new Date(sub.current_period_end * 1000).toISOString(),
            cancel_at_period_end: sub.cancel_at_period_end || false,
            updated_at: new Date().toISOString(),
          },
          { onConflict: "tenant_id" }
        );

        if (userId) {
          await supabase
            .from("subscriptions")
            .update({ user_id: userId, updated_at: new Date().toISOString() })
            .eq("tenant_id", tenantId);
        }

        // Also store customer ID on tenants table
        await supabase
          .from("tenants")
          .update({ stripe_customer_id: customerId })
          .eq("id", tenantId);

        console.log(`Subscription activated for tenant ${tenantId}, plan: ${plan}`);
        break;
      }

      case "customer.subscription.created":
      case "customer.subscription.updated": {
        const sub = event.data.object;
        const customerId = sub.customer;
        let plan = resolvePlan(sub);
        let limit = PLAN_LIMITS[plan] ?? 25;

        // Find tenant by stripe_customer_id
        const { data: tenants } = await supabase
          .from("tenants")
          .select("id")
          .eq("stripe_customer_id", customerId)
          .limit(1);

        if (!tenants?.length) {
          console.error(`No tenant found for Stripe customer ${customerId}`);
          break;
        }

        const tenantId = tenants[0].id;

        // If Stripe has a pending update (common for end-of-period downgrades),
        // keep current access until the cycle actually flips.
        const hasPendingUpdate = !!sub.pending_update;
        if (hasPendingUpdate) {
          const { data: curRows } = await supabase
            .from("subscriptions")
            .select("plan, employee_limit")
            .eq("tenant_id", tenantId)
            .limit(1);
          if (curRows?.length) {
            const currentPlan = curRows[0].plan;
            const currentLimit = curRows[0].employee_limit;
            if (currentPlan) plan = currentPlan;
            if (typeof currentLimit === "number") limit = currentLimit;
          }
        }

        await supabase
          .from("subscriptions")
          .update({
            plan: plan,
            status: sub.status, // active, past_due, canceled, etc.
            employee_limit: limit,
            current_period_end: new Date(sub.current_period_end * 1000).toISOString(),
            cancel_at_period_end: sub.cancel_at_period_end || false,
            stripe_subscription_id: sub.id,
            updated_at: new Date().toISOString(),
          })
          .eq("tenant_id", tenantId);

        console.log(`Subscription updated for tenant ${tenantId}: ${sub.status}, plan: ${plan}, pending=${hasPendingUpdate}`);
        break;
      }

      case "customer.subscription.deleted": {
        const sub = event.data.object;
        const customerId = sub.customer;

        const { data: tenants } = await supabase
          .from("tenants")
          .select("id")
          .eq("stripe_customer_id", customerId)
          .limit(1);

        if (tenants?.length) {
          await supabase
            .from("subscriptions")
            .update({
              status: "canceled",
              updated_at: new Date().toISOString(),
            })
            .eq("tenant_id", tenants[0].id);

          console.log(`Subscription canceled for tenant ${tenants[0].id}`);
        }
        break;
      }

      case "invoice.payment_failed": {
        const invoice = event.data.object;
        const customerId = invoice.customer;

        const { data: tenants } = await supabase
          .from("tenants")
          .select("id")
          .eq("stripe_customer_id", customerId)
          .limit(1);

        if (tenants?.length) {
          await supabase
            .from("subscriptions")
            .update({
              status: "past_due",
              updated_at: new Date().toISOString(),
            })
            .eq("tenant_id", tenants[0].id);

          console.log(`Payment failed for tenant ${tenants[0].id}`);
        }
        break;
      }

      // Renewal succeeded — refresh period end and ensure status is active.
      case "invoice.paid": {
        const invoice = event.data.object;
        if (invoice.billing_reason === "subscription_create") break; // already handled by checkout.session.completed
        const customerId = invoice.customer;
        const subscriptionId = invoice.subscription;
        if (!subscriptionId) break;

        const { data: tenants } = await supabase
          .from("tenants")
          .select("id")
          .eq("stripe_customer_id", customerId)
          .limit(1);

        if (tenants?.length) {
          const renewedSub = await getSubscriptionDetails(subscriptionId);
          const plan = resolvePlan(renewedSub);
          const limit = PLAN_LIMITS[plan] ?? 25;
          await supabase
            .from("subscriptions")
            .update({
              status: "active",
              plan: plan,
              employee_limit: limit,
              current_period_end: new Date(renewedSub.current_period_end * 1000).toISOString(),
              cancel_at_period_end: renewedSub.cancel_at_period_end || false,
              updated_at: new Date().toISOString(),
            })
            .eq("tenant_id", tenants[0].id);

          console.log(`Renewal synced for tenant ${tenants[0].id}, plan: ${plan}`);
        }
        break;
      }

      // 3DS / SCA authentication required — card needs action before subscription activates.
      case "invoice.payment_action_required": {
        const invoice = event.data.object;
        const customerId = invoice.customer;

        const { data: tenants } = await supabase
          .from("tenants")
          .select("id")
          .eq("stripe_customer_id", customerId)
          .limit(1);

        if (tenants?.length) {
          await supabase
            .from("subscriptions")
            .update({
              status: "incomplete",
              updated_at: new Date().toISOString(),
            })
            .eq("tenant_id", tenants[0].id);

          console.log(`Payment action required for tenant ${tenants[0].id}`);
        }
        break;
      }

      default:
        console.log(`Unhandled event type: ${event.type}`);
    }
  } catch (err) {
    console.error("Error processing webhook:", err);
    return new Response(`Webhook handler error: ${err.message}`, { status: 500 });
  }

  return new Response(JSON.stringify({ received: true }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});

