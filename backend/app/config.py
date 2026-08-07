"""全局配置与业务规则常量。"""
from typing import Dict, List

# ---- 规则口径常量 ----
DROP_RATE = 0.30          # A/B/D/F 环比、同比降幅阈值（严格大于）
MIN_POLICIES = 2          # A~G 参与门槛：客户总单量 >= 2（恰2单参与）
MIN_CONSECUTIVE = 2       # A/B 连续下降段最少环比下降次数
IDLE_MONTHS = 2           # C 停投判定：间隔 >= 2 个月命中
EPS = 1e-9                # 浮点容差

# ---- 会话配置 ----
SESSION_TTL_SECONDS = 12 * 3600      # 会话 TTL 12 小时
MAX_SESSIONS = 10                    # 会话上限，超限淘汰最旧
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 上传上限 50MB

# ---- 列识别 ----
EXPECTED_COLUMNS = ["签单时间", "客户代码", "保费量", "出单量"]

COLUMN_KEYWORDS: Dict[str, List[str]] = {
    "customer": ["客户代码", "客户", "编码"],
    "date": ["签单时间", "日期", "月份", "时间"],
    "premium": ["保费"],
    "policies": ["出单", "单量"],
}

# ---- CORS ----
CORS_ORIGINS = ["http://localhost:5173", "http://localhost:5174"]

# 无效行样例最多条数
MAX_INVALID_SAMPLES = 10
