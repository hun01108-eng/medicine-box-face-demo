# 树莓派流感周报更新器

该目录只负责从中国疾控中心官网下载最新周报、解析 PDF，并通过受保护接口
上传到云服务器。网页、SQLite 主数据库和 DeepSeek 密钥继续保留在云端。

手动运行：

```bash
cd /home/pi/medicine-box/current
FLU_DATA_DIR=/home/pi/medicine-box/flu-worker-data \
.flu-worker-venv/bin/python workers/flu_updater/update_db_curl.py \
  --cloud-url http://192.144.163.230 \
  --token-file /home/pi/medicine-box/secrets/flu_ingest_token
```

令牌文件权限应为 `600`。运行产生的本地数据库和 PDF 只是工作缓存，云服务器
成功接收后才算更新完成。不要把令牌、PDF 缓存或数据库提交到 Git。
