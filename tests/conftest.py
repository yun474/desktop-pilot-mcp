import sys
from pathlib import Path

# 让测试可以直接 import core 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
