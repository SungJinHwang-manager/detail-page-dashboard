# 배포 가이드 (Streamlit Community Cloud)

멋사 내부 구성원이라면 누구나 링크로 접속할 수 있게 하는 방법. 아래는 웹 화면에서 직접 해야 하는
단계라 담당자가 순서대로 따라 하면 됩니다 (5~10분).

## 1. Streamlit Community Cloud 가입/로그인
1. https://share.streamlit.io 접속
2. "Sign in" → 이 레포를 소유한 GitHub 계정으로 로그인
3. Private 레포로 만들었다면, Streamlit이 그 레포에 접근할 수 있도록 GitHub 연동 화면에서 권한을 허용해야 함

## 2. 새 앱 배포
1. "Create app" (또는 "New app") 클릭
2. 아래처럼 입력:
   - Repository: (이 레포)
   - Branch: `main`
   - Main file path: `app.py`
3. "Advanced settings"에서 Python 버전 3.11 이상으로 설정 (권장)
4. "Deploy" 클릭 → 몇 분 기다리면 `https://xxxxx.streamlit.app` 형태의 링크가 생성됨

## 3. Secrets 설정 (필수 — 이거 안 하면 BigQuery 연결 실패함)
1. 배포된 앱 화면에서 오른쪽 아래 "⋮" → "Settings" → "Secrets"
2. 이 폴더의 `.streamlit/secrets.toml.example` 파일을 열어서 형식을 참고
3. 실제 값 채워서 붙여넣기:
   - `APP_PASSWORD`: 팀에서 공유할 접속 비밀번호를 아무거나 정해서 입력
   - `[gcp_service_account]`: 기존 서비스계정 JSON 키 파일(`ga4-bigquery-377201-....json`) 내용을 그대로 옮겨 적기
     (파일 위치: `/Users/hwangsungjin/Documents/GitHub/ad-report-automation/ga4-bigquery-377201-7042882c9647.json`)
4. "Save" → 앱이 자동으로 재시작됨

## 4. 접속 링크 공유
- 생성된 `https://xxxxx.streamlit.app` 링크 + 위에서 정한 `APP_PASSWORD`를 팀원들에게 공유
- 비밀번호는 브라우저 세션에 저장되므로, 한 번 입력하면 탭을 닫기 전까진 다시 안 물어봄

## 알아둘 점
- **스크린샷(스크롤 히트맵용 캡처 이미지)은 재배포/재시작 시 초기화될 수 있습니다.** 로컬 디스크에
  저장하는 방식이라 Streamlit Cloud의 임시 파일시스템 특성상 영구 보관이 보장되지 않습니다.
  자주 초기화되어 불편하면 그때 GCS(Google Cloud Storage) 저장 방식으로 바꾸는 걸 논의해야 합니다.
- BigQuery 조회 비용은 서비스계정이 속한 GCP 프로젝트(`ga4-bigquery-377201`)로 청구됩니다.
- 이 레포는 Private로 만들었습니다. 서비스계정 키나 비밀번호는 어차피 secrets에만 있고 코드에는
  없어서 Public이어도 새는 건 없지만, 내부 쿼리 로직까지 굳이 공개할 필요는 없어서 Private로 유지합니다.
