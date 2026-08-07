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

TZ = "Asia/Jakarta"

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
REFRESH_SEC = 30

# ---- Supabase REST helpers ----
def _sb_get(params: dict):
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
        if isinstance(data, dict):
            st.error(f"Supabase error: {data}")
            return []
        return data
    except Exception as e:
        st.error(f"Request failed: {e}")
        return []

def fetch_latest() -> dict:
    data = _sb_get({"select": "*", "order": "created_at.desc", "limit": "1"})
    return data[0] if data else {}

def _to_jkt(df: pd.DataFrame) -> pd.DataFrame:
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True).dt.tz_convert(TZ)
    return df

def fetch_history(hours: int) -> pd.DataFrame:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    data = _sb_get({"select": "*", "created_at": f"gte.{since}",
                    "order": "created_at.asc", "limit": "2000"})
    if not data:
        return pd.DataFrame()
    return _to_jkt(pd.DataFrame(data))

def fetch_energy_since(since_iso: str) -> pd.DataFrame:
    """Fetch energy column from a given UTC ISO timestamp to now."""
    data = _sb_get({"select": "created_at,energy", "created_at": f"gte.{since_iso}",
                    "order": "created_at.asc", "limit": "10000"})
    if not data:
        return pd.DataFrame()
    df = _to_jkt(pd.DataFrame(data))
    df["energy"] = pd.to_numeric(df["energy"], errors="coerce").fillna(0)
    return df[df["energy"] > 0]   # skip rows where Modbus read failed

def start_of_today_utc() -> str:
    now_jkt = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo(TZ))
    sod = now_jkt.replace(hour=0, minute=0, second=0, microsecond=0)
    return sod.astimezone(timezone.utc).isoformat()

def start_of_month_utc() -> str:
    now_jkt = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo(TZ))
    som = now_jkt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return som.astimezone(timezone.utc).isoformat()

def start_of_year_utc() -> str:
    now_jkt = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo(TZ))
    soy = now_jkt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return soy.astimezone(timezone.utc).isoformat()

# ---- Gauge ----
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

# ---- kWh bar chart helper ----
def kwh_bar(df_energy: pd.DataFrame, freq: str, title: str, x_fmt: str, hover_prefix: str) -> go.Figure:
    """Energy is cumulative — consumption per period = max - min within period."""
    if df_energy.empty:
        fig = go.Figure()
        fig.update_layout(title=title, height=320,
                          annotations=[dict(text="No data yet", showarrow=False,
                                           font=dict(size=14), xref="paper", yref="paper", x=0.5, y=0.5)])
        return fig

    grp  = df_energy.set_index("created_at").resample(freq)["energy"]
    kwh  = (grp.max() - grp.min()).reset_index()
    kwh.columns = ["period", "kwh"]
    kwh  = kwh[kwh["kwh"] > 0]

    if kwh.empty:
        fig = go.Figure()
        fig.update_layout(title=title, height=320,
                          annotations=[dict(text="No data yet", showarrow=False,
                                           font=dict(size=14), xref="paper", yref="paper", x=0.5, y=0.5)])
        return fig

    label = kwh["period"].dt.strftime(x_fmt)
    hover = f"{hover_prefix}: %{{x}}<br>kWh: %{{y:.3f}}<extra></extra>"

    fig = go.Figure(go.Bar(
        x=label,
        y=kwh["kwh"],
        marker_color="#1976D2",
        hovertemplate=hover,
        text=kwh["kwh"].round(3),
        textposition="outside",
    ))
    fig.update_layout(
        title=title,
        yaxis_title="kWh",
        height=320,
        margin=dict(t=40, b=40, l=40, r=20),
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="#1e1e1e", font_color="white"),
    )
    return fig

# ================================================================
# Page
# ================================================================
st.set_page_config(page_title="Rajawali Smart MCB", page_icon="⚡", layout="wide")

# ---- Header with logo ----
col_logo, col_title = st.columns([1, 5])
with col_logo:
    try:
        st.image("LOGO RAJAWALI KONTROL UTAMA.png", width=100)
    except Exception:
        st.write("⚡")
with col_title:
    st.title("⚡ Rajawali Smart MCB Dashboard")

# ---- Device status indicator ----
def device_status(ts_utc_str: str):
    """
    Returns (state, elapsed_str).
    state: 'online' | 'reconnecting' | 'offline'
    online       < 2 min  — posting normally
    reconnecting 2–5 min  — WiFi connected but no internet / restarting
    offline      > 5 min  — completely down
    """
    if not ts_utc_str:
        return "offline", "never"
    last    = pd.to_datetime(ts_utc_str, utc=True)
    elapsed = (datetime.now(timezone.utc) - last.to_pydatetime()).total_seconds()
    if elapsed < 60:
        age = f"{int(elapsed)}s ago"
    elif elapsed < 3600:
        age = f"{int(elapsed//60)}m {int(elapsed%60)}s ago"
    else:
        age = f"{int(elapsed//3600)}h {int((elapsed%3600)//60)}m ago"
    if elapsed <= 120:
        return "online", age
    elif elapsed <= 300:
        return "reconnecting", age
    else:
        return "offline", age

with st.sidebar:
    st.header("Settings")
    hours = st.selectbox(
        "History window",
        [1, 6, 12, 24, 48, 168], index=3,
        format_func=lambda h: f"{h}h" if h < 24 else f"{h//24}d",
    )
    st.caption(f"Auto-refresh every {REFRESH_SEC}s  |  Timezone: WIB (UTC+7)")

# ---- Latest ----
latest = fetch_latest()

sw    = latest.get("switch_status")
alarm = int(latest.get("alarm") or 0)
trip  = int(latest.get("trip")  or 0)
ts    = latest.get("created_at", "")

# Format timestamp to WIB
if ts:
    dt_utc = pd.to_datetime(ts, utc=True)
    ts_wib = dt_utc.tz_convert(TZ).strftime("%Y-%m-%d %H:%M:%S WIB")
else:
    ts_wib = "—"

# ---- Device status banner ----
state, age = device_status(ts)
if state == "online":
    st.success(f"🟢 GATEWAY ONLINE — last data {age}")
elif state == "reconnecting":
    st.warning(f"🟡 GATEWAY RECONNECTING — last data {age}  |  WiFi connected, waiting for internet...")
else:
    st.error(f"🔴 GATEWAY OFFLINE — last data {age}  |  Check power / WiFi")

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
    st.metric("🕐 Last update", ts_wib)

st.divider()

# ---- Gauges ----
g1, g2, g3, g4 = st.columns(4)
with g1:
    st.plotly_chart(gauge("Current",      latest.get("current"),   "A",  0,  63,  warn=50,  fmt=".2f"), use_container_width=True, key="g_current")
with g2:
    st.plotly_chart(gauge("Voltage",      latest.get("voltage"),   "V",  0,  260, warn=242, fmt=".1f"), use_container_width=True, key="g_voltage")
with g3:
    st.plotly_chart(gauge("Active Power", latest.get("power"),     "W",  0,  7000,           fmt=".0f"), use_container_width=True, key="g_power")
with g4:
    st.plotly_chart(gauge("Frequency",    latest.get("frequency"), "Hz", 45, 55,  warn=51,  fmt=".2f"), use_container_width=True, key="g_freq")

e1, e2 = st.columns(2)
with e1:
    st.metric("⚡ Total Energy", f"{float(latest.get('energy') or 0):.3f} kWh")
with e2:
    st.metric("Power Factor", f"{float(latest.get('power_factor') or 0):.3f}")

st.divider()

# ---- kWh Bar Charts ----
st.subheader("⚡ Energy Consumption")

df_today = fetch_energy_since(start_of_today_utc())
df_month = fetch_energy_since(start_of_month_utc())
df_year  = fetch_energy_since(start_of_year_utc())

ek1, ek2, ek3 = st.columns(3)
with ek1:
    st.plotly_chart(
        kwh_bar(df_today, "h",  "Today — Hourly kWh",   "%H:00",    "Hour"),
        use_container_width=True, key="kwh_daily")
with ek2:
    st.plotly_chart(
        kwh_bar(df_month, "D",  "This Month — Daily kWh", "%d %b",  "Date"),
        use_container_width=True, key="kwh_monthly")
with ek3:
    st.plotly_chart(
        kwh_bar(df_year,  "ME", "This Year — Monthly kWh", "%b %Y", "Month"),
        use_container_width=True, key="kwh_yearly")

st.divider()

# ---- Historical line charts ----
st.subheader(f"📈 History — last {hours}h")
df = fetch_history(hours)

HOVER_T = "%{x|%Y-%m-%d %H:%M:%S WIB}<br>%{y}<extra></extra>"

df_clean = df

if df.empty:
    st.info("No data yet — GATEWAY will start logging once the sketch is uploaded.")
else:
    t1, t2, t3, t4 = st.tabs(["Current & Voltage", "Power & Energy", "Frequency & PF", "Table"])

    with t1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_clean["created_at"], y=df_clean["current"], name="Current (A)",
                                 line=dict(color="#1976D2"),
                                 hovertemplate="%{x|%Y-%m-%d %H:%M:%S WIB}<br>Current: %{y:.3f} A<extra></extra>"))
        fig.add_trace(go.Scatter(x=df_clean["created_at"], y=df_clean["voltage"], name="Voltage (V)", yaxis="y2",
                                 line=dict(color="#F57C00"),
                                 hovertemplate="%{x|%Y-%m-%d %H:%M:%S WIB}<br>Voltage: %{y:.1f} V<extra></extra>"))
        fig.update_layout(yaxis=dict(title="A"), yaxis2=dict(title="V", overlaying="y", side="right"),
                          legend=dict(orientation="h"), height=350, margin=dict(t=10), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True, key="hist_cv")

    with t2:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df_clean["created_at"], y=df_clean["power"], name="Power (W)", fill="tozeroy",
                                  line=dict(color="#43A047"),
                                  hovertemplate="%{x|%Y-%m-%d %H:%M:%S WIB}<br>Power: %{y:.1f} W<extra></extra>"))
        fig2.add_trace(go.Scatter(x=df_clean["created_at"], y=df_clean["energy"], name="Energy (kWh)", yaxis="y2",
                                  line=dict(color="#8E24AA"),
                                  hovertemplate="%{x|%Y-%m-%d %H:%M:%S WIB}<br>Energy: %{y:.3f} kWh<extra></extra>"))
        fig2.update_layout(yaxis=dict(title="W"), yaxis2=dict(title="kWh", overlaying="y", side="right"),
                           legend=dict(orientation="h"), height=350, margin=dict(t=10), hovermode="x unified")
        st.plotly_chart(fig2, use_container_width=True, key="hist_pe")

    with t3:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=df_clean["created_at"], y=df_clean["frequency"], name="Frequency (Hz)",
                                  line=dict(color="#00ACC1"),
                                  hovertemplate="%{x|%Y-%m-%d %H:%M:%S WIB}<br>Freq: %{y:.2f} Hz<extra></extra>"))
        fig3.add_trace(go.Scatter(x=df_clean["created_at"], y=df_clean["power_factor"], name="Power Factor", yaxis="y2",
                                  line=dict(color="#E53935"),
                                  hovertemplate="%{x|%Y-%m-%d %H:%M:%S WIB}<br>PF: %{y:.3f}<extra></extra>"))
        fig3.update_layout(yaxis=dict(title="Hz"), yaxis2=dict(title="PF", overlaying="y", side="right"),
                           legend=dict(orientation="h"), height=350, margin=dict(t=10), hovermode="x unified")
        st.plotly_chart(fig3, use_container_width=True, key="hist_fp")

    with t4:
        cols = ["created_at", "switch_status", "current", "voltage", "temperature",
                "power", "energy", "frequency", "power_factor", "alarm", "trip"]
        disp = df_clean[cols].copy()
        disp["created_at"] = disp["created_at"].dt.strftime("%Y-%m-%d %H:%M:%S WIB")
        st.caption(f"Showing {len(disp)} rows with valid electric data (voltage > 0)")
        st.dataframe(disp.sort_values("created_at", ascending=False).head(200), use_container_width=True)
        st.download_button("⬇ Download CSV", df_clean.to_csv(index=False).encode(), "mcb_readings.csv", "text/csv")

# ---- Auto-refresh ----
time.sleep(REFRESH_SEC)
st.rerun()
