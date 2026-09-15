# ===== rag_qa/utils/ssl_fix.py =====
"""
SSL 证书修复模块
使用方法：在脚本最顶部（所有 import 之前）导入本模块
    >>> from rag_qa.utils.ssl_fix import apply_ssl_fix
    >>> apply_ssl_fix()
"""

import os
import ssl


def apply_ssl_fix():
    """
    应用 SSL 证书修复，跳过 Windows 证书存储加载。
    必须在所有网络相关的 import 之前调用。
    """
    # 1. 设置环境变量
    os.environ.setdefault('SSL_CERT_FILE', '')
    os.environ.setdefault('REQUESTS_CA_BUNDLE', '')
    os.environ.setdefault('CURL_CA_BUNDLE', '')

    # 2. 直接修改 SSLContext.load_default_certs 方法
    _original_load_default_certs = ssl.SSLContext.load_default_certs

    def _patched_load_default_certs(self, purpose):
        """完全跳过加载 Windows 证书存储"""
        return  # 什么都不做，直接返回

    ssl.SSLContext.load_default_certs = _patched_load_default_certs

    # 3. 额外禁用 _load_windows_store_certs（防御性编程）
    if hasattr(ssl, '_load_windows_store_certs'):
        ssl._load_windows_store_certs = lambda self, storename, purpose: None

    # 4. 替换 create_default_context，使用 certifi 证书
    _original_create_default_context = ssl.create_default_context

    def _patched_create_default_context(*args, **kwargs):
        context = _original_create_default_context(*args, **kwargs)
        try:
            import certifi
            context.load_verify_locations(cafile=certifi.where())
        except Exception:
            pass
        return context

    ssl.create_default_context = _patched_create_default_context

    # print("[SSL Fix] 已应用，Windows 证书存储已绕过")


# 自动应用（方便直接 import 模块时生效）
apply_ssl_fix()