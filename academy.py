import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# --- PAGE CONFIG ---
st.set_page_config(page_title="SSL Academy Tracker", layout="wide", page_icon="⚽")

# --- API ENDPOINTS ---
URL_ALL_PLAYERS = 'https://api.simulationsoccer.com/player/getAllPlayers?active=true'
URL_OUTFIELD = 'https://api.simulationsoccer.com/index/academyOutfield?season=25'
URL_KEEPER = 'https://api.simulationsoccer.com/index/academyKeeper?season=25'
URL_TPE_HIST = 'https://api.simulationsoccer.com/player/getTPEhistory'

# --- DATA FETCHING & CACHING ---
@st.cache_data(ttl=3600) 
def get_academy_humans():
    outfield = requests.get(URL_OUTFIELD).json()
    keepers = requests.get(URL_KEEPER).json()
    
    # Combine and filter out NPCs (Legends)
    all_academy = outfield + keepers
    humans = [p for p in all_academy if 'legend' not in p.get('name', '').lower()]
    return pd.DataFrame(humans)

@st.cache_data(ttl=3600)
def get_all_active_players():
    players = requests.get(URL_ALL_PLAYERS).json()
    return pd.DataFrame(players)

@st.cache_data(ttl=3600)
def get_tpe_history(player_name):
    res = requests.get(f"{URL_TPE_HIST}?name={player_name}")
    if res.status_code == 200:
        return res.json()
    return []

def calculate_earn_rate(history_data, days=30):
    """Calculates how much TPE a player earned in the last X days, ignoring starting TPE."""
    if not history_data:
        return 0
        
    try:
        # Sort the history chronologically (oldest first) so we can isolate the starting TPE
        sorted_hist = sorted(history_data, key=lambda x: datetime.strptime(x['Time'], '%Y-%m-%d %H:%M:%S'))
    except Exception:
        # Fallback just in case there's a weird date formatting issue from the API
        sorted_hist = history_data 

    cutoff_date = datetime.now() - timedelta(days=days)
    earned = 0
    
    for i, entry in enumerate(sorted_hist):
        # 1. Skip the very first entry in their history (their starting TPE)
        if i == 0:
            continue
            
        # 2. Skip any source explicitly labeled as initial or creation
        source = str(entry.get('Source', '')).lower()
        if 'initial' in source or 'creation' in source:
            continue
            
        try:
            entry_date = datetime.strptime(entry['Time'], '%Y-%m-%d %H:%M:%S')
            # 3. Only count it if it was actually earned within our timeframe
            if entry_date >= cutoff_date:
                earned += entry.get('TPE Change', 0)
        except Exception:
            pass
            
    return earned

# --- MAIN APP LOGIC ---
st.title("⚽ SSL Academy Tracker")

# 1. Fetch the data
with st.spinner("Fetching live data from SSL APIs..."):
    df_academy = get_academy_humans()
    df_all = get_all_active_players()

if df_academy.empty or df_all.empty:
    st.error("Failed to load data. The season might not have started or the API is down.")
    st.stop()

# 2. Merge Data
df_merged = pd.merge(df_academy, df_all, on='name', how='inner')

# 3. Calculate TPE Earn Rates
if 'earn_rate_30d' not in st.session_state:
    earn_rates = []
    st.session_state.histories = {}
    
    progress_bar = st.progress(0, text="Calculating TPE earn rates for all players...")
    
    for i, row in df_merged.iterrows():
        hist = get_tpe_history(row['name'])
        st.session_state.histories[row['name']] = hist
        rate = calculate_earn_rate(hist, days=30)
        earn_rates.append(rate)
        progress_bar.progress((i + 1) / len(df_merged), text=f"Fetching history for {row['name']}...")
        
    df_merged['earn_rate_30d'] = earn_rates
    st.session_state.df_merged = df_merged
    progress_bar.empty()
else:
    df_merged = st.session_state.df_merged

# --- UI TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["🏆 Leaderboards", "📊 Team TPE Overview", "🧠 Team Attributes", "📈 Player Deep Dive"])

with tab1:
    st.header("Rookie TPE Leaderboards")
    st.write("See who has been grinding the hardest over the last 30 days (excluding starting TPE).")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("🔥 Top 10 Earners")
        top_earners = df_merged[['name', 'club', 'tpe', 'earn_rate_30d']].sort_values(by='earn_rate_30d', ascending=False).reset_index(drop=True)
        st.dataframe(top_earners.head(10), use_container_width=True, hide_index=True)
        
    with col2:
        st.subheader("All Academy Players")
        display_cols = ['name', 'club', 'position_y', 'tpe', 'earn_rate_30d', 'apps', 'average rating']
        display_cols = [c for c in display_cols if c in df_merged.columns]
        st.dataframe(df_merged[display_cols].sort_values('tpe', ascending=False), use_container_width=True, hide_index=True)

with tab2:
    st.header("Team TPE Overview")
    
    team_stats = df_merged.groupby('club').agg(
        Total_TPE=('tpe', 'sum'),
        Average_TPE=('tpe', 'mean'),
        Total_Earn_Rate=('earn_rate_30d', 'sum'),
        Average_Earn_Rate=('earn_rate_30d', 'mean'),
        Human_Players=('name', 'count')
    ).reset_index()
    
    c1, c2 = st.columns(2)
    with c1:
        fig1 = px.bar(team_stats, x='club', y='Total_TPE', title="Total TPE by Team", color='club', text_auto='.0f')
        fig1.update_layout(showlegend=False)
        st.plotly_chart(fig1, use_container_width=True)
        
        fig3 = px.bar(team_stats, x='club', y='Total_Earn_Rate', title="Total TPE Earned (Last 30 Days)", color='club', text_auto='.0f')
        fig3.update_layout(showlegend=False)
        st.plotly_chart(fig3, use_container_width=True)

    with c2:
        fig2 = px.bar(team_stats, x='club', y='Average_TPE', title="Average TPE per Player", color='club', text_auto='.0f')
        fig2.update_layout(showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)
        
        fig4 = px.bar(team_stats, x='club', y='Average_Earn_Rate', title="Average Earn Rate (Last 30 Days)", color='club', text_auto='.1f')
        fig4.update_layout(showlegend=False)
        st.plotly_chart(fig4, use_container_width=True)

with tab3:
    st.header("Team DNA & Attributes")
    st.write("Averaged attributes for the human players on each academy team.")
    
    attributes = ['pace', 'stamina', 'strength', 'passing', 'tackling', 'finishing', 'dribbling', 'positioning', 'work rate']
    
    team_attr = df_merged.groupby('club')[attributes].mean().reset_index()
    
    st.dataframe(team_attr.style.format({col: "{:.1f}" for col in attributes}), use_container_width=True, hide_index=True)
    
    st.subheader("🧬 Attribute Comparison Radar")
    selected_teams = st.multiselect("Select Teams to Compare", options=team_attr['club'].unique(), default=team_attr['club'].unique()[:2])
    
    if selected_teams:
        fig_radar = go.Figure()
        for team in selected_teams:
            team_data = team_attr[team_attr['club'] == team][attributes].values[0]
            fig_radar.add_trace(go.Scatterpolar(
                r=team_data,
                theta=attributes,
                fill='toself',
                name=team
            ))
        fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[5, 20])), showlegend=True)
        st.plotly_chart(fig_radar, use_container_width=True)

with tab4:
    st.header("Player Deep Dive")
    
    selected_player = st.selectbox("Search for a Player", options=df_merged['name'].sort_values())
    
    if selected_player:
        player_data = df_merged[df_merged['name'] == selected_player].iloc[0]
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current TPE", player_data['tpe'])
        c2.metric("30-Day Earn Rate", player_data['earn_rate_30d'])
        c3.metric("Team", player_data['club'])
        pos = player_data.get('position_y', player_data.get('position', 'Unknown'))
        c4.metric("Position", pos)
        
        st.subheader("TPE Growth Timeline")
        hist_data = st.session_state.histories.get(selected_player, [])
        
        if hist_data:
            df_hist = pd.DataFrame(hist_data)
            df_hist['Time'] = pd.to_datetime(df_hist['Time'])
            df_hist = df_hist.sort_values('Time')
            
            fig_hist = px.bar(df_hist, x='Time', y='TPE Change', color='Source', title=f"{selected_player}'s TPE Claims")
            st.plotly_chart(fig_hist, use_container_width=True)
        else:
            st.info("No TPE history found for this player yet.")