"""python -m scripts.probes.disclosure_api [--product deposit|saving]"""

import argparse

from scripts.probes.common import credential, fetch_sample


def main():
    parser = argparse.ArgumentParser(description="금융상품 한눈에 상품·금리 응답 확인")
    parser.add_argument("--product", choices=["deposit", "saving"], default="deposit")
    parser.add_argument("--group", default="020000", help="은행: 020000, 저축은행: 030300")
    parser.add_argument("--page", type=int, default=1)
    args = parser.parse_args()
    if args.page < 1:
        parser.error("page는 1 이상이어야 합니다")
    key = credential("FSS_API_KEY")
    endpoint = "depositProductsSearch.json" if args.product == "deposit" else "savingProductsSearch.json"
    payload = fetch_sample(
        f"https://finlife.fss.or.kr/finlifeapi/{endpoint}",
        {"auth": key, "topFinGrpNo": args.group, "pageNo": args.page},
        key, "disclosure", args.product,
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise SystemExit("예상 result 객체가 없습니다. 저장된 응답을 확인하세요.")
    print("result 필드:", list(result))
    if str(result.get("err_cd")) != "000":
        raise SystemExit("API 업무 오류: 정상 데이터가 아닙니다. 저장된 응답의 err_cd/err_msg를 확인하세요.")
    for name in ("baseList", "optionList"):
        rows = result.get(name)
        if not isinstance(rows, list):
            raise SystemExit(f"{name}가 목록이 아닙니다.")
        print(f"{name}: {len(rows)}건 / 첫 항목 필드: {list(rows[0]) if rows else []}")


if __name__ == "__main__":
    main()
