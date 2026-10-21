"""python -m scripts.probes.law_api [--law-id ID --article 002200]"""

import argparse

from scripts.probes.common import credential, fetch_sample


def main():
    parser = argparse.ArgumentParser(description="법령 검색 또는 조항호목 응답 확인")
    parser.add_argument("--query", default="금융소비자 보호에 관한 법률")
    parser.add_argument("--law-id")
    parser.add_argument("--article", default="002200")
    args = parser.parse_args()
    key = credential("LAW_OC")
    params = {"OC": key, "type": "JSON"}
    if args.law_id:
        params.update(target="lawjosub", ID=args.law_id, JO=args.article)
        endpoint, label = "lawService.do", "article"
    else:
        params.update(target="law", query=args.query, display="5", page="1")
        endpoint, label = "lawSearch.do", "search"
    payload = fetch_sample(f"https://www.law.go.kr/DRF/{endpoint}", params, key, "law", label)
    if not isinstance(payload, dict):
        raise SystemExit("정상 JSON 객체가 아닙니다. 저장된 응답을 확인하세요.")
    if not args.law_id:
        result = payload.get("LawSearch")
        if not isinstance(result, dict) or not result.get("law"):
            raise SystemExit("법령 검색 결과가 없습니다. 인증 또는 응답을 확인하세요.")
        print("검색 결과 필드:", list(result))
        laws = result["law"]
        first = laws[0] if isinstance(laws, list) else laws
        print("법령 항목 필드:", list(first))
        print("첫 법령 ID:", first.get("법령ID"))
    elif "법령" not in payload:
        raise SystemExit("예상 법령 필드가 없습니다. 저장된 응답을 확인하세요.")


if __name__ == "__main__":
    main()
