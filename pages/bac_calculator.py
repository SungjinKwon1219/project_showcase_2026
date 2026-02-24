import streamlit as st
import numpy as np
import matplotlib.pyplot as plt

st.title("BAC Calculator")

drinks = st.slider("Number of Drinks", 0, 10, 3)
weight = st.number_input("Weight (lbs)", 90, 300, 150)
hours = st.slider("Hours Drinking", 0.5, 6.0, 2.0)

if st.button("Estimate BAC"):
    r = 0.6
    beta = 0.015
    A = drinks * 14
    W = weight * 453.592

    bac = (A/(r*W))*100 - beta*hours

    st.success(f"Estimated BAC: {round(bac,3)}")

    t = np.linspace(0, 6, 100)
    bac_curve = (A/(r*W))*100 - beta*t

    fig, ax = plt.subplots()
    ax.plot(t, bac_curve)
    ax.axhline(0.08, linestyle="--")
    st.pyplot(fig)