# -*- coding: utf-8 -*-
"""从 lang_env 虚拟环境提取依赖版本"""
import subprocess

py = r'C:\Users\31077\anaconda3\envs\lang_env\python.exe'
result = subprocess.run(
    [py, '-m', 'pip', 'freeze'],
    capture_output=True, text=True, encoding='utf-8', errors='ignore'
)
if result.returncode != 0:
    print('执行失败:', result.stderr[:500])
else:
    lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    print(f'环境依赖总数: {len(lines)}')
    with open(r'D:\heima_lesson\多智能体+RAG综合项目\env_full_deps.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('已保存到 env_full_deps.txt')
    # 打印关键依赖用于核对
    for l in lines:
        if any(k in l.lower() for k in ['langchain', 'mcp', 'pymilvus', 'torch', 'transformers', 'sentence', 'flask', 'fastapi', 'aiohttp', 'requests', 'pymysql', 'redis', 'openai', 'pandas', 'numpy', 'matplotlib', 'jieba', 'rank_bm25', 'rapidocr', 'playwright', 'bs4', 'beautifulsoup', 'docx', 'pdfplumber', 'pypdf', 'fitz', 'pymupdf', 'sklearn', 'scikit', 'modelscope', 'certifi', 'python-dotenv', 'a2a']):
            print('  ', l)
