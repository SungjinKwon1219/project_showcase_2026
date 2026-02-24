import streamlit as st

# Page config
st.set_page_config(
    page_title="BAC Personalizer",
    page_icon="🍷",
    layout="centered",
)

# Custom CSS
st.markdown("""
<style>
body {
    background-color: #0F172A;
}

.main {
    background-color: #0F172A;
}

.card {
    background-color: #1E293B;
    padding: 2rem;
    border-radius: 15px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.3);
}

.title {
    font-size: 2.2rem;
    font-weight: 700;
    color: white;
}

.subtitle {
    color: #94A3B8;
}
</style>
""", unsafe_allow_html=True)

# Session state login
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

st.markdown('<div class="card">', unsafe_allow_html=True)

st.markdown('<div class="title">Safer</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Personalized BAC Estimation</div>', unsafe_allow_html=True)

st.write("")

email = st.text_input("Email")
password = st.text_input("Password", type="password")

if st.button("Login"):
    st.session_state.logged_in = True
    st.switch_page("1_Dashboard")

st.markdown('</div>', unsafe_allow_html=True)