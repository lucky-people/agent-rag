# -*- coding: utf-8 -*-
"""
端到端自测：调用 Web API (/api/chat) 覆盖全部链路
  chat      - 闲聊
  house     - 房源查询
  poi       - 景点查询
  combo     - 组合查询
  legal     - 法律咨询（RAG）
  recommend - 交叉推荐（Agentic RAG 双引擎）
"""
import json
import time
import urllib.request

BASE = "http://localhost:8501/api/chat"
SID = f"e2e_{int(time.time())}"

CASES = [
    ("chat", "你好呀"),
    ("house", "帮我推荐金水区2000元以内的房子"),
    ("poi", "二七广场附近有什么好玩的景点"),
    ("legal", "房东不退押金怎么办？"),
    ("combo", "帮我找金水区2000以下的房源，顺便看看二七广场附近有什么好吃的"),
    ("recommend", "推荐一套1号线沿线2000以内离地铁近的房子"),
]


def call(message):
    body = json.dumps({"session_id": SID, "message": message}).encode("utf-8")
    req = urllib.request.Request(BASE, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return round((time.time() - t0) * 1000), data


def main():
    print("=" * 70)
    print(f"端到端自测 session={SID}")
    print("=" * 70)
    ok = 0
    for route, msg in CASES:
        try:
            ms, data = call(msg)
            reply = (data.get("reply") or "")[:90].replace("\n", " ")
            r = data.get("route", "?")
            status = "OK" if reply else "EMPTY"
            if reply:
                ok += 1
            print(f"[{status}] {route:<10} {ms:>8.0f}ms | route={r} | {reply}")
        except Exception as e:
            print(f"[FAIL] {route:<10} EXC: {str(e)[:100]}")
    print("=" * 70)
    print(f"通过 {ok}/{len(CASES)} 条链路")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
