import streamlit as st


def apply_global_styles():
    st.html("""<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  /* Global font */
  html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif !important; }

  /* Hide Streamlit chrome */
  #MainMenu, footer,
  [data-testid="stDecoration"], [data-testid="stStatusWidget"] { visibility: hidden !important; display: none !important; }
  header[data-testid="stHeader"] { background: transparent !important; }

  /* When sidebar is hidden, keep the expand control visible and high-contrast. */
  [data-testid="stSidebarCollapsedControl"] {
    opacity: 1 !important;
    visibility: visible !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    background: #ffffff !important;
    border: 1px solid #C5D4E8 !important;
    border-radius: 999px !important;
    box-shadow: 0 2px 8px rgba(15, 45, 82, 0.16) !important;
    padding: 4px !important;
    z-index: 10000 !important;
  }
  [data-testid="stSidebarCollapsedControl"]:hover {
    background: #ffffff !important;
    border-color: #AFC3DA !important;
    box-shadow: 0 2px 8px rgba(15, 45, 82, 0.16) !important;
  }
  [data-testid="stSidebarCollapsedControl"] button,
  [data-testid="stSidebarCollapsedControl"] div {
    opacity: 1 !important;
    visibility: visible !important;
  }
  [data-testid="stSidebarCollapsedControl"] [data-testid="stIconMaterial"],
  [data-testid="stSidebarCollapsedControl"] span,
  [data-testid="stSidebarCollapsedControl"] svg,
  [data-testid="stSidebarCollapsedControl"] * {
    color: #000000 !important;
    fill: #000000 !important;
    opacity: 1 !important;
  }

  /* Page background */
  html, body { background: #F7F9FC !important; }
  .stApp { background: #F7F9FC !important; }
  [data-testid="stAppViewContainer"] { background: #F7F9FC !important; }
  .main { background: #F7F9FC !important; }
  .main .block-container { padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1200px; background: #F7F9FC !important; }

  /* Sidebar */
  [data-testid="stSidebar"] { background: #0F2D52 !important; border-right: none !important; }
  [data-testid="stSidebar"] > div { background: #0F2D52 !important; }
  [data-testid="stSidebar"] p,
  [data-testid="stSidebar"] span,
  [data-testid="stSidebar"] label,
  [data-testid="stSidebar"] div { color: #CBD8E8 !important; }
  [data-testid="stSidebar"] .stRadio label { font-size: 13px !important; padding: 6px 0 !important; font-weight: 500 !important; }
  [data-testid="stSidebar"] hr { border-color: #1A4A8A !important; opacity: 0.6; }

  h1 { color: #0F2D52 !important; font-weight: 600 !important; font-size: 1.6rem !important; letter-spacing: -0.02em; }
  h2 { color: #0F2D52 !important; font-weight: 600 !important; }
  h3 { color: #1A4A8A !important; font-weight: 500 !important; }
  [data-testid="stHeading"] { color: #0F2D52 !important; }

  .main p, .main span, .main label, .main div,
  .block-container p, .block-container span, .block-container label {
    color: #1A2D42;
  }
  .main .stCaption, .main small, .main caption { color: #5A7A9C !important; }

  .stButton > button,
  [data-testid="stFormSubmitButton"] > button,
  [data-testid="stBaseButton-primary"],
  [data-testid="stBaseButton-secondary"] {
    border-radius: 6px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    transition: background 0.15s, color 0.15s;
  }

  .stButton > button[kind="primary"],
  [data-testid="stFormSubmitButton"] > button,
  [data-testid="stFormSubmitButton"] > button[kind="primary"],
  button[data-testid="stBaseButton-primary"] {
    background-color: #0F2D52 !important;
    color: #ffffff !important;
    border: none !important;
  }
  .stButton > button[kind="primary"]:hover,
  [data-testid="stFormSubmitButton"] > button:hover,
  button[data-testid="stBaseButton-primary"]:hover {
    background-color: #1A4A8A !important;
    color: #ffffff !important;
  }
  .stButton > button[kind="primary"] p,
  .stButton > button[kind="primary"] span,
  [data-testid="stFormSubmitButton"] > button p,
  [data-testid="stFormSubmitButton"] > button span,
  button[data-testid="stBaseButton-primary"] p,
  button[data-testid="stBaseButton-primary"] span {
    color: #ffffff !important;
  }

  .stButton > button[kind="secondary"],
  .stButton > button:not([kind="primary"]),
  button[data-testid="stBaseButton-secondary"] {
    background-color: #ffffff !important;
    color: #0F2D52 !important;
    border: 1px solid #C5D4E8 !important;
  }

  [data-testid="stSidebar"] .stButton > button,
  [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
    background-color: #E8EEF6 !important;
    color: #000000 !important;
    border: 1px solid #AFC3DA !important;
    font-weight: 600 !important;
  }
  [data-testid="stSidebar"] .stButton > button p,
  [data-testid="stSidebar"] .stButton > button span,
  [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] p,
  [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] span {
    color: #000000 !important;
  }

  .stTabs [data-baseweb="tab-list"] { border-bottom: 2px solid #E2EBF4 !important; gap: 2px; }
  .stTabs [data-baseweb="tab"] {
    font-size: 12px !important; font-weight: 500 !important;
    color: #5A7A9C !important; padding: 7px 14px !important;
    border-radius: 4px 4px 0 0 !important; background: transparent !important;
  }
  .stTabs [aria-selected="true"] {
    color: #0F2D52 !important; border-bottom: 2px solid #0F2D52 !important;
    background: transparent !important;
  }

  [data-testid="stMetric"] { background: #ffffff; border: 1px solid #E2EBF4; border-radius: 8px; padding: 14px 18px; }
  [data-testid="stMetricLabel"] > div { font-size: 11px !important; font-weight: 600 !important; color: #5A7A9C !important; text-transform: uppercase; letter-spacing: 0.05em; }
  [data-testid="stMetricValue"] > div { font-size: 26px !important; font-weight: 600 !important; color: #0F2D52 !important; }

  .stTextInput input, .stTextInput textarea,
  .stNumberInput input,
  .stTextArea textarea {
    background: #ffffff !important;
    color: #1A2D42 !important;
    border: 1px solid #C5D4E8 !important;
    border-radius: 6px !important;
  }

  [data-baseweb="select"] > div {
    background: #ffffff !important;
    border-color: #C5D4E8 !important;
    border-radius: 6px !important;
    color: #1A2D42 !important;
  }

  [data-testid="stExpander"] {
    border: 1px solid #E2EBF4 !important;
    border-radius: 8px !important;
    background: #ffffff !important;
  }

  [data-testid="stDataFrame"] { border: 1px solid #E2EBF4 !important; border-radius: 8px !important; }
  .stProgress > div > div { background: #0F2D52 !important; border-radius: 4px; }

  /* File uploader readability */
  [data-testid="stFileUploaderDropzone"] {
    background: #12365f !important;
    border: 1px dashed #4DA3FF !important;
  }
  [data-testid="stFileUploaderDropzone"] * {
    color: #ffffff !important;
  }
  [data-testid="stFileUploaderDropzone"] button {
    background: #4DA3FF !important;
    color: #01223F !important;
    border: none !important;
    font-weight: 700 !important;
  }

  .dpd-rail {
    background: linear-gradient(135deg, #0F2D52 0%, #1A4A8A 100%);
    border-radius: 12px;
    padding: 26px 30px 22px;
    margin-bottom: 24px;
    box-shadow: 0 4px 20px rgba(15,45,82,0.28), 0 0 0 2px rgba(77,163,255,0.25);
    border-left: 6px solid #4DA3FF;
  }

  .dpd-sticky-wrap {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 9998;
    background: linear-gradient(135deg, #0F2D52 0%, #1A4A8A 100%);
    border-top: 3px solid #4DA3FF;
    padding: 14px 20px;
    box-shadow: 0 -4px 16px rgba(15, 45, 82, 0.14);
    animation: slideUp 0.3s ease-out;
  }

  .stButton > button {
    transition: transform 0.08s ease, box-shadow 0.12s ease !important;
  }
  .stButton > button:active {
    transform: scale(0.96) !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.18) !important;
  }

  .main .block-container {
    animation: dpd-fadein 0.18s ease-out;
  }
  @keyframes dpd-fadein {
    from { opacity: 0.4; transform: translateY(5px); }
    to   { opacity: 1;   transform: translateY(0); }
  }

  /* Expander header: black text when collapsed */
  [data-testid="stExpander"] > details summary,
  [data-testid="stExpander"] > details summary p,
  [data-testid="stExpander"] > details summary span,
  [data-testid="stExpander"] > details summary label {
    color: #1A2D42 !important;
  }
  [data-testid="stExpander"] > details summary svg {
    fill: #1A2D42 !important;
    color: #1A2D42 !important;
  }

  /* Expander header: white text + dark blue bg when expanded */
  [data-testid="stExpander"] > details[open] summary {
    background: linear-gradient(135deg, #0F2D52 0%, #1A4A8A 100%) !important;
    border-radius: 8px 8px 0 0 !important;
    padding: 12px 16px !important;
    margin: -16px -16px 12px -16px !important;
  }
  [data-testid="stExpander"] > details[open] summary,
  [data-testid="stExpander"] > details[open] summary p,
  [data-testid="stExpander"] > details[open] summary span,
  [data-testid="stExpander"] > details[open] summary label,
  [data-testid="stExpander"] > details[open] summary * {
    color: #ffffff !important;
  }
  [data-testid="stExpander"] > details[open] summary svg {
    fill: #ffffff !important;
    color: #ffffff !important;
  }

  /* Hover states */
  [data-testid="stExpander"] > details summary:hover {
    background: #f0f4f8 !important;
  }
  [data-testid="stExpander"] > details[open] summary:hover {
    background: linear-gradient(135deg, #1A4A8A 0%, #2563A8 100%) !important;
  }
</style>
""")
