#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信公众号周风险模板消息发送与防重复记录。

云端在周报成功入库后调用本模块。公众号凭据只从环境变量读取，不写入数据库、
日志或Git；相同 ``report_week + openid`` 已成功发送时默认跳过。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from database import get_wechat_push, save_wechat_push


TOKEN_API = "https://api.weixin.qq.com/cgi-bin/token"
MESSAGE_API = "https://api.weixin.qq.com/cgi-bin/message/template/send"


def request_json(
    url: str,
    operation: str,
    *,
    params: dict | None = None,
    payload: dict | None = None,
) -> dict:
    """调用HTTP JSON接口，并把网络或格式错误转换为可读异常。"""
    if params:
        url = f"{url}?{urlencode(params)}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url, data=data, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise RuntimeError(f"{operation}返回HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError(f"{operation}连接失败：{error.reason}") from error
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{operation}返回的不是JSON") from error


def build_message(config: dict, report: dict, openid: str | None = None) -> dict:
    """按照公众号模板字段组装一条周风险通知。"""
    message = {
        "touser": openid or config["openid"],
        "template_id": config["template_id"],
        "data": {
            "first": {"value": "本周流感风险监测结果已更新"},
            "report_week": {"value": str(report.get("report_week") or "未知")},
            "risk_level": {"value": f'{report.get("risk_level") or "未知"}风险'},
            "risk_reason": {
                "value": str(report.get("risk_reason") or "未触发风险规则")[:180]
            },
            "updated_at": {
                "value": str(
                    report.get("updated_at")
                    or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
            },
            "remark": {"value": "该结果仅作为公共卫生信息参考。"},
        },
    }
    if config.get("report_url"):
        message["url"] = config["report_url"]
    return message


def get_access_token(config: dict) -> str:
    """使用公众号AppID和AppSecret获取短期access_token。"""
    result = request_json(
        TOKEN_API,
        "微信access_token接口",
        params={
            "grant_type": "client_credential",
            "appid": config["app_id"],
            "secret": config["app_secret"],
        },
    )
    access_token = result.get("access_token")
    if not access_token:
        raise RuntimeError(
            f"获取access_token失败：{result.get('errcode')} {result.get('errmsg')}"
        )
    return access_token


def send_template_message(
    config: dict,
    report: dict,
    *,
    openid: str | None = None,
    access_token: str | None = None,
) -> dict:
    """发送一条模板消息，返回微信接口的原始成功结果。"""
    token = access_token or get_access_token(config)
    result = request_json(
        MESSAGE_API,
        "微信模板消息接口",
        params={"access_token": token},
        payload=build_message(config, report, openid),
    )
    if result.get("errcode") != 0:
        raise RuntimeError(
            f"微信发送失败：{result.get('errcode')} {result.get('errmsg')}"
        )
    return result


def config_from_environment() -> dict | None:
    """读取云端环境变量；配置不完整时关闭推送，不影响周报入库。"""
    app_id = os.getenv("WECHAT_APP_ID", "").strip()
    app_secret = os.getenv("WECHAT_APP_SECRET", "").strip()
    template_id = os.getenv("WECHAT_TEMPLATE_ID", "").strip()
    raw_openids = os.getenv("WECHAT_OPENIDS", os.getenv("WECHAT_OPENID", ""))
    openids = [value.strip() for value in raw_openids.split(",") if value.strip()]
    if not app_id or not app_secret or not template_id or not openids:
        return None
    return {
        "app_id": app_id,
        "app_secret": app_secret,
        "template_id": template_id,
        "openids": openids,
        "report_url": os.getenv("WECHAT_REPORT_URL", "").strip(),
    }


def push_weekly_report(report: dict, force: bool = False) -> dict:
    """向全部已配置用户推送一次；失败记录允许下次入库时重试。"""
    config = config_from_environment()
    if config is None:
        return {"status": "disabled", "reason": "wechat environment is incomplete"}

    results = []
    pending_openids = []
    for openid in config["openids"]:
        previous = get_wechat_push(report["report_week"], openid)
        if previous and previous["status"] == "success" and not force:
            results.append({"status": "skipped"})
        else:
            pending_openids.append(openid)

    if not pending_openids:
        return {"status": "completed", "results": results}

    try:
        token = get_access_token(config)
    except RuntimeError as error:
        for openid in pending_openids:
            save_wechat_push(
                report["report_week"],
                openid,
                report["risk_level"],
                "failed",
                error_message=str(error),
            )
            results.append({"status": "failed", "error": str(error)})
        return {"status": "completed", "results": results}

    for openid in pending_openids:
        try:
            response = send_template_message(
                config,
                report,
                openid=openid,
                access_token=token,
            )
            save_wechat_push(
                report["report_week"],
                openid,
                report["risk_level"],
                "success",
                message_id=response.get("msgid"),
            )
            results.append({"status": "success", "msgid": response.get("msgid")})
        except RuntimeError as error:
            save_wechat_push(
                report["report_week"],
                openid,
                report["risk_level"],
                "failed",
                error_message=str(error),
            )
            results.append({"status": "failed", "error": str(error)})
    return {"status": "completed", "results": results}
