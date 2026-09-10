"""
상세페이지 임시 분석 대시보드 - 공통 설정

값 자체는 비밀이 아니라서(프로젝트ID/데이터셋명/시트ID는 알아도 서비스계정 인증 없이는 접근 불가)
코드에 그대로 둔다. 실제 인증(서비스계정 키)은 auth.py가 담당 — 로컬은 SERVICE_ACCOUNT_PATH 파일,
배포 환경(Streamlit Cloud)은 secrets의 [gcp_service_account]를 사용한다.

로컬에서 기존 growthmarketing 프로젝트의 config/sheets_config.json이 있으면 그 값으로 덮어써서
기존 워크플로우(admin_attribution.py 등)와 동일한 값을 계속 공유한다. 없어도(예: 조직 레포로
옮겨서 배포하는 경우) 아래 기본값으로 그대로 동작한다.
"""
import json
import os

# --- GA4 원천 데이터 (읽기 전용) ---
BQ_PROJECT = "ga4-bigquery-377201"
GA4_DATASET = "analytics_465855462"
SERVICE_ACCOUNT_PATH = "/Users/hwangsungjin/Documents/GitHub/ad-report-automation/ga4-bigquery-377201-7042882c9647.json"

# --- 이 대시보드 전용 설정 테이블 (우리 팀 쓰기 전용 데이터셋) ---
CONFIG_DATASET = "growth_marketing"
CONFIG_TABLE = "detail_page_configs"

# --- '[그로스팀] 2026 마케팅 데이터' 시트 (본진 시트, 읽기 전용) — 과정 일정 자동 동기화용 ---
MASTER_SHEET_ID = "1Nqsc6xvHu-V1u7jyAgPvS1il0jIs9LK6cGRs4f98Qro"
CLASS_SCHEDULE_SHEET_NAME = "Index_클래스별 목표 데이터"

# 로컬 개발 환경이면(growthmarketing 프로젝트 안에서 실행 중이면) 기존 설정 파일 값으로 덮어쓴다.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SHEETS_CONFIG_PATH = os.path.join(_ROOT, "config", "sheets_config.json")
if os.path.exists(_SHEETS_CONFIG_PATH):
    with open(_SHEETS_CONFIG_PATH, "r", encoding="utf-8") as f:
        _base_config = json.load(f)
    BQ_PROJECT = _base_config.get("bq_project", BQ_PROJECT)
    GA4_DATASET = _base_config.get("ga4_dataset", GA4_DATASET)
    SERVICE_ACCOUNT_PATH = _base_config.get("service_account_path", SERVICE_ACCOUNT_PATH)
    MASTER_SHEET_ID = _base_config.get("sources", {}).get("admin", {}).get("spreadsheet_id", MASTER_SHEET_ID)

EVENTS_TABLE = f"`{BQ_PROJECT}.{GA4_DATASET}.events_*`"
CONFIG_TABLE_FQN = f"`{BQ_PROJECT}.{CONFIG_DATASET}.{CONFIG_TABLE}`"
