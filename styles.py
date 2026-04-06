import streamlit as st


def apply_global_styles():
    st.html("""<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    color-scheme: light !important;
    --dpd-navy-900: #0F2D52;
    --dpd-navy-800: #1A4A8A;
    --dpd-navy-700: #2563A8;
    --dpd-bg: #F5F8FC;
    --dpd-surface: #FFFFFF;
    --dpd-surface-soft: #EEF3FA;
    --dpd-border: #C8D5E6;
    --dpd-border-strong: #9DB4CF;
    --dpd-text: #182B40;
    --dpd-text-muted: #5D7693;
    --dpd-sidebar-text: #D6E2F2;
    --dpd-sidebar-text-strong: #FFFFFF;
    --dpd-on-navy: #FFFFFF;
    --dpd-focus: rgba(37, 99, 168, 0.35);
  }

  /* Base and layout */
  html, body, [class*="css"], .stApp {
    font-family: 'Inter', sans-serif !important;
    color: var(--dpd-text) !important;
    background: var(--dpd-bg) !important;
  }
  [data-testid="stAppViewContainer"],
  [data-testid="stAppViewContainer"] > .main,
  [data-testid="stAppViewContainer"] > .main > div,
  section.main,
  .main,
  .main .block-container {
    background: var(--dpd-bg) !important;
  }
  .main .block-container {
    padding-top: 1.8rem;
    padding-bottom: 3rem;
    max-width: 1200px;
  }

  /* Hide Streamlit chrome */
  #MainMenu, footer,
  [data-testid="stDecoration"],
  [data-testid="stStatusWidget"] {
    visibility: hidden !important;
    display: none !important;
  }
  header[data-testid="stHeader"] { background: transparent !important; }

  /* Global text legibility */
  h1, h2, h3, [data-testid="stHeading"] { color: var(--dpd-navy-900) !important; }
  h1 { font-weight: 700 !important; font-size: 1.62rem !important; letter-spacing: -0.02em; }
  h2 { font-weight: 700 !important; }
  h3 { font-weight: 600 !important; color: var(--dpd-navy-800) !important; }

  .main p,
  .main label,
  .block-container p,
  .block-container label,
  [data-testid="stMarkdownContainer"] p,
  [data-testid="stMarkdownContainer"] li {
    color: var(--dpd-text) !important;
  }
  .main .stCaption,
  .main small,
  .main caption {
    color: var(--dpd-text-muted) !important;
  }
  a, .main a {
    color: var(--dpd-navy-800) !important;
  }
  a:hover, .main a:hover {
    color: var(--dpd-navy-700) !important;
  }

  /* Sidebar */
  [data-testid="stSidebar"],
  [data-testid="stSidebar"] > div {
    background: linear-gradient(180deg, var(--dpd-navy-900) 0%, #123B6B 100%) !important;
    border-right: 1px solid #1E4E85 !important;
  }
  [data-testid="stSidebar"] p,
  [data-testid="stSidebar"] span,
  [data-testid="stSidebar"] label,
  [data-testid="stSidebar"] div {
    color: var(--dpd-sidebar-text) !important;
  }
  [data-testid="stSidebarNav"],
  [data-testid="stSidebarNav"] * {
    color: var(--dpd-sidebar-text) !important;
  }
  [data-testid="stSidebarNav"] a {
    border-radius: 8px !important;
  }
  [data-testid="stSidebarNav"] a:hover {
    background: rgba(255, 255, 255, 0.10) !important;
    color: var(--dpd-sidebar-text-strong) !important;
  }
  [data-testid="stSidebarNav"] a[aria-current="page"] {
    background: rgba(255, 255, 255, 0.16) !important;
    color: var(--dpd-sidebar-text-strong) !important;
  }
  [data-testid="stSidebar"] [data-baseweb="radio"] label {
    border-radius: 8px !important;
    padding: 6px 10px !important;
  }
  [data-testid="stSidebar"] [data-baseweb="radio"] label:hover {
    background: rgba(255, 255, 255, 0.12) !important;
  }
  [data-testid="stSidebar"] .stRadio label {
    font-size: 13px !important;
    padding: 6px 0 !important;
    font-weight: 600 !important;
  }
  [data-testid="stSidebar"] hr {
    border-color: #2D5C93 !important;
    opacity: 0.65 !important;
  }

  /* Sidebar collapsed handle */
  [data-testid="stSidebarCollapsedControl"] {
    opacity: 1 !important;
    visibility: visible !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    background: var(--dpd-surface) !important;
    border: 1px solid var(--dpd-border) !important;
    border-radius: 999px !important;
    box-shadow: 0 3px 10px rgba(15, 45, 82, 0.18) !important;
    padding: 4px !important;
    z-index: 10000 !important;
  }
  [data-testid="stSidebarCollapsedControl"]:hover {
    background: #F0F4FA !important;
    border-color: var(--dpd-border-strong) !important;
  }
  [data-testid="stSidebarCollapsedControl"] * {
    color: var(--dpd-navy-900) !important;
    fill: var(--dpd-navy-900) !important;
    opacity: 1 !important;
  }

  /* Buttons */
  .stButton > button,
  [data-testid="stFormSubmitButton"] > button,
  [data-testid="stBaseButton-primary"],
  [data-testid="stBaseButton-secondary"] {
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    transition: background-color 0.15s, border-color 0.15s, color 0.15s, transform 0.08s, box-shadow 0.12s !important;
  }
  .stButton > button:active,
  [data-testid="stFormSubmitButton"] > button:active {
    transform: scale(0.98) !important;
  }

  .stButton > button[kind="primary"],
  [data-testid="stFormSubmitButton"] > button,
  [data-testid="stFormSubmitButton"] > button[kind="primary"],
  button[data-testid="stBaseButton-primary"] {
    background-color: var(--dpd-navy-900) !important;
    color: #FFFFFF !important;
    border: 1px solid var(--dpd-navy-900) !important;
  }
  .stButton > button[kind="primary"]:hover,
  [data-testid="stFormSubmitButton"] > button:hover,
  button[data-testid="stBaseButton-primary"]:hover {
    background-color: var(--dpd-navy-800) !important;
    border-color: var(--dpd-navy-800) !important;
    color: #FFFFFF !important;
  }
  .stButton > button[kind="primary"] *,
  [data-testid="stFormSubmitButton"] > button *,
  button[data-testid="stBaseButton-primary"] * {
    color: #FFFFFF !important;
  }

  .stButton > button[kind="secondary"],
  .stButton > button:not([kind="primary"]),
  button[data-testid="stBaseButton-secondary"] {
    background-color: var(--dpd-surface) !important;
    color: var(--dpd-navy-900) !important;
    border: 1px solid var(--dpd-border) !important;
  }
  .stButton > button[kind="secondary"]:hover,
  .stButton > button:not([kind="primary"]):hover,
  button[data-testid="stBaseButton-secondary"]:hover {
    background-color: var(--dpd-surface-soft) !important;
    border-color: var(--dpd-border-strong) !important;
    color: var(--dpd-navy-900) !important;
  }

  [data-testid="stSidebar"] .stButton > button,
  [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
    background-color: #E7EEF8 !important;
    color: var(--dpd-navy-900) !important;
    border: 1px solid #AFC3DA !important;
    font-weight: 700 !important;
  }
  [data-testid="stSidebar"] .stButton > button:hover,
  [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover {
    background-color: #D7E4F5 !important;
    border-color: #97B0CD !important;
  }
  [data-testid="stSidebar"] .stButton > button *,
  [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] * {
    color: var(--dpd-navy-900) !important;
  }

  /* Inputs and selectors */
  .stTextInput input,
  .stTextInput textarea,
  .stNumberInput input,
  .stTextArea textarea,
  [data-baseweb="select"] > div,
  [data-baseweb="tag"] {
    background: var(--dpd-surface) !important;
    color: var(--dpd-text) !important;
    caret-color: var(--dpd-navy-900) !important;
    border: 1px solid var(--dpd-border) !important;
    border-radius: 8px !important;
  }
  .stTextInput input::selection,
  .stTextArea textarea::selection,
  .stNumberInput input::selection {
    background: #BBD8F8 !important;
    color: #0F2D52 !important;
  }
  .stTextInput input:focus,
  .stTextArea textarea:focus,
  .stNumberInput input:focus,
  [data-baseweb="select"] > div:focus-within {
    border-color: var(--dpd-navy-700) !important;
    box-shadow: 0 0 0 3px var(--dpd-focus) !important;
  }

  /* Radio / checkbox / toggle */
  [data-baseweb="radio"] label:hover,
  [data-baseweb="checkbox"] label:hover {
    background: rgba(26, 74, 138, 0.06) !important;
    border-radius: 6px !important;
  }

  /* Tabs */
  .stTabs [data-baseweb="tab-list"] {
    border-bottom: 2px solid #DDE7F3 !important;
    gap: 4px;
  }
  .stTabs [data-baseweb="tab"] {
    font-size: 12px !important;
    font-weight: 600 !important;
    color: var(--dpd-text-muted) !important;
    padding: 7px 14px !important;
    border-radius: 6px 6px 0 0 !important;
    background: transparent !important;
  }
  .stTabs [data-baseweb="tab"]:hover {
    background: #EAF1FA !important;
    color: var(--dpd-navy-900) !important;
  }
  .stTabs [aria-selected="true"] {
    color: var(--dpd-navy-900) !important;
    border-bottom: 2px solid var(--dpd-navy-900) !important;
    background: transparent !important;
  }

  /* Prevent unreadable tab text when hover/selected state mixes with inherited styles */
  .stTabs [data-baseweb="tab"] *,
  .stTabs [aria-selected="true"] * {
    color: inherit !important;
  }

  /* Metrics, cards, tables */
  [data-testid="stMetric"] {
    background: var(--dpd-surface) !important;
    border: 1px solid #DCE7F3 !important;
    border-radius: 10px !important;
    padding: 14px 18px !important;
  }
  [data-testid="stMetricLabel"] > div {
    font-size: 11px !important;
    font-weight: 700 !important;
    color: var(--dpd-text-muted) !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  [data-testid="stMetricValue"] > div {
    font-size: 26px !important;
    font-weight: 700 !important;
    color: var(--dpd-navy-900) !important;
  }
  [data-testid="stMetric"] * {
    color: var(--dpd-text) !important;
  }
  [data-testid="stMetricValue"] * {
    color: var(--dpd-navy-900) !important;
  }
  [data-testid="stDataFrame"] {
    border: 1px solid #DCE7F3 !important;
    border-radius: 10px !important;
    background: var(--dpd-surface) !important;
  }

  /* Expanders: collapsed + open + hover */
  [data-testid="stExpander"] {
    border: 1px solid #DCE7F3 !important;
    border-radius: 10px !important;
    background: var(--dpd-surface) !important;
  }
  [data-testid="stExpander"] > details summary {
    color: var(--dpd-text) !important;
  }
  [data-testid="stExpander"] > details summary:hover {
    background: #ECF3FB !important;
    border-radius: 10px !important;
  }
  [data-testid="stExpander"] > details summary * {
    color: var(--dpd-text) !important;
    fill: var(--dpd-text) !important;
  }
  [data-testid="stExpander"] > details[open] summary {
    background: linear-gradient(135deg, var(--dpd-navy-900) 0%, var(--dpd-navy-800) 100%) !important;
    border-radius: 10px 10px 0 0 !important;
    padding: 12px 16px !important;
    margin: -16px -16px 12px -16px !important;
  }
  [data-testid="stExpander"] > details[open] summary:hover {
    background: linear-gradient(135deg, var(--dpd-navy-800) 0%, var(--dpd-navy-700) 100%) !important;
  }
  [data-testid="stExpander"] > details[open] summary * {
    color: #FFFFFF !important;
    fill: #FFFFFF !important;
  }

  /* Uploader */
  [data-testid="stFileUploaderDropzone"] {
    background: #123A68 !important;
    border: 1px dashed #5AA2E4 !important;
  }
  [data-testid="stFileUploaderDropzone"] * {
    color: #FFFFFF !important;
  }
  [data-testid="stFileUploaderDropzone"] button {
    background: #58A3E8 !important;
    color: #032540 !important;
    border: none !important;
    font-weight: 700 !important;
  }

  /* Progress + branded custom blocks */
  .stProgress > div > div {
    background: var(--dpd-navy-900) !important;
    border-radius: 4px;
  }
  .dpd-rail {
    background: linear-gradient(135deg, var(--dpd-navy-900) 0%, var(--dpd-navy-800) 100%);
    border-radius: 12px;
    padding: 26px 30px 22px;
    margin-bottom: 24px;
    box-shadow: 0 4px 20px rgba(15, 45, 82, 0.28), 0 0 0 2px rgba(77, 163, 255, 0.25);
    border-left: 6px solid #4DA3FF;
  }
  .dpd-rail,
  .dpd-rail *,
  .dpd-rail-label,
  .dpd-rail-name,
  .dpd-rail-why,
  .dpd-rail-ok {
    color: var(--dpd-on-navy) !important;
  }
  .dpd-rail .stCaption,
  .dpd-rail small {
    color: #DCE9F8 !important;
  }
  .dpd-sticky-wrap {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 9998;
    background: linear-gradient(135deg, var(--dpd-navy-900) 0%, var(--dpd-navy-800) 100%);
    border-top: 3px solid #4DA3FF;
    padding: 14px 20px;
    box-shadow: 0 -4px 16px rgba(15, 45, 82, 0.14);
  }

  /* Small motion */
  .main .block-container { animation: dpd-fadein 0.16s ease-out; }
  @keyframes dpd-fadein {
    from { opacity: 0.45; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>
""")
