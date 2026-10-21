"""API 응답 확인용 공통 입출력. 인증값과 요청 URL은 기록하지 않는다."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote, quote_plus
from urllib.request import Request, urlopen

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def credential(name):
    value = os.environ.get(name) or dotenv_values(ROOT / ".env").get(name)
    if not value:
        raise SystemExit(f"{name} 미설정: 터미널에서 export하거나 프로젝트 .env에 입력하세요.")
    return value


def fetch_sample(url, params, secret, folder, label):
    request = Request(url + "?" + urlencode(params), headers={"User-Agent": "RedPen-API-Probe/0.1"})
    try:
        with urlopen(request, timeout=30) as response:
            status, content_type = response.status, response.headers.get("Content-Type", "")
            body = response.read().decode("utf-8-sig", errors="replace")
    except HTTPError as error:
        status, content_type = error.code, error.headers.get("Content-Type", "")
        body = error.read().decode("utf-8-sig", errors="replace")
    except (URLError, TimeoutError, OSError) as error:
        # 예외 문자열에는 인증값을 포함한 URL이 들어갈 수 있어 출력하지 않는다.
        raise SystemExit(f"요청 실패 ({type(error).__name__}). 네트워크·인증·API 가용성을 확인하세요.") from None

    for value in {secret, quote(secret, safe=""), quote_plus(secret)}:
        body = body.replace(value, "[REDACTED]")
    try:
        payload = json.loads(body)
        extension = "json"
    except json.JSONDecodeError:
        payload = None
        extension = "xml" if body.lstrip().startswith("<?xml") else "txt"
    timestamp = datetime.now(timezone.utc)
    directory = ROOT / "samples" / folder
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}_{label}"
    path.with_suffix("." + extension).write_text(body, encoding="utf-8")
    metadata = {
        "fetched_at": timestamp.isoformat(), "endpoint": url,
        "parameters": {key: value for key, value in params.items() if key not in {"OC", "auth"}},
        "http_status": status, "content_type": content_type,
        "json_parsed": payload is not None,
    }
    path.with_suffix(".meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"HTTP {status} / {content_type} / 저장: {path.relative_to(ROOT)}.{extension}")
    print("최상위 필드:", list(payload) if isinstance(payload, dict) else "JSON 객체 아님")
    if not 200 <= status < 300:
        raise SystemExit("HTTP 오류 응답을 저장했습니다. 정상 데이터 수신은 실패했습니다.")
    return payload
