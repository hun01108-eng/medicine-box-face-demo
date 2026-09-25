# 云端流感风险信息网站

本目录部署在云服务器，负责接收树莓派上传的官方周报数据与原始 PDF、保存
SQLite 数据、展示周报及图表，并调用 DeepSeek 生成月报。周风险是可审计规则的结果，AI 仅用于月度文字归纳，均不
代表个人诊断或医疗处方。

## 1. 安装依赖

推荐使用独立虚拟环境安装依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 2. 更新最新周报

```bash
.venv/bin/python update_db_curl.py
```

程序会保存疾控中心原始 PDF、解析数据，并使用本地规则生成周风险等级。

批量补录某个月份已经发布的周报：

```bash
.venv/bin/python import_history.py --month 2026-09
```

## 3. 配置 DeepSeek 密钥

```bash
export DEEPSEEK_API_KEY="替换为重新生成的密钥"
```

不要把密钥写进 Python 文件或提交到版本库。

## 4. 生成月报

可以从终端生成：

```bash
.venv/bin/python ai_flu_alert.py --month 2026-09
```

## 树莓派更新、云服务器展示

树莓派负责下载和解析，云服务器继续保存数据库、原始 PDF 并提供网页：

```bash
FLU_DATA_DIR=/home/pi/medicine-box/flu-worker-data \
python update_db_curl.py \
  --cloud-url http://192.144.163.230 \
  --token-file /home/pi/medicine-box/secrets/flu_ingest_token
```

云端接收接口为 `POST /api/ingest/weekly`，必须使用独立 Bearer Token。令牌
保存在 `FLU_INGEST_TOKEN_FILE` 指定的服务器文件中；DeepSeek API Key 只保留
在云服务器，不复制到树莓派。

也可以启动网站后，在页面上点击“生成本月月报”。同一月份已有月报时不会重复调用 AI。

## 5. 启动网站

```bash
.venv/bin/python app.py
```

`app.py` 默认只监听 `127.0.0.1:5000` 且关闭调试模式。正式部署建议使用现有
WSGI 服务并由 Nginx 反向代理；不要在公网启用 `FLU_WEB_DEBUG`。Windows 本地
联调仍可使用 `python start_web.py` 自动打开浏览器。
