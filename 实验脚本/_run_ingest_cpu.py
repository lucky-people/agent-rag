# -*- coding: utf-8 -*-
"""强制 CPU 运行入库脚本的包装器（规避本机 CUDA 崩溃问题）"""
import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ["PYTORCH_NO_CUDA"] = "1"
os.environ["CUDA_LAUNCH_BLOCKING"] = "0"

import runpy
import sys

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "Agent/ingest_rental_laws.py"
    runpy.run_path(target, run_name="__main__")
