#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: format.py
作者: 高帅舟
项目: 智租顾问（多智能体+RAG租房咨询系统）
创建日期: 2026/2/4
描述: 
"""
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal


def ensure_limit(sql, limit=20):
    """给SELECT语句补上 LIMIT（若本身没有），避免全表扫描/返回过多数据拖慢查询。
    仅在纯单条SELECT（不含分号分隔的SQL）时生效，作为兜底约束。"""
    s = sql.strip().rstrip(';').strip()
    if not s:
        return sql
    # 已有 LIMIT 则原样返回
    if re.search(r'\bLIMIT\b', s, re.IGNORECASE):
        return sql
    # 简单防御：非单条SELECT不做改动
    if not re.match(r'^(SELECT|WITH)\b', s, re.IGNORECASE):
        return sql
    semicolon = sql.rstrip().endswith(';')
    return f"{s} LIMIT {limit}" + (';' if semicolon else '')


# 禁止出现在查询 SQL 中的高危关键字（写操作/危险语句，大小写不敏感匹配）
_FORBIDDEN_SQL_KEYWORDS = [
    'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'TRUNCATE',
    'REPLACE', 'GRANT', 'REVOKE', 'RENAME', 'MERGE', 'CALL', 'EXEC',
    'INTO OUTFILE', 'INTO DUMPFILE', 'LOAD_FILE', 'SLEEP', 'BENCHMARK',
    'INFORMATION_SCHEMA', 'MYSQL.USER', 'SYSTEM_USER', 'SET @',
]


def validate_readonly_sql(sql):
    """校验 SQL 是否为安全的只读查询（SELECT/WITH 白名单）。

    返回 (ok, message)：
    - ok=True 表示可安全执行，message 为补过 LIMIT 的 SQL
    - ok=False 时 message 为拒绝原因

    规则：
    1. 必须以 SELECT / WITH 开头（忽略前导空白与注释）
    2. 不含写操作、系统表、危险函数等黑名单关键字
    3. 自动追加 LIMIT 兜底（防全表扫描）
    """
    s = (sql or '').strip()
    if not s:
        return False, "SQL为空"
    # 去掉可能的前导注释（--、#、/* */）
    s_clean = re.sub(r'^(?:\s*--[^\n]*|\s*#[^\n]*|\s*/\*.*?\*/)+', '', s, flags=re.S).strip()
    if not re.match(r'^(SELECT|WITH)\b', s_clean, re.IGNORECASE):
        return False, "仅允许SELECT/WITH只读查询，拒绝执行: " + sql[:80]
    for kw in _FORBIDDEN_SQL_KEYWORDS:
        # 用词边界匹配关键字（避免把 community 误判成 DELETE 之类）
        if re.search(r'\b' + re.escape(kw) + r'\b', s_clean, re.IGNORECASE):
            return False, "SQL包含危险关键字[" + kw + "]，已拒绝: " + sql[:80]
    return True, ensure_limit(sql)


def format_exception(e):
    """格式化异常信息：展开 ExceptionGroup/BaseExceptionGroup，返回真实底层错误，便于定位问题。"""
    exceptions = getattr(e, 'exceptions', None)  # ExceptionGroup 才有 exceptions 属性
    if exceptions:  # 若是异常组，递归展开每个子异常
        return "; ".join(format_exception(sub) for sub in exceptions)
    return str(e)


def robust_json_loads(text):
    """健壮地解析 LLM 输出的 JSON 字符串。

    处理常见脏输出：
    1. 包裹的 ```json ``` 代码围栏；
    2. 前后夹带的解释文字（截取第一个 { 到最后一个 } 区间）；
    3. 尾随逗号（如 {"a":1,}）。

    :raises ValueError: 解析失败时抛出，含定位信息，便于日志排查。
    """
    if not text:
        raise ValueError("空内容无法解析为 JSON")
    t = str(text).strip()
    t = re.sub(r'^```(?:json)?\s*', '', t)   # 去开头围栏
    t = re.sub(r'\s*```$', '', t)            # 去结尾围栏
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find('{'), t.rfind('}')
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"未找到 JSON 对象: {t[:120]}")
        sub = t[start:end + 1]
        sub = re.sub(r',(\s*[}\]])', r'\1', sub)  # 去掉尾随逗号
        try:
            return json.loads(sub)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败: {e} -> {sub[:200]}")


def extract_sql(text):
    """从 LLM 输出中提取纯 SQL 语句。

    处理情况：```sql 代码围栏、行首 "输出:"/"SQL:" 标签、前后解释文字。
    返回的 SQL 不含末尾分号与多余空白；无法识别时返回空字符串。
    """
    if not text:
        return ""
    t = str(text).strip()
    t = re.sub(r'^```(?:sql)?\s*', '', t)     # 去开头围栏
    t = re.sub(r'\s*```$', '', t)             # 去结尾围栏
    t = re.sub(r'^\s*(?:输出|SQL|sql)\s*[:：]\s*', '', t)  # 去标签
    m = re.search(r'\b(?:SELECT|WITH)\b', t, re.IGNORECASE)  # 定位SQL起点
    if m:
        t = t[m.start():]
    else:
        return ""
    return t.strip().rstrip(';').strip()


def extract_agent_result(raw_response):
    """从 A2A 任务的原始响应中提取最终文本结果，兼容各种异常状态，避免 KeyError 崩溃。

    - completed：取 artifacts 首个文本；否则回退到 status.message。
    - 其他状态（input_required/failed 等）：取 status.message.content.text。
    - 兜底：任何情况下都不返回空字符串，避免前端出现"空回复"。
    """
    text = ""
    try:
        if getattr(raw_response.status, 'state', '') == 'completed' and raw_response.artifacts:
            text = raw_response.artifacts[0]['parts'][0]['text']
        else:
            msg = getattr(raw_response.status, 'message', None) or {}
            content = msg.get('content', {})
            if isinstance(content, dict):
                text = content.get('text', '')
            else:
                text = str(content)
    except Exception:
        text = ""
    if not text or not str(text).strip():
        return "（本次查询未返回结果，建议换个条件或说法再试一次）"
    return text


def default_encoder(obj):  # 定义编码器方法，用于格式化单个对象
    if isinstance(obj, datetime):  # 检查是否为datetime，返回带时间的格式化字符串
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(obj, date):  # 检查是否为date，返回日期格式化字符串
        return obj.strftime('%Y-%m-%d')
    if isinstance(obj, timedelta):  # 检查是否为timedelta，转换为字符串
        return str(obj)
    if isinstance(obj, Decimal):  # 检查是否为Decimal，转换为浮点数
        return float(obj)
    return obj  # 否则返回原对象

# 定义自定义JSON编码器类，继承自json.JSONEncoder，用于处理非标准类型序列化
class DateEncoder(json.JSONEncoder):
    def default(self, obj):  # 重写default方法，处理序列化时的默认对象转换
        if isinstance(obj, (date, datetime)):  # 检查对象是否为date或datetime类型，对于datetime返回带时间的字符串，对于date返回日期字符串
            return obj.strftime('%Y-%m-%d %H:%M:%S') if isinstance(obj, datetime) else obj.strftime('%Y-%m-%d')
        if isinstance(obj, timedelta):  # 检查对象是否为timedelta类型，将时间差转换为字符串
            return str(obj)
        if isinstance(obj, Decimal):  # 检查对象是否为Decimal类型，将Decimal转换为浮点数以兼容JSON
            return float(obj)
        return super().default(obj)  # 对于其他类型，调用父类默认方法