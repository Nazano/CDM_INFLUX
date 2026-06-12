from __future__ import annotations

import html
from datetime import UTC, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from app.dashboard.data_access import (
    analyze_match_videos,
    fetch_videos_for_match,
    get_dashboard_repository,
    get_ranked_consensus,
    run_analysis_pipeline,
    run_queued_analysis,
    schedule_analysis_run,
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
    "Historique des analyses",
    "Santé des analyses",
    "Queue",
    "Explorateur de vidéos",
    "Détail d'une vidéo",
    "Comparateur de créateurs",
    "Pronos par match",
    "Fiabilité",
]

_STEP_ICONS: dict[str, str] = {
    "search": "🔍",
    "transcripts": "📄",
    "predictions": "🧠",
    "finalize": "✅",
}

_STATUS_ICONS: dict[str, str] = {
    "pending": "⏳",
    "running": "⏱️",
    "success": "✅",
    "failed": "❌",
    "skipped": "⏭️",
}

_RUN_STATUS_LABELS: dict[str, str] = {
    "queued": "🕐 En attente",
    "running": "⏱️ En cours",
    "success": "✅ Succès",
    "failed": "❌ Échec",
    "cancelled": "🚫 Annulé",
}


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
    elif page == "Historique des analyses":
        render_analysis_history(repository)
    elif page == "Santé des analyses":
        render_analysis_health(repository)
    elif page == "Queue":
        render_analysis_queue(repository)
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
    st.html(_build_match_card_html(match))
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

    st.html(_build_match_detail_header(selected_match))

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("Statut", _CARD_STYLE[_get_match_state(selected_match)]["label"])
    metric_col2.metric("Vidéos liées", selected_match.get("video_count", 0))
    metric_col3.metric("Vidéos analysées", selected_match.get("analyzed_video_count", 0))
    metric_col4.metric("Score prédit", selected_match.get("predicted_score") or "—")

    tab_videos, tab_analyses, tab_pronos = st.tabs(["🎥 Vidéos", "🔬 Analyses", "📊 Pronostics"])

    with tab_videos:
        render_match_videos(repository, preselected_match_id=selected_match_id)

    with tab_analyses:
        render_match_analyses_tab(repository, selected_match_id)

    with tab_pronos:
        render_match_consensus_for_match(repository, selected_match_id)


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
                fetched_video_count = fetch_videos_for_match(match_id, max_results)
            if fetched_video_count > 0:
                st.success(f"{fetched_video_count} vidéo(s) trouvée(s) et enregistrée(s).")
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


def render_match_analyses_tab(repository, match_id: str) -> None:
    """Pipeline view inside the match detail Analyses tab."""
    st.subheader("🔬 Lancer une analyse")

    run_col1, run_col2, run_col3 = st.columns([2, 1, 1])
    with run_col1:
        max_results = st.slider("Résultats max par requête", 1, 10, 5, key=f"pipeline-limit-{match_id}")
    with run_col2:
        step_filter_options = {
            "Pipeline complet": None,
            "Recherche uniquement": "search",
            "Transcripts uniquement": "transcripts",
            "Pronostics uniquement": "predictions",
        }
        step_label = st.selectbox("Étapes", list(step_filter_options.keys()), key=f"pipeline-step-{match_id}")
        step_filter = step_filter_options[step_label]
    with run_col3:
        note = st.text_input("Note (optionnel)", key=f"pipeline-note-{match_id}")

    if st.button("▶ Lancer le pipeline", key=f"pipeline-run-{match_id}", use_container_width=True, type="primary"):
        _run_pipeline_with_live_progress(match_id, max_results=max_results, step_filter=step_filter, note=note or None)

    st.divider()
    st.subheader("⏰ Planifier une analyse")
    sched_col1, sched_col2, sched_col3 = st.columns([2, 2, 1])
    with sched_col1:
        sched_date = st.date_input("Date", key=f"sched-date-{match_id}")
    with sched_col2:
        sched_time = st.time_input("Heure (UTC)", key=f"sched-time-{match_id}")
    with sched_col3:
        sched_note = st.text_input("Note", key=f"sched-note-{match_id}")

    if st.button("📅 Planifier", key=f"sched-btn-{match_id}", use_container_width=True):
        import datetime as _dt
        scheduled_for = _dt.datetime.combine(sched_date, sched_time, tzinfo=_dt.timezone.utc)
        run_id = schedule_analysis_run(match_id, scheduled_for=scheduled_for, note=sched_note or None)
        st.success(f"✅ Run planifié pour le {scheduled_for.strftime('%d/%m/%Y %H:%M UTC')} (ID: `{run_id}`)")
        st.rerun()

    st.divider()
    st.subheader("📋 Historique des runs pour ce match")
    runs = repository.list_analysis_runs(match_id=match_id)
    if not runs:
        st.info("Aucun run lancé pour ce match.")
        return

    for run in runs:
        _render_run_row(repository, run, show_match=False)


def render_analysis_history(repository) -> None:
    """Full analysis history page with filters."""
    st.title("📋 Historique des analyses")

    matches = repository.get_matches()
    match_options = {"Tous": None}
    match_options.update({
        f"{m.get('home_team') or 'TBD'} vs {m.get('away_team') or 'TBD'} ({m['tournament_stage']})": m["id"]
        for m in matches
    })

    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        selected_match_label = st.selectbox("Match", list(match_options.keys()))
        filter_match_id = match_options[selected_match_label]
    with filter_col2:
        status_options = {"Tous": None, "✅ Succès": "success", "❌ Échec": "failed", "⏱️ En cours": "running", "🕐 En attente": "queued"}
        selected_status_label = st.selectbox("Statut", list(status_options.keys()))
        filter_status = status_options[selected_status_label]
    with filter_col3:
        trigger_options = {"Tous": None, "Manuel": "manual", "Auto": "auto"}
        selected_trigger_label = st.selectbox("Déclencheur", list(trigger_options.keys()))
        filter_trigger = trigger_options[selected_trigger_label]
    with filter_col4:
        include_ignored = st.checkbox("Inclure les ignorés", value=False)

    date_col1, date_col2 = st.columns(2)
    with date_col1:
        start_date = st.date_input("Depuis", value=None, key="history-start-date")
    with date_col2:
        end_date = st.date_input("Jusqu'au", value=None, key="history-end-date")

    runs = repository.list_analysis_runs(
        match_id=filter_match_id,
        status=filter_status,
        trigger_type=filter_trigger,
        include_ignored=include_ignored,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
    )

    if not runs:
        st.info("Aucun run ne correspond aux critères.")
        return

    st.caption(f"{len(runs)} run(s) trouvé(s)")

    # Comparison mode
    with st.expander("⚖️ Comparer deux runs", expanded=False):
        run_id_options = {r["id"]: f"{r['id'][:16]}… · {r.get('home_team', 'TBD')} vs {r.get('away_team', 'TBD')} · {r.get('started_at', '')[:10]}" for r in runs}
        if len(run_id_options) >= 2:
            ids = list(run_id_options.keys())
            cmp_col1, cmp_col2 = st.columns(2)
            with cmp_col1:
                baseline_id = st.selectbox("Run baseline", ids, format_func=lambda x: run_id_options[x], key="cmp-baseline")
            with cmp_col2:
                candidate_id = st.selectbox("Run candidat", ids[1:], format_func=lambda x: run_id_options[x], key="cmp-candidate")
            if st.button("⚖️ Comparer", key="cmp-btn"):
                _render_run_comparison(repository, baseline_id, candidate_id)
        else:
            st.info("Au moins deux runs sont nécessaires pour une comparaison.")

    st.divider()
    for run in runs:
        _render_run_row(repository, run, show_match=True)


def render_analysis_health(repository) -> None:
    """Health/metrics dashboard for analyses."""
    st.title("🩺 Santé des analyses")
    metrics = repository.get_analysis_health_metrics()

    total = metrics["total_runs"]
    successful = metrics["successful_runs"]
    failed = metrics["failed_runs"]
    avg_dur = metrics["avg_duration_seconds"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Runs totaux", total)
    m2.metric("Taux de succès", f"{round((successful / total) * 100, 1) if total else 0}%")
    m3.metric("Runs échoués", failed)
    m4.metric("Durée moyenne", f"{int(avg_dur)}s" if avg_dur else "—")

    st.divider()

    # Step success rates
    step_data = metrics.get("step_success", [])
    if step_data:
        st.subheader("Taux de succès par étape")
        step_df = pd.DataFrame(step_data)
        step_df["étape"] = step_df["step_key"].map(lambda k: f"{_STEP_ICONS.get(k, '')} {k}")
        step_df["taux_succès"] = step_df["success_rate"]
        fig = px.bar(step_df, x="étape", y="taux_succès", title="% succès par étape du pipeline", range_y=[0, 100])
        st.plotly_chart(fig, use_container_width=True)

    # Transcript unavailability
    unavail_rate = metrics.get("transcript_unavailable_rate", 0)
    st.metric("% transcripts indisponibles", f"{unavail_rate}%")

    # Timeline
    timeline = metrics.get("timeline", [])
    if timeline:
        st.subheader("Évolution des runs dans le temps")
        timeline_df = pd.DataFrame(timeline)
        if not timeline_df.empty:
            fig2 = px.line(timeline_df, x="day", y=["runs", "successes"], title="Runs par jour", labels={"value": "Nombre", "day": "Jour"})
            st.plotly_chart(fig2, use_container_width=True)


def render_analysis_queue(repository) -> None:
    """Queue view: pending, running, done."""
    st.title("🗂️ Queue des analyses")

    matches = repository.get_matches()
    match_options = {m["id"]: f"{m.get('home_team') or 'TBD'} vs {m.get('away_team') or 'TBD'} ({m['tournament_stage']})" for m in matches}

    st.subheader("📅 Planifier un run")
    sched_match_label = st.selectbox("Match", list(match_options.values()), key="queue-match")
    sched_match_id = next(k for k, v in match_options.items() if v == sched_match_label)
    q_col1, q_col2, q_col3 = st.columns([2, 2, 2])
    with q_col1:
        q_date = st.date_input("Date (UTC)", key="queue-date")
    with q_col2:
        q_time = st.time_input("Heure (UTC)", key="queue-time")
    with q_col3:
        q_note = st.text_input("Note", key="queue-note")
    if st.button("📅 Ajouter à la queue", key="queue-add-btn", use_container_width=True):
        import datetime as _dt
        scheduled_for = _dt.datetime.combine(q_date, q_time, tzinfo=_dt.timezone.utc)
        run_id = schedule_analysis_run(sched_match_id, scheduled_for=scheduled_for, note=q_note or None)
        st.success(f"✅ Run planifié (ID: `{run_id}`)")
        st.rerun()

    st.divider()

    for status_label, status_val, icon in [
        ("⏱️ En cours", "running", "🔄"),
        ("🕐 En attente", "queued", "⏰"),
        ("✅ Récents (succès)", "success", "✅"),
        ("❌ Récents (échec)", "failed", "❌"),
    ]:
        runs = repository.list_analysis_runs(status=status_val, include_ignored=False)
        if status_val in ("success", "failed"):
            runs = runs[:5]
        with st.expander(f"{icon} {status_label} ({len(runs)})", expanded=bool(runs)):
            if not runs:
                st.info("Aucun run dans cette catégorie.")
            else:
                for run in runs:
                    _render_run_row_compact(repository, run, match_options)


def render_match_consensus_for_match(repository, match_id: str) -> None:
    """Pronostics tab inside match detail."""
    from app.services.ranking import rank_predictions
    consensus = repository.get_match_consensus()
    match_consensus = [r for r in consensus if r.get("subject") and match_id in (r.get("subject") or "")]
    if not match_consensus:
        st.info("Aucun pronostic disponible pour ce match. Lancez d'abord une analyse.")
        return
    df = pd.DataFrame(match_consensus)
    st.subheader("Consensus brut")
    st.dataframe(df, use_container_width=True)


def _render_run_row(repository, run: dict, *, show_match: bool) -> None:
    """Render a single run as an expander with pipeline steps, logs, and artifacts."""
    run_id = run["id"]
    status = run.get("status", "unknown")
    trigger = run.get("trigger_type", "manual")
    started = run.get("started_at", "")[:16].replace("T", " ")
    completed = run.get("completed_at") or ""
    if completed:
        completed = completed[:16].replace("T", " ")

    # Duration
    duration_str = ""
    if run.get("started_at") and run.get("completed_at"):
        try:
            from datetime import datetime as _dt
            s = _dt.fromisoformat(run["started_at"].replace("Z", "+00:00"))
            e = _dt.fromisoformat(run["completed_at"].replace("Z", "+00:00"))
            dur = int((e - s).total_seconds())
            duration_str = f"⏱ {dur}s"
        except Exception:
            pass

    label_parts = [_RUN_STATUS_LABELS.get(status, status)]
    if trigger == "auto":
        label_parts.append("🤖 auto")
    else:
        label_parts.append("👤 manuel")
    label_parts.append(f"📅 {started}")
    if duration_str:
        label_parts.append(duration_str)
    if show_match:
        match_label = f"{run.get('home_team') or 'TBD'} vs {run.get('away_team') or 'TBD'}"
        label_parts.insert(0, f"⚽ {match_label}")
    if run.get("is_reference"):
        label_parts.append("⭐ Référence")
    if run.get("is_ignored"):
        label_parts.append("🚫 Ignoré")
    if run.get("note"):
        label_parts.append(f"📝 {run['note'][:30]}")

    with st.expander(" · ".join(label_parts), expanded=False):
        detail = repository.get_analysis_run_detail(run_id)
        if not detail:
            st.warning("Détail introuvable.")
            return

        # Pipeline steps
        steps = detail.get("steps", [])
        if steps:
            st.markdown("**Pipeline**")
            for step in sorted(steps, key=lambda s: s.get("position", 0)):
                _render_step_block(step)

        # Artifacts
        artifacts = detail.get("artifacts", [])
        if artifacts:
            st.markdown("**Artifacts**")
            for artifact in artifacts:
                _render_artifact_block(artifact)

        # Annotations
        st.markdown("**Annotations**")
        ann_col1, ann_col2, ann_col3 = st.columns([3, 1, 1])
        with ann_col1:
            note_val = st.text_input("Note", value=run.get("note") or "", key=f"note-{run_id}")
        with ann_col2:
            is_ref = st.checkbox("⭐ Référence", value=bool(run.get("is_reference")), key=f"ref-{run_id}")
        with ann_col3:
            is_ign = st.checkbox("🚫 Ignorer", value=bool(run.get("is_ignored")), key=f"ign-{run_id}")
        if st.button("💾 Sauvegarder", key=f"ann-save-{run_id}"):
            repository.update_analysis_run_annotation(run_id, note=note_val, is_reference=is_ref, is_ignored=is_ign)
            st.success("Annotations mises à jour.")
            st.rerun()

        # Retry actions
        failed_steps = [s for s in steps if s.get("status") == "failed"]
        if failed_steps:
            st.markdown("**Relancer une étape**")
            retry_step_label = st.selectbox(
                "Étape à relancer",
                [s["step_key"] for s in failed_steps],
                format_func=lambda k: f"{_STEP_ICONS.get(k, '')} {k}",
                key=f"retry-select-{run_id}",
            )
            if st.button(f"🔁 Relancer {retry_step_label}", key=f"retry-btn-{run_id}"):
                match_id = run.get("match_id", "")
                if match_id:
                    _run_pipeline_with_live_progress(match_id, step_filter=retry_step_label, note=f"Retry de {retry_step_label}")
                else:
                    st.error("Match ID introuvable.")


def _render_step_block(step: dict) -> None:
    """Render a single pipeline step with logs and stats."""
    step_key = step.get("step_key", "")
    step_label = step.get("step_label", step_key)
    status = step.get("status", "pending")
    icon = _STATUS_ICONS.get(status, "❓")
    summary = step.get("summary") or ""

    started = (step.get("started_at") or "")[:16].replace("T", " ")
    completed = (step.get("completed_at") or "")[:16].replace("T", " ")
    duration_str = ""
    if step.get("started_at") and step.get("completed_at"):
        try:
            from datetime import datetime as _dt
            s = _dt.fromisoformat(step["started_at"].replace("Z", "+00:00"))
            e = _dt.fromisoformat(step["completed_at"].replace("Z", "+00:00"))
            duration_str = f" · ⏱ {int((e - s).total_seconds())}s"
        except Exception:
            pass

    header = f"{icon} {step_label}"
    if summary:
        header += f" — {summary}"
    if duration_str:
        header += duration_str

    with st.expander(header, expanded=(status == "failed")):
        stats = step.get("stats") or {}
        if stats:
            st.json(stats)
        logs = step.get("logs") or []
        if logs:
            st.markdown("**Logs**")
            for log in logs:
                level = log.get("level", "info")
                msg = log.get("message", "")
                ts = (log.get("created_at") or "")[:19].replace("T", " ")
                if level == "error":
                    st.error(f"[{ts}] {msg}")
                elif level == "warning":
                    st.warning(f"[{ts}] {msg}")
                else:
                    st.code(f"[{ts}] {msg}", language=None)


def _render_artifact_block(artifact: dict) -> None:
    """Render an artifact with a download button."""
    import json as _json
    label = artifact.get("label", artifact.get("artifact_type", "artifact"))
    step_key = artifact.get("step_key", "")
    step_icon = _STEP_ICONS.get(step_key, "📦")
    payload = artifact.get("payload") or {}
    payload_bytes = _json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"{artifact.get('artifact_type', 'artifact')}_{artifact.get('id', 'unknown')[:8]}.json"
    art_col1, art_col2 = st.columns([4, 1])
    with art_col1:
        st.caption(f"{step_icon} {label}")
    with art_col2:
        st.download_button(
            label="⬇️ Télécharger",
            data=payload_bytes,
            file_name=filename,
            mime="application/json",
            key=f"download-{artifact.get('id', label)}",
        )


def _render_run_row_compact(repository, run: dict, match_options: dict[str, str]) -> None:
    """Compact run row for queue view."""
    run_id = run["id"]
    status = run.get("status", "unknown")
    match_label = match_options.get(run.get("match_id", ""), "Match inconnu")
    trigger = "🤖 auto" if run.get("trigger_type") == "auto" else "👤 manuel"
    scheduled = (run.get("scheduled_for") or run.get("started_at") or "")[:16].replace("T", " ")

    col_status, col_match, col_trigger, col_time, col_action = st.columns([1, 3, 1, 2, 1])
    col_status.markdown(_RUN_STATUS_LABELS.get(status, status))
    col_match.markdown(match_label)
    col_trigger.markdown(trigger)
    col_time.markdown(scheduled)
    with col_action:
        if status == "queued":
            if st.button("▶ Lancer", key=f"queue-launch-{run_id}"):
                _run_queued_pipeline_with_progress(run_id)


def _render_run_comparison(repository, baseline_id: str, candidate_id: str) -> None:
    """Side-by-side run comparison."""
    comparison = repository.compare_analysis_runs(baseline_id, candidate_id)
    baseline = comparison.get("baseline") or {}
    candidate = comparison.get("candidate") or {}
    changes = comparison.get("changes") or []

    col_b, col_c = st.columns(2)
    with col_b:
        st.markdown(f"**Baseline** `{baseline_id[:16]}…`")
        st.caption(f"Status: {baseline.get('status')} · {(baseline.get('started_at') or '')[:10]}")
    with col_c:
        st.markdown(f"**Candidat** `{candidate_id[:16]}…`")
        st.caption(f"Status: {candidate.get('status')} · {(candidate.get('started_at') or '')[:10]}")

    if not changes:
        st.success("✅ Aucune différence détectée entre les deux runs.")
    else:
        st.warning(f"⚠️ {len(changes)} différence(s) détectée(s)")
        for change in changes:
            with st.expander(f"🔄 {change['key']}", expanded=True):
                diff_col1, diff_col2 = st.columns(2)
                with diff_col1:
                    st.markdown("**Avant**")
                    st.json(change.get("before") or {})
                with diff_col2:
                    st.markdown("**Après**")
                    st.json(change.get("after") or {})


def _run_pipeline_with_live_progress(
    match_id: str,
    *,
    max_results: int = 5,
    step_filter: str | None = None,
    note: str | None = None,
) -> None:
    """Run the full pipeline with live per-step progress display."""
    progress_placeholder = st.empty()
    status_text = st.empty()

    def _progress_callback(run_detail: dict) -> None:
        steps = sorted(run_detail.get("steps", []), key=lambda s: s.get("position", 0))
        with progress_placeholder.container():
            for step in steps:
                sk = step.get("step_key", "")
                sl = step.get("step_label", sk)
                st_val = step.get("status", "pending")
                icon = _STATUS_ICONS.get(st_val, "❓")
                summary = step.get("summary") or ""
                st.markdown(f"{icon} **{sl}** {f'— {summary}' if summary else ''}")

    with st.spinner("Pipeline en cours…"):
        result = run_analysis_pipeline(
            match_id,
            max_results=max_results,
            step_filter=step_filter,
            note=note,
            progress_callback=_progress_callback,
        )

    status_text.empty()
    final_status = result.get("status", "unknown")
    if final_status == "success":
        st.success("✅ Pipeline terminé avec succès.")
    else:
        st.error("❌ Pipeline terminé avec des erreurs.")

    st.rerun()


def _run_queued_pipeline_with_progress(run_id: str) -> None:
    """Run a queued analysis run with live progress."""
    progress_placeholder = st.empty()

    def _progress_callback(run_detail: dict) -> None:
        steps = sorted(run_detail.get("steps", []), key=lambda s: s.get("position", 0))
        with progress_placeholder.container():
            for step in steps:
                sk = step.get("step_key", "")
                sl = step.get("step_label", sk)
                st_val = step.get("status", "pending")
                icon = _STATUS_ICONS.get(st_val, "❓")
                summary = step.get("summary") or ""
                st.markdown(f"{icon} **{sl}** {f'— {summary}' if summary else ''}")

    with st.spinner("Lancement du run planifié…"):
        result = run_queued_analysis(run_id, progress_callback=_progress_callback)

    final_status = result.get("status", "unknown")
    if final_status == "success":
        st.success("✅ Run terminé avec succès.")
    else:
        st.error("❌ Run terminé avec des erreurs.")
    st.rerun()


def _run_match_pipeline(match_id: str) -> None:
    _run_pipeline_with_live_progress(match_id)


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

    # Pipeline step badge
    last_step = match.get("last_analysis_step")
    last_status = match.get("last_analysis_status")
    pipeline_html = ""
    if last_step and last_status:
        step_icon = _STEP_ICONS.get(last_step, "📌")
        status_icon = _STATUS_ICONS.get(last_status, "")
        pipeline_html = f"""
        <div style="background:rgba(255,255,255,0.82);border-radius:14px;padding:8px 12px;grid-column:1/-1;">
            <div style="font-size:0.8rem;color:#475569;">Dernière étape pipeline</div>
            <div style="font-weight:700;color:#0F172A;">{step_icon} {html.escape(last_step)} {status_icon}</div>
        </div>"""

    return f"""
    <a href="{href}" target="_top" style="text-decoration:none;color:inherit;">
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
                    {pipeline_html}
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
