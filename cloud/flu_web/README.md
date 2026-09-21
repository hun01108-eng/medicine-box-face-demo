# AI 流感月报网站

## 1. 安装依赖

本机同时安装了 Python 3.13 和 3.14。本项目统一使用已经装好依赖的 Python 3.13：

```powershell
python3.13 -m pip install -r requirements.txt
```

安装过程中出现 `Scripts is not on PATH` 是警告，不影响本项目运行。看到
`Successfully installed` 后即表示安装完成。

## 2. 更新最新周报

```powershell
python3.13 update_db_curl.py
```

程序会保存疾控中心原始 PDF、解析数据，并使用本地规则生成周风险等级。

批量补录某个月份已经发布的周报：

```powershell
python3.13 import_history.py --month 2026-09
```

## 3. 配置 DeepSeek 密钥

```powershell
$env:DEEPSEEK_API_KEY="替换为重新生成的密钥"
```

不要把密钥写进 Python 文件或提交到版本库。

## 4. 生成月报

可以从终端生成：

```powershell
python3.13 ai_flu_alert.py --month 2026-09
```

## 树莓派更新、云服务器展示

树莓派负责下载和解析，云服务器继续保存数据库、原始 PDF 并提供网页：

```bash
FLU_DATA_DIR=/home/pi/medicine-box/flu-worker-data \
python update_db_curl.py \
  --cloud-url http://192.144.163.230 \
  --token-file /home/pi/medicine-box/secrets/flu_ingest_token
```

云端接收接口为 `POST /api/ingest/weekly`，必须使用独立 Bearer Token；
DeepSeek API Key 只保留在云服务器，不复制到树莓派。

也可以启动网站后，在页面上点击“生成本月月报”。同一月份已有月报时不会重复调用 AI。

## 5. 启动网站

```powershell
python3.13 start_web.py
```

如果环境变量没有生效，启动脚本会在终端中安全询问 DeepSeek API Key，输入内容
不会显示，也不会写入代码。启动脚本会自动打开 `http://127.0.0.1:5000`。终端窗口必须保持开启；按
`Ctrl+C` 可以关闭网站。
