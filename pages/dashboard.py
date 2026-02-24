import streamlit as st

st.set_page_config(layout="wide")

st.markdown("## Welcome Back 👋")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Last Session Peak BAC", "0.094")

with col2:
    st.metric("Sessions Logged", "5")

with col3:
    st.metric("Personal r Estimate", "0.61")