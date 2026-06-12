from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from app.dashboard.data_access import get_dashboard_repository, get_ranked_consensus


def run() -> None:
    st.set_page_config(page_title="CDM_INFLUX", layout="wide")
    repository = get_dashboard_repository()
    page = st.sidebar.radio(
        "Navigation",
        [
            "Vue d’ensemble",
            "Explorateur de vidéos",
            "Détail d’une vidéo",
            "Comparateur de créateurs",
            "Pronos par match",
            "Fiabilité",
        ],
    )

    if page == "Vue d’ensemble":
        render_overview(repository)
    elif page == "Explorateur de vidéos":
        render_video_explorer(repository)
    elif page == "Détail d’une vidéo":
        render_video_detail(repository)
    elif page == "Comparateur de créateurs":
        render_creator_comparison(repository)
    elif page == "Pronos par match":
        render_match_consensus(repository)
    else:
        render_reliability(repository)


def render_overview(repository) -> None:
    st.title("CDM_INFLUX · Vue d’ensemble")
    metrics = repository.get_overview_metrics()
    col1, col2, col3 = st.columns(3)
    col1.metric("Chaînes suivies", metrics["channels"])
    col2.metric("Vidéos collectées", metrics["videos"])
    col3.metric("Pronostics extraits", metrics["predictions"])

    language_df = pd.DataFrame(metrics["languages"])
    if not language_df.empty:
        st.plotly_chart(px.bar(language_df, x="language", y="count", title="Répartition par langue"), use_container_width=True)


def render_video_explorer(repository) -> None:
    st.title("Explorateur de vidéos")
    channels = repository.list_channels()
    channel_options = {"Toutes": None, **{channel["name"]: channel["id"] for channel in channels}}
    language = st.selectbox("Langue", ["Toutes", "fr", "en", "es"])
    channel_name = st.selectbox("Chaîne", list(channel_options.keys()))
    team = st.text_input("Équipe")
    rows = repository.list_videos(
        language=None if language == "Toutes" else language,
        channel_id=channel_options[channel_name],
        team_filter=team or None,
    )
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)


def render_video_detail(repository) -> None:
    st.title("Détail d’une vidéo")
    videos = repository.list_videos()
    video_map = {f"{row['title']} ({row['channel_name']})": row["id"] for row in videos}
    if not video_map:
        st.info("Aucune vidéo disponible.")
        return
    selected_label = st.selectbox("Vidéo", list(video_map.keys()))
    payload = repository.get_video_detail(video_map[selected_label])
    if not payload:
        st.warning("Vidéo introuvable.")
        return
    st.subheader(payload["video"]["title"])
    st.write(payload["video"]["description"])
    st.json(payload["video"])
    if payload["transcript"]:
        st.subheader("Transcript")
        st.write(payload["transcript"].get("text") or "Transcript indisponible")
    if payload["prediction"]:
        st.subheader("Pronostics extraits")
        st.write(payload["prediction"]["summary"])
        st.dataframe(pd.DataFrame(payload["prediction_items"]), use_container_width=True)


def render_creator_comparison(repository) -> None:
    st.title("Comparateur de créateurs")
    rows = repository.get_creator_comparison()
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("Aucune donnée à comparer.")
        return
    st.dataframe(df, use_container_width=True)
    tournament_df = df[df["item_type"] == "tournament_winner"]
    if not tournament_df.empty:
        fig = px.histogram(tournament_df, x="value", color="creator_name", barmode="group", title="Comparatif des vainqueurs du tournoi")
        st.plotly_chart(fig, use_container_width=True)
    exact_scores_df = df[df["item_type"] == "exact_score"]
    if not exact_scores_df.empty:
        st.plotly_chart(px.bar(exact_scores_df, x="subject", y="confidence", color="creator_name", title="Comparatif des scores exacts"), use_container_width=True)


def render_match_consensus(repository) -> None:
    st.title("Pronos par match")
    consensus_df = pd.DataFrame(repository.get_match_consensus())
    ranked_df = pd.DataFrame(get_ranked_consensus(repository))
    if not consensus_df.empty:
        st.subheader("Agrégation brute")
        st.dataframe(consensus_df, use_container_width=True)
    if not ranked_df.empty:
        st.subheader("Consensus scoré")
        st.dataframe(ranked_df, use_container_width=True)
        st.plotly_chart(px.bar(ranked_df, x="subject", y="consensus_score", color="value", title="Consensus par match/pronostic"), use_container_width=True)


def render_reliability(repository) -> None:
    st.title("Fiabilité")
    reliability_df = pd.DataFrame(repository.get_creator_reliability())
    if reliability_df.empty:
        st.info("Aucune donnée de fiabilité disponible.")
        return
    st.dataframe(reliability_df, use_container_width=True)
    st.plotly_chart(
        px.scatter(
            reliability_df,
            x="historical_accuracy",
            y="avg_prediction_confidence",
            size="videos_count",
            color="creator_name",
            title="Score de précision des créateurs",
        ),
        use_container_width=True,
    )
