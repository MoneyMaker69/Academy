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

def calculate_earn_rate(history_data, days=None):
    if not history_data:
        return 0
    try:
        sorted_hist = sorted(history_data, key=lambda x: datetime.strptime(x['Time'], '%Y-%m-%d %H:%M:%S'))
    except Exception:
        sorted_hist = history_data 

    if days is not None:
        cutoff_date = datetime.now() - timedelta(days=days)
    else:
        cutoff_date = datetime.min
        
    earned = 0
    for i, entry in enumerate(sorted_hist):
        change = entry.get('TPE Change', 0)
        source = str(entry.get('Source', '')).lower()
        
        # Exclude the very first entry, anything labeled initial, OR any massive lumps sums (safety net)
        if i == 0 or 'initial' in source or 'creation' in source or change >= 150:
            continue
            
        try:
            entry_date = datetime.strptime(entry['Time'], '%Y-%m-%d %H:%M:%S')
            if entry_date >= cutoff_date:
                earned += change
        except Exception:
            pass
    return earned

# --- SIDEBAR SETTINGS ---
st.sidebar.image("https://simulationsoccer.com/images/ssl_logo.png", width=150) # Optional: Adds a logo if the URL works
st.sidebar.header("⚙️ Dashboard Settings")

timeframe_str = st.sidebar.radio(
    "Select TPE Earn Timeframe:", 
    ["Last 7 Days", "Last 30 Days", "All Time"], 
    index=1
)

st.sidebar.info("📌 **Note:** This timeframe ONLY affects TPE Earn Rates. Match stats, Team attributes, and Total TPE always display current season totals.")

if timeframe_str == "Last 7 Days":
    days_filter = 7
elif timeframe_str == "Last 30 Days":
    days_filter = 30
else:
    days_filter = None

# --- MAIN APP LOGIC ---
st.title("⚽ SSL Academy Tracker")

with st.spinner("Fetching live data from SSL APIs..."):
    df_academy = get_academy_humans()
    df_all = get_all_active_players()

if df_academy.empty or df_all.empty:
    st.error("Failed to load data. The season might not have started or the API is down.")
    st.stop()

# Fill missing numeric stats with 0 safely
numeric_cols = df_academy.select_dtypes(include=['number']).columns
df_academy[numeric_cols] = df_academy[numeric_cols].fillna(0)

# Merge Data & Remove Duplicates
df_merged = pd.merge(df_academy, df_all, on='name', how='inner')
df_merged = df_merged.drop_duplicates(subset=['name'], keep='first')

# Position Cleanup
df_merged['Position'] = df_merged.apply(lambda row: row.get('position_y', row.get('position', 'Unknown')), axis=1)

# Fetch Histories
if 'histories' not in st.session_state:
    st.session_state.histories = {}
    progress_bar = st.progress(0, text="Fetching TPE histories for all players...")
    for i, row in df_merged.iterrows():
        hist = get_tpe_history(row['name'])
        st.session_state.histories[row['name']] = hist
        progress_bar.progress((i + 1) / len(df_merged), text=f"Fetching history for {row['name']}...")
    progress_bar.empty()

# Calculate dynamic earn rate
dynamic_earn_rates = []
for i, row in df_merged.iterrows():
    hist = st.session_state.histories.get(row['name'], [])
    rate = calculate_earn_rate(hist, days=days_filter)
    dynamic_earn_rates.append(rate)
df_merged['Earned_TPE'] = dynamic_earn_rates

# --- BUILD TIMELINE DATA FOR LINE GRAPHS ---
timeline_records = []
for p_name, hist in st.session_state.histories.items():
    if p_name in df_merged['name'].values:
        team = df_merged[df_merged['name'] == p_name]['club'].iloc[0]
        sorted_hist = sorted(hist, key=lambda x: datetime.strptime(x['Time'], '%Y-%m-%d %H:%M:%S')) if hist else []
        for i, entry in enumerate(sorted_hist):
            try:
                dt = datetime.strptime(entry['Time'], '%Y-%m-%d %H:%M:%S')
                change = entry.get('TPE Change', 0)
                source = str(entry.get('Source', '')).lower()
                is_initial = (i == 0) or ('initial' in source) or ('creation' in source) or (change >= 150)
                timeline_records.append({
                    'Player': p_name, 'Team': team, 'Date': dt, 
                    'Week_Start': dt - timedelta(days=dt.weekday()), 
                    'Change': change, 'Is_Initial': is_initial
                })
            except: pass

df_hist = pd.DataFrame(timeline_records)

team_timeline_data = []
if not df_hist.empty:
    df_hist['Week_Start'] = pd.to_datetime(df_hist['Week_Start']).dt.date
    weeks = sorted(df_hist['Week_Start'].dropna().unique())
    teams = df_merged['club'].unique()
    
    for team in teams:
        team_players = df_merged[df_merged['club'] == team]
        current_team_tpe = team_players['tpe'].sum()
        num_players = len(team_players)
        team_hist = df_hist[df_hist['Team'] == team]
        
        for w in weeks:
            gain = team_hist[(team_hist['Week_Start'] == w) & (~team_hist['Is_Initial'])]['Change'].sum()
            end_of_week = pd.to_datetime(w) + pd.Timedelta(days=6, hours=23, minutes=59, seconds=59)
            future_changes = team_hist[team_hist['Date'] > end_of_week]['Change'].sum()
            total_tpe = current_team_tpe - future_changes
            avg_tpe = total_tpe / num_players if num_players > 0 else 0
            
            team_timeline_data.append({
                'Team': team, 'Week': w, 'Weekly Gain': gain, 
                'Total TPE': total_tpe, 'Average TPE': avg_tpe
            })

df_timeline = pd.DataFrame(team_timeline_data)


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
    st.header(f"Rookie TPE Leaderboards ({timeframe_str})")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("🔥 Top 10 Earners")
        top_earners = df_merged[['name', 'club', 'tpe', 'Earned_TPE']].sort_values(by='Earned_TPE', ascending=False).reset_index(drop=True)
        st.dataframe(top_earners.head(10), use_container_width=True, hide_index=True)
    with col2:
        st.subheader("All Academy Players")
        display_cols = ['name', 'club', 'Position', 'tpe', 'Earned_TPE', 'apps', 'average rating']
        st.dataframe(df_merged[display_cols].sort_values('tpe', ascending=False), use_container_width=True, hide_index=True)

with tab2:
    st.header("Team Rosters")
    selected_team = st.selectbox("Filter by Team:", options=sorted(df_merged['club'].unique()))
    roster_df = df_merged[df_merged['club'] == selected_team]
    display_cols = ['name', 'Position', 'tpe', 'Earned_TPE', 'apps', 'goals', 'assists', 'average rating']
    st.dataframe(roster_df[display_cols].sort_values('tpe', ascending=False), use_container_width=True, hide_index=True)

with tab3:
    st.header("Team TPE Overview")
    
    st.subheader(f"Current Snapshot ({timeframe_str})")
    team_stats = df_merged.groupby('club').agg(
        Total_TPE=('tpe', 'sum'),
        Average_TPE=('tpe', 'mean'),
        Total_Earn_Rate=('Earned_TPE', 'sum'),
        Average_Earn_Rate=('Earned_TPE', 'mean'),
    ).reset_index()
    c1, c2 = st.columns(2)
    with c1:
        fig1 = px.bar(team_stats, x='club', y='Total_TPE', title="Current Total TPE by Team", color='club', text_auto='.0f')
        st.plotly_chart(fig1, use_container_width=True)
        fig3 = px.bar(team_stats, x='club', y='Total_Earn_Rate', title=f"Total TPE Earned ({timeframe_str})", color='club', text_auto='.0f')
        st.plotly_chart(fig3, use_container_width=True)
    with c2:
        fig2 = px.bar(team_stats, x='club', y='Average_TPE', title="Current Average TPE per Player", color='club', text_auto='.0f')
        st.plotly_chart(fig2, use_container_width=True)
        fig4 = px.bar(team_stats, x='club', y='Average_Earn_Rate', title=f"Average Earn Rate ({timeframe_str})", color='club', text_auto='.1f')
        st.plotly_chart(fig4, use_container_width=True)

    st.markdown("---")

    st.subheader("Trends Over Time (Weekly)")
    if not df_timeline.empty:
        fig_line1 = px.line(df_timeline, x='Week', y='Total TPE', color='Team', markers=True, title='Total Team TPE (Progression Over Time)')
        st.plotly_chart(fig_line1, use_container_width=True)
        
        fig_line2 = px.line(df_timeline, x='Week', y='Average TPE', color='Team', markers=True, title='Average Team TPE (Progression Over Time)')
        st.plotly_chart(fig_line2, use_container_width=True)
        
        fig_line3 = px.line(df_timeline, x='Week', y='Weekly Gain', color='Team', markers=True, title='Weekly TPE Gain (Excluding Initial TPE)')
        st.plotly_chart(fig_line3, use_container_width=True)
    else:
        st.info("Not enough history data yet to build timelines.")

with tab4:
    st.header("Match Stats & Performance")
    active_players = df_merged[df_merged['apps'] > 0]
    colA, colB = st.columns(2)
    with colA:
        top_goals = active_players[['name', 'club', 'goals']].sort_values(by='goals', ascending=False).head(10)
        fig_goals = px.bar(top_goals, x='name', y='goals', color='club', title="Top Goal Scorers", text_auto=True)
        st.plotly_chart(fig_goals, use_container_width=True)
        
        top_rating = active_players[['name', 'club', 'average rating']].sort_values(by='average rating', ascending=False).head(10)
        fig_rating = px.bar(top_rating, x='name', y='average rating', color='club', title="Highest Average Ratings", text_auto=True)
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
                fig_radar.add_trace(go.Scatterpolar(r=team_data, theta=selected_attrs, fill='toself', name=team))
            fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[5, 15])), showlegend=True)
            st.plotly_chart(fig_radar, use_container_width=True)

with tab6:
    st.header("Player Deep Dive")
    selected_player = st.selectbox("Search for a Player", options=df_merged['name'].sort_values())
    if selected_player:
        player_data = df_merged[df_merged['name'] == selected_player].iloc[0]
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current TPE", player_data['tpe'])
        c2.metric(f"Earn Rate ({timeframe_str})", player_data['Earned_TPE'])
        c3.metric("Team", player_data['club'])
        c4.metric("Position", player_data['Position'])
        
        st.subheader("TPE Growth Timeline")
        hist_data = st.session_state.histories.get(selected_player, [])
        if hist_data:
            df_player_hist = pd.DataFrame(hist_data)
            df_player_hist['Date'] = pd.to_datetime(df_player_hist['Time']).dt.date
            df_player_hist = df_player_hist.sort_values('Date')
            
            fig_hist = px.bar(df_player_hist, x='Date', y='TPE Change', color='Source', title=f"{selected_player}'s TPE Claims")
            fig_hist.update_xaxes(type='category') 
            st.plotly_chart(fig_hist, use_container_width=True)
        else:
            st.info("No TPE history found for this player yet.")
