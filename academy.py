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
        sorted_hist = sorted(history_data, key=lambda x: datetime.strptime(x['Time'], '%Y-%m-%d %H:%M:%S'))
    except Exception:
        sorted_hist = history_data 

    cutoff_date = datetime.now() - timedelta(days=days)
    earned = 0
    
    for i, entry in enumerate(sorted_hist):
        if i == 0:
            continue
        source = str(entry.get('Source', '')).lower()
        if 'initial' in source or 'creation' in source:
            continue
        try:
            entry_date = datetime.strptime(entry['Time'], '%Y-%m-%d %H:%M:%S')
            if entry_date >= cutoff_date:
                earned += entry.get('TPE Change', 0)
        except Exception:
            pass
    return earned

# --- MAIN APP LOGIC ---
st.title("⚽ SSL Academy Tracker")

with st.spinner("Fetching live data from SSL APIs..."):
    df_academy = get_academy_humans()
    df_all = get_all_active_players()

if df_academy.empty or df_all.empty:
    st.error("Failed to load data. The season might not have started or the API is down.")
    st.stop()

# Fill missing stats with 0 (Keepers don't have goals, Outfielders don't have saves)
numeric_cols = df_academy.select_dtypes(include=['number']).columns
df_academy[numeric_cols] = df_academy[numeric_cols].fillna(0)

# 2. Merge Data
df_merged = pd.merge(df_academy, df_all, on='name', how='inner')

# Drop any duplicate players that the API accidentally sent us
df_merged = df_merged.drop_duplicates(subset=['name'], keep='first')

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

# Position Cleanup
df_merged['Position'] = df_merged.apply(lambda row: row.get('position_y', row.get('position', 'Unknown')), axis=1)

# --- UI TABS ---
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🏆 Leaderboards", 
    "📋 Team Rosters", 
    "📊 TPE Overview", 
    "⚽ Match Stats", 
    "🧠 Team Attributes", 
    "📈 Player Deep Dive"
])

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
        display_cols = ['name', 'club', 'Position', 'tpe', 'earn_rate_30d', 'apps', 'average rating']
        st.dataframe(df_merged[display_cols].sort_values('tpe', ascending=False), use_container_width=True, hide_index=True)

with tab2:
    st.header("Team Rosters")
    selected_team = st.selectbox("Filter by Team:", options=sorted(df_merged['club'].unique()))
    roster_df = df_merged[df_merged['club'] == selected_team]
    display_cols = ['name', 'Position', 'tpe', 'earn_rate_30d', 'apps', 'goals', 'assists', 'average rating']
    st.dataframe(roster_df[display_cols].sort_values('tpe', ascending=False), use_container_width=True, hide_index=True)

with tab3:
    st.header("Team TPE Overview")
    team_stats = df_merged.groupby('club').agg(
        Total_TPE=('tpe', 'sum'),
        Average_TPE=('tpe', 'mean'),
        Total_Earn_Rate=('earn_rate_30d', 'sum'),
        Average_Earn_Rate=('earn_rate_30d', 'mean'),
    ).reset_index()
    c1, c2 = st.columns(2)
    with c1:
        fig1 = px.bar(team_stats, x='club', y='Total_TPE', title="Total TPE by Team", color='club', text_auto='.0f')
        st.plotly_chart(fig1, use_container_width=True)
        fig3 = px.bar(team_stats, x='club', y='Total_Earn_Rate', title="Total TPE Earned (Last 30 Days)", color='club', text_auto='.0f')
        st.plotly_chart(fig3, use_container_width=True)
    with c2:
        fig2 = px.bar(team_stats, x='club', y='Average_TPE', title="Average TPE per Player", color='club', text_auto='.0f')
        st.plotly_chart(fig2, use_container_width=True)
        fig4 = px.bar(team_stats, x='club', y='Average_Earn_Rate', title="Average Earn Rate (Last 30 Days)", color='club', text_auto='.1f')
        st.plotly_chart(fig4, use_container_width=True)

with tab4:
    st.header("Match Stats & Performance")
    
    # Filter to players who have actually played
    active_players = df_merged[df_merged['apps'] > 0]
    
    colA, colB = st.columns(2)
    with colA:
        top_goals = active_players[['name', 'club', 'goals']].sort_values(by='goals', ascending=False).head(10)
        fig_goals = px.bar(top_goals, x='name', y='goals', color='club', title="Top Goal Scorers", text_auto=True)
        st.plotly_chart(fig_goals, use_container_width=True)
        
        top_rating = active_players[['name', 'club', 'average rating']].sort_values(by='average rating', ascending=False).head(10)
        fig_rating = px.bar(top_rating, x='name', y='average rating', color='club', title="Highest Average Ratings", text_auto=True)
        # Set y-axis to look better for ratings (e.g., 6.0 to 10)
        fig_rating.update_layout(yaxis=dict(range=[6, 10]))
        st.plotly_chart(fig_rating, use_container_width=True)

    with colB:
        top_assists = active_players[['name', 'club', 'assists']].sort_values(by='assists', ascending=False).head(10)
        fig_assists = px.bar(top_assists, x='name', y='assists', color='club', title="Top Assist Providers", text_auto=True)
        st.plotly_chart(fig_assists, use_container_width=True)
        
        if 'xg' in active_players.columns:
            top_xg = active_players[['name', 'club', 'xg']].sort_values(by='xg', ascending=False).head(10)
            fig_xg = px.bar(top_xg, x='name', y='xg', color='club', title="Highest Expected Goals (xG)", text_auto='.2f')
            st.plotly_chart(fig_xg, use_container_width=True)

with tab5:
    st.header("Team DNA & Attributes")
    st.write("Select the attributes you want to compare across the academy teams.")
    
    all_possible_attributes = sorted(['pace', 'stamina', 'strength', 'passing', 'tackling', 'finishing', 'dribbling', 'positioning', 'work rate', 'acceleration', 'agility', 'jumping reach', 'natural fitness', 'heading', 'marking', 'vision', 'technique', 'aggression', 'bravery', 'composure'])
    
    selected_attrs = st.multiselect("Select Attributes to Average", options=all_possible_attributes, default=['pace', 'stamina', 'passing', 'tackling', 'finishing'])
    
    if selected_attrs:
        team_attr = df_merged.groupby('club')[selected_attrs].mean().reset_index()
        st.dataframe(team_attr.style.format({col: "{:.1f}" for col in selected_attrs}), use_container_width=True, hide_index=True)
        
        st.subheader("🧬 Attribute Comparison Radar")
        selected_teams = st.multiselect("Select Teams to Compare on Radar Chart", options=team_attr['club'].unique(), default=team_attr['club'].unique()[:2])
        
        if selected_teams:
            fig_radar = go.Figure()
            for team in selected_teams:
                team_data = team_attr[team_attr['club'] == team][selected_attrs].values[0]
                fig_radar.add_trace(go.Scatterpolar(
                    r=team_data,
                    theta=selected_attrs,
                    fill='toself',
                    name=team
                ))
            fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[5, 15])), showlegend=True)
            st.plotly_chart(fig_radar, use_container_width=True)

with tab6:
    st.header("Player Deep Dive")
    selected_player = st.selectbox("Search for a Player", options=df_merged['name'].sort_values())
    
    if selected_player:
        player_data = df_merged[df_merged['name'] == selected_player].iloc[0]
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current TPE", player_data['tpe'])
        c2.metric("30-Day Earn Rate", player_data['earn_rate_30d'])
        c3.metric("Team", player_data['club'])
        c4.metric("Position", player_data['Position'])
        
        st.subheader("TPE Growth Timeline")
        hist_data = st.session_state.histories.get(selected_player, [])
        
        if hist_data:
            df_hist = pd.DataFrame(hist_data)
            # The Fix: Convert the exact timestamp to just the Date so bars stack correctly and have width
            df_hist['Date'] = pd.to_datetime(df_hist['Time']).dt.date
            df_hist = df_hist.sort_values('Date')
            
            fig_hist = px.bar(df_hist, x='Date', y='TPE Change', color='Source', title=f"{selected_player}'s TPE Claims")
            
            # Make sure the bars aren't tiny by forcing the x-axis to be categorical or adjusting the date layout
            fig_hist.update_xaxes(type='category') 
            
            st.plotly_chart(fig_hist, use_container_width=True)
        else:
            st.info("No TPE history found for this player yet.")
