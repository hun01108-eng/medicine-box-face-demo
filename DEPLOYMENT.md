# 树莓派第一阶段部署

目标：Raspberry Pi 4B 4GB，Debian 13 aarch64，OV5647。
基线：用户提供的 medicine-box-face-demo-main.zip，原 ZIP 保留在电脑。

## 存储

保留原 512MiB FAT32 启动分区及 28.4GiB ext4 根分区。
项目根目录为 /home/pi/medicine-box，releases/20260907-stage1 为本版本。
current 在硬件测试通过后指向本版本。
data、enrollment、logs、backups 与版本目录分离，目录权限 700。
本版本 data 和 enrollment 为链接；模板仍保存为 data/elder_001.json。
模型文件随版本保留，每版约 37MiB，配置备份到 backups。
独立 .venv 使用 --system-site-packages 复用系统 Picamera2、NumPy、OpenCV。

## 本版修正

- Picamera2 请求 RGB888，得到 OpenCV 使用的 BGR 字节顺序。
  参考：https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf
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

## 第二阶段实机验证（2026-09-10）

- 已在设备本地完成单人注册；临时原图在模板验证后删除，姓名、特征模板、
  原图和运行日志均不进入 Git。
- 本人连续 20 次识别全部为 MATCHED：P50 0.9367 秒、P95 1.2093 秒、
  最大 1.3313 秒，满足 3 秒目标。陌生人拒绝测试和阈值标定仍未完成。
- 新增持续 `monitor` 模式，在 VNC 桌面显示人脸框、中文身份、相似度和
  质量提示；当前帧不匹配时立即撤下之前显示的姓名，避免身份残留。
- 自动测试共 28 项并全部通过，中文字体内存渲染和 self-check 通过。
- 设备仍报告 `throttled=0x50005` 低电压/降频状态，长期测试前必须改善供电。
- 持续识别尚未配置开机自启，运行时不保存截图或视频。

启动持续预览：

```bash
cd /home/pi/medicine-box/current
PYTHONPATH=src .venv/bin/python -m facebox.app monitor --source picamera2
```

## 回退

当前没有旧部署版本。保留原 ZIP 及配置备份。
以后回退仅切换 current 到经过验证的旧版本，data 不随代码回退。
系统依赖安装不会由代码回退自动卸载，避免影响相机环境。
