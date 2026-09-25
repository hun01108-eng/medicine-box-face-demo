# 流感风险评估与 API 模块说明

## 功能定位

该模块将中国疾控中心公开的流感周报转化为结构化公共卫生风险信息，并为网页、
微信公众号和药箱语音提醒提供同一数据来源。这里的“风险”是基于公开监测指标的
信息分级，不是个人患病概率、医学诊断或用药建议。

## 部署边界

### 树莓派端

- `workers/flu_updater/update_db_curl.py`：每周从官网下载原始 PDF，解析指标并上传。
- `src/facebox/flu_api.py`：读取云端最新周风险；网络异常时可使用本地缓存并标记
  `stale=true`。
- `src/facebox/flu_app.py`：把高、中、低风险映射为 `0009`、`0010`、`0011`，通过
  Uno 串口发送；相同周次与等级默认不重复播报。
- `deploy/systemd/flu-weekly-update.timer`：每周一 10:00 启动更新流程。

### 云服务器端

- `cloud/flu_web/app.py`：接收入库、网页展示、查询 API、原始 PDF 浏览入口。
- `cloud/flu_web/database.py`：保存周报、AI 月报及微信推送状态。
- `cloud/flu_web/risk_rules.py`：对上传数据重新执行确定性风险分级。
- `cloud/flu_web/ai_flu_alert.py`：调用 DeepSeek 归纳月度趋势并严格校验 JSON。
- `cloud/flu_web/wechat_push.py`：周报入库后发送公众号模板消息并防止重复推送。

树莓派和云端保留独立的更新/规则文件，是为了让两个部署包分别可运行。规则镜像
由回归测试校验，避免阈值或输出漂移。

## 主流程

```text
中国疾控中心官网
        │ 周报 PDF
        ▼
树莓派下载与解析 ──加密令牌上传──► 云端入库与规则复核
        │                              ├─► 网页/API/原始PDF
        │                              ├─► DeepSeek 月度归纳
        │                              └─► 微信周风险通知
        │
        └────读取云端最新风险──────► Uno R3 播放 0009/0010/0011
```

只有上传、入库和 API 读取成功后才进入后续流程。微信接口故障不会破坏已入库数据；
树莓派更新失败会返回非零退出码，阻止 systemd 使用旧结果执行成功后播报。

## 对外接口

- `POST /api/ingest/weekly`：树莓派上传元数据与 PDF，要求 Bearer Token。
- `GET /api/weekly`：返回指定月份或最新月份的周报与风险等级。
- `GET /api/dashboard`：返回网页所需的月报、周报和图表数据。
- `POST /api/monthly/generate`：生成或读取指定月份的 AI 月报。
- `GET /reports/original/<report_week>`：查看本地原始 PDF；缺失时回退至官网链接。
- `GET /api/flu/health`：服务健康检查。

## 安全与配置

- `DEEPSEEK_API_KEY` 与微信凭据只放在云服务器环境变量中。
- 上传令牌使用权限受限的独立文件，树莓派和云端各保存一份。
- 数据库、PDF、缓存、令牌和本地微信测试配置均不提交到 Git。
- Flask 调试模式默认关闭；正式服务应通过 WSGI 与 Nginx 对外提供 HTTPS。
