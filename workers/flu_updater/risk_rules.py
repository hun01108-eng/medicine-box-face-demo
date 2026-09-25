"""树莓派端可审计的每周流感风险分级规则。

这是云端规则的独立部署镜像，便于树莓派断网时生成本地缓存；两端阈值和逻辑
必须保持一致。结果仅代表公共卫生信息风险，不用于个人诊断。
"""

# 阈值集中定义，便于后续根据专家意见统一调整。
SOUTH_HIGH_THRESHOLD = 15.0
NORTH_MEDIUM_THRESHOLD = 10.0
RESISTANCE_MEDIUM_THRESHOLD = 5.0


def assess_weekly_risk(data):
    """根据官方周报指标返回 ``(风险等级, 触发原因)``。"""
    high_reasons = []
    medium_reasons = []

    south_rate = data.get("south_positivity_rate")
    north_rate = data.get("north_positivity_rate")
    resistance = data.get("h3n2_resistance_ratio")

    if south_rate is not None and south_rate > SOUTH_HIGH_THRESHOLD:
        high_reasons.append(f"南方阳性率 {south_rate}% 超过 {SOUTH_HIGH_THRESHOLD}%")
    if north_rate is not None and north_rate > NORTH_MEDIUM_THRESHOLD:
        medium_reasons.append(f"北方阳性率 {north_rate}% 超过 {NORTH_MEDIUM_THRESHOLD}%")

    if data.get("south_trend") == "上升":
        medium_reasons.append("南方阳性率呈上升趋势")
    if data.get("north_trend") == "上升":
        medium_reasons.append("北方阳性率呈上升趋势")

    outbreak_count = data.get("outbreak_count")
    if outbreak_count is not None and outbreak_count > 0:
        medium_reasons.append(f"报告 {outbreak_count} 起暴发疫情")

    if resistance is not None and resistance > RESISTANCE_MEDIUM_THRESHOLD:
        medium_reasons.append(f"耐药性降低比例为 {resistance:.1f}%")

    if high_reasons:
        return "高", "；".join(high_reasons + medium_reasons)
    if medium_reasons:
        return "中", "；".join(medium_reasons)
    return "低", "未触发周风险规则"
