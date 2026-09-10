"""화면 렌더링 컴포넌트 (단일 조회 / 비교 조회에서 공통으로 재사용)"""
import base64
import os
from io import BytesIO

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

import bq

SCROLL_LINE_COLORS = ["#e8384f", "#f59e0b", "#3b82f6", "#10b981", "#8b5cf6", "#ec4899"]


def render_overview(overview: dict):
    col1, col2 = st.columns(2)
    col1.metric("총 page_view 수", f"{overview['page_view_count']:,}")
    col2.metric("순방문자 수 (UU)", f"{overview['unique_visitors']:,}")
    with st.expander("산정 기준"):
        st.markdown(
            "- **이벤트**: GA4 `page_view`\n"
            "- **범위**: 선택한 url_slug의 상세페이지 (`/school/{slug}` 및 하위 경로) — 지원페이지(`apply` 포함 경로)는 제외\n"
            "- **순방문자 수**: 해당 조건에서 page_view를 1회 이상 발생시킨 `user_pseudo_id`(GA4 기기/브라우저 단위 식별자) 수"
        )


def render_scroll_funnel(scroll_df: pd.DataFrame, key: str = None):
    """key: 같은 화면에 두 번(A/B 비교) 그릴 때 차트/표 ID가 겹치지 않도록 구분자로 넘긴다."""
    st.subheader("스크롤 도달률")
    scroll_main = scroll_df[scroll_df["group_type"] == "Scroll"].copy()
    if not scroll_main.empty:
        scroll_main["scroll_percent_num"] = pd.to_numeric(scroll_main["scroll_percent"])
        scroll_main = scroll_main.sort_values("scroll_percent_num")
        scroll_main["구간"] = scroll_main["scroll_percent_num"].astype(int).astype(str) + "% 이상 도달"
        scroll_main["label_text"] = scroll_main.apply(
            lambda r: f"{int(r['cumulative_users']):,}명 ({r['ratio']}%)", axis=1
        )

        # 값(명수)이 클수록 넓은 깔때기 형태로 그려서, 구간이 깊어질수록 얼마나 이탈하는지
        # 한눈에 보이게 한다. 막대 안에 '명수 (비율%)'를 그대로 텍스트로 박아서 숫자를 바로 읽을 수 있게 함.
        fig = go.Figure(go.Funnel(
            y=scroll_main["구간"],
            x=scroll_main["cumulative_users"],
            text=scroll_main["label_text"],
            textinfo="text",
            textfont=dict(size=16),
            marker=dict(color="#3b82f6"),
            connector=dict(line=dict(color="#cbd5e1", width=1)),
        ))
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=max(260, 70 * len(scroll_main)))
        st.plotly_chart(fig, use_container_width=True, key=f"scroll_funnel_chart_{key}")

        table = scroll_main[["구간", "cumulative_users", "ratio"]].rename(
            columns={"cumulative_users": "누적 도달 유저 수", "ratio": "비율(%)"}
        )
        st.dataframe(table, use_container_width=True, hide_index=True, key=f"scroll_funnel_table_{key}")
    else:
        st.warning("해당 기간에 scroll 이벤트가 없습니다.")

    below_min = scroll_df[scroll_df["group_type"] == "Scroll < min level"]
    no_scroll = scroll_df[scroll_df["group_type"] == "No Scroll Event"]
    c1, c2 = st.columns(2)
    if not below_min.empty and below_min["cumulative_users"].iloc[0]:
        c1.metric("최저 구간 미만 이탈", f"{int(below_min['cumulative_users'].iloc[0]):,}명",
                  f"{below_min['ratio'].iloc[0]}%")
    if not no_scroll.empty:
        c2.metric("스크롤 이벤트 자체 없음 (바로 이탈 추정)", f"{int(no_scroll['cumulative_users'].iloc[0]):,}명",
                  f"{no_scroll['ratio'].iloc[0]}%")

    with st.expander("산정 기준"):
        st.markdown(
            "- **이벤트**: GA4 `scroll` — 커스텀 구현 `scroll_percent`(20/50/70/90 등 구간별)와 "
            "GA4 향상된 측정 자동수집 `percent_scrolled`(90% 고정)를 합쳐서 본다 (`COALESCE`) — "
            "한쪽에만 찍히는 유저가 있어 둘 다 봐야 누락이 없음\n"
            "- **도달률**: 유저별 '최고 도달 %'를 구한 뒤, 각 구간(예: 20%)에 대해 '그 구간 이상 도달한 유저 수'를 누적으로 집계 "
            "(90%까지 간 유저는 20/50/70/90 모두에 카운트)\n"
            "- **최저 구간 미만 이탈**: scroll 이벤트는 있었지만 최저 등록 구간(예: 20%)에도 못 미친 유저\n"
            "- **스크롤 이벤트 자체 없음**: page_view는 있었지만 scroll 이벤트가 한 번도 없었던 유저 (바로 이탈로 추정)"
        )


def render_scroll_funnel_compare(df_a: pd.DataFrame, label_a: str, df_b: pd.DataFrame, label_b: str):
    """두 조건의 스크롤 퍼널을 하나의 그룹 바 차트로 겹쳐 비교"""
    st.subheader("스크롤 도달률 비교")

    def _prep(df, label):
        m = df[df["group_type"] == "Scroll"].copy()
        m["scroll_percent_num"] = pd.to_numeric(m["scroll_percent"])
        m["group"] = label
        return m

    merged = pd.concat([_prep(df_a, label_a), _prep(df_b, label_b)], ignore_index=True)
    if merged.empty:
        st.warning("비교할 scroll 이벤트가 없습니다.")
        return
    merged = merged.sort_values("scroll_percent_num")
    fig = px.bar(
        merged, x="scroll_percent_num", y="ratio", color="group", barmode="group", text="ratio",
        labels={"scroll_percent_num": "스크롤 도달 구간 (%)", "ratio": "도달 비율 (%)", "group": ""},
    )
    fig.update_traces(texttemplate="%{text}%", textposition="outside")
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, use_container_width=True)


def render_click_ranking(click_df: pd.DataFrame, totals: dict, top_n: int = 10, text_chars: int = 70,
                          key: str = None):
    """뷰저블 'Tap Count Rank' 스타일 — 어떤 텍스트인지 바로 보이는 랭킹 차트 + 표 + 큰 텍스트 카드
    key: 같은 화면에 두 번(A/B 비교) 그릴 때 차트/표 ID가 겹치지 않도록 구분자로 넘긴다."""
    st.subheader("클릭 랭킹 (콘텐츠 요소별)")
    st.caption("뷰저블 클릭 히트맵의 임시 대체 데이터 — click_activity 이벤트의 클릭된 요소 텍스트 기준")

    with st.expander("산정 기준 (뷰저블 수치와 다를 수 있어요)"):
        excluded_list = bq.get_click_exclusions()
        excluded_preview = ", ".join(excluded_list[:8]) + ("..." if len(excluded_list) > 8 else "")
        st.markdown(
            "- **이벤트**: GA4 커스텀 이벤트 `click_activity`의 `user_click` 파라미터(클릭된 요소의 텍스트) 기준 — "
            "뷰저블처럼 좌표 기반 히트맵이 아니라 텍스트 단위 집계라 **같은 텍스트를 쓰는 서로 다른 요소는 하나로 합쳐짐**\n"
            "- **정규화**: 줄바꿈만 다른 값(`지원하기` vs `지원하기\\n`)은 TRIM 후 합산\n"
            f"- **중복 제거**: 같은 유저 + 같은 `event_timestamp`로 완전히 동일하게 찍힌 이벤트는 1건으로 처리 "
            "(2026-09-10 확인 결과, 사이트 트래킹 자체가 동일 클릭을 최대 7회까지 중복 발생시키는 경우가 있어 반드시 필요했음)\n"
            f"- **제외 문구**: GNB/헤더/푸터 등 페이지 콘텐츠가 아닌 사이트 공통 클릭 {len(excluded_list)}개 제외 "
            f"(예: {excluded_preview}) — '설정 관리'에서 직접 추가/삭제 가능\n"
            "- **전체 클릭 비중(%)**: 위 제외·중복제거를 모두 적용한 뒤, 이 페이지의 전체 클릭 대비 비율\n"
            "- ⚠️ 뷰저블과 똑같은 숫자가 나오진 않습니다 (실측 비교 결과 뷰저블 대비 약 1.7배 — 2026-09-10, 27기 '지원하기' 버튼 기준). "
            "요소 판별 방식(좌표 vs 텍스트), 세션/유저 집계 기준이 서로 달라서인데 정확한 원인은 추가 확인이 필요합니다. "
            "이 도구는 절대값보다 **기간별 추세·상대비교** 용도로 참고해주세요."
        )

    if click_df.empty:
        st.warning("해당 기간에 click_activity 이벤트가 없습니다.")
        return

    top = click_df.head(top_n).reset_index(drop=True)
    top["rank"] = top.index + 1
    total_clicks = totals.get("total_clicks") or 1
    top["전체 클릭 비중(%)"] = (100 * top["clicks"] / total_clicks).round(1)

    # 차트 라벨에 순위뿐 아니라 실제 클릭 텍스트를 짧게 줄여서 같이 보여준다 (rank만 보이던 것 개선)
    def _short(text, n=28):
        text = (text or "").replace("\n", " ")
        return text if len(text) <= n else text[:n] + "…"

    top["chart_label"] = top.apply(lambda r: f"{int(r['rank'])}위 · {_short(r['user_click'])}", axis=1)

    fig = px.bar(
        top.sort_values("rank", ascending=False), x="clicks", y="chart_label", orientation="h", text="clicks"
    )
    fig.update_traces(marker_color="#e8384f", textposition="outside")
    fig.update_yaxes(automargin=True)
    fig.update_layout(
        yaxis_title=None, xaxis_title="클릭 수", showlegend=False,
        height=max(320, 42 * len(top)), margin=dict(r=40, t=10, b=0),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"click_rank_chart_{key}")

    # 차트 바로 아래에 원본 텍스트 전체를 보여주는 표를 먼저 배치 (카드보다 앞)
    table = top[["rank", "user_click", "clicks", "전체 클릭 비중(%)", "unique_clickers"]].rename(
        columns={"rank": "순위", "user_click": "클릭된 텍스트(원본)", "clicks": "클릭수", "unique_clickers": "클릭 유저수"}
    )
    st.dataframe(table, use_container_width=True, hide_index=True, key=f"click_rank_table_{key}")

    with st.expander("순위별 큰 글씨로 보기", key=f"click_rank_expander_{key}"):
        for _, r in top.iterrows():
            text = r["user_click"] or ""
            display_text = text if len(text) <= text_chars else text[:text_chars] + "…"
            row_key = f"{key}_{int(r['rank'])}"
            with st.container(border=True, key=f"click_rank_card_{row_key}"):
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"**{int(r['rank'])}위 · {int(r['clicks']):,}회 클릭**")
                c1.markdown(
                    "<div style='font-size:24px; font-weight:700; line-height:1.5; "
                    "background:var(--secondary-background-color, #f4f4f6); padding:14px 18px; "
                    "border-radius:10px; margin-top:4px; white-space:pre-line;'>"
                    f"{display_text}</div>",
                    unsafe_allow_html=True,
                )
                c2.metric("전체 클릭 비중", f"{r['전체 클릭 비중(%)']}%")
                c2.metric("클릭 유저수", f"{int(r['unique_clickers']):,}명")


def render_scroll_heatmap_overlay(screenshot_path: str, screenshot_height_px: int, scroll_df: pd.DataFrame,
                                   display_width: int = 640, box_height: int = 800):
    """
    상세페이지 캡처 이미지 위에 스크롤 구간별 도달 비율을 가로선으로 겹쳐 표시.

    Plotly의 layout_image로 그리면 세로로 아주 긴 이미지(수천~수만 px)를 억지로 리샘플링하면서
    뭉개져 보이는 문제가 있어서, 대신 순수 HTML <img> + CSS 절대위치 오버레이로 그린다.
    <img>는 브라우저가 원본 비율 그대로 부드럽게 축소해주기 때문에 화질이 훨씬 낫고,
    스크롤 지점 표시도 '전체 높이의 N%' 라는 의미 그대로 top: N% 로 그리면 되어 더 단순하다.
    """
    st.subheader("스크롤 도달 위치 미리보기")

    has_path = screenshot_path and not pd.isna(screenshot_path) and os.path.exists(str(screenshot_path))
    if not has_path:
        st.info(
            "이 부트캠프/기수에는 아직 상세페이지 캡처 이미지가 등록되지 않았습니다. "
            "'설정 관리' 화면에서 전체 페이지 캡처 이미지를 업로드하면 여기에 위치별 스크롤 도달률이 표시됩니다."
        )
        return

    scroll_main = scroll_df[scroll_df["group_type"] == "Scroll"].copy()
    if scroll_main.empty:
        st.warning("겹쳐 표시할 스크롤 도달 데이터가 없습니다.")
        return
    scroll_main["scroll_percent_num"] = pd.to_numeric(scroll_main["scroll_percent"])
    scroll_main = scroll_main.sort_values("scroll_percent_num")

    st.warning(
        "⚠️ **추정 위치입니다.** 방문자마다 실제 화면(모바일/PC) 높이가 달라, 아래 구간 표시는 "
        "이 캡처 이미지 기준 근사 위치이며 실제 위치와 다를 수 있어요."
    )

    img = Image.open(screenshot_path)
    img_w, img_h = img.size
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    lines_html = ""
    for i, (_, r) in enumerate(scroll_main.iterrows()):
        pct = r["scroll_percent_num"]
        color = SCROLL_LINE_COLORS[i % len(SCROLL_LINE_COLORS)]
        lines_html += f"""
        <div style="position:absolute; left:0; right:0; top:{pct}%; z-index:2;">
          <div style="border-top:6px solid {color}; box-shadow:0 0 10px 1px {color};"></div>
          <span style="position:absolute; left:8px; top:8px; background:{color}; color:#fff;
                       padding:5px 14px; border-radius:6px; font-size:17px; font-weight:800;
                       white-space:nowrap; font-family:-apple-system,sans-serif;
                       box-shadow:0 2px 8px rgba(0,0,0,.35); letter-spacing:-0.2px;">
            {int(pct)}% 도달 지점 · {int(r['cumulative_users']):,}명 ({r['ratio']}%)
          </span>
        </div>"""

    html = f"""
    <div style="width:100%; height:{box_height}px; overflow-y:auto; overflow-x:hidden;
                border:1px solid #e5e7eb; border-radius:8px;">
      <div style="position:relative; width:{display_width}px; margin:0 auto;">
        <img src="data:image/png;base64,{b64}"
             style="width:{display_width}px; display:block; image-rendering:auto;" />
        {lines_html}
      </div>
    </div>
    """
    components.html(html, height=box_height + 4, scrolling=False)
    st.caption(f"원본 이미지 {img_w}×{img_h}px · 박스 안에서 스크롤해 전체를 볼 수 있어요.")
