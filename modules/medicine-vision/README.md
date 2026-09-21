# 药品余量视觉识别模块

本目录是从用户提供的树莓派程序中独立整理的绿色/红色目标检测与低库存提醒模块。它只负责视觉计数和低库存事件，不识别、推断或修改药品名称与剂量。

## 功能边界

```text
CSI摄像头（Picamera2）
→ 固定宽度缩放
→ HSV颜色分割
→ 形态学去噪/连接
→ 轮廓面积筛选
→ 绿色和红色目标计数
→ 连续多帧低库存确认
→ 画面提示
→ 可选Uno串口提醒
```

普通运行不保存视频、图片或日志文件。

## 目录

```text
src/medicine_vision/config.py       配置读取与参数校验
src/medicine_vision/detector.py     HSV、形态学、轮廓与画框
src/medicine_vision/alerting.py     多帧确认和报警限流
src/medicine_vision/serial_link.py  四位数字换行协议及ACK/ERR读取
src/medicine_vision/app.py          Picamera2、窗口和资源生命周期
tests/                              无硬件逻辑测试
config.json                         默认参数
REVIEW_REPORT.md                    审查与修复记录
```

## Raspberry Pi依赖

优先使用Raspberry Pi OS系统包，不要用普通pip覆盖系统NumPy、OpenCV或Picamera2：

```bash
sudo apt update
sudo apt install -y python3-opencv python3-numpy python3-picamera2 python3-serial
```

无串口模式不需要`pyserial`。`requirements.txt`只记录可选串口依赖。

## 运行

在本目录执行：

```bash
PYTHONPATH=src python3 -m medicine_vision.app --config config.json
```

无图形桌面时可以执行：

```bash
PYTHONPATH=src python3 -m medicine_vision.app --config config.json --headless
```

预览窗口中按`q`退出；`Ctrl+C`也会释放摄像头和串口。

## 串口协议阻断项

用户原代码发送：

```text
0012\n
```

但本仓库当前R3固件和《R3串口通信对接说明》只接受`0001`至`0011`，现有音频也只有`001.mp3`至`011.mp3`。因此默认配置为：

```json
"serial": {
  "enabled": false,
  "protocol_confirmed": false,
  "alert_command": "0012"
}
```

在完成以下事项前，不应把`enabled`改为`true`：

1. 为R3协议正式分配`0012`的含义；
2. 增加并核对`012.mp3`；
3. 将固件命令上限和音频数量同步扩展到12；
4. 修正R3播放队列满时覆盖已确认旧指令的问题；
5. 实机验证收到`0012\n`后返回`ACK\n`；
6. 最后同时设置`protocol_confirmed=true`和`enabled=true`。

不能把`0009`、`0010`或`0011`临时挪作低库存提醒，因为这些编号已经用于流感风险播报。

## 默认识别参数

- 绿色HSV：H 50–90、S ≥ 50、V ≥ 150；面积300–40000；阈值3个。
- 红色HSV：H 0–10或170–179、S ≥ 100、V 60–255；面积200–100000；阈值3个。
- 连续5帧均不足后确认低库存。
- 持续不足时，提醒事件最短间隔10秒。
- `debug`和`show_masks`默认关闭，减少正式运行开销。

## 测试

测试不会访问摄像头或串口：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
python3 -m unittest discover -s tests -v
```

## 能力限制

- 这是颜色和轮廓计数，不是药品身份鉴别。
- 光照变化、遮挡、目标粘连、相近背景颜色和摄像头位置变化会影响数量。
- 两个接触目标可能被视为一个轮廓。
- HSV与面积阈值必须在固定机位、固定照明和实际样品上标定。
- 提交前仍需进行摄像头、串口、ACK和长时间稳定性实机验收。
