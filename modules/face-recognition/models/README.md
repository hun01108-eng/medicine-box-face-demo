# 模型文件

本审核包不重复附带约37 MiB的ONNX模型。执行：

```bash
python3 scripts/download_models.py
```

脚本从OpenCV Zoo下载并校验：

- `face_detection_yunet_2023mar.onnx`
  - SHA-256：`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`
- `face_recognition_sface_2021dec.onnx`
  - SHA-256：`0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`

模型来源：OpenCV Zoo。模型许可证与再分发条件应以OpenCV Zoo对应目录中的最新说明为准。
