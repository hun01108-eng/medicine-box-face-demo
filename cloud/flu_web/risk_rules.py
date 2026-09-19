SOUTH_HIGH_THRESHOLD = 15.0
NORTH_MEDIUM_THRESHOLD = 10.0
RESISTANCE_MEDIUM_THRESHOLD = 5.0


def assess_weekly_risk(data):
    """使用确定性规则生成周报风险标签，避免每周调用 AI。"""
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
