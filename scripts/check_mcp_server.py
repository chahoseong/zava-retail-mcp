"""실행 중인 MCP 서버에 HTTP로 접속하여 도구 이름 목록을 출력한다."""

import argparse
import asyncio
import json
import sys
from urllib.parse import urlsplit

from mcp import Client


def server_url(value: str) -> str:
    """HTTP URL만 받아 SDK의 다른 전송 방식으로 해석되는 것을 막는다."""
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )
        _ = parsed.port  # 잘못된 포트 표기는 ValueError로 거부한다.
    except ValueError:
        valid = False
    if not valid:
        raise argparse.ArgumentTypeError(
            "사용자 정보와 프래그먼트가 없는 HTTP(S) URL을 지정하세요"
        )
    return value


async def check_server(url: str) -> None:
    """서버 객체를 직접 전달하지 않고 실제 URL로 도구 목록을 요청한다."""
    async with asyncio.timeout(15):
        async with Client(url) as client:
            result = await client.list_tools()
    print(json.dumps([tool.name for tool in result.tools], ensure_ascii=False))


def main() -> int:
    """접속 실패나 시간 초과는 원본 예외 없이 비정상 종료로 보고한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", type=server_url, help="실행 중인 서버의 MCP HTTP URL")
    args = parser.parse_args()
    try:
        asyncio.run(check_server(args.url))
    except KeyboardInterrupt:
        return 130
    except Exception:
        print(
            "MCP 통신 확인 실패: 서버 실행 상태와 접속 URL을 확인하세요 (제한 15초).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
