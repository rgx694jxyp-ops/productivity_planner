import os

from core.dependencies import audit
from core.runtime import st


def track_landing_event(event: str, detail: str = "") -> None:
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
        .lp-hero {
            text-align: center;
            padding: 40px 16px 16px;
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
            font-size: 2.2rem;
            font-weight: 800;
            color: #0F2D52;
            letter-spacing: -0.02em;
            margin-bottom: 6px;
        }
        .lp-sub {
            font-size: 1.05rem;
            color: #39506A;
            margin-bottom: 8px;
        }
        .lp-note {
            font-size: 0.95rem;
            color: #5A7A9C;
            margin-bottom: 10px;
        }
        .lp-card {
            background: #ffffff;
            border: 1px solid #E2EBF4;
            border-radius: 10px;
            padding: 16px;
            height: 100%;
        }
        .lp-list {
            color: #1A2D42;
            line-height: 1.8;
            margin: 0;
            padding-left: 18px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="lp-sticky">'
            '<a class="lp-primary" href="?start=1">Try the app</a>'
        '<a class="lp-ghost" href="?demo=1">See Demo</a>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="lp-hero">', unsafe_allow_html=True)
    st.markdown('<div class="lp-eyebrow">Built for small warehouses</div>', unsafe_allow_html=True)
    st.markdown('<div class="lp-title">Know what needs attention on the floor right now — and why.</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="lp-sub">Upload messy warehouse data and get a prioritized Today queue that shows what changed, why it surfaced, and how much trust to put in it.</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="lp-note">Works with spreadsheets or manual entry. No setup required.</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    if c1.button("Try sample data", type="primary", use_container_width=True, key="lp_get_started_top"):
        track_landing_event("cta_click", "hero_try_sample_data")
        st.session_state["show_login"] = True
        st.rerun()
    if c2.button("Upload a CSV", use_container_width=True, key="lp_how_it_works"):
        track_landing_event("cta_click", "hero_upload_csv")
        st.session_state["lp_show_demo"] = True
        st.rerun()

    if st.session_state.get("_pending_invite"):
        st.info(f"Team invite detected: {st.session_state.get('_pending_invite')} — continue to sign in to join.")

    st.markdown("### See what you get instantly")
    shot_cfg = os.getenv("LANDING_SCREENSHOT_PATH", "")
    try:
        shot_cfg = shot_cfg or str(st.secrets.get("LANDING_SCREENSHOT_PATH", "") or "")
    except Exception:
        pass
    shot = shot_cfg.strip() or os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "landing-supervisor-screenshot.png")
    if shot and os.path.exists(shot):
        st.image(shot, use_container_width=True)
    else:
        st.info("Add a screenshot at assets/landing-supervisor-screenshot.png to boost conversions.")
    st.caption("A prioritized view of where signals are surfacing — with the context behind each one.")

    demo_url = os.getenv("LANDING_DEMO_URL", "").strip()
    try:
        demo_url = demo_url or str(st.secrets.get("LANDING_DEMO_URL", "") or "").strip()
    except Exception:
        pass
    if st.session_state.get("lp_show_demo") or demo_url:
        st.markdown("### Watch how it works")
        if demo_url:
            st.video(demo_url)
            st.caption("30-second product walkthrough")
        else:
            st.info("Add LANDING_DEMO_URL in environment or secrets to embed your Loom/video.")

    st.markdown("### The problem")
    st.markdown(
        """
            - Signals are scattered across spreadsheets, people, and memory
            - It's unclear what changed between shifts or why
            - Priorities are hard to assess objectively when volume shifts
        """
    )

    st.markdown("### The solution")
    st.markdown(
        """
        - See where performance signals are surfacing now
        - Understand likely contributing factors quickly
        - Track trends over time with supporting context
        """
    )

    st.markdown("### How it works")
    st.markdown(
        """
        1. Upload CSV/Excel or enter data manually
        2. Get a prioritized review queue
        3. Review context, document notes, and monitor results
        """
    )

    st.markdown("### What changes after using this")
    b1, b2 = st.columns(2)
    with b1:
           st.markdown('<div class="lp-card"><strong>Before</strong><ul class="lp-list"><li>Signals unclear without data context</li><li>Problems surface after the fact</li><li>No consistent cross-shift view</li></ul></div>', unsafe_allow_html=True)
    with b2:
           st.markdown('<div class="lp-card"><strong>After</strong><ul class="lp-list"><li>Prioritized queue each day, with evidence</li><li>Signal context surfaced before each shift</li><li>Trend visibility across shifts</li></ul></div>', unsafe_allow_html=True)

    st.markdown("### Simple pricing")
    p1, p2, p3 = st.columns(3)
    with p1:
        st.markdown('<div class="lp-card"><strong>Starter</strong><br>$29/month<br><span style="color:#5A7A9C;">Get control of your team</span></div>', unsafe_allow_html=True)
    with p2:
        st.markdown('<div class="lp-card"><strong>Pro</strong><br>$59/month<br><span style="color:#5A7A9C;">Run with deeper insights</span></div>', unsafe_allow_html=True)
    with p3:
        st.markdown('<div class="lp-card"><strong>Business</strong><br>$99/month<br><span style="color:#5A7A9C;">Full operational visibility</span></div>', unsafe_allow_html=True)
    st.caption("Cancel anytime. No contracts.")
    track_landing_event("view_section", "pricing")

    st.success(
        "✔ No setup required\n"
        "✔ Works with spreadsheets or manual entry\n"
        "✔ Takes minutes to get started\n"
        "✔ Cancel anytime"
    )
    st.info("Not sure if it will fit your team? Reach out and we can help you get set up quickly.")

    st.markdown("---")
    st.markdown("### See what's surfacing on your floor today")
    if st.button("Get Started", type="primary", use_container_width=True, key="lp_get_started_bottom"):
        track_landing_event("cta_click", "bottom_get_started")
        st.session_state["show_login"] = True
        st.rerun()
