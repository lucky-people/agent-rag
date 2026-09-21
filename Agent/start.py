# -*- coding: utf-8 -*-
"""
智租顾问 · 一键启动器（企业级）

用法:
    python start.py            启动全部服务（预检 -> 分组拉起 -> 健康轮询 -> 汇总 -> Web 前台）
    python start.py --status   查看各端口服务与中间件状态
    python start.py --stop     停止由本启动器拉起的全部后台服务

设计要点:
    1. 预检: Python / 中间件(MySQL/Redis/Milvus) / 端口冲突, 问题一次性列清
    2. 分组启动: MCP(4) -> A2A(5) -> Web(1), 组内并发拉起, 组间等待就绪,
       避免 9 个进程同时抢中间件/加载模型导致部分服务起不来
    3. 健康轮询: 每个服务 TCP 端口探测, 最长等待 60s, 就绪后输出汇总表
    4. 日志落盘: logs/startup/<name>.log(.err), 起不来看日志尾部即知原因
    5. PID 追踪: logs/startup/<name>.pid, --stop 只清理本启动器拉起的进程
"""
import os
import socket
import subprocess
import sys
import time
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs", "startup")
os.makedirs(LOGS_DIR, exist_ok=True)

# (服务名, 端口, 启动命令模块)
MCP_SERVERS = [
    ("MCP-House",    8004, "mcp_server.mcp_house_server"),
    ("MCP-Poi",      8005, "mcp_server.mcp_poi_server"),
    ("MCP-Metro",    8006, "mcp_server.mcp_metro_server"),
    ("MCP-Recom",    8007, "mcp_server.mcp_recommend_server"),
]
A2A_SERVERS = [
    ("A2A-House",    5006, "a2a_server.house_server"),
    ("A2A-Poi",      5007, "a2a_server.poi_server"),
    ("A2A-Metro",    5008, "a2a_server.metro_server"),
    ("A2A-Recom",    5009, "a2a_server.recommend_server"),
    ("A2A-Legal",    5010, "a2a_server.legal_agent_server"),
]
WEB_SERVER = ("Web-Frontend", 8501, "web_server")

MIDDLEWARES = [("MySQL", 3306), ("Redis", 6379), ("Milvus", 19530)]
ALL_PORTS = [p for _, p, _ in MCP_SERVERS + A2A_SERVERS + [WEB_SERVER]]


def pick_python():
    py = os.environ.get("ZHIZU_PYTHON", "")
    if not py:
        cand = r"C:\Users\31077\anaconda3\envs\lang_env\python.exe"
        if os.path.exists(cand):
            py = cand
    return py or sys.executable


def port_listening(port, host="127.0.0.1", timeout=0.6):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def tail_log(path, n=12):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return "(无日志)"


def check_python(py):
    try:
        subprocess.run([py, "--version"], capture_output=True, timeout=10, check=True)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def preflight(py):
    print("=" * 62)
    print("  智租顾问 · 一键启动器")
    print("=" * 62)
    if not check_python(py):
        print(f"  [✗] Python 不可用: {py}")
        print("      请设置 ZHIZU_PYTHON 环境变量指向你的 python.exe")
        return False
    print(f"  [✓] Python: {py}")

    print("  ---- 中间件预检 ----")
    for name, port in MIDDLEWARES:
        if port_listening(port):
            print(f"  [✓] {name:<8} {port}")
        else:
            print(f"  [✗] {name:<8} {port} 未监听 -- 相关服务(法律问答/房源)可能异常")
            print("      请先启动: docker compose up -d (MySQL/Redis/Milvus)")

    print("  ---- 端口冲突预检 ----")
    busy = [p for p in ALL_PORTS if port_listening(p)]
    if busy:
        print(f"  [!] 以下端口已被占用(可能是残留进程): {busy}")
        print(f"      可运行: {sys.argv[0]} --stop 清理上次残留, 或手动结束占用进程")
        print("      继续启动可能导致该服务失败。")
    else:
        print("  [✓] 目标端口全部空闲")
    return True


def spawn(py, module, tag, port):
    """后台拉起一个服务, 日志落盘, 记录 PID; 端口已就绪则跳过"""
    if port_listening(port):
        print(f"  [=] {tag:<12} 端口 {port} 已在监听, 跳过启动")
        return "running"
    log = os.path.join(LOGS_DIR, f"{tag}.log")
    err = os.path.join(LOGS_DIR, f"{tag}.err.log")
    with open(log, "w", encoding="utf-8"), open(err, "w", encoding="utf-8"):
        pass
    try:
        proc = subprocess.Popen(
            [py, "-m", module],
            cwd=BASE_DIR,
            stdout=open(log, "w", encoding="utf-8"),
            stderr=open(err, "w", encoding="utf-8"),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as e:
        print(f"  [✗] {tag:<12} 启动失败: {e}")
        return "failed"
    with open(os.path.join(LOGS_DIR, f"{tag}.pid"), "w") as f:
        f.write(str(proc.pid))
    print(f"  [→] {tag:<12} 启动中 (pid={proc.pid})")
    return "started"


def boot_group(py, servers):
    states = {}
    for tag, port, module in servers:
        states[tag] = spawn(py, module, tag, port)
    print("  ---- 健康轮询(最长 60s) ----")
    deadline = time.time() + 60
    pending = {t: p for t, p, _ in servers if states.get(t) == "started"}
    while pending and time.time() < deadline:
        for tag in list(pending):
            if port_listening(pending[tag]):
                states[tag] = "up"
                del pending[tag]
        if pending:
            time.sleep(1)
    for tag, port, _ in servers:
        if states.get(tag) == "up":
            continue
        if states.get(tag) in ("running", "started") and not port_listening(port):
            states[tag] = "failed"
    return states


def print_summary(states, group_name):
    print(f"  ---- {group_name} 汇总 ----")
    for tag, port, _ in (MCP_SERVERS if group_name == "MCP" else A2A_SERVERS):
        st = states.get(tag, "?")
        icon = {"up": "✓", "running": "=", "failed": "✗"}.get(st, "?")
        line = f"  [{icon}] {tag:<12} :{port}  {st}"
        if st == "failed":
            line += f"\n        日志尾部: {tail_log(os.path.join(LOGS_DIR, tag + '.err.log'))}"
        print(line)


def stop_all():
    killed = 0
    for f in os.listdir(LOGS_DIR):
        if not f.endswith(".pid"):
            continue
        pid_file = os.path.join(LOGS_DIR, f)
        tag = f[:-4]
        try:
            pid = int(open(pid_file).read().strip())
        except (OSError, ValueError):
            continue
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=15)
            killed += 1
            print(f"  [✓] 已停止 {tag} (pid={pid})")
        except subprocess.SubprocessError:
            print(f"  [!] 停止 {tag} (pid={pid}) 失败")
        os.remove(pid_file)
    print(f"  共停止 {killed} 个服务进程")


def status_all():
    print("  ---- 中间件 ----")
    for name, port in MIDDLEWARES:
        print(f"  [{'✓' if port_listening(port) else '✗'}] {name:<8} {port}")
    print("  ---- 服务 ----")
    for tag, port, _ in MCP_SERVERS + A2A_SERVERS + [WEB_SERVER]:
        print(f"  [{'✓' if port_listening(port) else '✗'}] {tag:<12} :{port}")


def main():
    py = pick_python()
    args = sys.argv[1:]
    if "--status" in args:
        status_all()
        return 0
    if "--stop" in args:
        stop_all()
        return 0

    if not preflight(py):
        print("\n  预检未通过, 请先解决上述问题后重试。")
        return 1

    print("  [1/3] 启动 MCP 工具服务器 (4)")
    s1 = boot_group(py, MCP_SERVERS)
    print_summary(s1, "MCP")

    print("  [2/3] 启动 A2A 智能体服务器 (5)")
    s2 = boot_group(py, A2A_SERVERS)
    print_summary(s2, "A2A")

    failed = [t for st in (s1, s2) for t, v in st.items() if v == "failed"]
    if failed:
        print(f"\n  [!] 以下服务启动失败: {failed}")
        print(f"      日志目录: {LOGS_DIR}")
        print("      可查看 .err.log 尾部定位原因, 或运行 --stop 后重试。")

    print("  [3/3] 启动 Web 前端 (前台运行)")
    print("  " + "-" * 58)
    print("  浏览器将自动打开 http://localhost:8501")
    print("  管理员看板: http://localhost:8501/admin/dashboard  (admin/admin123)")
    print("  关闭本窗口或 Ctrl+C = 停止 Web; 其他服务保持后台运行")
    print("  停止全部服务: python start.py --stop")
    print("  " + "-" * 58)
    if not port_listening(WEB_SERVER[1]):
        webbrowser.open("http://localhost:8501")
        try:
            proc = subprocess.run([py, "-m", WEB_SERVER[2]], cwd=BASE_DIR)
            return proc.returncode
        except KeyboardInterrupt:
            return 0
    else:
        print("  [=] Web 端口 8501 已在监听, 跳过启动。")
        input("  按回车退出...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
