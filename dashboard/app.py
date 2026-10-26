"""PanganWatch dashboard entry point.  Run:  streamlit run dashboard/app.py

Pages live in views/ (not pages/): a pages/ folder makes Streamlit add its own automatic
navigation, which overrides st.navigation.
"""

import streamlit as st

st.set_page_config(page_title="PanganWatch", page_icon="🌶️", layout="wide")

pages = [
    st.Page("views/today.py", title="Today", default=True),
    st.Page("views/explore.py", title="Explore prices", url_path="explore"),
    st.Page("views/insights.py", title="Insights", url_path="insights"),
    st.Page("views/data_quality.py", title="Data quality & about",
            url_path="data-quality"),
]
st.navigation(pages).run()
