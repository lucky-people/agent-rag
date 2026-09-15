#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: web_server.py
描述: 智租顾问 统一智能助手后端（A2A智能体 + RAG法律咨询 双路线）。
      - /          提供新版网页.html 静态页面
      - /api/chat  接收 {session_id, message}，意图识别后自动路由：
          * house/poi/metro/recommend → A2A 智能体网络
          * legal → RAG 法律问答系统（懒加载）
      返回 {reply, suggestions, route}
"""
import os
import sys
import uuid
import asyncio
import threading
import time
from datetime import datetime

# 路径配置：把项目根目录加入 sys.path，支持 from Agent.xxx import 绝对路径导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytz
from flask import Flask, request, jsonify, send_file, Response
from python_a2a import AgentNetwork, TextContent, Message, MessageRole, Task
from langchain_openai import ChatOpenAI

from Agent.config import Config
from Agent.create_logger import logger
from Agent.main_prompts import RentalAdvisorPrompts
from Agent.utils.format import robust_json_loads, extract_agent_result
from Agent import user_system

conf = Config()
app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sessions = {}           # session_id -> {network, llm, history, messages, last_access}
sessions_lock = threading.Lock()
SESSION_TTL = 3600     # 会话空闲过期时间（秒）：1小时无访问自动清理

def _cleanup_sessions():
    """清理空闲超时的会话，防止内存无限增长（重启后历史丢失属预期）。"""
    now = time.time()
    with sessions_lock:
        expired = [sid for sid, s in sessions.items()
                   if now - s.get("last_access", 0) > SESSION_TTL]
        for sid in expired:
            del sessions[sid]
        if expired:
            logger.info(f"已清理 {len(expired)} 个空闲超时会话")

# ==================== 智能体协作链路追踪 ====================
traces = {}             # session_id -> [trace1, trace2, ...]
traces_lock = threading.Lock()

# Agent中文名称映射
AGENT_DISPLAY_NAMES = {
    "HouseQueryAssistant": "房源查询Agent",
    "PoiQueryAssistant": "周边探索Agent",
    "MetroQueryAssistant": "交通出行Agent",
    "RecommendQueryAssistant": "综合推荐Agent",
    "LegalQASystem": "法律问答RAG",
    "ChatLLM": "通用对话LLM",
    "IntentRecognizer": "意图识别器",
    "LLMSummarizer": "LLM摘要器",
}

# Agent图标/颜色配置
AGENT_STYLES = {
    "HouseQueryAssistant": {"icon": "🏠", "color": "#1976D2", "bg": "#E3F2FD"},
    "PoiQueryAssistant": {"icon": "📍", "color": "#388E3C", "bg": "#E8F5E9"},
    "MetroQueryAssistant": {"icon": "🚇", "color": "#F57C00", "bg": "#FFF3E0"},
    "RecommendQueryAssistant": {"icon": "⭐", "color": "#7B1FA2", "bg": "#F3E5F5"},
    "LegalQASystem": {"icon": "⚖️", "color": "#C62828", "bg": "#FFEBEE"},
    "ChatLLM": {"icon": "💬", "color": "#455A64", "bg": "#ECEFF1"},
    "IntentRecognizer": {"icon": "🎯", "color": "#00838F", "bg": "#E0F7FA"},
    "LLMSummarizer": {"icon": "📝", "color": "#5D4037", "bg": "#EFEBE9"},
}


def create_trace(session_id, user_query):
    """创建一条新的协作链路追踪记录"""
    trace = {
        "trace_id": "trace-" + str(uuid.uuid4())[:8],
        "session_id": session_id,
        "user_query": user_query,
        "start_time": time.time(),
        "end_time": None,
        "total_duration_ms": None,
        "steps": [],
        "status": "running",
    }
    with traces_lock:
        if session_id not in traces:
            traces[session_id] = []
        traces[session_id].append(trace)
        # 最多保留20条历史
        if len(traces[session_id]) > 20:
            traces[session_id] = traces[session_id][-20:]
    return trace


def add_trace_step(trace, agent_type, name, input_data, output_data=None,
                   status="success", error_msg=None, start_time=None):
    """向trace中添加一个调用节点"""
    now = time.time()
    duration_ms = round((now - start_time) * 1000, 1) if start_time else None
    style = AGENT_STYLES.get(agent_type, {"icon": "⚙️", "color": "#666", "bg": "#f5f5f5"})
    step = {
        "step_id": len(trace["steps"]) + 1,
        "agent_type": agent_type,
        "display_name": AGENT_DISPLAY_NAMES.get(agent_type, name),
        "name": name,
        "icon": style["icon"],
        "color": style["color"],
        "bg_color": style["bg"],
        "input": str(input_data)[:500] if input_data else "",
        "output": str(output_data)[:500] if output_data else "",
        "status": status,
        "error_msg": error_msg,
        "start_time": start_time,
        "end_time": now,
        "duration_ms": duration_ms,
    }
    trace["steps"].append(step)
    return step


def finish_trace(trace, status="success"):
    """完成trace记录"""
    trace["end_time"] = time.time()
    trace["total_duration_ms"] = round((trace["end_time"] - trace["start_time"]) * 1000, 1)
    trace["status"] = status
    return trace

# ========== RAG 法律问答系统（懒加载） ==========
_legal_qa_system = None
_legal_qa_lock = threading.Lock()
_legal_qa_ready = False
_legal_qa_error = None

def _init_legal_qa():
    """懒加载法律问答系统，只初始化一次。"""
    global _legal_qa_system, _legal_qa_ready, _legal_qa_error
    with _legal_qa_lock:
        if _legal_qa_ready:
            return _legal_qa_system
        if _legal_qa_error:
            return None
        try:
            # 切换工作目录，确保 legal_qa 内部相对路径（config.ini、models、data）能正确解析
            old_cwd = os.getcwd()
            os.chdir(os.path.join(BASE_DIR, "legal_qa"))
            try:
                # 统一按 Agent.legal_qa.* 绝对导入
                from Agent.legal_qa.new_main import IntegratedQASystem
                _legal_qa_system = IntegratedQASystem()
            finally:
                os.chdir(old_cwd)
            _legal_qa_ready = True
            logger.info("RAG 法律问答系统初始化成功")
            return _legal_qa_system
        except Exception as e:
            _legal_qa_error = str(e)
            logger.error(f"RAG 法律问答系统初始化失败: {e}")
            return None

def query_legal(question, session_id):
    """调用法律问答系统，返回完整答案字符串。"""
    qa = _init_legal_qa()
    if qa is None:
        return f"法律咨询服务暂不可用（初始化失败：{_legal_qa_error}）。请检查 MySQL/Redis/Milvus 服务是否启动。"
    try:
        legal_qa_path = os.path.join(BASE_DIR, "legal_qa")
        old_cwd = os.getcwd()
        os.chdir(legal_qa_path)
        try:
            collected = ""
            for token, is_complete in qa.query(question, session_id=session_id):
                if token:
                    collected += token
                if is_complete:
                    break
        finally:
            os.chdir(old_cwd)
        return collected if collected else "未找到相关法律答案。"
    except Exception as e:
        logger.error(f"法律问答查询失败: {e}")
        return f"法律咨询失败：{str(e)}"


def query_legal_stream(question, session_id):
    """法律问答流式输出生成器，yield SSE 事件字符串。"""
    qa = _init_legal_qa()
    if qa is None:
        yield f'data: {{"type":"error","content":"法律咨询服务暂不可用（初始化失败：{_legal_qa_error}）"}}\n\n'
        return
    try:
        legal_qa_path = os.path.join(BASE_DIR, "legal_qa")
        old_cwd = os.getcwd()
        os.chdir(legal_qa_path)
        collected = ""
        try:
            for item in qa.query(question, session_id=session_id):
                token = item[0]
                is_complete = item[1] if len(item) > 1 else False
                # 检测引用条文标记（特殊格式：("__REFERENCES__", [refs])）
                if token == "__REFERENCES__":
                    refs = is_complete  # 第二个元素是引用列表
                    import json as _json
                    refs_json = _json.dumps(refs, ensure_ascii=False)
                    yield f'data: {{"type":"references","content":{refs_json}}}\n\n'
                    continue
                if token:
                    collected += token
                    # 逐 token 推送（转义引号和换行）
                    safe_token = token.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                    yield f'data: {{"type":"token","content":"{safe_token}"}}\n\n'
                if is_complete:
                    break
        finally:
            os.chdir(old_cwd)
        if not collected:
            yield 'data: {"type":"token","content":"未找到相关法律答案。"}\n\n'
    except Exception as e:
        logger.error(f"法律问答流式查询失败: {e}")
        safe_err = str(e).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        yield f'data: {{"type":"error","content":"法律咨询失败：{safe_err}"}}\n\n'

# 每个意图对应的"猜你想问"推荐问题
SUGGESTIONS = {
    "house": ["推荐几套三室的房子", "郑东新区2000元以下的房源", "离地铁站近的两室房源"],
    "poi": ["1号线沿线有哪些景点", "二七广场附近有什么好吃的", "金水区有哪些公园"],
    "metro": ["郑州东站坐几号线", "离二七广场最近的地铁站", "1号线有哪些站点"],
    "recommend": ["1号线附近2000以下的房源", "金水区离地铁近的景点", "中原区交通方便的房源"],
    "legal": ["房东卖房后我能拒绝搬走吗", "租房合同没到期房东涨房租怎么办", "租客拖欠房租多久可以解约"],
    "chat": ["你好，你是谁", "讲个笑话听听", "1+1等于几"]
}
DEFAULT_SUGGESTIONS = ["推荐几个郑州好玩的景点", "金水区2000元以下的房源", "郑州东站坐几号线", "房东卖房后我能拒绝搬走吗"]



def get_session(session_id):
    """按会话ID获取(或创建)会话状态，等价于Streamlit的session_state"""
    with sessions_lock:
        if session_id not in sessions:
            network = AgentNetwork(name="旅行助手网络")
            network.add("HouseQueryAssistant", "http://localhost:5006")
            network.add("PoiQueryAssistant", "http://localhost:5007")
            network.add("MetroQueryAssistant", "http://localhost:5008")
            network.add("RecommendQueryAssistant", "http://localhost:5009")
            llm = ChatOpenAI(
                model=conf.model_name,
                api_key=conf.api_key,
                base_url=conf.base_url,
                temperature=0.1
            )
            sessions[session_id] = {
                "network": network,
                "llm": llm,
                "history": "",
                "messages": [],
                "last_access": time.time(),
            }
        sessions[session_id]["last_access"] = time.time()
        return sessions[session_id]


def intent_agent(sess, user_input):
    """意图识别：返回 intents, user_queries, follow_up_message"""
    llm = sess["llm"]
    chain = RentalAdvisorPrompts.intent_prompt() | llm
    current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
    intent_response = chain.invoke(
        {"conversation_history": '\n'.join(sess["history"].split("\n")[-6:]), "query": user_input,
         "current_date": current_date}).content.strip()
    logger.info(f"意图识别原始响应: {intent_response}")
    # 健壮解析：容忍代码围栏、前后杂文与尾随逗号，避免复杂问题时 JSON 解析失败
    intent_output = robust_json_loads(intent_response)
    intents = intent_output.get("intents", [])
    user_queries = intent_output.get("user_queries", {})
    follow_up_message = intent_output.get("follow_up_message", "")
    logger.info(f"intents: {intents}||user_queries: {user_queries}||follow_up_message: {follow_up_message}")
    return intents, user_queries, follow_up_message


def process(sess, prompt, session_id="default"):
    """处理用户输入：意图识别 + 双路线路由（A2A智能体 / RAG法律）"""
    llm = sess["llm"]
    with sessions_lock:
        sess["history"] += f"\nUser: {prompt}"

    # 创建协作链路追踪
    trace = create_trace(session_id, prompt)

    # ===== 节点1：意图识别 =====
    intent_start = time.time()
    intents, user_queries, follow_up_message = intent_agent(sess, prompt)
    add_trace_step(trace, "IntentRecognizer", "意图识别器",
                    input_data=prompt,
                    output_data=f"识别意图: {intents}, 子查询: {user_queries}",
                    start_time=intent_start)

    if "out_of_scope" in intents:
        response = follow_up_message
        route = "chat"
    elif follow_up_message != "":
        response = follow_up_message
        route = "chat"
    else:
        responses = []
        route = "agent"
        for intent in intents:
            agent_name = conf.intent.get(intent)
            if not agent_name:
                responses.append("暂不支持此意图。")
                continue
            query_str = user_queries.get(intent, {})
            logger.info(f"{agent_name} 查询：{query_str}")

            # ===== 法律路线：调用 RAG 法律问答系统 =====
            if agent_name == "LegalQASystem":
                route = "legal"
                legal_start = time.time()
                try:
                    legal_answer = query_legal(query_str, sess.get("legal_session_id", str(uuid.uuid4())))
                    add_trace_step(trace, "LegalQASystem", "法律问答RAG",
                                    input_data=query_str, output_data=legal_answer,
                                    start_time=legal_start)
                    responses.append(legal_answer)
                except Exception as e:
                    add_trace_step(trace, "LegalQASystem", "法律问答RAG",
                                    input_data=query_str, output_data=str(e),
                                    status="error", error_msg=str(e),
                                    start_time=legal_start)
                    responses.append(f"法律咨询失败：{str(e)}")
                continue

            # ===== 通用对话路线：直接调用大模型生成答案 =====
            if agent_name == "ChatLLM":
                route = "chat"
                chat_start = time.time()
                chat_prompt = f"你是一个友好的智能助手，请用简洁自然的中文回答用户问题。\n用户问题：{query_str}"
                chat_response = llm.invoke(chat_prompt).content.strip()
                add_trace_step(trace, "ChatLLM", "通用对话LLM",
                                input_data=query_str, output_data=chat_response,
                                start_time=chat_start)
                responses.append(chat_response)
                continue

            # ===== 智能体路线：调用 A2A Agent =====
            agent_start = time.time()
            try:
                agent = sess["network"].get_agent(agent_name)
                chat_history = '\n'.join(sess["history"].split("\n")[-7:-1]) + f'\nUser: {query_str}'
                message = Message(content=TextContent(text=chat_history), role=MessageRole.USER)
                task = Task(id="task-" + str(uuid.uuid4()), message=message.to_dict())
                raw_response = asyncio.run(agent.send_task_async(task))
                logger.info(f"{agent_name} 原始响应: {raw_response}")
                agent_result = extract_agent_result(raw_response)

                # ===== 节点：LLM摘要（可选） =====
                if conf.use_llm_summary:
                    summarize = {
                        "HouseQueryAssistant": RentalAdvisorPrompts.summarize_house_prompt,
                        "PoiQueryAssistant": RentalAdvisorPrompts.summarize_poi_prompt,
                        "MetroQueryAssistant": RentalAdvisorPrompts.summarize_metro_prompt,
                        "RecommendQueryAssistant": RentalAdvisorPrompts.summarize_recommend_prompt,
                    }.get(agent_name)
                    if summarize:
                        summary_start = time.time()
                        chain = summarize() | llm
                        final_response = chain.invoke({"query": query_str, "raw_response": agent_result}).content.strip()
                        add_trace_step(trace, "LLMSummarizer", "LLM摘要器",
                                        input_data=f"原始响应长度: {len(agent_result)}字",
                                        output_data=final_response,
                                        start_time=summary_start)
                    else:
                        final_response = agent_result
                else:
                    final_response = agent_result

                add_trace_step(trace, agent_name, agent_name,
                                input_data=query_str, output_data=final_response,
                                start_time=agent_start)
                responses.append(final_response)

                # === 租房知识普及引导（追问式：不直接输出条文） ===
                if agent_name == "HouseQueryAssistant" and conf.enable_rental_tips:
                    responses.append("\n\n💡 需要我帮你普及租房注意事项或租客权益吗？或推荐周边好玩的？")
            except Exception as e:
                logger.error(f"{agent_name} 调用异常: {str(e)}")
                add_trace_step(trace, agent_name, agent_name,
                                input_data=query_str, output_data="调用异常（详见日志）",
                                status="error", error_msg=str(e),
                                start_time=agent_start)
                # 脱敏：不向用户暴露内部异常细节（路径/地址/堆栈），只给通用提示
                responses.append(f"{agent_name}暂时不可用，请稍后重试或换个说法。")
        response = "\n\n".join(responses)

    with sessions_lock:
        sess["history"] += f"\nAssistant: {response}"
    # 完成trace记录
    finish_trace(trace)
    return response, intents, route, trace


@app.route("/")
def index():
    return send_file(os.path.join(BASE_DIR, "新版网页.html"))


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    session_id = (data.get("session_id") or "default").strip()
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"reply": "请输入内容。", "suggestions": DEFAULT_SUGGESTIONS, "route": "chat"})
    sess = get_session(session_id)
    # 为法律问答准备独立 session_id（复用同一会话）
    sess.setdefault("legal_session_id", session_id)
    try:
        reply, intents, route, trace = process(sess, message, session_id)
    except Exception as e:
        logger.error(f"处理异常: {str(e)}")
        reply = "处理失败，请稍后重试或换个说法。"
        intents = []
        route = "error"
        trace = None
    # 依据意图生成推荐问题，去重后最多4个
    suggestions = []
    for i in intents:
        suggestions.extend(SUGGESTIONS.get(i, []))
    if not suggestions:
        suggestions = DEFAULT_SUGGESTIONS
    seen, uniq = set(), []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    result = {"reply": reply, "suggestions": uniq[:4], "route": route}
    if trace:
        result["trace"] = trace
    return jsonify(result)


@app.route("/api/trace", methods=["GET"])
def get_trace():
    """获取指定会话的协作链路追踪历史"""
    session_id = (request.args.get("session_id") or "default").strip()
    limit = int(request.args.get("limit", 10))
    with traces_lock:
        session_traces = traces.get(session_id, [])
        # 返回最近的N条
        result_traces = session_traces[-limit:] if limit > 0 else session_traces
    return jsonify({
        "success": True,
        "session_id": session_id,
        "total": len(session_traces),
        "traces": result_traces,
    })


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """流式输出接口（SSE）：法律路线逐 token 返回，智能体路线分块返回。"""
    data = request.get_json(force=True)
    session_id = (data.get("session_id") or "default").strip()
    message = (data.get("message") or "").strip()
    user_id = data.get("user_id")
    if not message:
        def _empty():
            yield 'data: {"type":"done","reply":"请输入内容。","suggestions":[],"route":"chat"}\n\n'
        return Response(_empty(), mimetype="text/event-stream")

    sess = get_session(session_id)
    sess.setdefault("legal_session_id", session_id)
    with sessions_lock:
        sess["history"] += f"\nUser: {message}"

    def _save_history(uid, sid, role, content, route_name):
        """保存聊天历史（异步，不阻塞流式输出）"""
        if uid:
            try:
                user_system.save_chat_message(int(uid), sid, role, content, route_name)
            except Exception as e:
                logger.error(f"保存历史失败: {e}")

    def generate():
        try:
            # 创建协作链路追踪
            trace = create_trace(session_id, message)

            # 1. 意图识别（同步，很快）
            intent_start = time.time()
            intents, user_queries, follow_up_message = intent_agent(sess, message)
            add_trace_step(trace, "IntentRecognizer", "意图识别器",
                            input_data=message,
                            output_data=f"识别意图: {intents}, 子查询: {user_queries}",
                            start_time=intent_start)

            # 推送思考过程：意图识别完成
            _intent_text = "、".join(intents) if intents else "通用对话"
            yield f'data: {{"type":"thinking","step":"intent","text":"已识别您的需求：{_intent_text}","status":"done"}}\n\n'

            # 2. 处理 out_of_scope / 追问
            if "out_of_scope" in intents or follow_up_message != "":
                reply = follow_up_message or "暂不支持此类问题。"
                route = "chat"
                finish_trace(trace)
                safe = reply.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                yield f'data: {{"type":"token","content":"{safe}"}}\n\n'
                with sessions_lock:
                    sess["history"] += f"\nAssistant: {reply}"
                _save_history(user_id, session_id, "user", message, route)
                _save_history(user_id, session_id, "assistant", reply, route)
                suggestions = DEFAULT_SUGGESTIONS
                import json as _json
                yield f'data: {{"type":"done","reply":"{safe}","suggestions":{_json.dumps(suggestions, ensure_ascii=False)},"route":"{route}","trace":{_json.dumps(trace, ensure_ascii=False)}}}\n\n'
                return

            # 3. 逐意图处理
            all_responses = []
            route = "agent"
            show_house_fav = False
            for intent in intents:
                agent_name = conf.intent.get(intent)
                if not agent_name:
                    all_responses.append("暂不支持此意图。")
                    continue
                # 仅房源/组合推荐 agent 的回复才允许前端显示收藏；法律/闲聊/POI/地铁一律不显示
                if agent_name in ("HouseQueryAssistant", "RecommendQueryAssistant"):
                    show_house_fav = True
                query_str = user_queries.get(intent, {})
                # === 个性化推荐：房源/组合推荐查询时注入用户完整偏好（预算/区域/户型）===
                if intent in ("house", "recommend") and user_id:
                    try:
                        pref = user_system.get_user_preferences(int(user_id))
                        if pref:
                            extra = []
                            if pref.get("budget_min") and pref["budget_min"] > 0:
                                extra.append(f"预算最低{pref['budget_min']}元")
                            if pref.get("budget_max") and pref["budget_max"] < 99999:
                                extra.append(f"预算最高{pref['budget_max']}元")
                            if pref.get("preferred_districts"):
                                extra.append(f"偏好区域{','.join(pref['preferred_districts'])}")
                            if pref.get("preferred_house_type"):
                                extra.append(f"户型偏好{pref['preferred_house_type']}")
                            if extra:
                                if isinstance(query_str, dict):
                                    query_str = str(query_str)
                                query_str = f"{query_str}（用户偏好：{'，'.join(extra)}，请优先推荐符合条件的房源）"
                                logger.info(f"个性化房源/推荐查询（注入偏好）：{query_str}")
                    except Exception as e:
                        logger.error(f"获取用户偏好失败: {e}")
                # === 个性化推荐：周边POI/地铁查询时注入偏好区域（仅当用户未明确指定区域）===
                elif intent in ("poi", "metro") and user_id:
                    try:
                        pref = user_system.get_user_preferences(int(user_id))
                        if pref and pref.get("preferred_districts"):
                            qs_text = str(query_str) if not isinstance(query_str, dict) else str(query_str)
                            has_region = any(k in qs_text for k in ["区", "县", "市", "广场", "站", "路"])
                            if not has_region:
                                regions = '/'.join(pref["preferred_districts"])
                                query_str = f"{qs_text}（用户偏好区域：{regions}，若未指定区域请优先查询这些区域）"
                                logger.info(f"个性化周边/地铁查询（注入偏好区域）：{query_str}")
                    except Exception as e:
                        logger.error(f"获取用户偏好失败: {e}")
                logger.info(f"{agent_name} 查询：{query_str}")

                # 推送思考过程：正在调用对应Agent
                _thinking_texts = {
                    "HouseQueryAssistant": "正在检索房源数据库...",
                    "PoiQueryAssistant": "正在查询周边景点与POI...",
                    "MetroQueryAssistant": "正在查询地铁线路与站点...",
                    "RecommendQueryAssistant": "正在生成综合推荐方案...",
                    "LegalQASystem": "正在检索法律条文知识库...",
                    "ChatLLM": "正在生成回复...",
                }
                _thinking_text = _thinking_texts.get(agent_name, f"正在调用 {agent_name}...")
                yield f'data: {{"type":"thinking","step":"{agent_name}","text":"{_thinking_text}","status":"running"}}\n\n'

                # === 法律路线：真正的流式输出 ===
                if agent_name == "LegalQASystem":
                    route = "legal"
                    legal_start = time.time()
                    # 先推送一个开始信号
                    yield 'data: {"type":"start","route":"legal"}\n\n'
                    legal_collected = ""
                    for sse_event in query_legal_stream(query_str, sess["legal_session_id"]):
                        # 从 SSE 事件中提取 token 内容累积
                        if '"type":"token"' in sse_event:
                            import json as _json
                            try:
                                obj = _json.loads(sse_event.replace('data: ', '').strip())
                                legal_collected += obj.get("content", "")
                            except Exception:
                                pass
                        yield sse_event
                    legal_answer = legal_collected if legal_collected else "未找到相关法律答案。"
                    add_trace_step(trace, "LegalQASystem", "法律问答RAG",
                                    input_data=query_str, output_data=legal_answer,
                                    start_time=legal_start)
                    all_responses.append(legal_answer)
                    continue

                # === 通用对话路线：LLM 真流式（astream 逐 token 推送） ===
                if agent_name == "ChatLLM":
                    route = "chat"
                    chat_start = time.time()
                    yield 'data: {"type":"start","route":"chat"}\n\n'
                    chat_prompt = f"你是一个友好的智能助手，请用简洁自然的中文回答用户问题。\n用户问题：{query_str}"
                    # 后台线程消费 LLM token 流 → 队列逐条投递给 SSE 生成器，实现首字低延迟的真流式
                    import queue as _queue
                    _evt_q = _queue.Queue()
                    _chat_collected = []

                    def _chat_worker():
                        async def _run():
                            async for chunk in sess["llm"].astream(chat_prompt):
                                token_text = getattr(chunk, "content", "")
                                if token_text:
                                    _chat_collected.append(token_text)
                                    safe = token_text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                                    _evt_q.put(f'data: {{"type":"token","content":"{safe}"}}\n\n')
                        try:
                            asyncio.run(_run())
                        except Exception as e:
                            logger.error(f"闲聊流式输出异常: {str(e)}")
                            _evt_q.put(f'data: {{"type":"token","content":"（回答中断，请重试）"}}\n\n')
                        finally:
                            _evt_q.put(None)   # 结束哨兵

                    threading.Thread(target=_chat_worker, daemon=True).start()
                    while True:
                        evt = _evt_q.get()
                        if evt is None:
                            break
                        yield evt
                    chat_response = "".join(_chat_collected).strip()
                    add_trace_step(trace, "ChatLLM", "通用对话LLM",
                                    input_data=query_str, output_data=chat_response,
                                    start_time=chat_start)
                    all_responses.append(chat_response or "抱歉，暂时没有生成回答。")
                    continue

                # === 智能体路线：同步调用后分块模拟流式 ===
                agent_start = time.time()
                agent = sess["network"].get_agent(agent_name)
                chat_history = '\n'.join(sess["history"].split("\n")[-7:-1]) + f'\nUser: {query_str}'
                msg = Message(content=TextContent(text=chat_history), role=MessageRole.USER)
                task = Task(id="task-" + str(uuid.uuid4()), message=msg.to_dict())
                raw_response = asyncio.run(agent.send_task_async(task))
                logger.info(f"{agent_name} 原始响应: {raw_response}")
                agent_result = extract_agent_result(raw_response)

                if conf.use_llm_summary:
                    summarize = {
                        "HouseQueryAssistant": RentalAdvisorPrompts.summarize_house_prompt,
                        "PoiQueryAssistant": RentalAdvisorPrompts.summarize_poi_prompt,
                        "MetroQueryAssistant": RentalAdvisorPrompts.summarize_metro_prompt,
                        "RecommendQueryAssistant": RentalAdvisorPrompts.summarize_recommend_prompt,
                    }.get(agent_name)
                    if summarize:
                        summary_start = time.time()
                        chain = summarize() | sess["llm"]
                        final_response = chain.invoke({"query": query_str, "raw_response": agent_result}).content.strip()
                        add_trace_step(trace, "LLMSummarizer", "LLM摘要器",
                                        input_data=f"原始响应长度: {len(agent_result)}字",
                                        output_data=final_response,
                                        start_time=summary_start)
                    else:
                        final_response = agent_result
                else:
                    final_response = agent_result

                add_trace_step(trace, agent_name, agent_name,
                                input_data=query_str, output_data=final_response,
                                start_time=agent_start)
                all_responses.append(final_response)
                # 分块推送（每 8 个字一个块，模拟流式效果）
                for i in range(0, len(final_response), 8):
                    chunk = final_response[i:i+8]
                    safe = chunk.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                    yield f'data: {{"type":"token","content":"{safe}"}}\n\n'
                # === 租房知识普及引导（追问式：生成可点击选项对话框，用户点击后再展开回答） ===
                if agent_name == "HouseQueryAssistant" and conf.enable_rental_tips:
                    _guide = "\n\n💡 需要我帮你进一步了解吗？点下方选项即可展开："
                    _safe_guide = _guide.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                    yield f'data: {{"type":"token","content":"{_safe_guide}"}}\n\n'
                    import json as _json
                    _options = [
                        {"label": "📜 了解租房注意事项", "query": "了解租房注意事项"},
                        {"label": "🛡️ 我有哪些租客权益", "query": "我有哪些租客权益"},
                        {"label": "🗺️ 周边有哪些好玩的", "query": "周边有哪些好玩的"},
                    ]
                    yield 'data: {"type":"options","content":' + _json.dumps(_options, ensure_ascii=False) + '}\n\n'
                    all_responses.append(_guide)

            reply = "\n\n".join(all_responses)
            with sessions_lock:
                sess["history"] += f"\nAssistant: {reply}"
            _save_history(user_id, session_id, "user", message, route)
            _save_history(user_id, session_id, "assistant", reply, route)

            # 生成推荐问题（租房追问选项已通过 options 事件在消息内展示，不重复注入）
            suggestions = []
            for i in intents:
                suggestions.extend(SUGGESTIONS.get(i, []))
            if not suggestions:
                suggestions = DEFAULT_SUGGESTIONS
            seen, uniq = set(), []
            for s in suggestions:
                if s not in seen:
                    seen.add(s)
                    uniq.append(s)
            suggestions = uniq[:4]

            safe_reply = reply.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            # 完成trace记录
            finish_trace(trace)
            import json as _json_full
            trace_json = _json_full.dumps(trace, ensure_ascii=False)
            yield f'data: {{"type":"done","reply":"{safe_reply}","suggestions":{_json_suggestions(suggestions)},"route":"{route}","fav":{"true" if show_house_fav else "false"},"trace":{trace_json}}}\n\n'

        except Exception as e:
            logger.error(f"流式处理异常: {str(e)}")
            safe_err = str(e).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            yield f'data: {{"type":"error","content":"处理失败：{safe_err}"}}\n\n'
            yield f'data: {{"type":"done","reply":"处理失败：{safe_err}","suggestions":[],"route":"error"}}\n\n'

    return Response(generate(), mimetype="text/event-stream")


def _json_suggestions(suggestions):
    """将推荐问题列表转为 JSON 字符串（用于 SSE 内嵌）。"""
    import json as _json
    return _json.dumps(suggestions, ensure_ascii=False)


# ========== 租房合同智能审查 ==========
CONTRACT_UPLOAD_DIR = os.path.join(BASE_DIR, "contract_uploads")
os.makedirs(CONTRACT_UPLOAD_DIR, exist_ok=True)


def extract_contract_text(file_path):
    """从合同文件提取文本：PDF 用 fitz，图片用 OCR"""
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    try:
        if ext == '.pdf':
            import fitz
            doc = fitz.open(file_path)
            for page in doc:
                text += page.get_text() + "\n"
            doc.close()
            # 如果 PDF 提取文本过少（可能是扫描件），尝试 OCR
            if len(text.strip()) < 50:
                logger.info("PDF 文本过少，尝试 OCR...")
                from Agent.legal_qa.rag_qa.edu_document_loaders import OCRPDFLoader
                loader = OCRPDFLoader(file_path)
                docs = loader.load()
                text = "\n".join([d.page_content for d in docs])
        elif ext in ('.jpg', '.jpeg', '.png', '.bmp', '.webp'):
            from Agent.legal_qa.rag_qa.edu_document_loaders import OCRIMGLoader
            loader = OCRIMGLoader(file_path)
            docs = loader.load()
            text = "\n".join([d.page_content for d in docs])
        elif ext == '.txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
    except Exception as e:
        logger.error(f"合同文本提取失败: {e}")
    return text.strip()


def analyze_contract_risk(contract_text, llm):
    """调用 LLM 分析合同风险，返回结构化结果

    速度优化：限制 issues 数量与各字段长度，避免模型照抄大段合同原文，显著缩短生成耗时。
    """
    # 压缩空白：去掉多余空行/行尾空格，减少输入 token（缩短首字延迟）
    import re as _re_inner
    _cleaned = _re_inner.sub(r'[ \t]+', ' ', contract_text)
    _cleaned = _re_inner.sub(r'\n\s*\n+', '\n', _cleaned).strip()
    prompt = f"""你是一位专业的租房合同审查律师。请审查以下租房合同，找出对租客不利的风险点。

合同内容：
{_cleaned[:8000]}

只输出 JSON（不要 markdown 代码块、不要多余文字），格式如下，所有字段尽量简短：
{{
  "summary": "合同整体评价（40字以内）",
  "risk_level": "低风险/中风险/高风险",
  "issues": [
    {{
      "clause": "条款摘录（只摘关键短句，30字以内）",
      "risk_type": "霸王条款/押金风险/租金风险/维修责任/退租条款/其他",
      "severity": "高/中/低",
      "analysis": "风险原因（40字以内）",
      "suggestion": "修改建议（40字以内）"
    }}
  ],
  "positive_points": ["对租客有利要点1（20字以内）"],
  "missing_clauses": ["应补充条款1（20字以内）"]
}}

要求：
1. 只看租客权益；issues 最多列 5 条，宁缺毋滥。
2. 严禁大段照抄合同原文；条款摘录只保留最关键的半句。
3. 若合同内容不完整或无法识别，在 summary 中说明并让 issues 为空数组。
"""
    try:
        response = llm.invoke(prompt).content.strip()
        # 提取 JSON（可能被 markdown 代码块包裹）
        import json as _json
        import re as _re
        json_match = _re.search(r'\{[\s\S]*\}', response)
        if json_match:
            result = _json.loads(json_match.group(0))
        else:
            result = {"summary": response, "risk_level": "未知", "issues": [], "positive_points": [], "missing_clauses": []}
        return result
    except Exception as e:
        logger.error(f"合同风险分析失败: {e}")
        return {"summary": f"分析失败: {str(e)}", "risk_level": "未知", "issues": [], "positive_points": [], "missing_clauses": []}


@app.route("/api/contract/review", methods=["POST"])
def contract_review():
    """租房合同智能审查接口：上传 PDF/图片 → OCR提取 → AI分析风险"""
    if 'file' not in request.files:
        return jsonify({"error": "请上传合同文件"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "文件名为空"}), 400

    # 保存文件
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.webp', '.txt'):
        return jsonify({"error": f"不支持的文件格式: {ext}，支持 PDF/图片/TXT"}), 400

    filename = f"contract_{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(CONTRACT_UPLOAD_DIR, filename)
    file.save(file_path)
    logger.info(f"合同文件已保存: {file_path}")

    try:
        # 1. 提取文本
        logger.info("正在提取合同文本...")
        contract_text = extract_contract_text(file_path)
        if not contract_text:
            return jsonify({"error": "未能从文件中提取到文本，请确认文件是否清晰或是否为可识别格式"}), 400
        logger.info(f"合同文本提取完成，长度: {len(contract_text)} 字符")

        # 2. 获取 LLM 实例（复用会话或新建）
        sess = get_session("contract_review")
        llm = sess["llm"]

        # 3. AI 分析风险
        logger.info("正在进行 AI 风险分析...")
        result = analyze_contract_risk(contract_text, llm)
        result["text_length"] = len(contract_text)
        result["file_name"] = file.filename

        return jsonify(result)
    except Exception as e:
        logger.error(f"合同审查失败: {e}")
        return jsonify({"error": f"审查失败: {str(e)}"}), 500
    finally:
        # 清理临时文件
        try:
            os.remove(file_path)
        except:
            pass


# ========== 用户系统 API ==========
def get_current_user_id():
    """从请求中获取当前用户ID（header 或 body）"""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
    return int(user_id) if user_id else None


@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    """用户注册"""
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    phone = data.get("phone", "").strip() or None

    if not username or not password:
        return jsonify({"success": False, "error": "用户名和密码不能为空"}), 400
    if len(username) < 2:
        return jsonify({"success": False, "error": "用户名至少2个字符"}), 400
    if len(password) < 4:
        return jsonify({"success": False, "error": "密码至少4个字符"}), 400

    result = user_system.register_user(username, password, phone)
    if result["success"]:
        logger.info(f"用户注册成功: {username}")
    return jsonify(result)


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    """用户登录"""
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"success": False, "error": "用户名和密码不能为空"}), 400

    result = user_system.login_user(username, password)
    if result["success"]:
        logger.info(f"用户登录: {username}")
    return jsonify(result)


@app.route("/api/user/profile", methods=["GET"])
def user_profile():
    """获取用户信息和偏好"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "未登录"}), 401

    preferences = user_system.get_user_preferences(user_id)
    favorites_count = len(user_system.get_favorites(user_id))
    return jsonify({
        "success": True,
        "user_id": user_id,
        "preferences": preferences,
        "favorites_count": favorites_count
    })


@app.route("/api/user/preferences", methods=["POST"])
def update_preferences():
    """更新用户偏好"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "未登录"}), 401

    data = request.get_json()
    result = user_system.update_user_preferences(
        user_id,
        budget_min=data.get("budget_min"),
        budget_max=data.get("budget_max"),
        preferred_districts=data.get("preferred_districts"),
        preferred_house_type=data.get("preferred_house_type")
    )
    return jsonify(result)


@app.route("/api/user/favorites", methods=["GET", "POST"])
def user_favorites():
    """收藏列表（GET）/ 添加收藏（POST）"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "未登录"}), 401

    if request.method == "GET":
        item_type = request.args.get("type")
        favorites = user_system.get_favorites(user_id, item_type)
        return jsonify({"success": True, "favorites": favorites})
    else:
        data = request.get_json()
        result = user_system.add_favorite(
            user_id,
            item_type=data.get("item_type", "general"),
            item_title=data.get("item_title", "未命名"),
            item_data=data.get("item_data", {})
        )
        return jsonify(result)


@app.route("/api/user/favorites/<int:fav_id>", methods=["DELETE"])
def delete_favorite(fav_id):
    """删除收藏"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "未登录"}), 401

    result = user_system.delete_favorite(user_id, fav_id)
    return jsonify(result)


@app.route("/api/user/favorites/compare", methods=["POST"])
def compare_favorites():
    """收藏房源六边形雷达图对比：6个维度（朝向、价格、面积、户型、地铁、配套）"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "未登录"}), 401

    data = request.get_json()
    fav_ids = data.get("ids", [])
    if not fav_ids or len(fav_ids) < 2:
        return jsonify({"success": False, "error": "请至少选择2个房源进行对比"}), 400

    # 获取所有收藏
    all_favs = user_system.get_favorites(user_id)
    selected = [f for f in all_favs if f["id"] in fav_ids]

    if len(selected) < 2:
        return jsonify({"success": False, "error": "选中的房源不足2个"}), 400

    import re as _re

    def parse_house(fav):
        """从收藏文本中解析房源信息"""
        text = (fav.get("item_data", {}).get("content", "") or fav.get("item_title", ""))
        info = {
            "name": fav.get("item_title", "未命名房源"),
            "price": None,        # 租金 元/月
            "area": None,         # 面积 ㎡
            "rooms": None,        # 室数
            "halls": None,        # 厅数
            "metro_dist": None,   # 地铁距离 米
            "floor": None,        # 楼层（第几层），无则用模拟数据
            "orientation": None,  # 朝向（保留解析，不参与新维度）
            "poi_count": 0,       # 周边POI数量
        }

        # 价格：匹配 "2500元" "2500/月" "租金2500"
        price_match = _re.search(r'(\d{3,6})\s*(?:元|块|/月|每月)', text)
        if price_match:
            info["price"] = int(price_match.group(1))

        # 面积：匹配 "85㎡" "85平" "85平方米"
        area_match = _re.search(r'(\d+(?:\.\d+)?)\s*(?:㎡|平|平方米|平米)', text)
        if area_match:
            info["area"] = float(area_match.group(1))

        # 户型：匹配 "3室2厅" "两室一厅"
        room_match = _re.search(r'(\d+|[一二三四五六七八九])\s*室\s*(\d+|[一二三四五六七八九])?\s*厅?', text)
        if room_match:
            cn_num = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
            r = room_match.group(1)
            info["rooms"] = cn_num.get(r, int(r)) if r in cn_num else (int(r) if r.isdigit() else None)
            h = room_match.group(2)
            if h:
                info["halls"] = cn_num.get(h, int(h)) if h in cn_num else (int(h) if h.isdigit() else None)

        # 地铁距离：匹配 "约500米" "距离地铁300m" "地铁站500米"
        metro_match = _re.search(r'(?:地铁|地铁站).*?(\d+)\s*(?:米|m|km)', text)
        if metro_match:
            dist = int(metro_match.group(1))
            matched_text = text[metro_match.start():metro_match.end()]
            if 'km' in matched_text:
                dist *= 1000
            info["metro_dist"] = dist

        # 朝向：匹配 "朝南" "南向" "南北通透" "朝东" 等
        if _re.search(r'南北通透|朝南|南向|坐北朝南', text):
            info["orientation"] = "南北通透/朝南"
        elif _re.search(r'东南|西南', text):
            info["orientation"] = "东南/西南"
        elif _re.search(r'朝东|东向|朝西|西向', text):
            info["orientation"] = "朝东/朝西"
        elif _re.search(r'朝北|北向', text):
            info["orientation"] = "朝北"

        # 楼层：匹配 "第X层" "X/X层" "X层" "X楼" 等；匹配不到则用模拟数据（稳定生成）
        floor = None
        m_floor = _re.search(r'第\s*(\d{1,2})\s*[层楼]', text)
        if not m_floor:
            m_floor = _re.search(r'(\d{1,2})\s*[/／]\s*\d{1,2}\s*[层楼]', text)
        if not m_floor:
            m_floor = _re.search(r'(\d{1,2})\s*[层楼]', text)
        if m_floor:
            floor = int(m_floor.group(1))
        if floor is None:
            # 模拟楼层：基于收藏ID稳定生成 3~27 层，保证同一房源每次一致
            floor = 3 + ((fav.get('id') or 0) * 7) % 25
        info["floor"] = floor

        # 周边POI：统计附近景点、公园、商场、超市、医院、学校等丰富度
        poi_keywords = [
            '景点', '公园', '广场', '商场', '购物中心', '超市', '便利店',
            '医院', '诊所', '学校', '小学', '中学', '大学', '幼儿园',
            '地铁', '公交', '银行', '餐厅', '美食', '影院', '健身房'
        ]
        info["poi_count"] = sum(1 for k in poi_keywords if k in text)

        return info

    # 解析所有房源
    houses = [parse_house(f) for f in selected]

    # 维度1：面积评分（越大越好）
    def get_area_score(h):
        if h["area"] is None: return 50
        areas = [x["area"] for x in houses if x["area"] is not None]
        if not areas: return 50
        amin, amax = min(areas), max(areas)
        if amax == amin: return 80
        return round((h["area"] - amin) / (amax - amin) * 100, 1)

    # 维度2：价格评分（越低越好，基于选中房源范围归一化）
    def get_price_score(h):
        if h["price"] is None: return 50
        prices = [x["price"] for x in houses if x["price"] is not None]
        if not prices: return 50
        pmin, pmax = min(prices), max(prices)
        if pmax == pmin: return 80
        return round((1 - (h["price"] - pmin) / (pmax - pmin)) * 100, 1)

    # 维度3：楼层评分（中间偏高层最佳：视野采光好；低层采光隐私差，超高层电梯久）
    def get_floor_score(h):
        f = h["floor"]
        if f is None: return 50
        if f <= 3: return 50
        if f <= 9: return 72
        if f <= 20: return 100
        if f <= 30: return 85
        return 70

    # 维度4：地铁距离评分（越近越好）
    def get_metro_score(h):
        if h["metro_dist"] is None: return 30
        dists = [x["metro_dist"] for x in houses if x["metro_dist"] is not None]
        if not dists: return 50
        dmin, dmax = min(dists), max(dists)
        if dmax == dmin: return 80
        if h["metro_dist"] > 3000: return 10
        return round((1 - (h["metro_dist"] - dmin) / (dmax - dmin)) * 100, 1)

    # 维度5：规格评分（室+厅越多越好）
    def get_spec_score(h):
        if h["rooms"] is None: return 50
        specs = [(x["rooms"] or 0) + (x["halls"] or 0) for x in houses]
        smin, smax = min(specs), max(specs)
        if smax == smin: return 80
        val = (h["rooms"] or 0) + (h["halls"] or 0)
        return round((val - smin) / (smax - smin) * 100, 1)

    # 维度6：周边POI评分（越多越好）
    def get_poi_score(h):
        return round(min(h["poi_count"] / 6 * 100, 100), 1)

    # 组装对比数据（新六维：面积/价格/楼层/地铁/规格/周边POI）
    dimensions = ["面积", "价格", "楼层", "地铁", "规格", "周边"]
    series = []
    for h in houses:
        series.append({
            "name": h["name"],
            "value": [
                get_area_score(h),
                get_price_score(h),
                get_floor_score(h),
                get_metro_score(h),
                get_spec_score(h),
                get_poi_score(h),
            ],
            "raw": {
                "area": f'{h["area"]}㎡' if h["area"] else "未知",
                "price": f'{h["price"]}元/月' if h["price"] else "未知",
                "floor": f'{h["floor"]}层' if h["floor"] is not None else "未知",
                "spec": f'{h["rooms"] or "?"}室{h["halls"] or "?"}厅' if h["rooms"] else "未知",
                "metro": f'{h["metro_dist"]}米' if h["metro_dist"] else "未知",
                "poi": f'{h["poi_count"]}项',
            }
        })

    return jsonify({
        "success": True,
        "dimensions": dimensions,
        "series": series
    })


@app.route("/api/user/favorites/ai-compare", methods=["POST"])
def ai_compare_favorites():
    """AI智能房源对比：多维度分析 + 个性化推荐理由（基于用户画像）"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "未登录"}), 401

    data = request.get_json()
    fav_ids = data.get("ids", [])
    if not fav_ids or len(fav_ids) < 2:
        return jsonify({"success": False, "error": "请至少选择2个房源进行对比"}), 400
    if len(fav_ids) > 3:
        return jsonify({"success": False, "error": "最多对比3套房源"}), 400

    # 获取所有收藏
    all_favs = user_system.get_favorites(user_id)
    selected = [f for f in all_favs if f["id"] in fav_ids]
    if len(selected) < 2:
        return jsonify({"success": False, "error": "选中的房源不足2个"}), 400

    import re as _re

    def parse_house_info(fav):
        """从收藏文本中解析房源结构化信息"""
        text = (fav.get("item_data", {}).get("content", "") or fav.get("item_title", ""))
        info = {
            "name": fav.get("item_title", "未命名房源"),
            "price": None, "area": None, "rooms": None, "halls": None,
            "metro_dist": None, "floor": None, "orientation": None, "poi_count": 0,
            "raw_text": text[:500]
        }
        # 价格
        m = _re.search(r'(\d{3,6})\s*(?:元|块|/月|每月)', text)
        if m: info["price"] = int(m.group(1))
        # 面积
        m = _re.search(r'(\d+(?:\.\d+)?)\s*(?:㎡|平|平方米|平米)', text)
        if m: info["area"] = float(m.group(1))
        # 户型
        m = _re.search(r'(\d+|[一二三四五六七八九])\s*室\s*(\d+|[一二三四五六七八九])?\s*厅?', text)
        if m:
            cn = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
            r = m.group(1)
            info["rooms"] = cn.get(r, int(r)) if r in cn else (int(r) if r.isdigit() else None)
            h = m.group(2)
            if h: info["halls"] = cn.get(h, int(h)) if h in cn else (int(h) if h.isdigit() else None)
        # 地铁距离
        m = _re.search(r'(?:地铁|地铁站).*?(\d+)\s*(?:米|m|km)', text)
        if m:
            dist = int(m.group(1))
            if 'km' in text[m.start():m.end()]: dist *= 1000
            info["metro_dist"] = dist
        # 朝向
        if _re.search(r'南北通透|朝南|南向|坐北朝南', text): info["orientation"] = "南北通透/朝南"
        elif _re.search(r'东南|西南', text): info["orientation"] = "东南/西南"
        elif _re.search(r'朝东|东向|朝西|西向', text): info["orientation"] = "朝东/朝西"
        elif _re.search(r'朝北|北向', text): info["orientation"] = "朝北"
        # 楼层
        m = _re.search(r'第\s*(\d{1,2})\s*[层楼]', text) or _re.search(r'(\d{1,2})\s*[/／]\s*\d{1,2}\s*[层楼]', text) or _re.search(r'(\d{1,2})\s*[层楼]', text)
        if m: info["floor"] = int(m.group(1))
        else: info["floor"] = 3 + ((fav.get('id') or 0) * 7) % 25
        # 周边POI丰富度
        poi_kw = ['景点','公园','广场','商场','购物中心','超市','便利店','医院','诊所','学校','小学','中学','大学','幼儿园','地铁','公交','银行','餐厅','美食','影院','健身房']
        info["poi_count"] = sum(1 for k in poi_kw if k in text)
        return info

    # 解析所有房源
    houses = [parse_house_info(f) for f in selected]

    # 获取用户画像
    user_profile = {}
    try:
        pref = user_system.get_user_preferences(int(user_id))
        if pref:
            user_profile = {
                "budget_min": pref.get("budget_min"),
                "budget_max": pref.get("budget_max"),
                "preferred_districts": pref.get("preferred_districts", []),
                "preferred_house_type": pref.get("preferred_house_type"),
            }
    except Exception as e:
        logger.error(f"获取用户偏好失败: {e}")

    # 获取用户最近查询历史
    recent_queries = []
    try:
        history = user_system.get_chat_history(int(user_id), 10)
        recent_queries = [h.get("content", "") for h in history if h.get("role") == "user"][-5:]
    except Exception as e:
        logger.error(f"获取用户历史失败: {e}")

    # 构建房源数据文本
    houses_text = ""
    for i, h in enumerate(houses, 1):
        houses_text += f"\n【房源{i}】{h['name']}\n"
        houses_text += f"  租金: {h['price']}元/月\n" if h['price'] else "  租金: 未知\n"
        houses_text += f"  面积: {h['area']}㎡\n" if h['area'] else "  面积: 未知\n"
        houses_text += f"  户型: {h['rooms']}室{h['halls'] or ''}厅\n" if h['rooms'] else "  户型: 未知\n"
        houses_text += f"  地铁距离: {h['metro_dist']}米\n" if h['metro_dist'] else "  地铁距离: 未知\n"
        houses_text += f"  楼层: 第{h['floor']}层\n" if h['floor'] else "  楼层: 未知\n"
        houses_text += f"  朝向: {h['orientation']}\n" if h['orientation'] else "  朝向: 未知\n"
        houses_text += f"  周边配套丰富度: {h['poi_count']}个设施\n"

    # 构建用户画像文本
    profile_text = ""
    if user_profile:
        if user_profile.get("budget_min") or user_profile.get("budget_max"):
            profile_text += f"预算范围: {user_profile.get('budget_min', '不限')}-{user_profile.get('budget_max', '不限')}元/月\n"
        if user_profile.get("preferred_districts"):
            profile_text += f"偏好区域: {', '.join(user_profile['preferred_districts'])}\n"
        if user_profile.get("preferred_house_type"):
            profile_text += f"户型偏好: {user_profile['preferred_house_type']}\n"
    if recent_queries:
        profile_text += f"最近查询: {'; '.join(recent_queries)}\n"

    # 构建Prompt
    prompt = f"""你是一位专业的租房顾问。请根据以下房源信息和用户画像，生成一份专业的房源对比分析报告。

## 待对比房源
{houses_text}

## 用户画像
{profile_text if profile_text else '用户未设置明确偏好，按一般租房者需求分析。'}

## 请按以下格式输出分析报告：

### 一、多维度对比分析
从以下4个维度逐一对比各房源的优缺点：
1. **租金性价比**：结合面积、户型计算单位面积租金，分析哪套更划算
2. **通勤便利性**：结合地铁距离、楼层，分析通勤体验
3. **周边配套**：结合POI丰富度、朝向，分析生活便利度
4. **居住舒适度**：结合楼层、朝向、户型，分析居住体验

### 二、每套房源的推荐理由
针对每套房源，结合用户画像，给出2-3条个性化推荐理由（如果用户是学生，强调近地铁+低租金；如果是上班族，强调通勤时间；如果有区域偏好，强调区域匹配度）。

### 三、最终推荐结论
明确推荐哪套房源，并说明核心理由（不超过100字）。

请用中文回答，语言专业但通俗易懂，适当使用emoji增加可读性。"""

    # 调用LLM生成分析
    try:
        llm = ChatOpenAI(
            model=conf.model_name,
            api_key=conf.api_key,
            base_url=conf.base_url,
            temperature=0.3
        )
        ai_analysis = llm.invoke(prompt).content.strip()
        return jsonify({
            "success": True,
            "houses": houses,
            "user_profile": user_profile,
            "ai_analysis": ai_analysis
        })
    except Exception as e:
        logger.error(f"AI对比分析失败: {e}")
        return jsonify({"success": False, "error": f"AI分析失败: {str(e)}"}), 500


@app.route("/api/user/history", methods=["GET", "DELETE"])
def user_history():
    """聊天历史（GET）/ 清空历史（DELETE）"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "未登录"}), 401

    if request.method == "GET":
        limit = int(request.args.get("limit", 50))
        history = user_system.get_chat_history(user_id, limit)
        return jsonify({"success": True, "history": history})
    else:
        result = user_system.clear_chat_history(user_id)
        return jsonify(result)


if __name__ == "__main__":
    logger.info("智租顾问 统一智能助手 Web 前端已启动: http://localhost:8501")
    # 后台线程定期清理空闲超时会话，防止内存无限增长
    def _cleanup_loop():
        while True:
            time.sleep(300)   # 每5分钟清理一次
            try:
                _cleanup_sessions()
            except Exception as e:
                logger.error(f"会话清理异常: {e}")
    threading.Thread(target=_cleanup_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=8501, debug=False, threaded=True)
