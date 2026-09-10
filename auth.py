"""
GCP 서비스계정 인증 헬퍼.

로컬 개발: config.SERVICE_ACCOUNT_PATH의 JSON 키 파일을 그대로 사용.
Streamlit Community Cloud 배포: 로컬 파일이 없으므로, 배포 시 앱 설정의 secrets(TOML)에
[gcp_service_account] 섹션으로 키 내용을 넣어두면 그걸 우선 사용한다.
→ 서비스계정 키 파일이 git에 커밋될 일이 없다 (secrets는 Streamlit Cloud 쪽에만 저장됨).
"""
import streamlit as st
from google.oauth2 import service_account

import config as cfg


def get_credentials(scopes=None):
    try:
        if "gcp_service_account" in st.secrets:
            info = dict(st.secrets["gcp_service_account"])
            return service_account.Credentials.from_service_account_info(info, scopes=scopes)
    except Exception:
        pass  # secrets.toml 자체가 없는 로컬 환경 등 — 파일 방식으로 폴백
    return service_account.Credentials.from_service_account_file(cfg.SERVICE_ACCOUNT_PATH, scopes=scopes)


def app_password() -> str:
    """배포 시 secrets에 설정한 접속 비밀번호. 로컬 개발(secrets 없음)에서는 None."""
    try:
        return st.secrets.get("APP_PASSWORD")
    except Exception:
        return None
