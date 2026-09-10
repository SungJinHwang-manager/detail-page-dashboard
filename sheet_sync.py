"""
'[그로스팀] 2026 마케팅 데이터' 시트의 'Index_클래스별 목표 데이터' 탭에서
과정별 url_slug(클래스)/시작일정/종료일정을 읽어와 설정(config) 테이블에 자동 반영한다.

담당자가 이 시트에 이미 항상 기록해두는 데이터라서, '설정 관리' 화면에서 slug/기간을 다시
손으로 입력할 필요 없이 이 시트를 그대로 소스로 쓴다. (본진 시트는 읽기 전용 — 절대 쓰지 않는다)
"""
import re
from datetime import datetime

import gspread
import streamlit as st

import auth
import config as cfg

# url_slug 접두사(kdt-XXX) -> 화면에 보여줄 부트캠프 표시명.
# 2026-09-10 기준 이 시트에 실제로 존재하는 접두사(backendj/cld/growth/aiplus_nlp)만 확인해서 채움.
# 새 과정 라인이 생기면 여기 추가해야 함 — 없는 접두사는 그냥 접두사 그대로 표시(동작은 함).
PREFIX_TO_NAME = {
    "kdt-backendj": "백엔드 자바",
    "kdt-cld": "클라우드",
    "kdt-growth": "그로스마케팅",
    "kdt-aiplus_nlp": "AI(자연어처리)",
}

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
           "https://www.googleapis.com/auth/drive.readonly"]


@st.cache_resource
def _get_gspread_client():
    creds = auth.get_credentials(scopes=_SCOPES)
    return gspread.authorize(creds)


def _parse_slug(slug: str):
    m = re.match(r"^(kdt-[a-z_]+)-(\d+)th$", slug)
    if m:
        prefix, num = m.group(1), m.group(2)
        return PREFIX_TO_NAME.get(prefix, prefix), f"{num}기"
    return slug, "-"


def fetch_class_schedule() -> list:
    """시트에서 (url_slug, bootcamp_name, cohort, start_date, end_date) 목록을 읽어온다.
    날짜 파싱에 실패하거나 클래스명이 비어있는 행은 건너뛴다."""
    gc = _get_gspread_client()
    sh = gc.open_by_key(cfg.MASTER_SHEET_ID)
    ws = sh.worksheet(cfg.CLASS_SCHEDULE_SHEET_NAME)
    rows = ws.get("B2:D")  # B=클래스, C=시작일정, D=종료일정

    result = []
    skipped = []
    for row in rows:
        if len(row) < 3 or not row[0].strip():
            continue
        slug = row[0].strip()
        try:
            start_date = datetime.strptime(row[1].strip(), "%Y/%m/%d").date()
            end_date = datetime.strptime(row[2].strip(), "%Y/%m/%d").date()
        except (ValueError, IndexError):
            skipped.append(slug)
            continue
        name, cohort = _parse_slug(slug)
        result.append({
            "url_slug": slug, "bootcamp_name": name, "cohort": cohort,
            "start_date": start_date, "end_date": end_date,
        })
    return result, skipped
