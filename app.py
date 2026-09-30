"""
상세페이지 임시 분석 대시보드 (뷰저블 대체용)

담당자가 기간/부트캠프명/기수를 사전 등록해두면, 확인하고 싶은 사람이 목록에서 선택해
GA4 BigQuery 원천 데이터를 기반으로 클릭수 / 스크롤 도달률을 바로 시각화해서 볼 수 있다.
등록된 조건을 기본값으로 쓰되, 필요하면 slug/기간을 직접 바꿔서 조회하거나 두 조건을 나란히 비교할 수 있다.

실행: /Users/hwangsungjin/ads_automation/.venv/bin/streamlit run app.py
(반드시 detail_page_dashboard 폴더 안에서 실행해야 config.py 상대경로가 맞는다)
"""
import os

import pandas as pd
import streamlit as st
from PIL import Image

import auth
import bq
import queries
import sheet_sync
import viz

st.set_page_config(page_title="상세페이지 분석 대시보드 (임시)", layout="wide")

# 탭(스크롤/클릭) 버튼을 크고 뚜렷하게. Streamlit 1.63 프론트엔드 번들에서 실제 쓰는 속성인
# data-testid="stTab"/aria-selected 기준으로 만듦 (예전 버전 예시에 흔한 data-baseweb="tab"은
# 이 버전엔 없어서 안 먹힘 — playwright로 렌더링 확인 후 반영).
st.markdown("""
<style>
div[data-testid="stTabs"] div[data-baseweb="tab-list"] {
    gap: 10px;
}
div[data-testid="stTabs"] [data-testid="stTab"] {
    height: auto;
    padding: 14px 32px;
    border-radius: 10px 10px 0 0;
    background-color: rgba(120, 120, 120, 0.08);
}
div[data-testid="stTabs"] [data-testid="stTab"] p {
    font-size: 20px;
    font-weight: 700;
}
div[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] {
    background-color: #e8384f;
}
div[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] p {
    color: #ffffff;
}
</style>
""", unsafe_allow_html=True)

# 배포(Streamlit Cloud) 시 secrets에 APP_PASSWORD를 설정해두면 여기서 막는다.
# 로컬 개발 환경(secrets 없음)에서는 auth.app_password()가 None이라 그냥 통과한다.
_required_pw = auth.app_password()
if _required_pw:
    if not st.session_state.get("authed"):
        st.title("🔒 상세페이지 분석 대시보드")
        pw = st.text_input("접속 비밀번호", type="password")
        if pw:
            if pw == _required_pw:
                st.session_state["authed"] = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
        st.stop()

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)

if "config_table_ready" not in st.session_state:
    bq.ensure_config_table()
    bq.ensure_click_exclusions_table()
    st.session_state["config_table_ready"] = True

st.sidebar.title("상세페이지 분석 (임시)")
st.sidebar.caption("뷰저블 트래킹 복구 전까지 GA4 BigQuery 기반으로 임시 운영")
page = st.sidebar.radio("메뉴", ["데이터 조회", "설정 관리 (관리자)"])


def _fmt_label(row) -> str:
    return f"{row['bootcamp_name']} · {row['cohort']} ({row['start_date']} ~ {row['end_date']})"


def _pick_condition(configs, label, key_prefix):
    """등록된 목록에서 하나를 고르고, 필요하면 slug/기간을 직접 수정할 수 있게 한다."""
    configs = configs.copy()
    configs["_label"] = configs.apply(_fmt_label, axis=1)
    sel_label = st.selectbox(label, configs["_label"], key=f"{key_prefix}_select")
    row = configs[configs["_label"] == sel_label].iloc[0]

    # 위젯 key에 선택된 url_slug를 포함시켜, 드롭다운 선택이 바뀌면 완전히 새로운 위젯으로 취급되게 한다.
    # (key가 고정이면 Streamlit이 이전 렌더링 때 저장된 값을 새 value= 인자보다 우선시해서,
    #  드롭다운만 바뀌고 실제 slug/기간은 이전 값에 고정되는 문제가 있었음)
    widget_key = f"{key_prefix}_{row['url_slug']}"

    with st.expander("조건 직접 수정 (선택)"):
        slug = st.text_input("url_slug", value=row["url_slug"], key=f"{widget_key}_slug")
        c1, c2 = st.columns(2)
        sd = c1.date_input("시작일", value=row["start_date"], key=f"{widget_key}_start")
        ed = c2.date_input("종료일", value=row["end_date"], key=f"{widget_key}_end")

    return {
        "slug": slug,
        "start_date": sd,
        "end_date": ed,
        "title": f"{row['bootcamp_name']} {row['cohort']}",
        "screenshot_path": row.get("screenshot_path"),
        "screenshot_height_px": row.get("screenshot_height_px"),
    }


def _run_query_set(cond, top_n=10, channel=None):
    """조건(cond)으로 BQ 조회 실행. 방문자 0명이거나 에러면 None 반환하고 화면에 안내만 띄운다.
    channel: 지정 시 그 유입경로(first-touch utm_source)로 방문한 유저만으로 한정."""
    try:
        excluded = bq.get_click_exclusions()
        with st.spinner(f"[{cond['title']}] BigQuery 조회 중..."):
            overview = queries.get_overview(cond["start_date"], cond["end_date"], cond["slug"], channel=channel)
            if overview["unique_visitors"] == 0:
                st.warning(
                    f"**{cond['title']}** — 이 기간 동안 `{cond['slug']}` 상세페이지 방문 기록이 없습니다"
                    + (f" (유입경로: {channel})." if channel else ".")
                    + " url_slug/기간/유입경로를 확인해주세요."
                )
                return None
            scroll_df = queries.get_scroll_funnel(cond["start_date"], cond["end_date"], cond["slug"], channel=channel)
            click_df = queries.get_click_activity(cond["start_date"], cond["end_date"], cond["slug"],
                                                    excluded=excluded, limit=top_n, channel=channel)
            totals = queries.get_click_totals(cond["start_date"], cond["end_date"], cond["slug"],
                                               excluded=excluded, channel=channel)
    except Exception as e:
        st.error(f"**{cond['title']}** 조회 중 오류가 발생했습니다.")
        st.exception(e)
        return None
    return {"overview": overview, "scroll_df": scroll_df, "click_df": click_df, "totals": totals}


def _channel_picker(cond, key_prefix):
    """'유입경로 목록 불러오기'를 누르면 그때만 utm_source 목록을 조회해 선택창을 보여준다
    (누르기 전엔 추가 쿼리를 안 날려서 평소엔 비용이 안 든다). 선택값(None=전체)을 반환."""
    state_key = f"channels_{key_prefix}_{cond['slug']}"
    if st.button("유입경로 목록 불러오기 (선택)", key=f"{key_prefix}_load_channels"):
        with st.spinner("유입경로 조회 중..."):
            st.session_state[state_key] = queries.get_traffic_channels(
                cond["start_date"], cond["end_date"], cond["slug"]
            )

    ch_df = st.session_state.get(state_key)
    if ch_df is None or ch_df.empty:
        return None

    label_map = {"__ALL__": f"전체 ({int(ch_df['users'].sum()):,}명)"}
    for _, r in ch_df.iterrows():
        label_map[r["utm_source"]] = f"{r['utm_source']} ({int(r['users']):,}명)"
    options = ["__ALL__"] + ch_df["utm_source"].tolist()
    sel = st.selectbox("유입경로", options, format_func=lambda x: label_map.get(x, x), key=f"{key_prefix}_channel_sel")
    return None if sel == "__ALL__" else sel


def _render_full(cond, result, top_n=10, key="single", channel=None):
    st.markdown(f"### {cond['title']}")
    caption = f"url_slug: `{cond['slug']}` · 기간: {cond['start_date']} ~ {cond['end_date']}"
    if channel:
        caption += f" · 유입경로: **{channel}**"
    st.caption(caption)
    viz.render_overview(result["overview"])

    tab_scroll, tab_click = st.tabs(["📜 스크롤", "👆 클릭"])
    with tab_scroll:
        viz.render_scroll_funnel(result["scroll_df"], key=key)
        viz.render_scroll_heatmap_overlay(
            cond.get("screenshot_path"), cond.get("screenshot_height_px"), result["scroll_df"]
        )
    with tab_click:
        viz.render_click_ranking(result["click_df"], result["totals"], top_n=top_n, key=key)


# ────────────────────────────────────────────────────────────
# 데이터 조회
# ────────────────────────────────────────────────────────────
if page == "데이터 조회":
    st.title("📊 상세페이지 분석 대시보드")

    configs = bq.list_configs()
    if configs.empty:
        st.info("아직 등록된 부트캠프/기수가 없습니다. 왼쪽 메뉴에서 '설정 관리 (관리자)'로 먼저 등록해주세요.")
        st.stop()

    mode = st.radio("조회 모드", ["단일 조회", "두 조건 비교"], horizontal=True)

    if mode == "단일 조회":
        cond = _pick_condition(configs, "확인할 부트캠프/기수를 선택하세요", "single")
        top_n = st.selectbox(
            "클릭 랭킹 — 몇 개까지 볼까요?", [10, 20, 30, 50], index=1,
            help="차트는 가독성을 위해 상위 20개까지만 보여지고, 표는 여기서 고른 개수만큼 전부 보여줍니다.",
        )
        channel = _channel_picker(cond, "single")
        if st.button("조회하기", type="primary"):
            result = _run_query_set(cond, top_n=top_n, channel=channel)
            if result:
                _render_full(cond, result, top_n=top_n, channel=channel)

    else:
        st.caption("예: 이전 기수를 A, 현재 진행 중인 기수를 B로 놓고 비교해보세요.")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("#### 기준 A")
            cond_a = _pick_condition(configs, "A", "a")
        with col_b:
            st.markdown("#### 비교 B")
            cond_b = _pick_condition(configs, "B", "b")

        if st.button("비교하기", type="primary"):
            result_a = _run_query_set(cond_a, top_n=5)
            result_b = _run_query_set(cond_b, top_n=5)

            col_a2, col_b2 = st.columns(2)
            if result_a:
                col_a2.markdown(f"**{cond_a['title']}**")
                col_a2.metric("순방문자 수", f"{result_a['overview']['unique_visitors']:,}")
                col_a2.metric("총 page_view 수", f"{result_a['overview']['page_view_count']:,}")
            if result_b:
                col_b2.markdown(f"**{cond_b['title']}**")
                col_b2.metric("순방문자 수", f"{result_b['overview']['unique_visitors']:,}")
                col_b2.metric("총 page_view 수", f"{result_b['overview']['page_view_count']:,}")

            if result_a and result_b:
                st.divider()
                viz.render_scroll_funnel_compare(
                    result_a["scroll_df"], cond_a["title"], result_b["scroll_df"], cond_b["title"]
                )

            st.divider()
            col_a3, col_b3 = st.columns(2)
            if result_a:
                with col_a3:
                    viz.render_click_ranking(result_a["click_df"], result_a["totals"], top_n=5, text_chars=40, key="a")
            if result_b:
                with col_b3:
                    viz.render_click_ranking(result_b["click_df"], result_b["totals"], top_n=5, text_chars=40, key="b")

# ────────────────────────────────────────────────────────────
# 설정 관리 (관리자) — APP_PASSWORD와 별개로 ADMIN_PASSWORD가 있으면 한 번 더 막는다 (관리자 본인만 진입)
# ────────────────────────────────────────────────────────────
else:
    _admin_pw = auth.admin_password()
    if _admin_pw and not st.session_state.get("admin_authed"):
        st.title("🔒 설정 관리 (관리자 전용)")
        apw = st.text_input("관리자 비밀번호", type="password", key="admin_pw_input")
        if apw:
            if apw == _admin_pw:
                st.session_state["admin_authed"] = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
        st.stop()

    st.title("⚙️ 설정 관리 (관리자)")
    st.caption("부트캠프명/기수/상세페이지 URL slug/조회 기간을 등록하면, '데이터 조회' 화면 목록에 바로 반영됩니다.")

    st.subheader("구글시트에서 자동 동기화")
    st.caption(
        "'[그로스팀] 2026 마케팅 데이터' 시트의 'Index_클래스별 목표 데이터' 탭(담당자가 항상 기록해두는 시트, 읽기 전용)에서 "
        "과정별 slug/시작일정/종료일정을 그대로 가져와 등록합니다. 직접 입력할 필요가 없어요."
    )
    if st.button("시트에서 불러오기"):
        with st.spinner("시트 조회 중..."):
            rows, skipped = sheet_sync.fetch_class_schedule()
        st.session_state["sync_rows"] = rows
        st.session_state["sync_skipped"] = skipped

    if st.session_state.get("sync_rows"):
        rows = st.session_state["sync_rows"]
        skipped = st.session_state.get("sync_skipped", [])
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        if skipped:
            st.caption(f"⚠️ 날짜 형식이 예상과 달라 건너뛴 행: {', '.join(skipped)}")
        if st.button(f"위 {len(rows)}건 전체 등록/갱신", type="primary"):
            for r in rows:
                bq.upsert_config(r["url_slug"], r["bootcamp_name"], r["cohort"],
                                  r["start_date"], r["end_date"], created_by="auto-sync(시트)")
            st.success(f"{len(rows)}건 동기화 완료")
            del st.session_state["sync_rows"]
            st.rerun()

    st.divider()
    st.subheader("등록된 목록 — 표에서 직접 추가 / 수정 / 삭제")
    st.caption(
        "셀을 클릭해서 바로 고칠 수 있고, 맨 아래 빈 줄에 입력하면 새로 추가돼요. "
        "행 맨 왼쪽 체크박스로 선택 후 위쪽 휴지통 아이콘을 누르면 삭제됩니다. "
        "다 고치신 다음 **아래 '변경사항 저장' 버튼을 눌러야** 실제 반영돼요 (누르기 전까진 화면에서만 수정 중인 상태)."
    )
    configs = bq.list_configs()
    editable_cols = ["url_slug", "bootcamp_name", "cohort", "start_date", "end_date"]
    base_df = configs[editable_cols] if not configs.empty else pd.DataFrame(columns=editable_cols)
    edited = st.data_editor(
        base_df,
        num_rows="dynamic",
        use_container_width=True,
        key="configs_editor",
        column_config={
            "url_slug": st.column_config.TextColumn("url_slug (고유키)", required=True),
            "bootcamp_name": st.column_config.TextColumn("부트캠프명", required=True),
            "cohort": st.column_config.TextColumn("기수", required=True),
            "start_date": st.column_config.DateColumn("시작일", required=True),
            "end_date": st.column_config.DateColumn("종료일", required=True),
        },
    )

    if st.button("변경사항 저장", type="primary"):
        original_slugs = set(configs["url_slug"]) if not configs.empty else set()
        valid = edited.dropna(subset=editable_cols).copy()
        valid = valid[valid["url_slug"].astype(str).str.strip() != ""]
        new_slugs = set(valid["url_slug"].astype(str).str.strip())

        to_delete = original_slugs - new_slugs
        for slug in to_delete:
            bq.delete_config(slug)

        bad_rows = len(edited) - len(valid)
        for _, r in valid.iterrows():
            bq.upsert_config(
                str(r["url_slug"]).strip(), str(r["bootcamp_name"]).strip(), str(r["cohort"]).strip(),
                r["start_date"], r["end_date"], created_by="관리자 수정",
            )
        msg = f"저장 완료 — 등록/수정 {len(valid)}건, 삭제 {len(to_delete)}건"
        if bad_rows:
            msg += f" (필수값이 빈 {bad_rows}개 행은 저장하지 않고 건너뜀)"
        st.success(msg)
        st.rerun()

    if not configs.empty:
        with st.expander("스크린샷/작성자 등 부가 정보 보기"):
            st.dataframe(
                configs[["url_slug", "created_by", "updated_at", "screenshot_path"]],
                use_container_width=True, hide_index=True,
            )

        st.divider()
        st.subheader("상세페이지 캡처 이미지 등록 (스크롤 히트맵용, 선택)")
        st.caption(
            "전체 페이지를 세로로 길게 캡처한 이미지를 올리면, 조회 화면에서 스크롤 도달 위치를 "
            "이미지 위에 겹쳐 보여줍니다. (크롬 확장 'GoFullPage' 등으로 촬영한 풀페이지 캡처 권장)"
        )
        target_slug = st.selectbox("이미지를 등록할 url_slug", configs["url_slug"].tolist(), key="shot_slug")
        uploaded = st.file_uploader("캡처 이미지 (PNG/JPG)", type=["png", "jpg", "jpeg"], key="shot_file")
        if uploaded and st.button("이미지 저장", key="shot_save"):
            img = Image.open(uploaded)
            save_path = os.path.join(ASSETS_DIR, f"{target_slug}.png")
            img.convert("RGB").save(save_path, "PNG")
            bq.set_screenshot(target_slug, save_path, img.size[1])
            st.success(f"'{target_slug}' 캡처 이미지 등록 완료 (높이 {img.size[1]}px)")

        st.divider()
        st.subheader("클릭 랭킹 제외 문구 관리")
        st.caption(
            "GNB/헤더/푸터처럼 페이지 콘텐츠가 아닌 사이트 공통 클릭 텍스트를 여기서 관리합니다. "
            "여기 있는 문구와 정확히 일치하는 클릭은 모든 과정의 '클릭 랭킹'에서 제외됩니다. 한 줄에 문구 하나씩."
        )
        current_exclusions = bq.get_click_exclusions()
        exclusions_text = st.text_area(
            "제외 문구 목록", value="\n".join(current_exclusions), height=200, key="exclusions_text"
        )
        if st.button("제외 문구 저장"):
            new_list = [line for line in exclusions_text.split("\n")]
            bq.set_click_exclusions(new_list)
            st.success(f"{len([l for l in new_list if l.strip()])}개 문구 저장 완료")
