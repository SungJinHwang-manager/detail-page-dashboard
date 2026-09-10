"""BigQuery 클라이언트 및 설정(config) 테이블 CRUD"""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from google.cloud import bigquery

import auth
import config as cfg


@st.cache_resource
def get_client() -> bigquery.Client:
    creds = auth.get_credentials()
    return bigquery.Client(credentials=creds, project=cfg.BQ_PROJECT)


def ensure_config_table():
    """설정 테이블이 없으면 생성, 있으면 신규 컬럼(스크린샷 관련)만 추가 마이그레이션"""
    client = get_client()
    schema = [
        bigquery.SchemaField("url_slug", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("bootcamp_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("cohort", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("start_date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("end_date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("created_by", "STRING"),
        bigquery.SchemaField("created_at", "TIMESTAMP"),
        bigquery.SchemaField("updated_at", "TIMESTAMP"),
        bigquery.SchemaField("screenshot_path", "STRING"),
        bigquery.SchemaField("screenshot_height_px", "INTEGER"),
    ]
    table_id = f"{cfg.BQ_PROJECT}.{cfg.CONFIG_DATASET}.{cfg.CONFIG_TABLE}"
    table = bigquery.Table(table_id, schema=schema)
    table = client.create_table(table, exists_ok=True)

    existing_names = {f.name for f in table.schema}
    missing = [f for f in schema if f.name not in existing_names]
    if missing:
        table.schema = list(table.schema) + missing
        client.update_table(table, ["schema"])


@st.cache_data(ttl=60)
def list_configs() -> pd.DataFrame:
    client = get_client()
    query = f"""
        SELECT url_slug, bootcamp_name, cohort, start_date, end_date, created_by, updated_at,
               screenshot_path, screenshot_height_px
        FROM {cfg.CONFIG_TABLE_FQN}
        ORDER BY updated_at DESC
    """
    return client.query(query).to_dataframe()


def set_screenshot(url_slug: str, screenshot_path: str, height_px: int):
    """설정 관리 화면에서 업로드한 상세페이지 캡처 이미지 경로/높이 저장"""
    client = get_client()
    query = f"""
        UPDATE {cfg.CONFIG_TABLE_FQN}
        SET screenshot_path = @path, screenshot_height_px = @height, updated_at = CURRENT_TIMESTAMP()
        WHERE url_slug = @url_slug
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("path", "STRING", screenshot_path),
            bigquery.ScalarQueryParameter("height", "INT64", height_px),
            bigquery.ScalarQueryParameter("url_slug", "STRING", url_slug),
        ]
    )
    client.query(query, job_config=job_config).result()
    list_configs.clear()


def upsert_config(url_slug: str, bootcamp_name: str, cohort: str, start_date, end_date, created_by: str):
    """url_slug를 고유키로 등록/수정 (MERGE)"""
    client = get_client()
    now = datetime.now(timezone.utc).isoformat()
    query = f"""
        MERGE {cfg.CONFIG_TABLE_FQN} T
        USING (SELECT
            @url_slug AS url_slug,
            @bootcamp_name AS bootcamp_name,
            @cohort AS cohort,
            @start_date AS start_date,
            @end_date AS end_date,
            @created_by AS created_by,
            TIMESTAMP(@now) AS now
        ) S
        ON T.url_slug = S.url_slug
        WHEN MATCHED THEN UPDATE SET
            bootcamp_name = S.bootcamp_name,
            cohort = S.cohort,
            start_date = S.start_date,
            end_date = S.end_date,
            updated_at = S.now
        WHEN NOT MATCHED THEN
            INSERT (url_slug, bootcamp_name, cohort, start_date, end_date, created_by, created_at, updated_at)
            VALUES (S.url_slug, S.bootcamp_name, S.cohort, S.start_date, S.end_date, S.created_by, S.now, S.now)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("url_slug", "STRING", url_slug),
            bigquery.ScalarQueryParameter("bootcamp_name", "STRING", bootcamp_name),
            bigquery.ScalarQueryParameter("cohort", "STRING", cohort),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            bigquery.ScalarQueryParameter("created_by", "STRING", created_by),
            bigquery.ScalarQueryParameter("now", "STRING", now),
        ]
    )
    client.query(query, job_config=job_config).result()
    list_configs.clear()  # 캐시 무효화


CLICK_EXCLUSIONS_TABLE = "click_exclusions"
CLICK_EXCLUSIONS_FQN = f"`{cfg.BQ_PROJECT}.{cfg.CONFIG_DATASET}.{CLICK_EXCLUSIONS_TABLE}`"

# GNB/헤더/푸터처럼 페이지 콘텐츠가 아닌 사이트 공통 클릭 텍스트 (2026-09-10, kdt-backendj-28th
# click_activity 상위 40개 실데이터 기준으로 확인된 것만 시드. 애매한 것(닫기/오늘 그만보기/내일배움카드 등)은
# 일부러 제외 목록에 넣지 않음 - 설정 관리 화면에서 마케터가 직접 검토 후 추가/삭제하면 된다.
DEFAULT_CLICK_EXCLUSIONS = [
    "로그인", "log in", "로그아웃",
    "부트캠프", "취업지원", "블로그", "강의목록", "수강신청",
    "블로그 홈", "IT 트렌드", "학습 일기", "환불규정", "이용약관", "개인정보처리방침",
    "멋쟁이사자처럼", "멋사 커리어",
    "클라우드 엔지니어링", "백엔드 : JAVA", "백엔드 : Python", "프론트엔드",
    "앱 개발 : iOS", "앱 개발 : Android", "유니티 게임 개발", "블록체인",
    "데이터 분석", "그로스 마케팅", "AI 심화 : 자연어 처리",
    "부트캠프\n취업지원\n블로그\n내일배움카드",
]


def ensure_click_exclusions_table():
    client = get_client()
    schema = [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("phrases", "STRING", mode="REPEATED"),
        bigquery.SchemaField("updated_at", "TIMESTAMP"),
    ]
    table = bigquery.Table(f"{cfg.BQ_PROJECT}.{cfg.CONFIG_DATASET}.{CLICK_EXCLUSIONS_TABLE}", schema=schema)
    client.create_table(table, exists_ok=True)

    # 최초 1회, 비어있을 때만 기본 시드값 삽입
    existing = client.query(
        f"SELECT COUNT(*) AS n FROM {CLICK_EXCLUSIONS_FQN} WHERE id = 'global'"
    ).to_dataframe()
    if existing.iloc[0]["n"] == 0:
        set_click_exclusions(DEFAULT_CLICK_EXCLUSIONS)


@st.cache_data(ttl=60)
def get_click_exclusions() -> list:
    client = get_client()
    df = client.query(
        f"SELECT phrases FROM {CLICK_EXCLUSIONS_FQN} WHERE id = 'global'"
    ).to_dataframe()
    if df.empty:
        return []
    return list(df.iloc[0]["phrases"])


def set_click_exclusions(phrases: list):
    """설정 관리 화면에서 편집한 제외 문구 목록 저장 (사이트 전역 적용, 문구 그대로 TRIM 후 정확히 일치할 때만 제외)"""
    client = get_client()
    phrases = [p.strip() for p in phrases if p.strip()]
    query = f"""
        MERGE {CLICK_EXCLUSIONS_FQN} T
        USING (SELECT 'global' AS id, @phrases AS phrases, CURRENT_TIMESTAMP() AS now) S
        ON T.id = S.id
        WHEN MATCHED THEN UPDATE SET phrases = S.phrases, updated_at = S.now
        WHEN NOT MATCHED THEN INSERT (id, phrases, updated_at) VALUES (S.id, S.phrases, S.now)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("phrases", "STRING", phrases)]
    )
    client.query(query, job_config=job_config).result()
    get_click_exclusions.clear()


def delete_config(url_slug: str):
    client = get_client()
    query = f"DELETE FROM {cfg.CONFIG_TABLE_FQN} WHERE url_slug = @url_slug"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("url_slug", "STRING", url_slug)]
    )
    client.query(query, job_config=job_config).result()
    list_configs.clear()
