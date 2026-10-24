# 서울 아파트 실거래 탐색

국토교통부 실거래가(매매·전월세)를 매일 아침 자동으로 받아 정리하고, 필터·정렬이 되는 사이트로 보여줍니다.

## 구성
- `scripts/fetch_molit.py` — 서울 25개 구, 최근 6개월 실거래 수집 및 정제
  - 해제된 거래와 직거래는 빼요.
  - 같은 동의 같은 이름 단지는 하나로 합쳐요.
  - 전용면적은 1㎡ 단위로 묶고, 대표값은 중간값을 써요.
- `.github/workflows/update.yml` — 매일 06:17(KST)에 수집하고, 데이터를 커밋한 뒤 사이트에 배포
- `site/` — 사이트 (`site/data/summary.json`은 자동 생성)

## 최초 설정
1. **인증키 등록:** Settings → Secrets and variables → Actions에 `MOLIT_API_KEY` 이름으로 공공데이터포털 Decoding 인증키를 등록해요.
2. **배포 방식 설정:** Settings → Pages → Build and deployment의 Source를 **GitHub Actions**로 바꿔요.
3. **첫 실행:** Actions 탭 → "실거래 데이터 업데이트" → **Run workflow**를 눌러요.
   - 첫 실행은 10~20분쯤 걸려요.
   - 끝나면 `https://<아이디>.github.io/<저장소이름>/`에서 사이트를 볼 수 있어요.

## 참고
- 실거래 신고 기한은 계약 후 30일이에요. 그래서 최근 두 달은 데이터가 덜 차 있어요.
- 표시 가격은 신고된 계약가예요. 현재 매물의 호가가 아니에요.
