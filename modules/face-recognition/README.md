# 智能药箱：独立人脸识别审核模块

本目录是从`medicine-box-face-demo`中单独提取、审查并精简的人脸识别部分，供评委组独立审核。

本模块只负责：

```text
摄像头取帧
→ YuNet检测人脸
→ 图像质量门禁
→ SFace提取特征并计算余弦相似度
→ 3至5帧确定性决策
→ 输出MATCHED / UNKNOWN / UNKNOWN_RETRY
```

不包含红外检测、流感API、Arduino Uno音频协议、云端网页或R3固件。上层系统应读取本模块输出的JSON状态，再决定是否调用其他模块。

> 人脸识别只是用户档案选择器。它不识别药品，不生成或修改药品名称、剂量，也不能证明用户已经服药。

## 1. 审核后保留的核心设计

- **YuNet**：检测人脸并输出五点关键点；
- **SFace**：人脸对齐、特征提取和相似度计算；
- **质量门禁**：拒绝人脸过小、过暗、过曝或模糊帧；
- **开放集拒绝**：只有注册老人可以输出`MATCHED`，其余人员输出`UNKNOWN`；
- **多帧确认**：默认3个匹配帧确认，最多使用5个有效帧；
- **3秒超时**：从首次检测到人脸开始计时，不包含程序和摄像头冷启动；
- **本地模板**：只保存归一化特征向量，不保存注册照片；
- **USB摄像头默认输入**：默认`/dev/video0`、640×480，同时保留可选Picamera2适配。

## 2. 目录

```text
face-recognition-module/
├── config.json
├── pyproject.toml
├── requirements.txt
├── README.md
├── REVIEW_REPORT.md
├── models/README.md
├── enrollment_images/README.md
├── scripts/download_models.py
├── src/facebox/
│   ├── app.py
│   ├── camera.py
│   ├── config.py
│   ├── decision.py
│   ├── metrics.py
│   ├── opencv_engine.py
│   ├── quality.py
│   ├── templates.py
│   └── types.py
└── tests/
```

已删除未进入生产流程的`session.py`，以及所有红外、流感、R3、云端和部署脚本。

## 3. 依赖

### Raspberry Pi OS

建议复用系统NumPy和OpenCV：

```bash
sudo apt update
sudo apt install -y python3-opencv v4l-utils
python3 -m venv --system-site-packages .venv
```

本审核包没有替用户执行安装命令。

### 普通Linux虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 4. 获取模型

模型未放入源码压缩包，以免重复提交大文件。下载脚本包含固定SHA-256：

```bash
python3 scripts/download_models.py
```

详见`models/README.md`。

## 5. 无硬件测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

审核版包含34项测试，覆盖多帧决策、超时、质量门禁、模板存储、时延统计、CLI边界、非有限数值拒绝和配置身份一致性。

模拟流程：

```bash
PYTHONPATH=src python3 -m facebox.app simulate --case known
PYTHONPATH=src python3 -m facebox.app simulate --case unknown
PYTHONPATH=src python3 -m facebox.app simulate --case dark
PYTHONPATH=src python3 -m facebox.app simulate --case multiple
PYTHONPATH=src python3 -m facebox.app simulate --case timeout
```

## 6. 注册与运行

采集多光照注册照片后执行：

```bash
PYTHONPATH=src python3 -m facebox.app enroll \
  --images enrollment_images \
  --minimum 5
```

生成：

```text
data/elder_001.json
```

确认模板生成后删除临时照片。模板仍是敏感生物特征数据，必须限制访问。

自检：

```bash
PYTHONPATH=src python3 -m facebox.app self-check
```

单次识别：

```bash
PYTHONPATH=src python3 -m facebox.app run --display
```

持续预览：

```bash
PYTHONPATH=src python3 -m facebox.app monitor
```

20次时延基准：

```bash
PYTHONPATH=src python3 -m facebox.app benchmark --trials 20
```

## 7. 状态含义

- `WAITING`：信息不足，继续观察；
- `MATCHED`：多帧确认`elder_001`；
- `UNKNOWN`：有效人脸与模板不匹配；
- `UNKNOWN_RETRY`：暗光、模糊、多人、超时或识别数据异常。

任何非`MATCHED`状态都不得加载个人用药计划。

## 8. 关键配置

默认配置：

```json
{
  "similarity_threshold": 0.55,
  "required_matches": 3,
  "max_valid_frames": 5,
  "timeout_seconds": 3.0,
  "user_id": "elder_001"
}
```

`0.55`只是初始值，必须使用实际老人和多位非注册人员样本标定，不能为了暗光通过率盲目降低。

## 9. 隐私与安全边界

- 普通运行只在内存中处理视频帧；
- 不调用`imwrite`或`VideoWriter`；
- 不保存日常截图、视频或原始注册照片；
- 模板ID必须与配置ID一致，否则拒绝启动；
- 模板、候选特征或相似度出现`NaN/Infinity`时安全拒绝；
- 未知人员、多张人脸、低质量画面和超时均不得放行；
- 第一版没有可靠活体检测，不能抵抗照片或手机屏幕冒用，不能宣传为强身份认证。

## 10. 尚需实机完成

- USB摄像头设备名和取帧稳定性；
- 老人多光照注册；
- 阈值与陌生人误放行率标定；
- 明亮、普通、暗光、侧光、逆光测试；
- 20次以上P50/P95时延；
- 摄像头安装距离、对焦与补光；
- 活体检测方案（如比赛要求更高安全等级）。
