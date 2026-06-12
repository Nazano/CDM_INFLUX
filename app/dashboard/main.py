from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from app.dashboard.data_access import (
    analyze_match_videos,
    fetch_videos_for_match,
    get_dashboard_repository,
    get_ranked_consensus,
)


def run() -> None:
    st.set_page_config(page_title="CDM_INFLUX", layout="wide")
    repository = get_dashboard_repository()
    page = st.sidebar.radio(
        "Navigation",
        [
            "Vue d'ensemble",
            "Planning CDM",
            "Vidéos par match",
            "Explorateur de vidéos",
            "Détail d'une vidéo",
            "Comparateur de créateurs",
            "Pronos par match",
            "Fiabilité",
        ],
    )

    if page == "Vue d'ensemble":
        render_overview(repository)
    elif page == "Planning CDM":
        render_schedule(repository)
    elif page == "Vidéos par match":
        render_match_videos(repository)
    elif page == "Explorateur de vidéos":
        render_video_explorer(repository)
    elif page == "Détail d'une vidéo":
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


def render_schedule(repository) -> None:
    st.title("📅 Planning CDM 2026")
    matches = repository.get_matches()
    if not matches:
        st.info("Aucun match dans la base. Redémarrez l'application pour charger le calendrier.")
        return

    df = pd.DataFrame(matches)
    df["scheduled_at"] = pd.to_datetime(df["scheduled_at"], utc=True, errors="coerce")
    df["date"] = df["scheduled_at"].dt.strftime("%d/%m/%Y %H:%M")
    df["match"] = df["home_team"].fillna("TBD") + " vs " + df["away_team"].fillna("TBD")
    df["is_past"] = df["is_past"].astype(bool)

    stages = ["Tous"] + sorted(df["tournament_stage"].dropna().unique().tolist())
    selected_stage = st.selectbox("Phase", stages)
    if selected_stage != "Tous":
        df = df[df["tournament_stage"] == selected_stage]

    tab_upcoming, tab_past = st.tabs(["⬇️ À venir", "✅ Terminés"])

    with tab_upcoming:
        upcoming = df[~df["is_past"]].copy()
        if upcoming.empty:
            st.info("Aucun match à venir dans la sélection.")
        else:
            display_cols = ["date", "tournament_stage", "match", "video_count"]
            st.dataframe(
                upcoming[display_cols].rename(columns={
                    "date": "Date (heure locale)",
                    "tournament_stage": "Phase",
                    "match": "Match",
                    "video_count": "Vidéos",
                }),
                use_container_width=True,
                hide_index=True,
            )

    with tab_past:
        past = df[df["is_past"]].copy()
        if past.empty:
            st.info("Aucun match passé dans la sélection.")
        else:
            display_cols = ["date", "tournament_stage", "match", "video_count"]
            st.dataframe(
                past[display_cols].rename(columns={
                    "date": "Date (heure locale)",
                    "tournament_stage": "Phase",
                    "match": "Match",
                    "video_count": "Vidéos",
                }),
                use_container_width=True,
                hide_index=True,
            )


def render_match_videos(repository) -> None:
    st.title("🎬 Vidéos par match")
    matches = repository.get_matches()
    if not matches:
        st.info("Aucun match disponible. Chargez d'abord le calendrier.")
        return

    match_options = {
        f"{m['home_team'] or 'TBD'} vs {m['away_team'] or 'TBD'} ({m['tournament_stage']})": m["id"]
        for m in matches
        if (m.get("home_team") or "TBD") != "À déterminer"
    }
    if not match_options:
        st.info("Aucun match avec des équipes connues.")
        return

    selected_label = st.selectbox("Sélectionner un match", list(match_options.keys()))
    match_id = match_options[selected_label]
    selected_match = next(m for m in matches if m["id"] == match_id)

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        home = selected_match.get("home_team") or "TBD"
        away = selected_match.get("away_team") or "TBD"
        st.metric("Match", f"{home} vs {away}")
    with col2:
        st.metric("Phase", selected_match["tournament_stage"])
    with col3:
        st.metric("Vidéos liées", selected_match.get("video_count", 0))

    st.divider()

    # Fetch button
    with st.expander("🔍 Rechercher des vidéos YouTube pour ce match", expanded=False):
        max_results = st.slider("Résultats max par requête", 1, 10, 5)
        if st.button("Lancer la recherche YouTube (FR + EN)"):
            with st.spinner("Recherche en cours…"):
                count = fetch_videos_for_match(match_id, max_results)
            if count > 0:
                st.success(f"{count} vidéo(s) trouvée(s) et enregistrée(s).")
                st.rerun()
            else:
                st.warning("Aucune vidéo trouvée. Vérifiez votre clé API YouTube dans le fichier .env")

    # List videos for this match
    videos = repository.list_videos_for_match(match_id)

    if not videos:
        st.info("Aucune vidéo liée à ce match. Utilisez le bouton ci-dessus pour chercher des vidéos.")
        return

    st.subheader(f"🎥 {len(videos)} vidéo(s) trouvée(s)")

    videos_df = pd.DataFrame(videos)
    videos_df["publish_date"] = pd.to_datetime(videos_df["publish_date"], errors="coerce")
    videos_df["date"] = videos_df["publish_date"].dt.strftime("%d/%m/%Y")
    videos_df["pertinence"] = (videos_df["relevance_score"] * 100).round(0).astype(int).astype(str) + "%"
    videos_df["lien"] = videos_df["video_url"]

    # Color-code relevance
    def relevance_label(score: float) -> str:
        if score >= 0.6:
            return "🟢 Haute"
        if score >= 0.3:
            return "🟡 Moyenne"
        return "🔴 Faible"

    videos_df["pertinence_label"] = videos_df["relevance_score"].apply(relevance_label)

    display_cols = ["title", "channel_name", "language", "date", "pertinence_label", "transcript_status", "video_url"]
    st.dataframe(
        videos_df[display_cols].rename(columns={
            "title": "Titre",
            "channel_name": "Chaîne",
            "language": "Langue",
            "date": "Publication",
            "pertinence_label": "Pertinence",
            "transcript_status": "Transcript",
            "video_url": "URL",
        }),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()
    st.subheader("⚙️ Analyser les transcripts")

    col_sel, col_btn = st.columns([3, 1])
    with col_sel:
        selected_video_ids = st.multiselect(
            "Choisir les vidéos à analyser (vide = toutes)",
            options=videos_df["id"].tolist(),
            format_func=lambda vid: videos_df.set_index("id").loc[vid, "title"] if vid in videos_df["id"].values else vid,
        )
    with col_btn:
        st.write("")
        st.write("")
        if st.button("🚀 Lancer l'analyse"):
            target_ids = selected_video_ids if selected_video_ids else None
            with st.spinner("Extraction des transcripts et des pronostics…"):
                result = analyze_match_videos(match_id, target_ids)
            st.success(
                f"✅ {result['transcripts']} transcript(s) extrait(s), "
                f"{result['predictions']} pronostic(s) identifié(s)."
            )
