const button = document.getElementById("generate-report");

if (button) {
  button.addEventListener("click", async () => {
    const status = document.getElementById("generate-status");
    button.disabled = true;
    status.textContent = "正在调用 AI 生成月报，请稍候……";

    try {
      const response = await fetch("/api/monthly/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ month: button.dataset.month })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || "生成失败");
      status.textContent = "月报生成成功，正在刷新页面……";
      window.location.reload();
    } catch (error) {
      status.textContent = error.message;
      button.disabled = false;
    }
  });
}

const chartDataElement = document.getElementById("weekly-chart-data");

if (chartDataElement) {
  const weekly = JSON.parse(chartDataElement.textContent).slice().reverse();
  renderPositivityChart(weekly);
  renderOutbreakChart(weekly);
  renderRiskChart(weekly);
}

function svgElement(name, attributes = {}, text = "") {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  if (text !== "") element.textContent = text;
  return element;
}

function createSvg(container, width, height, description) {
  container.replaceChildren();
  const svg = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": description
  });
  container.appendChild(svg);
  return svg;
}

function shortWeek(reportWeek) {
  return reportWeek ? `W${reportWeek.split("W").pop()}` : "—";
}

function renderPositivityChart(data) {
  const container = document.getElementById("positivity-chart");
  if (!container) return;
  const valid = data.filter(item => item.south_positivity_rate != null || item.north_positivity_rate != null);
  if (!valid.length) {
    container.innerHTML = '<p class="chart-empty">暂无阳性率数据</p>';
    return;
  }

  const width = 940, height = 300;
  const margin = { top: 38, right: 34, bottom: 48, left: 58 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const allValues = valid.flatMap(item => [item.south_positivity_rate, item.north_positivity_rate]).filter(value => value != null);
  const maxValue = Math.max(5, Math.ceil(Math.max(...allValues) / 5) * 5);
  const x = index => margin.left + (valid.length === 1 ? chartWidth / 2 : index * chartWidth / (valid.length - 1));
  const y = value => margin.top + chartHeight - value / maxValue * chartHeight;
  const svg = createSvg(container, width, height, "南北方流感病毒检测阳性率按周变化");

  for (let tick = 0; tick <= 4; tick += 1) {
    const value = maxValue * tick / 4;
    const tickY = y(value);
    svg.appendChild(svgElement("line", { x1: margin.left, y1: tickY, x2: width - margin.right, y2: tickY, class: "grid-line" }));
    svg.appendChild(svgElement("text", { x: margin.left - 10, y: tickY + 4, "text-anchor": "end", class: "axis-label" }, `${value.toFixed(1)}%`));
  }

  valid.forEach((item, index) => {
    svg.appendChild(svgElement("text", { x: x(index), y: height - 18, "text-anchor": "middle", class: "axis-label" }, shortWeek(item.report_week)));
  });

  const drawSeries = (field, lineClass, pointClass) => {
    const points = valid.map((item, index) => item[field] == null ? null : [x(index), y(item[field]), item[field]]).filter(Boolean);
    if (points.length > 1) {
      svg.appendChild(svgElement("polyline", { points: points.map(point => `${point[0]},${point[1]}`).join(" "), class: lineClass }));
    }
    points.forEach(point => {
      const circle = svgElement("circle", { cx: point[0], cy: point[1], r: 5, class: pointClass });
      circle.appendChild(svgElement("title", {}, `${point[2]}%`));
      svg.appendChild(circle);
    });
  };
  drawSeries("south_positivity_rate", "south-line", "south-point");
  drawSeries("north_positivity_rate", "north-line", "north-point");

  svg.appendChild(svgElement("circle", { cx: margin.left, cy: 16, r: 5, class: "south-point" }));
  svg.appendChild(svgElement("text", { x: margin.left + 12, y: 20, class: "legend-label" }, "南方"));
  svg.appendChild(svgElement("circle", { cx: margin.left + 78, cy: 16, r: 5, class: "north-point" }));
  svg.appendChild(svgElement("text", { x: margin.left + 90, y: 20, class: "legend-label" }, "北方"));
}

function renderOutbreakChart(data) {
  const container = document.getElementById("outbreak-chart");
  if (!container) return;
  const width = 440, height = 270;
  const margin = { top: 28, right: 20, bottom: 45, left: 45 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const values = data.map(item => Number(item.outbreak_count || 0));
  const maxValue = Math.max(1, ...values);
  const step = chartWidth / Math.max(1, data.length);
  const barWidth = Math.min(46, step * .55);
  const svg = createSvg(container, width, height, "每周报告的流感样病例暴发疫情数量");

  svg.appendChild(svgElement("line", { x1: margin.left, y1: margin.top + chartHeight, x2: width - margin.right, y2: margin.top + chartHeight, class: "axis" }));
  data.forEach((item, index) => {
    const value = values[index];
    const barHeight = value / maxValue * chartHeight;
    const barX = margin.left + index * step + (step - barWidth) / 2;
    const barY = margin.top + chartHeight - barHeight;
    svg.appendChild(svgElement("rect", { x: barX, y: barY, width: barWidth, height: barHeight, rx: 5, class: "outbreak-bar" }));
    svg.appendChild(svgElement("text", { x: barX + barWidth / 2, y: Math.max(18, barY - 8), "text-anchor": "middle", class: "value-label" }, String(value)));
    svg.appendChild(svgElement("text", { x: barX + barWidth / 2, y: height - 18, "text-anchor": "middle", class: "axis-label" }, shortWeek(item.report_week)));
  });
}

function renderRiskChart(data) {
  const container = document.getElementById("risk-chart");
  if (!container) return;
  const counts = { "高": 0, "中": 0, "低": 0 };
  data.forEach(item => counts[item.risk_level] = (counts[item.risk_level] || 0) + 1);
  const width = 440, height = 270;
  const svg = createSvg(container, width, height, "高、中、低风险周报数量");
  const entries = [
    ["高", counts["高"], "risk-high"],
    ["中", counts["中"], "risk-medium"],
    ["低", counts["低"], "risk-low"]
  ];
  const maxValue = Math.max(1, ...entries.map(entry => entry[1]));
  entries.forEach(([label, value, className], index) => {
    const y = 42 + index * 70;
    const barWidth = 260 * value / maxValue;
    svg.appendChild(svgElement("text", { x: 22, y: y + 21, class: "axis-label" }, `${label}风险`));
    svg.appendChild(svgElement("rect", { x: 88, y, width: Math.max(2, barWidth), height: 28, rx: 6, class: className }));
    svg.appendChild(svgElement("text", { x: 365, y: y + 21, class: "value-label" }, `${value} 周`));
  });
}
