from __future__ import annotations

import html

import pandas as pd
import plotly.express as px
import streamlit as st

from app.dashboard.data_access import (
    analyze_match_videos,
    fetch_videos_for_match,
    get_dashboard_repository,
    get_ranked_consensus,
)

_CARD_STYLE = {
    "not_started": {"label": "Pas analysé", "badge": "⚪", "border": "#94A3B8", "background": "#F8FAFC"},
    "videos_found": {"label": "Vidéos récupérées", "badge": "🟡", "border": "#F59E0B", "background": "#FFFBEB"},
    "partial": {"label": "Analyse partielle", "badge": "🟠", "border": "#F97316", "background": "#FFF7ED"},
    "analyzed": {"label": "Analysé", "badge": "🟢", "border": "#22C55E", "background": "#F0FDF4"},
}

_FIFA_TO_ISO2 = {
    "ALG": "DZ",
    "ARG": "AR",
    "AUS": "AU",
    "AUT": "AT",
    "BEL": "BE",
    "BOL": "BO",
    "BRA": "BR",
    "CAN": "CA",
    "CHI": "CL",
    "CMR": "CM",
    "COL": "CO",
    "CRC": "CR",
    "CRO": "HR",
    "CZE": "CZ",
    "DEN": "DK",
    "ECU": "EC",
    "EGY": "EG",
    "ENG": "GB",
    "ESP": "ES",
    "FRA": "FR",
    "GER": "DE",
    "HON": "HN",
    "IRN": "IR",
    "ITA": "IT",
    "JAM": "JM",
    "JPN": "JP",
    "KOR": "KR",
    "KSA": "SA",
    "MAR": "MA",
    "MEX": "MX",
    "NED": "NL",
    "NGA": "NG",
    "NZL": "NZ",
    "PAN": "PA",
    "PER": "PE",
    "POL": "PL",
    "POR": "PT",
    "QAT": "QA",
    "ROU": "RO",
    "SEN": "SN",
    "SLV": "SV",
    "SRB": "RS",
    "SUI": "CH",
    "TUR": "TR",
    "UKR": "UA",
    "URU": "UY",
    "USA": "US",
    "VEN": "VE",
}

_ADVANCED_PAGES = [
    "Explorateur de vidéos",
    "Détail d’une vidéo",
    "Comparateur de créateurs",
    "Pronos par match",
    "Fiabilité",
]


def run() -> None:
    st.set_page_config(page_title="CDM_INFLUX", layout="wide")
    repository = get_dashboard_repository()
    selected_match_id = st.query_params.get("match")
    pages = ["Landing page", "Détail match", *_ADVANCED_PAGES]
    default_page = "Détail match" if selected_match_id else "Landing page"
    page = st.sidebar.radio(
        "Navigation",
        pages,
        index=pages.index(default_page),
        key=f"navigation-{selected_match_id or 'home'}",
    )

    if page == "Landing page":
        render_landing_page(repository)
    elif page == "Détail match":
        render_match_detail(repository, selected_match_id)
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


def render_landing_page(repository) -> None:
    st.title("CDM_INFLUX · Match center")
    matches = repository.get_matches()
    if not matches:
        st.info("Aucun match disponible pour le moment.")
        return

    metrics = repository.get_overview_metrics()
    total_analyzed = sum(1 for match in matches if _get_match_state(match) == "analyzed")
    total_pending = sum(1 for match in matches if _get_match_state(match) == "not_started")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Matchs", len(matches))
    col2.metric("Matchs analysés", total_analyzed)
    col3.metric("Matchs à lancer", total_pending)
    col4.metric("Vidéos collectées", metrics["videos"])

    filter_col1, filter_col2 = st.columns([2, 1])
    with filter_col1:
        stages = ["Toutes"] + sorted({match["tournament_stage"] for match in matches if match.get("tournament_stage")})
        selected_stage = st.selectbox("Phase", stages)
    with filter_col2:
        selected_status = st.selectbox(
            "Statut",
            ["Tous", "Pas analysé", "Vidéos récupérées", "Analyse partielle", "Analysé"],
        )

    filtered_matches = []
    for match in matches:
        state = _get_match_state(match)
        if selected_stage != "Toutes" and match["tournament_stage"] != selected_stage:
            continue
        if selected_status != "Tous" and _CARD_STYLE[state]["label"] != selected_status:
            continue
        filtered_matches.append(match)

    _render_status_legend()
    if not filtered_matches:
        st.info("Aucun match ne correspond aux filtres.")
        return

    for start in range(0, len(filtered_matches), 3):
        columns = st.columns(3)
        for column, match in zip(columns, filtered_matches[start:start + 3]):
            with column:
                render_match_card(match)


def render_match_card(match: dict) -> None:
    st.markdown(_build_match_card_html(match), unsafe_allow_html=True)
    detail_col, run_col = st.columns(2)
    with detail_col:
        if st.button("Voir les détails", key=f"details-{match['id']}", use_container_width=True):
            _open_match_detail(match["id"])
    with run_col:
        if st.button("▶ Run", key=f"run-card-{match['id']}", use_container_width=True):
            _run_match_pipeline(match["id"])


def render_match_detail(repository, selected_match_id: str | None = None) -> None:
    st.title("Détail match")
    matches = repository.get_matches()
    if not matches:
        st.info("Aucun match disponible.")
        return

    match_map = {match["id"]: match for match in matches}
    selectable_matches = {
        f"{match.get('home_team') or 'TBD'} vs {match.get('away_team') or 'TBD'} · {match['tournament_stage']}": match["id"]
        for match in matches
    }

    if selected_match_id not in match_map:
        selected_label = st.selectbox("Sélectionner un match", list(selectable_matches.keys()))
        selected_match_id = selectable_matches[selected_label]

    selected_match = match_map[selected_match_id]

    action_col, back_col = st.columns([1, 1])
    with action_col:
        if st.button("▶ Run ce match", key=f"run-detail-{selected_match_id}", use_container_width=True):
            _run_match_pipeline(selected_match_id)
    with back_col:
        if st.button("← Retour à l’accueil", use_container_width=True):
            st.query_params.clear()
            st.rerun()

    st.markdown(_build_match_detail_header(selected_match), unsafe_allow_html=True)

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("Statut", _CARD_STYLE[_get_match_state(selected_match)]["label"])
    metric_col2.metric("Vidéos liées", selected_match.get("video_count", 0))
    metric_col3.metric("Vidéos analysées", selected_match.get("analyzed_video_count", 0))
    metric_col4.metric("Score prédit", selected_match.get("predicted_score") or "—")

    render_match_videos(repository, preselected_match_id=selected_match_id)


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
    if not df.empty and "processed_at" in df.columns:
        df["processed_at"] = pd.to_datetime(df["processed_at"], errors="coerce")
        df["Analysé le"] = df["processed_at"].dt.strftime("%d/%m/%Y %H:%M")
    st.dataframe(df, use_container_width=True)


def render_video_detail(repository) -> None:
    st.title("Détail d’une vidéo")
    videos = repository.list_videos()
    if not videos:
        st.info("Aucune vidéo disponible.")
        return

    def _video_label(row: dict) -> str:
        label = f"{row['title']} ({row['channel_name']})"
        if row.get("processed_at"):
            try:
                import datetime as _dt
                ts = _dt.datetime.fromisoformat(str(row["processed_at"]))
                label += f" — analysé le {ts.strftime('%d/%m/%Y %H:%M')}"
            except Exception:
                pass
        return label

    video_map = {_video_label(row): row["id"] for row in videos}
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


def render_match_videos(repository, preselected_match_id: str | None = None) -> None:
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

    default_index = 0
    if preselected_match_id and preselected_match_id in match_options.values():
        default_index = list(match_options.values()).index(preselected_match_id)

    selected_label = st.selectbox("Match", list(match_options.keys()), index=default_index, key=f"match-select-{preselected_match_id or 'default'}")
    match_id = match_options[selected_label]
    selected_match = next(m for m in matches if m["id"] == match_id)

    st.divider()
    st.subheader("Recherche et analyse")

    with st.expander("🔍 Rechercher des vidéos YouTube pour ce match", expanded=False):
        max_results = st.slider("Résultats max par requête", 1, 10, 5, key=f"search-limit-{match_id}")
        if st.button("Lancer la recherche YouTube (FR + EN)", key=f"search-{match_id}"):
            with st.spinner("Recherche en cours…"):
                count = fetch_videos_for_match(match_id, max_results)
            if count > 0:
                st.success(f"{count} vidéo(s) trouvée(s) et enregistrée(s).")
                _open_match_detail(match_id)
            else:
                st.warning("Aucune vidéo trouvée. Vérifiez la clé API YouTube ou la disponibilité des résultats.")

    videos = repository.list_videos_for_match(match_id)
    if not videos:
        st.info("Aucune vidéo liée à ce match. Utilisez le bouton Run ou lancez une recherche ciblée.")
        return

    st.subheader(f"🎥 {len(videos)} vidéo(s) trouvée(s)")
    videos_df = pd.DataFrame(videos)
    videos_df["publish_date"] = pd.to_datetime(videos_df["publish_date"], errors="coerce")
    videos_df["date"] = videos_df["publish_date"].dt.strftime("%d/%m/%Y")
    videos_df["processed_at"] = pd.to_datetime(videos_df["processed_at"], errors="coerce")
    videos_df["analysed_le"] = videos_df["processed_at"].dt.strftime("%d/%m/%Y %H:%M")

    def relevance_label(score: float) -> str:
        if score >= 0.6:
            return "🟢 Haute"
        if score >= 0.3:
            return "🟡 Moyenne"
        return "🔴 Faible"

    videos_df["pertinence_label"] = videos_df["relevance_score"].apply(relevance_label)

    st.dataframe(
        videos_df[["title", "channel_name", "language", "date", "analysed_le", "pertinence_label", "transcript_status", "video_url"]].rename(columns={
            "title": "Titre",
            "channel_name": "Chaîne",
            "language": "Langue",
            "date": "Publication",
            "analysed_le": "Analysé le",
            "pertinence_label": "Pertinence",
            "transcript_status": "Transcript",
            "video_url": "URL",
        }),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()
    st.subheader("⚙️ Analyser les transcripts")
    st.caption(f"Score prédit actuel : {selected_match.get('predicted_score') or 'emplacement disponible'}")

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
        if st.button("🚀 Lancer l'analyse", key=f"analyze-{match_id}", use_container_width=True):
            target_ids = selected_video_ids if selected_video_ids else None
            with st.spinner("Extraction des transcripts et des pronostics…"):
                result = analyze_match_videos(match_id, target_ids)
            st.success(
                f"✅ {result['transcripts']} transcript(s) extrait(s), "
                f"{result['predictions']} pronostic(s) identifié(s)."
            )
            _open_match_detail(match_id)


def _run_match_pipeline(match_id: str) -> None:
    with st.spinner("Récupération des vidéos et analyse en cours…"):
        fetched_count = fetch_videos_for_match(match_id, 5)
        result = analyze_match_videos(match_id)
    st.success(
        f"Run terminé : {fetched_count} vidéo(s) récupérée(s), "
        f"{result['transcripts']} transcript(s) extrait(s), "
        f"{result['predictions']} pronostic(s) détecté(s)."
    )
    _open_match_detail(match_id)


def _open_match_detail(match_id: str) -> None:
    st.query_params.clear()
    st.query_params["match"] = match_id
    st.rerun()


def _get_match_state(match: dict) -> str:
    video_count = int(match.get("video_count") or 0)
    analyzed_count = int(match.get("analyzed_video_count") or 0)
    predicted_count = int(match.get("predicted_video_count") or 0)

    if predicted_count and analyzed_count >= video_count > 0:
        return "analyzed"
    if analyzed_count > 0:
        return "partial"
    if video_count > 0:
        return "videos_found"
    return "not_started"


def _build_match_card_html(match: dict) -> str:
    state = _CARD_STYLE[_get_match_state(match)]
    home_team = match.get("home_team") or "TBD"
    away_team = match.get("away_team") or "TBD"
    home_flag = _flag_emoji(match.get("home_team_code"))
    away_flag = _flag_emoji(match.get("away_team_code"))
    date_label = _format_match_datetime(match.get("scheduled_at"))
    predicted_score = match.get("predicted_score") or "—"
    href = f"?match={html.escape(match['id'])}"
    return f"""
    <a href="{href}" style="text-decoration:none;color:inherit;">
        <div style="
            background:{state['background']};
            border:2px solid {state['border']};
            border-radius:18px;
            padding:18px 18px 10px 18px;
            min-height:270px;
            box-shadow:0 8px 24px rgba(15, 23, 42, 0.08);
            margin-bottom:0.5rem;
        ">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
                <span style="font-size:0.9rem;font-weight:700;color:#0F172A;">{html.escape(match['tournament_stage'])}</span>
                <span style="
                    display:inline-flex;
                    align-items:center;
                    gap:6px;
                    background:white;
                    border-radius:999px;
                    padding:6px 10px;
                    color:#0F172A;
                    font-size:0.85rem;
                    font-weight:600;
                ">{state['badge']} {state['label']}</span>
            </div>
            <div style="margin-top:18px;display:grid;gap:14px;">
                <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
                    <div>
                        <div style="font-size:2rem;">{home_flag}</div>
                        <div style="font-size:1.05rem;font-weight:700;color:#0F172A;">{html.escape(home_team)}</div>
                    </div>
                    <div style="font-size:1.2rem;font-weight:800;color:#475569;">VS</div>
                    <div style="text-align:right;">
                        <div style="font-size:2rem;">{away_flag}</div>
                        <div style="font-size:1.05rem;font-weight:700;color:#0F172A;">{html.escape(away_team)}</div>
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div style="background:rgba(255,255,255,0.82);border-radius:14px;padding:12px;">
                        <div style="font-size:0.8rem;color:#475569;">Date</div>
                        <div style="font-weight:700;color:#0F172A;">{html.escape(date_label)}</div>
                    </div>
                    <div style="background:rgba(255,255,255,0.82);border-radius:14px;padding:12px;">
                        <div style="font-size:0.8rem;color:#475569;">Score prédit</div>
                        <div style="font-weight:700;color:#0F172A;">{html.escape(predicted_score)}</div>
                    </div>
                    <div style="background:rgba(255,255,255,0.82);border-radius:14px;padding:12px;">
                        <div style="font-size:0.8rem;color:#475569;">Vidéos</div>
                        <div style="font-weight:700;color:#0F172A;">{int(match.get('video_count') or 0)}</div>
                    </div>
                    <div style="background:rgba(255,255,255,0.82);border-radius:14px;padding:12px;">
                        <div style="font-size:0.8rem;color:#475569;">Analysées</div>
                        <div style="font-weight:700;color:#0F172A;">{int(match.get('analyzed_video_count') or 0)}</div>
                    </div>
                </div>
            </div>
        </div>
    </a>
    """


def _build_match_detail_header(match: dict) -> str:
    state = _CARD_STYLE[_get_match_state(match)]
    home_team = match.get("home_team") or "TBD"
    away_team = match.get("away_team") or "TBD"
    return f"""
    <div style="
        background:{state['background']};
        border:2px solid {state['border']};
        border-radius:20px;
        padding:20px;
        margin:0.5rem 0 1rem 0;
    ">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
            <div style="font-size:1.6rem;font-weight:800;color:#0F172A;">
                {_flag_emoji(match.get("home_team_code"))} {html.escape(home_team)} vs {_flag_emoji(match.get("away_team_code"))} {html.escape(away_team)}
            </div>
            <div style="font-size:0.95rem;font-weight:700;color:#0F172A;">{state['badge']} {state['label']}</div>
        </div>
        <div style="margin-top:8px;color:#475569;">
            {html.escape(match['tournament_stage'])} · {html.escape(_format_match_datetime(match.get('scheduled_at')))}
        </div>
    </div>
    """


def _render_status_legend() -> None:
    legend = " · ".join(f"{value['badge']} {value['label']}" for value in _CARD_STYLE.values())
    st.caption(f"Codes couleur : {legend}")


def _format_match_datetime(value: str | None) -> str:
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return "Date à confirmer"
    return timestamp.tz_convert("UTC").strftime("%d/%m/%Y %H:%M UTC")


def _flag_emoji(code: str | None) -> str:
    iso_code = _FIFA_TO_ISO2.get((code or "").upper())
    if not iso_code:
        return "🏳️"
    return "".join(chr(127397 + ord(char)) for char in iso_code.upper())
