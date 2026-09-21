#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能药箱 - 流感预警声光模块（增强版）
支持两种模式：debug（终端打印）和 real（串口控制 Arduino）
"""

import requests
import time
import argparse
import sys

API_URL = "http://127.0.0.1:5000/api/flu/alert"

# 阈值（用于显示，实际判断在 API 端）
SOUTH_THRESHOLD = 15.0
NORTH_THRESHOLD = 10.0


# ==================== 硬件控制（实际模式）====================
def init_serial(port="COM3", baudrate=9600):
    try:
        import serial
        ser = serial.Serial(port, baudrate, timeout=2)
        time.sleep(2)
        return ser
    except Exception as e:
        print(f"⚠️ 串口初始化失败: {e}")
        return None

def send_to_arduino(ser, command):
    if ser is None:
        return
    try:
        ser.write((command + "\n").encode())
        print(f"   📤 已发送: {command}")
    except Exception as e:
        print(f"   ❌ 发送失败: {e}")


def buzzer_on(mode, ser=None):
    if mode == "debug":
        print("   🔔 [调试] 蜂鸣器: 响")
    else:
        send_to_arduino(ser, "BUZZER_ON")

def buzzer_off(mode, ser=None):
    if mode == "debug":
        print("   🔕 [调试] 蜂鸣器: 关")
    else:
        send_to_arduino(ser, "BUZZER_OFF")

def led_on(mode, ser=None):
    if mode == "debug":
        print("   💡 [调试] LED: 亮")
    else:
        send_to_arduino(ser, "LED_ON")

def led_off(mode, ser=None):
    if mode == "debug":
        print("   💤 [调试] LED: 灭")
    else:
        send_to_arduino(ser, "LED_OFF")


def trigger_alert(mode, ser=None):
    print("\n🚨 === 触发预警（声光）===")
    for i in range(3):
        print(f"  第 {i+1} 次")
        buzzer_on(mode, ser)
        led_on(mode, ser)
        time.sleep(0.3)
        buzzer_off(mode, ser)
        led_off(mode, ser)
        time.sleep(0.2)
    print("   ✅ 预警信号已发送")
    print("========================")


def check_flu_alert(mode="debug", port="COM3"):
    ser = None
    if mode == "real":
        print("🔌 尝试连接 Arduino...")
        ser = init_serial(port)
        if ser is None:
            print("⚠️ 串口连接失败，自动切换到调试模式")
            mode = "debug"
        else:
            print("✅ 串口连接成功")

    print(f"📋 当前模式: {'实际模式（串口→UNO）' if mode == 'real' else '调试模式（打印信号）'}")
    print("-" * 40)

    try:
        resp = requests.get(API_URL, timeout=10)
        data = resp.json()
        if data.get('status') != 'success':
            print("❌ API返回异常")
            return

        alert = data.get('alert', {})
        flu_data = data.get('data', {})

        print(f"📊 最新数据（{flu_data.get('report_week')}）")
        print(f"   南方趋势: {flu_data.get('south_trend', '未知')}")
        print(f"   北方趋势: {flu_data.get('north_trend', '未知')}")
        print(f"   暴发疫情: {flu_data.get('outbreak_status', '未知')}")
        if flu_data.get('h3n2_antigen_ratio'):
            print(f"   H3N2抗原类似株: {flu_data['h3n2_antigen_ratio']}%")
        if flu_data.get('h1n1_antigen_ratio'):
            print(f"   H1N1抗原类似株: {flu_data['h1n1_antigen_ratio']}%")
        if flu_data.get('b_antigen_ratio'):
            print(f"   B/Victoria抗原类似株: {flu_data['b_antigen_ratio']}%")
        if flu_data.get('h3n2_resistance_ratio'):
            print(f"   H3N2耐药性降低: {flu_data['h3n2_resistance_ratio']}%")

        print("-" * 40)
        level = alert.get('level', 'normal')
        message = alert.get('message', '')
        details = alert.get('details', {})

        if level != "normal":
            print(f"🚨 预警触发！级别: {level}")
            print(f"📢 提醒内容: {message}")
            if details.get('dominant_type'):
                print(f"   🦠 主要流行株: {details['dominant_type']}")
            trigger_alert(mode, ser)
        else:
            print("✅ 流感活动水平正常，无需预警")
    except requests.exceptions.RequestException as e:
        print(f"❌ 网络请求失败: {e}")
        print("   请确认 Flask 服务已启动: python app.py")
    except Exception as e:
        print(f"❌ 错误: {e}")
    finally:
        if ser:
            ser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="智能药箱 - 流感预警声光模块")
    parser.add_argument("--mode", choices=["debug", "real"], default="debug", help="运行模式")
    parser.add_argument("--port", default="COM3", help="Arduino串口号")
    args = parser.parse_args()

    print("🩺 智能药箱 - 流感预警声光模块")
    print(f"   运行时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    check_flu_alert(mode=args.mode, port=args.port)
