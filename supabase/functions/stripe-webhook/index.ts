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

function resolvePendingPlan(sub: any): string {
  const pendingItem = sub.pending_update?.subscription_items?.[0];
  const pendingPrice = pendingItem?.price;
  const pendingPriceMetaPlan =
    typeof pendingPrice === "object"
      ? pendingPrice?.metadata?.plan?.toLowerCase?.()
      : "";
  if (pendingPriceMetaPlan && PLAN_LIMITS[pendingPriceMetaPlan] !== undefined) {
    return pendingPriceMetaPlan;
  }

  const pendingPriceId =
    typeof pendingPrice === "string" ? pendingPrice : pendingPrice?.id;
  if (pendingPriceId && PRICE_PLAN_MAP[pendingPriceId]) {
    return PRICE_PLAN_MAP[pendingPriceId];
  }
  return "";
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

// Stripe moved current_period_end to items.data[0] in newer API versions.
// Fall back gracefully between both locations.
function getPeriodEnd(sub: any): string | null {
  const ts =
    sub.current_period_end ||
    sub.items?.data?.[0]?.current_period_end ||
    null;
  if (!ts || !Number.isFinite(Number(ts))) return null;
  return new Date(Number(ts) * 1000).toISOString();
}

function getPeriodStart(sub: any): string | null {
  const ts =
    sub.current_period_start ||
    sub.items?.data?.[0]?.current_period_start ||
    null;
  if (!ts || !Number.isFinite(Number(ts))) return null;
  return new Date(Number(ts) * 1000).toISOString();
}

function hasPendingChangeElapsed(pendingChangeAt: string | null): boolean {
  if (!pendingChangeAt) return false;
  const pendingTs = Date.parse(pendingChangeAt);
  return Number.isFinite(pendingTs) && Date.now() >= pendingTs;
}

// Log a Stripe event to subscription_events for debugging.
// Wrapped in try/catch so a missing table never breaks the main webhook flow.
async function logSubscriptionEvent(
  supabase: any,
  tenantId: string | null,
  eventType: string,
  rawObj: any
): Promise<void> {
  try {
    await supabase.from("subscription_events").insert({
      tenant_id: tenantId || null,
      event_type: eventType,
      raw_json: rawObj ?? null,
    });
  } catch (_) {
    // Non-fatal — never block webhook response
  }
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

  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false },
  });

  try {
    console.log(`Processing event: ${event.type}, supa_url=${SUPABASE_URL?.slice(0, 30)}, key_len=${SUPABASE_SERVICE_ROLE_KEY?.length}`);
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

        // Upsert subscription — omit user_id from webhook write to avoid FK constraint
        // violations (the userId comes from session metadata, not guaranteed to be a
        // confirmed auth.users row at webhook time). The RLS SELECT policy uses
        // tenant_id via user_profiles as the primary lookup anyway.
        const upsertRow: Record<string, unknown> = {
          tenant_id: tenantId,
          stripe_customer_id: customerId,
          stripe_subscription_id: subscriptionId,
          plan: plan,
          status: "active",
          employee_limit: limit,
          current_period_start: getPeriodStart(sub),
          current_period_end: getPeriodEnd(sub),
          cancel_at_period_end: sub.cancel_at_period_end || false,
          pending_plan: null,
          pending_change_at: null,
          updated_at: new Date().toISOString(),
        };

        const { error: upsertErr } = await supabase.from("subscriptions").upsert(
          upsertRow,
          { onConflict: "tenant_id" }
        );
        if (upsertErr) throw new Error(`subscriptions upsert failed: ${upsertErr.message} (code=${upsertErr.code})`);
        console.log(`Upsert OK for tenant ${tenantId}, plan: ${plan}`);

        // Also store customer ID on tenants table
        await supabase
          .from("tenants")
          .update({ stripe_customer_id: customerId })
          .eq("id", tenantId);

        await logSubscriptionEvent(supabase, tenantId, event.type, event.data.object);
        console.log(`Subscription activated for tenant ${tenantId}, plan: ${plan}`);
        break;
      }

      case "customer.subscription.created":
      case "customer.subscription.updated": {
        const sub = event.data.object;
        const customerId = sub.customer;
        let plan = resolvePlan(sub);
        let limit = PLAN_LIMITS[plan] ?? 25;

        // Find tenant by stripe_customer_id (primary path)
        const { data: tenants } = await supabase
          .from("tenants")
          .select("id")
          .eq("stripe_customer_id", customerId)
          .limit(1);

        let tenantId = tenants?.length ? tenants[0].id : null;

        // Fallback: recover tenant from Stripe metadata if customer lookup fails.
        // This covers cases where checkout completed but tenants.stripe_customer_id
        // was not yet backfilled at the moment this event arrived.
        if (!tenantId) {
          tenantId =
            sub.metadata?.tenant_id ||
            sub.items?.data?.[0]?.metadata?.tenant_id ||
            null;
          if (!tenantId) {
            console.error(`No tenant found for Stripe customer ${customerId} and no tenant_id metadata on subscription ${sub.id}`);
            break;
          }

          // Self-heal: backfill customer id on tenant for future events.
          await supabase
            .from("tenants")
            .update({ stripe_customer_id: customerId })
            .eq("id", tenantId);
        }

        // If Stripe has a pending update (common for end-of-period downgrades),
        // keep current access until pending_change_at passes.
        const hasPendingUpdate = !!sub.pending_update;
        const pendingPlanFromStripe = resolvePendingPlan(sub);
        let pendingPlan: string | null = null;
        let pendingChangeAt: string | null = null;

        const { data: curRows } = await supabase
          .from("subscriptions")
          .select("plan, employee_limit, pending_plan, pending_change_at")
          .eq("tenant_id", tenantId)
          .limit(1);
        const existing = curRows?.[0] || null;
        const existingPendingPlan = existing?.pending_plan || null;
        const existingPendingChangeAt = existing?.pending_change_at || null;

        if (existingPendingPlan && !hasPendingChangeElapsed(existingPendingChangeAt)) {
          if (existing?.plan) plan = existing.plan;
          if (typeof existing?.employee_limit === "number") limit = existing.employee_limit;
          pendingPlan = existingPendingPlan;
          pendingChangeAt = existingPendingChangeAt;
        } else if (hasPendingUpdate) {
          pendingPlan = pendingPlanFromStripe || existingPendingPlan || null;
          pendingChangeAt = getPeriodEnd(sub) || existingPendingChangeAt;
        }

        const upsertRow: Record<string, unknown> = {
          tenant_id: tenantId,
          stripe_customer_id: customerId,
          stripe_subscription_id: sub.id,
          plan: plan,
          status: sub.status,
          employee_limit: limit,
          current_period_start: getPeriodStart(sub),
          current_period_end: getPeriodEnd(sub),
          cancel_at_period_end: sub.cancel_at_period_end || false,
          pending_plan: pendingPlan,
          pending_change_at: pendingChangeAt,
          updated_at: new Date().toISOString(),
        };

        const { error: upsertErr } = await supabase
          .from("subscriptions")
          .upsert(upsertRow, { onConflict: "tenant_id" });
        if (upsertErr) {
          throw new Error(`subscriptions upsert (customer.subscription.*) failed: ${upsertErr.message} (code=${upsertErr.code})`);
        }

        await logSubscriptionEvent(supabase, tenantId, event.type, event.data.object);
        console.log(`Subscription updated for tenant ${tenantId}: ${sub.status}, plan: ${plan}, pending=${pendingPlan || "none"}`);
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
              pending_plan: null,
              pending_change_at: null,
              updated_at: new Date().toISOString(),
            })
            .eq("tenant_id", tenants[0].id);

          await logSubscriptionEvent(supabase, tenants[0].id, event.type, event.data.object);
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

          await logSubscriptionEvent(supabase, tenants[0].id, event.type, event.data.object);
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
              current_period_start: getPeriodStart(renewedSub),
              current_period_end: getPeriodEnd(renewedSub),
              cancel_at_period_end: renewedSub.cancel_at_period_end || false,
              pending_plan: null,
              pending_change_at: null,
              updated_at: new Date().toISOString(),
            })
            .eq("tenant_id", tenants[0].id);

          await logSubscriptionEvent(supabase, tenants[0].id, event.type, event.data.object);
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

