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
  const metaPending = sub.metadata?.pending_plan?.toLowerCase?.();
  if (metaPending && PLAN_LIMITS[metaPending] !== undefined) {
    return metaPending;
  }

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

function resolvePendingChangeAt(sub: any): string | null {
  const metaTs = sub.metadata?.pending_change_at;
  if (metaTs && typeof metaTs === "string") {
    const parsed = Date.parse(metaTs);
    if (Number.isFinite(parsed)) return new Date(parsed).toISOString();
  }
  return getPeriodEnd(sub);
}

// Resolve a pending plan change from a Stripe subscription schedule.
// Stripe portal-initiated downgrades attach a schedule to the subscription
// rather than setting pending_update, so we must read the schedule phases.
async function resolvePendingPlanFromSchedule(
  sub: any
): Promise<{ plan: string; changeAt: string | null } | null> {
  const scheduleId = typeof sub.schedule === "string" ? sub.schedule : null;
  if (!scheduleId) return null;
  try {
    const resp = await fetch(
      `https://api.stripe.com/v1/subscription_schedules/${scheduleId}`,
      { headers: { Authorization: `Bearer ${STRIPE_SECRET_KEY}` } }
    );
    if (!resp.ok) return null;
    const schedule = await resp.json();
    if (schedule.status !== "active") return null;
    const phases: any[] = schedule.phases || [];
    if (phases.length < 2) return null;
    // Find the phase that contains now, then take the next phase.
    const now = Math.floor(Date.now() / 1000);
    const currentIdx = phases.reduce(
      (best: number, p: any, i: number) =>
        (p.start_date || 0) <= now ? i : best,
      -1
    );
    if (currentIdx === -1 || currentIdx >= phases.length - 1) return null;
    const nextPhase = phases[currentIdx + 1];
    const rawPrice = nextPhase.items?.[0]?.price;
    const resolvedPriceId =
      typeof rawPrice === "string" ? rawPrice : rawPrice?.id ?? null;
    const changeAt = nextPhase.start_date
      ? new Date(Number(nextPhase.start_date) * 1000).toISOString()
      : null;
    if (!resolvedPriceId) return null;
    const plan = PRICE_PLAN_MAP[resolvedPriceId] || "";
    if (!plan) return null;
    return { plan, changeAt };
  } catch {
    return null;
  }
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
    const { error } = await supabase.from("subscription_events").insert({
      tenant_id: tenantId || null,
      event_type: eventType,
      raw_json: rawObj ?? null,
    });
    if (error) {
      console.error("Failed to insert subscription event", {
        tenantId,
        eventType,
        error: error.message,
        code: error.code,
      });
    }
  } catch (err) {
    console.error("Exception during subscription event insert", {
      tenantId,
      eventType,
      error: err?.message || err,
    });
  }
}

// Helper to build the full mirrored subscription row
function buildSubscriptionRow(sub: any, tenantId: string, customerId: string, existing?: any) {
  let currentPlan = resolvePlan(sub);
  let currentLimit = PLAN_LIMITS[currentPlan] ?? 25;

  let pendingPlan: string | null = null;
  let pendingChangeAt: string | null = null;

  // Handle pending update (Stripe's pending_update or metadata)
  if (sub.pending_update?.subscription_items?.[0]?.price?.id) {
    const pendingPriceId = sub.pending_update.subscription_items[0].price.id;
    pendingPlan = PRICE_PLAN_MAP[pendingPriceId] || null;
    const expiresAt = sub.pending_update.expires_at;
    pendingChangeAt = expiresAt ? new Date(expiresAt * 1000).toISOString() : null;
  } else if (sub.metadata?.pending_plan) {
    pendingPlan = sub.metadata.pending_plan;
    pendingChangeAt = resolvePendingChangeAt(sub);
  }

  // Portal-initiated downgrade via schedule
  // (This is handled in the event handler, but can be added here if needed)

  // Preserve current access until the pending change applies
  if (pendingPlan && existing?.plan && pendingChangeAt && !hasPendingChangeElapsed(pendingChangeAt)) {
    currentPlan = existing.plan;
    currentLimit = existing.employee_limit;
  }

  // Always clear pending fields if not present
  if (!pendingPlan) pendingPlan = null;
  if (!pendingChangeAt) pendingChangeAt = null;

  return {
    tenant_id: tenantId,
    stripe_customer_id: customerId,
    stripe_subscription_id: sub.id,
    plan: currentPlan,
    status: sub.status,
    employee_limit: currentLimit,
    current_period_start: getPeriodStart(sub),
    current_period_end: getPeriodEnd(sub),
    cancel_at_period_end: !!sub.cancel_at_period_end,
    pending_plan: pendingPlan,
    pending_change_at: pendingChangeAt,
    updated_at: new Date().toISOString(),
  };
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

  // Webhook idempotency: insert event_id, return early if duplicate
  const { error: eventInsertErr } = await supabase
    .from("stripe_webhook_events")
    .insert({
      event_id: event.id,
      event_type: event.type,
    });
  if (eventInsertErr) {
    if (eventInsertErr.code === "23505") {
      return new Response(JSON.stringify({ received: true, duplicate: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    throw new Error(`event log insert failed: ${eventInsertErr.message}`);
  }

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
        // Read existing row (if any)
        const { data: existingRows } = await supabase
          .from("subscriptions")
          .select("plan, employee_limit, pending_plan, pending_change_at, updated_at")
          .eq("tenant_id", tenantId)
          .limit(1);
        const existing = existingRows?.[0] || null;
        const upsertRow = buildSubscriptionRow(sub, tenantId, customerId, existing);

        const { error: upsertErr } = await supabase.from("subscriptions").upsert(
          upsertRow,
          { onConflict: "tenant_id" }
        );
        if (upsertErr) throw new Error(`subscriptions upsert failed: ${upsertErr.message} (code=${upsertErr.code})`);
        console.log(`Upsert OK for tenant ${tenantId}, plan: ${upsertRow.plan}`);

        // Also store customer ID on tenants table
        await supabase
          .from("tenants")
          .update({ stripe_customer_id: customerId })
          .eq("id", tenantId);

        await logSubscriptionEvent(supabase, tenantId, event.type, event.data.object);
        console.log(`Subscription activated for tenant ${tenantId}, plan: ${upsertRow.plan}`);
        break;
      }

      case "customer.subscription.created":
      case "customer.subscription.updated": {
        const sub = event.data.object;
        const customerId = sub.customer;
        // Find tenant by stripe_customer_id (primary path)
        const { data: tenants } = await supabase
          .from("tenants")
          .select("id")
          .eq("stripe_customer_id", customerId)
          .limit(1);

        let tenantId = tenants?.length ? tenants[0].id : null;

        // Fallback: recover tenant from Stripe metadata if customer lookup fails.
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

        // Read existing row before upsert
        const { data: existingRows } = await supabase
          .from("subscriptions")
          .select("plan, employee_limit, pending_plan, pending_change_at, updated_at")
          .eq("tenant_id", tenantId)
          .limit(1);
        const existing = existingRows?.[0] || null;

        // If no pending_update/metadata, check for schedule-based downgrade
        let upsertRow;
        if (!sub.pending_update && !sub.metadata?.pending_plan) {
          const schedulePending = await resolvePendingPlanFromSchedule(sub);
          if (schedulePending?.plan) {
            // Simulate pending fields for buildSubscriptionRow
            sub.metadata = { ...sub.metadata, pending_plan: schedulePending.plan };
            upsertRow = buildSubscriptionRow(sub, tenantId, customerId, existing);
            upsertRow.pending_change_at = schedulePending.changeAt;
          } else {
            upsertRow = buildSubscriptionRow(sub, tenantId, customerId, existing);
          }
        } else {
          upsertRow = buildSubscriptionRow(sub, tenantId, customerId, existing);
        }

        const { error: upsertErr } = await supabase
          .from("subscriptions")
          .upsert(upsertRow, { onConflict: "tenant_id" });
        if (upsertErr) {
          throw new Error(`subscriptions upsert (customer.subscription.*) failed: ${upsertErr.message} (code=${upsertErr.code})`);
        }

        await logSubscriptionEvent(supabase, tenantId, event.type, event.data.object);
        console.log(`Subscription updated for tenant ${tenantId}: ${sub.status}, plan: ${upsertRow.plan}, pending=${upsertRow.pending_plan || "none"}`);
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
              cancel_at_period_end: false,
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
          // Read existing row (if any)
          const { data: existingRows } = await supabase
            .from("subscriptions")
            .select("plan, employee_limit, pending_plan, pending_change_at, updated_at")
            .eq("tenant_id", tenants[0].id)
            .limit(1);
          const existing = existingRows?.[0] || null;
          const upsertRow = buildSubscriptionRow(renewedSub, tenants[0].id, customerId, existing);
          await supabase
            .from("subscriptions")
            .upsert(upsertRow, { onConflict: "tenant_id" });

          await logSubscriptionEvent(supabase, tenants[0].id, event.type, event.data.object);
          console.log(`Renewal synced for tenant ${tenants[0].id}, plan: ${upsertRow.plan}`);
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

