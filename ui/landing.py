import os

from core.dependencies import audit, log_operational_event
from core.onboarding_intent import (
    SAMPLE_DATA_POST_AUTH_INTENT,
    begin_onboarding_correlation_id,
    build_onboarding_event_context,
    clear_post_auth_intent,
    queue_sample_data_post_auth_intent,
)
from core.runtime import st


def track_landing_event(event: str, detail: str = "") -> None:
    if event == "cta_click" and detail == "hero_try_sample_data":
        log_operational_event(
            "landing_sample_cta_clicked",
            status="success",
            detail=detail,
            context=build_onboarding_event_context({"surface": "landing", "cta": detail}),
        )
    elif event == "cta_click" and detail in {"bottom_get_started", "sticky_get_started"}:
        log_operational_event(
            "landing_generic_cta_clicked",
            status="success",
            detail=detail,
            context=build_onboarding_event_context({"surface": "landing", "cta": detail}),
        )

    try:
        audit(f"landing:{event}", detail)
    except Exception:
        pass


def show_landing_page() -> None:
    if not st.session_state.get("_lp_view_logged"):
        st.session_state["_lp_view_logged"] = True
        track_landing_event("view")

    st.markdown(
        """
        <style>
        .lp-sticky {
            position: fixed;
            bottom: 12px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 9999;
            background: rgba(15, 45, 82, 0.96);
            border: 1px solid #4DA3FF;
            box-shadow: 0 8px 24px rgba(15,45,82,0.35);
            border-radius: 999px;
            padding: 8px 10px;
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .lp-sticky a {
            text-decoration: none;
            font-size: 12px;
            font-weight: 700;
            border-radius: 999px;
            padding: 8px 12px;
        }
        .lp-sticky .lp-primary {
            background: #4DA3FF;
            color: #01223F;
        }
        .lp-sticky .lp-ghost {
            background: rgba(77,163,255,0.16);
            color: #E8F0F9;
            border: 1px solid rgba(77,163,255,0.35);
        }
        .lp-shell {
            max-width: 1080px;
            margin: 0 auto;
            padding: 8px 8px 52px;
        }
        .lp-hero {
            padding: 30px 16px 12px;
            text-align: center;
        }
        .lp-eyebrow {
            display: inline-block;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: .08em;
            text-transform: uppercase;
            color: #1A4A8A;
            background: #E8F0F9;
            border: 1px solid #C5D4E8;
            border-radius: 999px;
            padding: 5px 10px;
            margin-bottom: 10px;
        }
        .lp-title {
            font-size: 2.35rem;
            font-weight: 800;
            color: #0F2D52;
            letter-spacing: -0.02em;
            margin-bottom: 8px;
        }
        .lp-sub {
            font-size: 1.02rem;
            color: #39506A;
            margin-bottom: 10px;
            max-width: 840px;
            margin-left: auto;
            margin-right: auto;
        }
        .lp-note {
            font-size: 0.95rem;
            color: #5A7A9C;
            margin-bottom: 10px;
        }
        .lp-section {
            margin-top: 20px;
        }
        .lp-section h3 {
            margin-bottom: 6px;
            color: #123C66;
        }
        .lp-section p {
            color: #2A415B;
        }
        .lp-card {
            background: #ffffff;
            border: 1px solid #E2EBF4;
            border-radius: 10px;
            padding: 16px;
            height: 100%;
        }
        .lp-card-title {
            font-weight: 700;
            color: #123C66;
            margin-bottom: 4px;
        }
        .lp-card-text {
            color: #2A415B;
            font-size: 0.95rem;
            line-height: 1.5;
        }
        .lp-list {
            color: #1A2D42;
            line-height: 1.8;
            margin: 0;
            padding-left: 18px;
        }
        .lp-kicker {
            color: #4A6A8D;
            font-size: 0.86rem;
            text-transform: uppercase;
            letter-spacing: .04em;
            font-weight: 700;
            margin-bottom: 4px;
        }
        .lp-workflow {
            background: #ffffff;
            border: 1px solid #D8E6F4;
            border-radius: 12px;
            padding: 14px;
        }
        .lp-step {
            border: 1px solid #E2EBF4;
            border-radius: 10px;
            padding: 10px 12px;
            margin-bottom: 8px;
            background: #F9FCFF;
        }
        .lp-step:last-child {
            margin-bottom: 0;
        }
        .lp-step-title {
            color: #123C66;
            font-size: 0.92rem;
            font-weight: 700;
        }
        .lp-step-meta {
            color: #5A7A9C;
            font-size: 0.82rem;
            margin-top: 2px;
        }
        .lp-final {
            margin-top: 24px;
            padding: 16px;
            border-radius: 12px;
            border: 1px solid #D8E6F4;
            background: #F5FAFF;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="lp-sticky">'
            '<a class="lp-primary" href="?start=1">Try Pulse Ops</a>'
            '<a class="lp-ghost" href="?demo=1">See Demo</a>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="lp-shell">', unsafe_allow_html=True)
    st.markdown('<div class="lp-hero">', unsafe_allow_html=True)
    st.markdown('<div class="lp-eyebrow">Pulse Ops</div>', unsafe_allow_html=True)
    st.markdown('<div class="lp-title">Know what needs attention now</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="lp-sub">Pulse Ops turns messy floor data into a daily action queue: what changed, who needs review, and what follow-through is still open.</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="lp-note">Built for supervisors running warehouse operations shift by shift.</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    if c1.button("Try sample data", type="primary", use_container_width=True, key="lp_get_started_top"):
        correlation_id = begin_onboarding_correlation_id()
        track_landing_event("cta_click", "hero_try_sample_data")
        queue_sample_data_post_auth_intent(correlation_id=correlation_id)
        log_operational_event(
            "onboarding_sample_intent_preserved",
            status="success",
            detail="landing_sample_cta",
            context=build_onboarding_event_context(
                {"mechanism": "query_param", "source": "landing_sample_cta"},
                correlation_id=correlation_id,
            ),
        )
        st.session_state["show_login"] = True
        st.rerun()
    if c2.button("Upload a CSV", use_container_width=True, key="lp_how_it_works"):
        track_landing_event("cta_click", "hero_upload_csv")
        clear_post_auth_intent()
        st.session_state["lp_show_demo"] = True
        st.rerun()

    if st.session_state.get("_pending_invite"):
        st.info(f"Team invite detected: {st.session_state.get('_pending_invite')} — continue to sign in to join.")

    st.markdown('<div class="lp-section">', unsafe_allow_html=True)
    st.markdown('<div class="lp-kicker">Today Queue</div>', unsafe_allow_html=True)
    st.markdown("### The Today queue is the product")
    st.markdown("Open Pulse Ops and start with a compact queue of who needs review now, then capture follow-through as work moves.")

    shot_cfg = os.getenv("LANDING_SCREENSHOT_PATH", "")
    try:
        shot_cfg = shot_cfg or str(st.secrets.get("LANDING_SCREENSHOT_PATH", "") or "")
    except Exception:
        pass
    shot = shot_cfg.strip() or os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "landing-supervisor-screenshot.png")
    if shot and os.path.exists(shot):
        st.image(shot, use_container_width=True)
    else:
                st.markdown(
                        """
                        <div class="lp-workflow">
                            <div class="lp-step">
                                <div class="lp-step-title">1. Maya · Receiving</div>
                                <div class="lp-step-meta">Below expected pace · Medium confidence · Current shift</div>
                            </div>
                            <div class="lp-step">
                                <div class="lp-step-title">2. Luis · Packing</div>
                                <div class="lp-step-meta">Repeated variance across shifts · Follow-up due</div>
                            </div>
                            <div class="lp-step">
                                <div class="lp-step-title">3. Dana · Pick Line</div>
                                <div class="lp-step-meta">Process friction signal surfaced · Note required</div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                )
        st.caption("Action-first by design: review the queue, document context, and keep follow-through visible.")
        st.markdown('</div>', unsafe_allow_html=True)

    demo_url = os.getenv("LANDING_DEMO_URL", "").strip()
    try:
        demo_url = demo_url or str(st.secrets.get("LANDING_DEMO_URL", "") or "").strip()
    except Exception:
        pass
    if st.session_state.get("lp_show_demo") or demo_url:
        st.markdown('<div class="lp-section">', unsafe_allow_html=True)
        st.markdown("### Watch Pulse Ops in 30 seconds")
        if demo_url:
            st.video(demo_url)
            st.caption("Queue-first workflow walkthrough")
        else:
            st.info("Add LANDING_DEMO_URL in environment or secrets to embed your Loom/video.")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="lp-section">', unsafe_allow_html=True)
    st.markdown("### Problem")
    p1, p2, p3 = st.columns(3)
    with p1:
        st.markdown('<div class="lp-card"><div class="lp-card-title">Signals are fragmented</div><div class="lp-card-text">Shift context is split across spreadsheets, chats, and memory.</div></div>', unsafe_allow_html=True)
    with p2:
        st.markdown('<div class="lp-card"><div class="lp-card-title">Priorities are unclear</div><div class="lp-card-text">It is hard to see who needs review first when volume and staffing move daily.</div></div>', unsafe_allow_html=True)
    with p3:
        st.markdown('<div class="lp-card"><div class="lp-card-title">Follow-through gets lost</div><div class="lp-card-text">Notes and next checks are inconsistent between supervisors and shifts.</div></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="lp-section">', unsafe_allow_html=True)
    st.markdown("### Solution")
    st.markdown(
        """
        - Turn raw floor data into a daily queue ordered by operational attention
        - Show concise context and confidence so each signal is reviewable
        - Keep follow-through visible with notes and due checkpoints
        """
    )
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="lp-section">', unsafe_allow_html=True)
    st.markdown("### How it works")
    st.markdown(
        """
        1. Ingest shift data from CSV/Excel or manual entry
        2. Review the Today queue and close the most urgent items first
        3. Capture what happened and what follow-up is due
        """
    )
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="lp-section">', unsafe_allow_html=True)
    st.markdown("### Why it is different")
    st.markdown(
        """
        - Pulse Ops is **not a dashboard**: it starts with a daily action queue
        - Pulse Ops is **not a WMS**: it layers decisions on top of your existing systems
        - Pulse Ops is **not generic BI**: it is tuned for warehouse shift operations
        """
    )
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="lp-section">', unsafe_allow_html=True)
    st.markdown("### Trust and context")
    st.markdown(
        """
        - Signals include confidence and freshness cues
        - Every surfaced item includes enough context for quick review
        - Supervisors can log evidence and follow-through in the same flow
        """
    )
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="lp-section">', unsafe_allow_html=True)
    st.markdown("### Who it is for")
    st.markdown(
        """
        - Frontline warehouse supervisors managing daily execution
        - Operations leads coordinating handoffs across shifts
        - Teams that need clear, practical signal review without analytics overhead
        """
    )
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div class="lp-final">', unsafe_allow_html=True)
    st.markdown("### Bring today into focus")
    st.markdown("Start with sample data or your own file and open the Pulse Ops Today queue in minutes.")
    if st.button("Get Started", type="primary", use_container_width=True, key="lp_get_started_bottom"):
        begin_onboarding_correlation_id()
        track_landing_event("cta_click", "bottom_get_started")
        clear_post_auth_intent()
        st.session_state["show_login"] = True
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
