"""
GA4 BigQuery 파라미터화 쿼리 모음

공통 규칙:
- 상세페이지 경로 판별은 '?' 이전 path만 잘라서(SPLIT) 비교한다.
  (page_view/scroll의 page_location 파라미터는 UTM 쿼리스트링이 붙은 전체 URL이고,
   click_activity의 page_location 파라미터는 path만 담겨 있어 포맷이 다르기 때문 - 실데이터로 확인함)
- 지원페이지(.../apply, .../kdt-apply 등)는 path에 'apply'가 포함되므로 항상 제외한다.
- 날짜 파라미터는 GA4 테이블 suffix 포맷(YYYYMMDD 문자열)으로 넘긴다.
"""
from google.cloud import bigquery

import config as cfg
from bq import get_client


def _date_params(start_date, end_date, url_slug):
    return [
        bigquery.ScalarQueryParameter("start_suffix", "STRING", start_date.strftime("%Y%m%d")),
        bigquery.ScalarQueryParameter("end_suffix", "STRING", end_date.strftime("%Y%m%d")),
        bigquery.ScalarQueryParameter("slug", "STRING", url_slug),
    ]


# 상세페이지(path) 매칭 + 지원페이지 제외 조건. path 컬럼 표현식을 그대로 넘겨서 재사용한다.
def _page_match_sql(path_expr: str) -> str:
    return f"""(
        ({path_expr} LIKE CONCAT('%/school/', @slug) OR {path_expr} LIKE CONCAT('%/school/', @slug, '/%'))
        AND {path_expr} NOT LIKE '%apply%'
    )"""


def get_overview(start_date, end_date, url_slug) -> dict:
    """총 page_view 수 / 순방문자 수(UU)"""
    client = get_client()
    path_expr = "SPLIT(ep.value.string_value, '?')[OFFSET(0)]"
    query = f"""
        SELECT
          COUNT(*) AS page_view_count,
          COUNT(DISTINCT user_pseudo_id) AS unique_visitors
        FROM {cfg.EVENTS_TABLE}, UNNEST(event_params) AS ep
        WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
          AND event_name = 'page_view'
          AND ep.key = 'page_location'
          AND {_page_match_sql(path_expr)}
    """
    job_config = bigquery.QueryJobConfig(query_parameters=_date_params(start_date, end_date, url_slug))
    df = client.query(query, job_config=job_config).to_dataframe()
    row = df.iloc[0]
    return {"page_view_count": int(row["page_view_count"]), "unique_visitors": int(row["unique_visitors"])}


def get_scroll_funnel(start_date, end_date, url_slug):
    """
    스크롤 도달률 퍼널 (20/50/70/90% 등 구간별 누적 도달자 수 + 비율)

    원본 쿼리 대비 수정한 부분:
      1) page_visitors에도 지원페이지 제외 필터 추가 (원본은 base_scroll에만 있고 여기 누락되어 있었음)
      2) scroll_percent(커스텀, 20/50/70/90) 뿐 아니라 percent_scrolled(GA4 자동수집, 90 고정)도
         COALESCE로 함께 봐야 90% 도달 유저 누락이 없음 (실데이터 확인: 두 키는 서로 배타적으로 찍힘)
    """
    client = get_client()
    pv_path_expr = "SPLIT(ep.value.string_value, '?')[OFFSET(0)]"
    sr_path_expr = "SPLIT((SELECT ep2.value.string_value FROM UNNEST(event_params) ep2 WHERE ep2.key='page_location'), '?')[OFFSET(0)]"

    query = f"""
        WITH page_visitors AS (
            SELECT DISTINCT user_pseudo_id
            FROM {cfg.EVENTS_TABLE}, UNNEST(event_params) AS ep
            WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
              AND event_name = 'page_view'
              AND ep.key = 'page_location'
              AND {_page_match_sql(pv_path_expr)}
        )

        , scroll_raw AS (
            SELECT
                user_pseudo_id,
                {sr_path_expr} AS page_path,
                COALESCE(
                    (SELECT ep3.value.int_value FROM UNNEST(event_params) ep3 WHERE ep3.key = 'scroll_percent'),
                    (SELECT ep4.value.int_value FROM UNNEST(event_params) ep4 WHERE ep4.key = 'percent_scrolled')
                ) AS scroll_percent
            FROM {cfg.EVENTS_TABLE}
            WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
              AND event_name = 'scroll'
        )

        , base_scroll AS (
            SELECT *
            FROM scroll_raw
            WHERE {_page_match_sql('page_path')}
        )

        , max_scroll_per_user AS (
            SELECT user_pseudo_id, MAX(scroll_percent) AS scroll_percent
            FROM base_scroll
            GROUP BY user_pseudo_id
        )

        , user_scroll AS (
            SELECT pv.user_pseudo_id, ms.scroll_percent
            FROM page_visitors pv
            LEFT JOIN max_scroll_per_user AS ms ON pv.user_pseudo_id = ms.user_pseudo_id
        )

        , scroll_levels AS (
            SELECT DISTINCT scroll_percent
            FROM user_scroll
            WHERE scroll_percent IS NOT NULL
        )

        , expanded_scrolls AS (
            SELECT sl.scroll_percent AS level, us.user_pseudo_id
            FROM user_scroll us
            JOIN scroll_levels sl ON sl.scroll_percent <= us.scroll_percent
        )

        SELECT
            CAST(level AS STRING) AS scroll_percent,
            COUNT(DISTINCT user_pseudo_id) AS cumulative_users,
            ROUND(SAFE_DIVIDE(100 * COUNT(DISTINCT user_pseudo_id), (SELECT COUNT(DISTINCT user_pseudo_id) FROM page_visitors)), 1) AS ratio,
            'Scroll' AS group_type
        FROM expanded_scrolls
        GROUP BY level

        UNION ALL

        SELECT
            'NULL' AS scroll_percent,
            COUNT(DISTINCT user_pseudo_id) AS cumulative_users,
            ROUND(SAFE_DIVIDE(100 * COUNT(DISTINCT user_pseudo_id), (SELECT COUNT(DISTINCT user_pseudo_id) FROM page_visitors)), 1) AS ratio,
            'Scroll < min level' AS group_type
        FROM user_scroll
        WHERE scroll_percent IS NULL
          AND user_pseudo_id IN (SELECT DISTINCT user_pseudo_id FROM base_scroll)

        UNION ALL

        SELECT
            'NULL' AS scroll_percent,
            COUNT(DISTINCT user_pseudo_id) AS cumulative_users,
            ROUND(SAFE_DIVIDE(100 * COUNT(DISTINCT user_pseudo_id), (SELECT COUNT(DISTINCT user_pseudo_id) FROM page_visitors)), 1) AS ratio,
            'No Scroll Event' AS group_type
        FROM user_scroll
        WHERE scroll_percent IS NULL
          AND user_pseudo_id NOT IN (SELECT DISTINCT user_pseudo_id FROM base_scroll)
    """
    job_config = bigquery.QueryJobConfig(query_parameters=_date_params(start_date, end_date, url_slug))
    return client.query(query, job_config=job_config).to_dataframe()


def _clicks_cte(path_expr: str, excluded: list) -> str:
    """
    click_activity 원시 클릭을 TRIM + 중복제거해서 뽑는 공통 CTE 문자열.

    - 중복제거(SELECT DISTINCT ... event_timestamp 포함): 실제 데이터 확인 결과, 사이트 트래킹 자체가
      동일 유저의 같은 클릭을 event_timestamp까지 완전히 동일하게 2~7회 중복 발생시키는 경우가 많았음
      (2026-09-10, kdt-backendj-27th 기준 전체 click_activity의 42%가 정확히 동일 (유저,timestamp) 중복 —
      뷰저블 tap 수 대비 2배 가까이 부풀려져 있던 원인). event_timestamp까지 같은 행은 1건으로만 센다.
    - TRIM: '지원하기' vs '지원하기\\n' 처럼 줄바꿈만 다른 값이 별개로 집계되던 문제 정리
    - excluded: GNB/헤더/푸터 등 페이지 콘텐츠가 아닌 사이트 공통 클릭 텍스트 제외 (설정 관리에서 편집 가능)
    """
    exclude_clause = "AND TRIM(user_click_raw) NOT IN UNNEST(@excluded)" if excluded else ""
    return f"""
        clicks AS (
            SELECT DISTINCT
                user_pseudo_id,
                event_timestamp,
                TRIM((SELECT ep.value.string_value FROM UNNEST(event_params) ep WHERE ep.key = 'user_click')) AS user_click_raw
            FROM {cfg.EVENTS_TABLE}
            WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
              AND event_name = 'click_activity'
              AND {_page_match_sql(path_expr)}
        ), clicks_filtered AS (
            SELECT user_pseudo_id, user_click_raw AS user_click
            FROM clicks
            WHERE user_click_raw IS NOT NULL AND user_click_raw != ''
            {exclude_clause}
        )
    """


def get_click_activity(start_date, end_date, url_slug, excluded=None, limit=30):
    """
    click_activity 이벤트의 user_click(클릭된 요소 텍스트) 별 클릭수/클릭유저수
    - 뷰저블 클릭 히트맵의 임시 대체 데이터
    - excluded: GNB/헤더/푸터 같은 사이트 공통 클릭 텍스트 목록 (bq.get_click_exclusions())
    """
    client = get_client()
    excluded = excluded or []
    path_expr = "SPLIT((SELECT ep2.value.string_value FROM UNNEST(event_params) ep2 WHERE ep2.key='page_location'), '?')[OFFSET(0)]"
    query = f"""
        WITH {_clicks_cte(path_expr, excluded)}
        SELECT
            user_click,
            COUNT(*) AS clicks,
            COUNT(DISTINCT user_pseudo_id) AS unique_clickers
        FROM clicks_filtered
        GROUP BY user_click
        ORDER BY clicks DESC
        LIMIT {int(limit)}
    """
    params = _date_params(start_date, end_date, url_slug)
    if excluded:
        params.append(bigquery.ArrayQueryParameter("excluded", "STRING", excluded))
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    return client.query(query, job_config=job_config).to_dataframe()


def get_click_totals(start_date, end_date, url_slug, excluded=None) -> dict:
    """click_activity 총 클릭수 / 총 클릭유저수 (랭킹 카드의 '전체 클릭 비중 %' 계산용, excluded 제외 후 기준)"""
    client = get_client()
    excluded = excluded or []
    path_expr = "SPLIT((SELECT ep2.value.string_value FROM UNNEST(event_params) ep2 WHERE ep2.key='page_location'), '?')[OFFSET(0)]"
    query = f"""
        WITH {_clicks_cte(path_expr, excluded)}
        SELECT COUNT(*) AS total_clicks, COUNT(DISTINCT user_pseudo_id) AS total_clickers
        FROM clicks_filtered
    """
    params = _date_params(start_date, end_date, url_slug)
    if excluded:
        params.append(bigquery.ArrayQueryParameter("excluded", "STRING", excluded))
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    df = client.query(query, job_config=job_config).to_dataframe()
    row = df.iloc[0]
    return {"total_clicks": int(row["total_clicks"]), "total_clickers": int(row["total_clickers"])}
