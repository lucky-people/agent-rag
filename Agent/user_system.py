#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户系统数据库模块（MySQL 版）
- 用户注册/登录
- 用户偏好（预算、区域、户型）
- 收藏房源/咨询
- 聊天历史记录
"""
import pymysql
import hashlib
import json
from Agent.config import Config

_conf = Config()
DB_CONFIG = {
    "host": _conf.host,
    "user": _conf.user,
    "password": _conf.password,
    "database": _conf.database,
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": True,
}


def get_db():
    """获取数据库连接"""
    return pymysql.connect(**DB_CONFIG)


def init_db():
    """初始化数据库表"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            # 用户表
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(128) NOT NULL,
                phone VARCHAR(20),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

            # 用户偏好表
            c.execute('''CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INT PRIMARY KEY,
                budget_min FLOAT DEFAULT 0,
                budget_max FLOAT DEFAULT 99999,
                preferred_districts TEXT,
                preferred_house_type VARCHAR(50) DEFAULT '',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

            # 收藏表
            c.execute('''CREATE TABLE IF NOT EXISTS favorites (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                item_type VARCHAR(30) NOT NULL,
                item_title VARCHAR(200),
                item_data TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                INDEX idx_user (user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

            # 聊天历史表
            c.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT,
                session_id VARCHAR(100),
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                route VARCHAR(30),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                INDEX idx_user (user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
    finally:
        conn.close()


def hash_password(password):
    """密码哈希（SHA256 + 盐）"""
    salt = "zhizu_advisor_2026"
    return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()


# ========== 用户认证 ==========
def register_user(username, password, phone=None):
    """注册用户"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            # 检查用户名是否存在
            c.execute("SELECT id FROM users WHERE username=%s", (username,))
            if c.fetchone():
                return {"success": False, "error": "用户名已存在"}

            password_hash = hash_password(password)
            c.execute(
                "INSERT INTO users (username, password_hash, phone) VALUES (%s, %s, %s)",
                (username, password_hash, phone)
            )
            user_id = c.lastrowid

            # 初始化偏好
            c.execute("INSERT INTO user_preferences (user_id) VALUES (%s)", (user_id,))
            return {"success": True, "user_id": user_id, "username": username}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def login_user(username, password):
    """用户登录"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute(
                "SELECT id, username, password_hash, phone FROM users WHERE username=%s",
                (username,)
            )
            user = c.fetchone()

        if not user:
            return {"success": False, "error": "用户不存在"}
        if user["password_hash"] != hash_password(password):
            return {"success": False, "error": "密码错误"}

        return {
            "success": True,
            "user_id": user["id"],
            "username": user["username"],
            "phone": user["phone"]
        }
    finally:
        conn.close()


# ========== 用户偏好 ==========
def get_user_preferences(user_id):
    """获取用户偏好"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT * FROM user_preferences WHERE user_id=%s", (user_id,))
            pref = c.fetchone()
        if not pref:
            return {}
        return {
            "budget_min": pref["budget_min"],
            "budget_max": pref["budget_max"],
            "preferred_districts": json.loads(pref["preferred_districts"] or "[]"),
            "preferred_house_type": pref["preferred_house_type"] or ""
        }
    finally:
        conn.close()


def update_user_preferences(user_id, budget_min=None, budget_max=None,
                            preferred_districts=None, preferred_house_type=None):
    """更新用户偏好"""
    current = get_user_preferences(user_id)
    if not current:
        conn = get_db()
        try:
            with conn.cursor() as c:
                c.execute("INSERT INTO user_preferences (user_id) VALUES (%s)", (user_id,))
        finally:
            conn.close()
        current = {"budget_min": 0, "budget_max": 99999,
                   "preferred_districts": [], "preferred_house_type": ""}

    new_budget_min = budget_min if budget_min is not None else current["budget_min"]
    new_budget_max = budget_max if budget_max is not None else current["budget_max"]
    new_districts = json.dumps(preferred_districts, ensure_ascii=False) if preferred_districts is not None else json.dumps(current["preferred_districts"], ensure_ascii=False)
    new_house_type = preferred_house_type if preferred_house_type is not None else current["preferred_house_type"]

    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute('''UPDATE user_preferences SET
                budget_min=%s, budget_max=%s, preferred_districts=%s, preferred_house_type=%s
                WHERE user_id=%s''',
                (new_budget_min, new_budget_max, new_districts, new_house_type, user_id))
        return {"success": True}
    finally:
        conn.close()


# ========== 收藏功能 ==========
def add_favorite(user_id, item_type, item_title, item_data):
    """添加收藏"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            # 检查是否已收藏
            c.execute(
                "SELECT id FROM favorites WHERE user_id=%s AND item_type=%s AND item_title=%s",
                (user_id, item_type, item_title)
            )
            if c.fetchone():
                return {"success": False, "error": "已收藏"}

            c.execute(
                "INSERT INTO favorites (user_id, item_type, item_title, item_data) VALUES (%s, %s, %s, %s)",
                (user_id, item_type, item_title, json.dumps(item_data, ensure_ascii=False))
            )
            fav_id = c.lastrowid
            return {"success": True, "favorite_id": fav_id}
    finally:
        conn.close()


def get_favorites(user_id, item_type=None):
    """获取收藏列表"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            if item_type:
                c.execute(
                    "SELECT * FROM favorites WHERE user_id=%s AND item_type=%s ORDER BY created_at DESC",
                    (user_id, item_type)
                )
            else:
                c.execute(
                    "SELECT * FROM favorites WHERE user_id=%s ORDER BY created_at DESC",
                    (user_id,)
                )
            rows = c.fetchall()

        result = []
        for row in rows:
            try:
                data = json.loads(row["item_data"]) if row["item_data"] else {}
            except Exception:
                data = {}
            result.append({
                "id": row["id"],
                "item_type": row["item_type"],
                "item_title": row["item_title"],
                "item_data": data,
                "created_at": str(row["created_at"]) if row["created_at"] else ""
            })
        return result
    finally:
        conn.close()


def delete_favorite(user_id, favorite_id):
    """删除收藏"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM favorites WHERE id=%s AND user_id=%s", (favorite_id, user_id))
        return {"success": True}
    finally:
        conn.close()


# ========== 聊天历史 ==========
def save_chat_message(user_id, session_id, role, content, route=None):
    """保存聊天消息"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute(
                "INSERT INTO chat_history (user_id, session_id, role, content, route) VALUES (%s, %s, %s, %s, %s)",
                (user_id, session_id, role, content, route)
            )
    finally:
        conn.close()


def get_chat_history(user_id, limit=50):
    """获取聊天历史"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute(
                "SELECT * FROM chat_history WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit)
            )
            rows = c.fetchall()

        result = []
        for row in rows:
            result.append({
                "id": row["id"],
                "session_id": row["session_id"],
                "role": row["role"],
                "content": row["content"],
                "route": row["route"],
                "created_at": str(row["created_at"]) if row["created_at"] else ""
            })
        return list(reversed(result))
    finally:
        conn.close()


def clear_chat_history(user_id):
    """清空聊天历史"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM chat_history WHERE user_id=%s", (user_id,))
        return {"success": True}
    finally:
        conn.close()


# 初始化数据库表
try:
    init_db()
except Exception as e:
    print(f"用户系统 MySQL 初始化失败: {e}")
