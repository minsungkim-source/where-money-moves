# เงินไหลไปไหน · Where Money Moves Thailand (MVP)

태국 **군(อำเภอ) 단위로 돈이 어디로 움직이는지** 보여주는 정적 웹사이트.
태국중앙은행(BOT)의 월간 군별 예금·여신·지점 수를 전년 동월과 비교해 순위를 매긴다.

- 태국어가 메인(`/th/`), 영어는 같은 페이지의 다른 판(`/en/`)
- 페이지 696개: 홈 · 주 77 · 군 264 · 순위 5 · 방법론 (×2 언어)
- 휴대폰 우선 레이아웃, PWA(홈 화면 설치), JS 없이도 전부 읽힘 (검색 노출용)
- 런타임 백엔드 없음. `build.py`는 표준 라이브러리만 쓴다

기획 배경: 미국판 `WhereMoneyMoves` 기획을 태국·동남아로 옮긴 것.
"90일 계획 대신 최소 MVP를 먼저 내고 확장" 원칙으로 만든 첫 판이다.

## 데이터

| 소스 | 쓰는 값 | 기준 | 비고 |
|---|---|---|---|
| BOT `cb_t3E-district.zip` | 군별 지점 수 · 예금 · 여신 (월) | **2026-07** | 상업은행 4곳 이상인 군만 (~235곳) |
| thailand-canonical-admin-names v1.0.2 | 주·군 코드, 태국어 이름, 중심점 | | CC BY 4.0 |
| geoBoundaries / OCHA (via blindspot-th) | 주 경계 | | CC BY 3.0 IGO |
| NESDC GPP 2024 (via blindspot-th) | 주 인구 · 1인당 GPP (맥락값) | 2024 | `data/reference/nesdc_context.json` |

**왜 주별 표가 아니라 군별 파일인가** — BOT 주별 표(reportID=781) 공개 페이지는 2025-06에서
멈춰 있다. 군별 zip은 계속 갱신된다. "돈이 어디로 움직이나"는 신선도가 생명이다.

### 알아 둘 성질

- **수록 기준이 움직인다.** 군이 표에서 빠지면(2025-07 → 2026-07에 16곳) 은행이 4곳 미만이 됐다는 뜻으로
  BOT는 설명한다. 증가율은 **두 시점 모두에 있는 군끼리만** 비교한다. 빠진 군을 0으로 두지 않는다.
- 주 수치는 **커버된 군의 합**이지 주 전체가 아니다. 군이 하나도 없는 9개 주는 점수가 없다.
- 같은 달이 두 파일에 있다 (`(2025).xlsx`의 잠정 'P' vs `(2025)_S2.xlsx` 개정). **개정판이 이긴다.**
- 표 양식이 둘이다 (여신 세부 3칸 / 4칸). 지문이 둘 다 아니면 ETL이 멈춘다.
- 여신 세부 칸은 차주 5명 이하면 `n.a.`로 가려진다. 합계는 늘 공표된다.
- 여신은 대형 차주 하나로 크게 튈 수 있다 (예: Rat Burana +5,781%). ±50% 넘으면 ⚠ 배지.
- 명목값. 인플레이션 조정 없음.

## 점수 (Money Momentum Score)

```
score = 평균( pct(예금 YoY), pct(여신 YoY) )     # pct = 같은 단위(군 234 / 주 68) 안의 백분위 0–100
```

백분위를 쓰는 이유는 blindspot-th와 같다 — 방콕이 극단 이상치라 원값이면 나머지가 구분되지 않는다.

## 실행

```bash
# 데이터 (requests + openpyxl 필요. blindspot-th의 venv를 그대로 쓸 수 있다)
../blindspot-th/etl/.venv/bin/python etl/etl.py               # BOT에서 받기 (~9MB)
../blindspot-th/etl/.venv/bin/python etl/etl.py --use-cache   # data/raw/의 zip 재사용

# 사이트 (표준 라이브러리만)
python3 build.py                 # → site/
python3 -m http.server 5180 -d site

# 아이콘·OG 이미지 (macOS, 한 번만. 태국어 글꼴 모양은 CoreText가 잡는다)
../blindspot-th/etl/.venv/bin/python tools/make_assets.py
```

군 이름이 안 붙으면 ETL이 목록을 찍고 멈춘다 → `data/reference/district_aliases.csv`에 한 줄 추가하고 근거를 적는다.
코드에서 이름을 문자열 치환하지 않는다.

## 배포

`vercel.json`이 `python3 build.py` → `site/`를 서빙한다 (Vercel 빌드에 별도 패키지가 필요 없다).
수동 배포는 `./deploy.sh`. 배포 주소가 정해지면 `build.py`의 `SITE_URL`을 바꾼다.

## 다음 (확장 순서)

`docs/BACKLOG.md` 참조.
