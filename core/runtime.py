import html as _html_mod
import io
import json
import math
import re
import tempfile
import time
import traceback
from datetime import date, datetime

import pandas as pd
import streamlit as st

from styles import apply_global_styles


PAGE_CONFIG = {
    "page_title": "Productivity Planner",
    "page_icon": "📦",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
}


_INITIALIZED = False


def init_runtime() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    st.set_page_config(**PAGE_CONFIG)
    apply_global_styles()
    _INITIALIZED = True
