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
    "page_title": "Pulse Ops",
    "page_icon": "📦",
    "layout": "wide",
    "initial_sidebar_state": "collapsed",
}


_PAGE_CONFIG_SET = False


def init_runtime() -> None:
    """Initialize runtime: set page config once, apply styles every load."""
    global _PAGE_CONFIG_SET
    if not _PAGE_CONFIG_SET:
        st.set_page_config(**PAGE_CONFIG)
        _PAGE_CONFIG_SET = True
    # Always apply styles on every page load (styles are lost on nav)
    apply_global_styles()
