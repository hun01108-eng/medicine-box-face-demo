# 药品余量视觉识别最小运行版

本目录只保留绿色/红色目标计数和低库存提醒所需文件：

```text
medicine_vision.py  全部运行源码
config.json         HSV、面积、数量、摄像头和串口配置
requirements.txt    可选串口依赖说明
README.md           运行说明
```

程序流程：

```text
Picamera2取帧 → HSV分割 → 形态学处理 → 轮廓面积筛选
→ 绿色/红色计数 → 连续5帧不足确认 → 画面提醒 → 可选串口通知
```

程序不保存图片、视频或日志，不处理药品名称和剂量。

## 依赖

Raspberry Pi OS优先使用系统软件包：

```bash
sudo apt update
sudo apt install -y python3-opencv python3-numpy python3-picamera2 python3-serial
```

## 运行

```bash
python3 medicine_vision.py --config config.json
```

预览窗口中按`q`退出，也可按`Ctrl+C`退出。

## 串口注意事项

当前R3固件只接受`0001`至`0011`，尚未支持低库存指令`0012\n`，所以`config.json`默认关闭串口。完成以下工作前不要启用：

1. 为R3增加`0012`协议和`012.mp3`；
2. 同步修改固件命令上限、音频数量和时长表；
3. 修正R3队列满时覆盖旧指令的问题；
4. 实机确认`0012\n`返回`ACK\n`；
5. 将`protocol_confirmed`和`enabled`同时设为`true`。

`0009`至`0011`已有流感风险含义，不能挪作低库存提醒。

## 能力限制

该程序依据颜色、轮廓和面积进行余量计数，不是药品身份鉴别。光照、遮挡、目标粘连、相近背景颜色和摄像头位置变化都可能影响结果，HSV和面积阈值必须在固定机位及实际样品上标定。
