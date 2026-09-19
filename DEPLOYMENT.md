# 树莓派第一阶段部署

目标：Raspberry Pi 4B 4GB，Debian 13 aarch64，USB 摄像头。
基线：用户提供的 medicine-box-face-demo-main.zip，原 ZIP 保留在电脑。

## 存储

保留原 512MiB FAT32 启动分区及 28.4GiB ext4 根分区。
项目根目录为 /home/pi/medicine-box，releases/20260907-stage1 为本版本。
current 在硬件测试通过后指向本版本。
data、enrollment、logs、backups 与版本目录分离，目录权限 700。
本版本 data 和 enrollment 为链接；模板仍保存为 data/elder_001.json。
模型文件随版本保留，每版约 37MiB，配置备份到 backups。
独立 .venv 使用 --system-site-packages 复用系统 NumPy 和 OpenCV。

## 本版修正

- 默认通过 OpenCV VideoCapture 读取 `/dev/video0`；可在 `config.json` 修改
  `camera_device`，也可在命令行使用 `--device` 临时覆盖。
- 会话启动后，无脸帧也执行超时检查；无脸时清空旧匹配票数。
- 帧处理完成时间参与决策及耗时统计，避免漏计最后一次推理。
- 达到 3 秒时返回 timeout；没有出现过人脸则继续等待。
- 增加 6 个回归测试，总计 24 个。

计时从第一张带脸帧的处理开始，含该帧及最后一帧的推理时间，
不含摄像头启动、模型加载及第一帧之前的等待。
同步推理不是硬实时中断：一次推理可跨过截止时间，但完成后拒绝超时结果。
相机读取阻塞需由外层超时或未来服务监护处理。

## 使用

在树莓派终端执行：

```bash
cd /home/pi/medicine-box/current
.venv/bin/python scripts/facebox_logged.py simulate --case known
```

通过 facebox_logged.py 启动时日志自动轮转：单文件约 20MiB，保留 4 个备份，
合计约 100MiB；直接调用 facebox.app 仅输出终端，不自动记录。
一次性阶段测试日志单独保存，目前仅数 KB。

注册前 self-check 中 profile=false、ready=false 属预期。
本阶段没有创建真实人脸模板，没有保存相机图像，没有配置开机自启。
真实样本注册、误识率标定、20 次 P95 和长期运行均待下一阶段审批。

## 回退

当前没有旧部署版本。保留原 ZIP 及配置备份。
以后回退仅切换 current 到经过验证的旧版本，data 不随代码回退。
系统依赖安装不会由代码回退自动卸载，避免影响相机环境。
# 红外模块附加依赖

红外经过检测需要 `python3-serial`，并通过独立 USB 串口向 Uno 发送
`PERSON_IN\n`。部署前使用 `/dev/serial/by-id/` 记录红外模块和 Uno 的稳定
设备路径，避免把两个串口接反。红外运行日志放在共享的 `logs/` 目录，不应
提交到 Git。
