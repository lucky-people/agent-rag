# -*- coding: utf-8 -*-
"""一次性脚本：web_server.py 补最后一处锁 + 启动时挂后台清理线程"""
import io
import os
import subprocess
import sys

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'web_server.py')
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

# 1) 683 行锁外写
old = '''            reply = "\\n\\n".join(all_responses)
            sess["history"] += f"\\nAssistant: {reply}"
            _save_history(user_id, session_id, "user", message, route)'''
new = '''            reply = "\\n\\n".join(all_responses)
            with sessions_lock:
                sess["history"] += f"\\nAssistant: {reply}"
            _save_history(user_id, session_id, "user", message, route)'''
if old in text:
    text = text.replace(old, new, 1)
    print('[683 lock] OK')
else:
    print('[683 lock] WARN')

# 2) 启动时挂后台清理线程
old_main = '''if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8501, debug=False, threaded=True)'''
new_main = '''if __name__ == "__main__":
    # 后台线程定期清理空闲超时会话
    def _cleanup_loop():
        while True:
            time.sleep(300)   # 每5分钟清理一次
            try:
                _cleanup_sessions()
            except Exception as e:
                logger.error(f"会话清理异常: {e}")
    threading.Thread(target=_cleanup_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=8501, debug=False, threaded=True)'''
if old_main in text:
    text = text.replace(old_main, new_main, 1)
    print('[cleanup thread] OK')
else:
    print('[cleanup thread] WARN')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
print('compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:300])
