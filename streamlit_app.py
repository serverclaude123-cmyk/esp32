"""
streamlit_app.py — Hongfa Smart MCB Dashboard
Reads from Supabase REST API directly (no supabase-py dependency).
Deploy via GitHub → Streamlit Cloud.
"""

import os
import time
import requests
from datetime import datetime, timezone, timedelta

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# ---- Credentials ----
def _s(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, default)

SB_URL  = _s("SUPABASE_URL", "https://izfhplviuamhcsklujoc.supabase.co")
SB_KEY  = _s("SUPABASE_KEY", "sb_publishable_48Y3ZSxJDA8zvqbL-8UFPQ_z_Qd1cAP")
SB_HDRS = {
    "apikey":        SB_KEY,
    "Authorization": f"Bearer {SB_KEY}",
    "Content-Type":  "application/json",
}
REFRESH_SEC = 5

# ---- Supabase REST helpers ----
def _sb_get(params: dict):
    """GET from mcb_readings. Returns list or shows error."""
    try:
        r = requests.get(
            f"{SB_URL}/rest/v1/mcb_readings",
            headers=SB_HDRS,
            params=params,
            timeout=10,
        )
        if not r.ok:
            st.error(f"Supabase {r.status_code}: {r.text}")
            return []
        data = r.json()
        if isinstance(data, dict):          # error object, not a list
            st.error(f"Supabase error: {data}")
            return []
        return data
    except Exception as e:
        st.error(f"Request failed: {e}")
        return []

def fetch_latest() -> dict:
    data = _sb_get({"select": "*", "order": "created_at.desc", "limit": "1"})
    return data[0] if data else {}

def fetch_history(hours: int) -> pd.DataFrame:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    data = _sb_get({
        "select":     "*",
        "created_at": f"gte.{since}",
        "order":      "created_at.asc",
        "limit":      "2000",
    })
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True).dt.tz_convert("Asia/Bangkok")
    return df

# ---- Gauge helper ----
def gauge(title, value, unit, lo, hi, warn=None, fmt=".2f"):
    v = float(value or 0)
    bar_color = "#e53935" if (warn and v > warn) else "#43a047"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=v,
        number={"suffix": f" {unit}", "valueformat": fmt},
        title={"text": title, "font": {"size": 13}},
        gauge={
            "axis": {"range": [lo, hi]},
            "bar":  {"color": bar_color},
            "steps": [
                {"range": [lo,        hi * 0.6],  "color": "#e8f5e9"},
                {"range": [hi * 0.6,  hi * 0.85], "color": "#fff9c4"},
                {"range": [hi * 0.85, hi],         "color": "#ffebee"},
            ],
        },
    ))
    fig.update_layout(height=200, margin=dict(t=40, b=0, l=10, r=10))
    return fig

# ================================================================
# Page
# ================================================================
st.set_page_config(page_title="Hongfa MCB", page_icon="⚡", layout="wide")
st.title("⚡ Hongfa Smart MCB Dashboard")

with st.sidebar:
    st.header("Settings")
    hours = st.selectbox(
        "History window",
        [1, 6, 12, 24, 48, 168], index=3,
        format_func=lambda h: f"{h}h" if h < 24 else f"{h//24}d",
    )
    st.caption(f"Auto-refresh every {REFRESH_SEC}s")

# ---- Fetch latest ----
latest = fetch_latest()

sw    = latest.get("switch_status")
alarm = int(latest.get("alarm") or 0)
trip  = int(latest.get("trip")  or 0)
ts    = latest.get("created_at", "")

# ---- Status row ----
c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    if sw == 1:
        st.success("🟢 CLOSED")
    elif sw == 0:
        st.error("🔴 OPEN")
    else:
        st.info("— Switch —")

with c2:
    if alarm:
        st.warning(f"⚠️ ALARM  0x{alarm:04X}")
    else:
        st.success("✅ No Alarm")

with c3:
    if trip:
        st.error(f"🚨 TRIP  0x{trip:04X}")
    else:
        st.success("✅ No Trip")

with c4:
    t = latest.get("temperature")
    st.metric("🌡 Temperature", f"{t} °C" if t is not None else "—")

with c5:
    st.metric("🕐 Last update", ts[:19] if ts else "—")

st.divider()

# ---- Gauges ----
g1, g2, g3, g4 = st.columns(4)
with g1:
    st.plotly_chart(gauge("Current",     latest.get("current"),   "A",  0,  63,  warn=50,  fmt=".2f"), use_container_width=True)
with g2:
    st.plotly_chart(gauge("Voltage",     latest.get("voltage"),   "V",  0,  260, warn=242, fmt=".1f"), use_container_width=True)
with g3:
    st.plotly_chart(gauge("Active Power",latest.get("power"),     "W",  0,  7000,           fmt=".0f"), use_container_width=True)
with g4:
    st.plotly_chart(gauge("Frequency",   latest.get("frequency"), "Hz", 45, 55,  warn=51,  fmt=".2f"), use_container_width=True)

# ---- Energy + PF ----
e1, e2 = st.columns(2)
with e1:
    st.metric("⚡ Total Energy",  f"{float(latest.get('energy') or 0):.3f} kWh")
with e2:
    st.metric("Power Factor", f"{float(latest.get('power_factor') or 0):.3f}")

st.divider()

# ---- Historical charts ----
st.subheader(f"📈 History — last {hours}h")
df = fetch_history(hours)

if df.empty:
    st.info("No data yet — ESP32 will start logging once the sketch is uploaded.")
else:
    t1, t2, t3, t4 = st.tabs(["Current & Voltage", "Power & Energy", "Frequency & PF", "Table"])

    with t1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["created_at"], y=df["current"], name="Current (A)", line=dict(color="#1976D2")))
        fig.add_trace(go.Scatter(x=df["created_at"], y=df["voltage"], name="Voltage (V)", yaxis="y2", line=dict(color="#F57C00")))
        fig.update_layout(
            yaxis=dict(title="A"),
            yaxis2=dict(title="V", overlaying="y", side="right"),
            legend=dict(orientation="h"), height=350, margin=dict(t=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    with t2:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df["created_at"], y=df["power"],  name="Power (W)",    fill="tozeroy", line=dict(color="#43A047")))
        fig2.add_trace(go.Scatter(x=df["created_at"], y=df["energy"], name="Energy (kWh)", yaxis="y2",     line=dict(color="#8E24AA")))
        fig2.update_layout(
            yaxis=dict(title="W"),
            yaxis2=dict(title="kWh", overlaying="y", side="right"),
            legend=dict(orientation="h"), height=350, margin=dict(t=10),
        )
        st.plotly_chart(fig2, use_container_width=True)

    with t3:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=df["created_at"], y=df["frequency"],    name="Frequency (Hz)", line=dict(color="#00ACC1")))
        fig3.add_trace(go.Scatter(x=df["created_at"], y=df["power_factor"], name="Power Factor",   yaxis="y2", line=dict(color="#E53935")))
        fig3.update_layout(
            yaxis=dict(title="Hz"),
            yaxis2=dict(title="PF", overlaying="y", side="right"),
            legend=dict(orientation="h"), height=350, margin=dict(t=10),
        )
        st.plotly_chart(fig3, use_container_width=True)

    with t4:
        cols = ["created_at", "switch_status", "current", "voltage", "temperature",
                "power", "energy", "frequency", "power_factor", "alarm", "trip"]
        st.dataframe(
            df[cols].sort_values("created_at", ascending=False).head(200),
            use_container_width=True,
        )
        st.download_button("⬇ Download CSV", df.to_csv(index=False).encode(), "mcb_readings.csv", "text/csv")

# ---- Auto-refresh ----
time.sleep(REFRESH_SEC)
st.rerun()
