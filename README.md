# 상세페이지 임시 분석 대시보드 (뷰저블 대체용)

뷰저블(Beuseable) 트래킹이 상세페이지 조건 변경으로 중단된 동안, GA4 BigQuery 원천 데이터로
클릭수 / 스크롤 도달률을 임시로 확인하기 위한 Streamlit 앱.

## 플로우
1. **설정 관리 (관리자)** 화면에서 부트캠프명 / 기수 / 상세페이지 URL slug / 조회 기간을 등록
2. **데이터 조회** 화면에서 등록된 목록 중 확인하고 싶은 항목을 선택
3. 자동으로 GA4 BigQuery를 조회해 개요 지표 / 스크롤 퍼널 / 클릭 분석을 시각화

## 실행 방법
```bash
cd /Users/hwangsungjin/Desktop/growthmarketing/scripts/detail_page_dashboard
/Users/hwangsungjin/ads_automation/.venv/bin/streamlit run app.py
```
브라우저가 자동으로 열리며, 기본적으로 `localhost`에서만 접속 가능하다 (본인 컴퓨터에서만 확인 가능).
팀원들이 같이 접속하려면 별도 호스팅(사내 서버 / Streamlit Community Cloud 등)이 필요 — 아직 미정, 논의 필요.

## 파일 구성
| 파일 | 역할 |
|---|---|
| `app.py` | Streamlit UI (설정 관리 / 데이터 조회 2개 화면) |
| `config.py` | 공통 설정 (기존 `config/sheets_config.json`의 BQ 프로젝트/GA4 데이터셋/서비스계정 재사용) |
| `bq.py` | BigQuery 클라이언트 + 설정(config) 테이블 CRUD |
| `queries.py` | 개요/스크롤 퍼널/클릭 분석 파라미터화 쿼리 |

## 데이터 저장 위치
- 설정(등록) 테이블: `growth_marketing.detail_page_configs` (우리 팀 쓰기 전용 데이터셋, 기존 `admin_attribution`과 동일 위치)
- 원천 데이터: `analytics_465855462` (GA4, **읽기 전용** — 이 앱은 SELECT만 수행)

## 쿼리 설계 시 확인한 실제 데이터 기반 주의사항
- **scroll_percent vs percent_scrolled**: `scroll` 이벤트에 두 파라미터가 서로 배타적으로 찍힘.
  - `scroll_percent` (커스텀 구현): 20/50/70/90 구간별
  - `percent_scrolled` (GA4 향상된 측정 자동수집): 90 고정값만
  - 반드시 `COALESCE(scroll_percent, percent_scrolled)`로 합쳐야 90% 도달 유저 누락이 없다. (`queries.get_scroll_funnel` 참고)
- **page_location 필드 포맷이 이벤트마다 다름**: `page_view`/`scroll`의 `page_location`은 UTM 쿼리스트링이 붙은 전체 URL, `click_activity`의 `page_location`은 path만 담김. 그래서 항상 `SPLIT(url, '?')[OFFSET(0)]`로 path만 잘라서 비교한다.
- **지원페이지가 상세페이지 슬러그를 서브패스로 포함**: 예) `.../school/kdt-backendj-27th/kdt-apply`. `LIKE '%슬러그%'` 조건만으로는 지원페이지도 같이 잡히므로, 상세페이지 방문자를 셀 때는 항상 `NOT LIKE '%apply%'`를 함께 걸어야 한다 (원본 쿼리는 이 필터가 `page_visitors`에는 빠져 있었음 — 수정함).
- **클릭수**: `click_activity` 이벤트의 `user_click` 파라미터에 클릭된 요소의 텍스트가 그대로 담겨 있어, 이걸 뷰저블 클릭 히트맵의 임시 대체 데이터로 사용한다.
  - `kdt_*_btn_click`, `GNB_*_btn_click` 같은 이름 붙은 CTA 이벤트는 **의도적으로 제외**했다. 이 이벤트들엔 페이지 컨텍스트 파라미터가 없어서 "해당 기간 상세페이지 방문 유저" 기준으로만 근사할 수 있었는데, `GNB_*`처럼 전역 네비게이션 버튼은 유저가 다른 페이지에서 누른 것까지 섞여 들어가 상세페이지 클릭으로 보기엔 부정확했다. `click_activity`는 이벤트 자체에 해당 페이지의 `page_location`이 찍혀 있어 상세페이지 스코프가 명확하므로, 클릭 분석은 이것만 사용한다.
  - **GNB/헤더/푸터 텍스트 제외**: `click_activity`는 상세페이지 콘텐츠뿐 아니라 로그인/부트캠프/취업지원 같은 사이트 공통 메뉴 클릭도 같이 잡는다. `growth_marketing.click_exclusions` 테이블(전역, url_slug 무관하게 공통 적용)에 정확히 일치하는 문구를 등록해두면 제외된다 — "설정 관리" 화면에서 마케터가 직접 편집 가능. 2026-09-10 실데이터(28기) 상위 40개 중 검토해서 27개를 시드로 등록해둠(`bq.DEFAULT_CLICK_EXCLUSIONS`).
  - **중복 이벤트 제거 (중요)**: 2026-09-10, 뷰저블 tap 리포트(27기, 2026-07-16~08-15)와 직접 대조한 결과, 같은 유저의 같은 클릭이 `event_timestamp`까지 완전히 동일하게 최대 7회까지 중복 발생하는 사례를 다수 확인함 (해당 기간 전체 click_activity의 42%가 이런 정확한 중복). `queries._clicks_cte`에서 `SELECT DISTINCT (user_pseudo_id, event_timestamp, user_click)`로 중복 제거 후 집계한다.
  - **뷰저블과 정확히 일치하지는 않음**: 위 중복 제거를 적용해도 뷰저블 대비 여전히 차이가 있다 (2026-09-10 확인: 27기 "지원하기" 버튼 — 뷰저블 956회 vs 우리 쪽 1,626회, 약 1.7배). 남은 차이의 정확한 원인은 미확인(요소 판별 방식이 좌표 기반 vs 텍스트 기반으로 다른 점, PV 집계 자체도 뷰저블 36,550 vs 우리 49,256으로 이미 ~35% 차이 나는 점 등이 후보). **이 도구는 뷰저블과 절대값을 맞추는 게 목적이 아니라, 산정 기준을 명확히 밝힌 상태로 기간별 추세·상대비교를 보기 위한 임시 대체재**라는 게 담당자와 합의된 방향 — 화면의 "산정 기준" 펼치기에 이 내용을 그대로 노출한다.

## 남아있는 결정/미구현 사항
- **호스팅**: 지금은 로컬 실행만 됨. 여러 사람이 접속하려면 사내 서버든 외부 서비스든 배포 방식 결정 필요.
- **접근 제어**: 관리자/조회자 구분이 화면상 메뉴 분리로만 되어 있고 별도 인증은 없음. 필요시 추가 논의.
- **비용/캐싱**: 설정 목록은 60초 캐싱하지만, 조회 쿼리 자체는 매번 새로 실행됨. 조회가 잦아지면 캐싱 또는 사전 집계 테이블화 검토.
