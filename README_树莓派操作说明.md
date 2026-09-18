# 智能药箱箱外单人脸识别Demo

这是第三板块的软件框架：在树莓派本地识别唯一注册老人`elder_001`，其余人员统一输出`UNKNOWN`。人脸识别只负责选择用户档案，不判断药品、剂量或是否已经服药。

## 1. 当前能力

- OpenCV YuNet人脸检测；
- OpenCV SFace人脸对齐、特征提取和余弦比对；
- 普通OpenCV/USB摄像头和Picamera2两种输入；
- 过暗、过曝、模糊、人脸太小的质量门禁；
- 多人画面拒绝；
- 3个匹配帧确认、最多5个有效帧；
- 从首个有效人脸出现开始计算3秒超时；
- 单一注册人员与`UNKNOWN`开放集判断；
- 注册模板只保存归一化特征，不复制或保存原始人脸图片；
- 身份结果只输出JSON文本；
- P50/P95延迟基准命令；
- 无摄像头模拟测试。

> 第一版没有可靠活体检测，不能防止照片或手机屏幕冒用，不能作为强身份认证系统。

## 2. 目录结构

```text
medicine-box-face-demo/
├── config.json                 参数与阈值
├── models/                     YuNet和SFace官方ONNX模型
├── enrollment_images/          临时注册照片；注册后删除
├── data/                        运行后产生特征模板
├── scripts/download_models.py  官方模型下载及SHA-256验证
├── src/facebox/
│   ├── app.py                  命令入口
│   ├── camera.py               摄像头适配层
│   ├── opencv_engine.py        YuNet＋SFace
│   ├── quality.py              图像质量门禁
│   ├── decision.py             多帧开放集决策
│   ├── templates.py            特征模板存储
│   ├── session.py              身份会话过期
│   └── metrics.py              P50/P95统计
└── tests/                       不访问摄像头的自动测试
```

## 3. 复制到树莓派

把整个工程复制到树莓派，例如放到：

```bash
/home/pi/medicine-box-face-demo
```

进入目录：

```bash
cd /home/pi/medicine-box-face-demo
```

模型已包含在交付包中。如果模型丢失，可重新下载并校验：

```bash
python3 scripts/download_models.py
```

## 4. 树莓派依赖

### Raspberry Pi OS＋CSI摄像头

先检查系统是否已经具有依赖：

```bash
python3 - <<'PY'
import cv2
import numpy
from picamera2 import Picamera2
print("OpenCV:", cv2.__version__)
print("NumPy:", numpy.__version__)
print("FaceDetectorYN:", hasattr(cv2, "FaceDetectorYN"))
print("FaceRecognizerSF:", hasattr(cv2, "FaceRecognizerSF"))
print("Picamera2: OK")
PY
```

如果缺少软件包，在Raspberry Pi OS中由设备管理员执行：

```bash
sudo apt update
sudo apt install -y python3-opencv python3-picamera2
```

不要优先用`pip`覆盖Raspberry Pi OS自带的Picamera2/libcamera环境。

### USB摄像头或普通Linux

建议使用独立虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 5. 先运行软件测试

不需要摄像头：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

模拟已注册老人：

```bash
PYTHONPATH=src python3 -m facebox.app simulate --case known
```

预期核心结果：

```json
{"status":"MATCHED","user_id":"elder_001"}
```

模拟陌生人：

```bash
PYTHONPATH=src python3 -m facebox.app simulate --case unknown
```

预期状态为`UNKNOWN`。该命令退出码为2，表示安全拒绝，不代表程序崩溃。

其他安全路径：

```bash
PYTHONPATH=src python3 -m facebox.app simulate --case dark
PYTHONPATH=src python3 -m facebox.app simulate --case multiple
PYTHONPATH=src python3 -m facebox.app simulate --case timeout
```

## 6. 采集注册照片

注册必须由老人或监护人主动启动。注册图片不得放入代码仓库或云端。

Picamera2系统可使用`rpicam-still`逐张拍摄，例如：

```bash
rpicam-still --width 640 --height 480 --output enrollment_images/normal_front.jpg
rpicam-still --width 640 --height 480 --output enrollment_images/bright_front.jpg
rpicam-still --width 640 --height 480 --output enrollment_images/dim_front.jpg
rpicam-still --width 640 --height 480 --output enrollment_images/left_light.jpg
rpicam-still --width 640 --height 480 --output enrollment_images/right_light.jpg
rpicam-still --width 640 --height 480 --output enrollment_images/turn_left.jpg
rpicam-still --width 640 --height 480 --output enrollment_images/turn_right.jpg
```

采集要求：

- 每张图只出现老人一人；
- 脸部无遮挡且清晰；
- 包含普通、明亮、较暗、侧光和轻微转头；
- 老人平时戴眼镜，则增加戴眼镜样本；
- 不使用严重模糊、全黑或强过曝图片。

## 7. 生成老人特征模板

```bash
PYTHONPATH=src python3 -m facebox.app enroll \
  --images enrollment_images \
  --minimum 5
```

成功后生成：

```text
data/elder_001.json
```

它只包含特征向量，不包含原图，但仍属于敏感个人信息，文件权限自动设为仅当前用户读写。确认模板生成后删除临时注册图片：

```bash
rm enrollment_images/*.jpg enrollment_images/*.jpeg enrollment_images/*.png 2>/dev/null || true
```

## 8. 运行前自检

```bash
PYTHONPATH=src python3 -m facebox.app self-check
```

必须看到：

```json
"ready": true
```

### CSI/Picamera2摄像头

```bash
PYTHONPATH=src python3 -m facebox.app run --source picamera2 --display
```

### USB摄像头

先查看设备：

```bash
v4l2-ctl --list-devices
```

再运行：

```bash
PYTHONPATH=src python3 -m facebox.app run \
  --source opencv \
  --device /dev/video0 \
  --display
```

无桌面环境时去掉`--display`。程序输出以下状态之一：

- `MATCHED`：确认`elder_001`；
- `UNKNOWN`：人脸存在但不匹配；
- `UNKNOWN_RETRY`：画面质量不足、多人或超时；
- `ERROR`：模型、摄像头或模板错误。

## 9. 测试3秒目标

老人稳定站在识别位置后运行20次：

```bash
PYTHONPATH=src python3 -m facebox.app benchmark \
  --source picamera2 \
  --trials 20
```

USB摄像头则改为：

```bash
PYTHONPATH=src python3 -m facebox.app benchmark \
  --source opencv \
  --device /dev/video0 \
  --trials 20
```

输出包含：

```json
{
  "p50_seconds": 0.0,
  "p95_seconds": 0.0,
  "max_seconds": 0.0,
  "p95_within_3s": true
}
```

这里的数值由实机产生；上面的`0.0`只是字段示例，不是测试结果。验收重点是`p95_within_3s`为`true`，并检查`statuses`中的20次是否全部为`MATCHED`。

## 10. 参数调整

参数都在`config.json`：

- `similarity_threshold`：身份匹配阈值；当前0.55只是保守起点，必须用老人和多位陌生人的实测数据标定；
- `required_matches`：确认所需匹配帧数；
- `max_valid_frames`：一次判断最多使用的有效帧；
- `timeout_seconds`：从第一张人脸出现开始的超时；
- `min_face_width`：最小人脸宽度；
- `min_brightness`和`max_brightness`：亮度范围；
- `min_sharpness`：模糊拒绝阈值；
- `use_clahe`：是否对齐后进行受控亮度均衡。

不要只用注册老人的图片调低阈值。必须加入至少数位非注册人员测试，优先防止陌生人被错误识别为老人。

## 11. 隐私与医疗边界

- 普通运行只在内存中处理摄像头帧；
- 源码不调用`imwrite`或`VideoWriter`；
- 默认不保存识别截图和视频；
- 日志只输出身份状态、相似度和延迟；
- 模板需要删除机制，删除`data/elder_001.json`即可注销；
- `UNKNOWN`不得加载任何人的个性化用药计划；
- 人脸模块不得识别、生成或修改药品名称和剂量；
- AI不得绕过确定性身份门禁。

## 12. 下一阶段实机验收

当前交付已完成软件框架和无硬件测试。下面这些只能在你们的树莓派和实际摄像头上验证：

1. Picamera2或`/dev/video0`取帧；
2. 老人多光照注册；
3. 相似度阈值标定；
4. 明亮、普通、较暗、侧光和逆光测试；
5. 多位陌生人误放行测试；
6. 20次实机P95延迟；
7. 摄像头实际安装距离和OV5647固定焦点清晰度。

## 13. 红外经过检测通知 Uno

安装串口依赖并将运行用户加入串口组：

```bash
sudo apt install -y python3-serial
sudo usermod -aG dialout pi
```

组权限修改后需要注销重新登录或重启。用稳定设备名区分两个 USB 串口：

```bash
ls -l /dev/serial/by-id/
```

启动命令：

```bash
cd /home/pi/medicine-box/current
PYTHONPATH=src python3 -m facebox.app thermal-monitor \
  --thermal-port /dev/serial/by-id/<MLX90642设备> \
  --uno-port /dev/serial/by-id/<Arduino-Uno设备>
```

通信协议为一行 ASCII 文本：树莓派发送 `PERSON_IN\n`，Uno播放语音后返回
`ACK\n`。一次进入事件只发送一次；热斑消失、检测器复位且冷却结束后，下一次
进入才会再次发送。事件日志默认写入 `logs/person_events.csv`。

常用参数：

- `--thermal-baud 921600`：红外模块波特率；
- `--uno-baud 9600`：Uno通信波特率；
- `--confirm-seconds 0.6`：热斑持续多久才确认有人；
- `--clear-seconds 1.5`：人离开多久后复位；
- `--cooldown-seconds 3.0`：两次通知的最短间隔；
- `--offset 4.0`：仅用于日志显示的温度校准值，不参与人体检测。

先运行无硬件模拟测试：

```bash
PYTHONPATH=src python3 -m facebox.app thermal-monitor --simulate
```

按 `Ctrl+C` 停止。红外检测与人脸实时预览是两个独立进程，可分别启动；
红外模块不会修改人脸模板，也不会保存可见光或红外图像。

## 14. 接入云端流感风险

该功能仅使用 Python 标准库，不需要在树莓派额外安装 HTTP 包，也不需要把
DeepSeek API Key 放到设备上。确认树莓派可以访问云服务器后，先执行一次：

```bash
cd /home/pi/medicine-box/current
PYTHONPATH=src python3 -m facebox.app flu-status
```

指定月份或临时服务器地址：

```bash
PYTHONPATH=src python3 -m facebox.app flu-status --month 2026-08
PYTHONPATH=src python3 -m facebox.app flu-status --api-base-url http://192.144.163.230
```

持续轮询：

```bash
PYTHONPATH=src python3 -m facebox.app flu-monitor --interval 3600
```

成功输出 `FLU_RISK`，字段 `risk_level` 为 `高`、`中`或`低`。断网时程序读取
`data/flu_risk_cache.json`，并输出 `"source":"cache","stale":true`；如果从未
成功联网且没有缓存，则输出 `ERROR`。若要禁止使用缓存，加 `--no-cache`。

人脸识别、红外检测和流感轮询建议先在三个终端分别运行并验收。仓库暂不自动
安装 systemd 服务，也不自动把风险等级发送给 Uno；这两项应在树莓派实测和
通信协议确认后再启用。
