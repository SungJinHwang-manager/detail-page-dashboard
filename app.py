"""
상세페이지 임시 분석 대시보드 (뷰저블 대체용)

담당자가 기간/부트캠프명/기수를 사전 등록해두면, 확인하고 싶은 사람이 목록에서 선택해
GA4 BigQuery 원천 데이터를 기반으로 클릭수 / 스크롤 도달률을 바로 시각화해서 볼 수 있다.
등록된 조건을 기본값으로 쓰되, 필요하면 slug/기간을 직접 바꿔서 조회하거나 두 조건을 나란히 비교할 수 있다.

실행: /Users/hwangsungjin/ads_automation/.venv/bin/streamlit run app.py
(반드시 detail_page_dashboard 폴더 안에서 실행해야 config.py 상대경로가 맞는다)
"""
import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from PIL import Image

import auth
import bq
import queries
import sheet_sync
import viz

st.set_page_config(page_title="상세페이지 분석 대시보드 (임시)", layout="wide")

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


def _run_query_set(cond, top_n=10):
    """조건(cond)으로 BQ 조회 실행. 방문자 0명이거나 에러면 None 반환하고 화면에 안내만 띄운다."""
    try:
        excluded = bq.get_click_exclusions()
        with st.spinner(f"[{cond['title']}] BigQuery 조회 중..."):
            overview = queries.get_overview(cond["start_date"], cond["end_date"], cond["slug"])
            if overview["unique_visitors"] == 0:
                st.warning(
                    f"**{cond['title']}** — 이 기간 동안 `{cond['slug']}` 상세페이지 방문 기록이 없습니다. "
                    "url_slug 철자나 기간을 확인해주세요."
                )
                return None
            scroll_df = queries.get_scroll_funnel(cond["start_date"], cond["end_date"], cond["slug"])
            click_df = queries.get_click_activity(cond["start_date"], cond["end_date"], cond["slug"],
                                                    excluded=excluded, limit=top_n)
            totals = queries.get_click_totals(cond["start_date"], cond["end_date"], cond["slug"], excluded=excluded)
    except Exception as e:
        st.error(f"**{cond['title']}** 조회 중 오류가 발생했습니다.")
        st.exception(e)
        return None
    return {"overview": overview, "scroll_df": scroll_df, "click_df": click_df, "totals": totals}


def _render_full(cond, result, top_n=10, key="single"):
    st.markdown(f"### {cond['title']}")
    st.caption(f"url_slug: `{cond['slug']}` · 기간: {cond['start_date']} ~ {cond['end_date']}")
    viz.render_overview(result["overview"])
    st.divider()
    viz.render_scroll_funnel(result["scroll_df"], key=key)
    viz.render_scroll_heatmap_overlay(
        cond.get("screenshot_path"), cond.get("screenshot_height_px"), result["scroll_df"]
    )
    st.divider()
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
        if st.button("조회하기", type="primary"):
            result = _run_query_set(cond, top_n=10)
            if result:
                _render_full(cond, result, top_n=10)

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
# 설정 관리 (관리자)
# ────────────────────────────────────────────────────────────
else:
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
    st.subheader("직접 등록 (수동)")
    st.caption("자동 동기화 대상이 아닌 과정이거나, slug/기간을 개별적으로 고칠 때 사용하세요.")
    with st.form("config_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        bootcamp_name = c1.text_input("부트캠프명", placeholder="예: 백엔드 자바")
        cohort = c2.text_input("기수", placeholder="예: 27기")
        url_slug = st.text_input(
            "상세페이지 URL slug",
            placeholder="예: kdt-backendj-27th",
            help="상세페이지 URL 중 bootcamp.likelion.net/school/ 뒤에 오는 부분",
        )
        c3, c4 = st.columns(2)
        start_date = c3.date_input("조회 시작일", value=date.today() - timedelta(days=14))
        end_date = c4.date_input("조회 종료일", value=date.today())
        created_by = st.text_input("작성자", placeholder="이름 또는 이메일")
        submitted = st.form_submit_button("등록 / 수정")

    if submitted:
        if not (bootcamp_name and cohort and url_slug):
            st.error("부트캠프명 / 기수 / URL slug는 필수입니다.")
        elif start_date > end_date:
            st.error("시작일이 종료일보다 늦을 수 없습니다.")
        else:
            bq.upsert_config(url_slug.strip(), bootcamp_name.strip(), cohort.strip(), start_date, end_date,
                              created_by.strip() or "익명")
            st.success(f"'{bootcamp_name} {cohort}' 등록 완료 (url_slug: {url_slug})")

    st.divider()
    st.subheader("등록된 목록")
    configs = bq.list_configs()
    if configs.empty:
        st.caption("등록된 항목이 없습니다.")
    else:
        st.dataframe(
            configs[["url_slug", "bootcamp_name", "cohort", "start_date", "end_date",
                     "created_by", "updated_at", "screenshot_path"]],
            use_container_width=True,
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

        st.divider()
        del_slug = st.selectbox("삭제할 url_slug 선택", [""] + configs["url_slug"].tolist())
        if del_slug and st.button(f"'{del_slug}' 삭제", type="secondary"):
            bq.delete_config(del_slug)
            st.success(f"'{del_slug}' 삭제 완료")
            st.rerun()
