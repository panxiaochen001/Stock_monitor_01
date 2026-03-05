#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台公告检查脚本 - 由 GitHub Actions 定时调用
数据源：东方财富（data.eastmoney.com）- 免费，HTTPS，对海外IP友好
"""

import os
import json
import hashlib
import requests
import base64
from datetime import datetime, timedelta
from time import sleep

SENDKEY      = os.environ.get("SENDKEY", "")
SENDKEY2     = os.environ.get("SENDKEY2", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "panxiaochen001/Stock_monitor_01")

STOCKS_FILE  = "stocks.json"
CACHE_FILE   = "seen_cache.json"
CHECK_DAYS   = 2

EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/notices/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

# ─────────────────────────────────────────────
# GitHub 读写
# ─────────────────────────────────────────────
def github_headers():
    return {"Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"}

def read_github_file(filename):
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
        r = requests.get(url, headers=github_headers(), timeout=10)
        if r.status_code == 404:
            return None, ""
        if r.status_code == 200:
            data = r.json()
            return json.loads(base64.b64decode(data["content"]).decode("utf-8")), data.get("sha","")
    except Exception as e:
        print(f"❌ 读取 {filename} 失败：{e}")
    return None, ""

def write_github_file(filename, data, sha=""):
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
        content_b64 = base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")
        payload = {"message": f"auto update {filename} {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                   "content": content_b64}
        if sha: payload["sha"] = sha
        resp = requests.put(url, headers=github_headers(), json=payload, timeout=15)
        return resp.status_code in (200, 201)
    except Exception as e:
        print(f"❌ 写入 {filename} 失败：{e}")
        return False

# ─────────────────────────────────────────────
# 微信推送
# ─────────────────────────────────────────────
def send_wechat(title, content):
    keys = [k.strip() for k in [SENDKEY, SENDKEY2] if k.strip()]
    if not keys:
        print("⚠️  未配置 SendKey，跳过推送")
        return
    for key in keys:
        try:
            r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                              data={"title": title, "desp": content}, timeout=10)
            res = r.json()
            ok = res.get("data", {}).get("errno", -1) == 0 or res.get("code") == 0
            print(f"  微信推送 {'✅ 成功' if ok else '❌ 失败'} (key:{key[:8]}...)")
        except Exception as e:
            print(f"  推送异常：{e}")

def build_wechat_content(anns):
    lines = ["# 📋 持仓股票新公告提醒\n"]
    for a in anns:
        lines.append(f"## {a['name']}（{a['code']}）")
        lines.append(f"**{a['title']}**")
        lines.append(f"⏰ {a['time']}")
        if a.get("url"):
            lines.append(f"[🔗 查看原文]({a['url']})")
        lines.append("---")
    lines.append(f"\n*检查时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    return "\n\n".join(lines)

# ─────────────────────────────────────────────
# 东方财富公告接口
# ─────────────────────────────────────────────
def code_to_secid(code: str) -> str:
    """600036.SH → 1.600036，000858.SZ → 0.000858"""
    pure  = code.split(".")[0]
    mkt   = code.split(".")[1].upper() if "." in code else "SH"
    return f"1.{pure}" if mkt == "SH" else f"0.{pure}"

def fetch_eastmoney(stock: dict) -> list:
    """调用东方财富公告接口"""
    code   = stock["code"]
    secid  = code_to_secid(code)
    pure   = code.split(".")[0]
    name   = stock.get("name", code)

    # 东方财富公告接口
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "sr":       -1,
        "page_size": 50,
        "page_index": 1,
        "ann_type": "A",      # A=全部公告
        "client_source": "web",
        "stock_list": pure,
        "f_node":   0,
        "s_node":   0,
    }
    try:
        r = requests.get(url, params=params, headers=EM_HEADERS, timeout=15)
        data = r.json()
        items = data.get("data", {}).get("list", [])
        if not items:
            print(f"  {code}（{name}）：无公告")
            return []

        cutoff = datetime.now() - timedelta(days=CHECK_DAYS)
        result = []
        for item in items:
            # 公告时间
            ann_time_str = item.get("notice_date", "") or item.get("create_time", "")
            try:
                ann_time = datetime.strptime(ann_time_str[:10], "%Y-%m-%d")
            except Exception:
                ann_time = datetime.now()
            if ann_time < cutoff:
                continue

            title  = item.get("title", "").strip()
            ann_id = str(item.get("art_code", "") or item.get("notice_id", ""))
            # 原文链接
            art_url = f"https://data.eastmoney.com/notices/detail/{pure}/{ann_id}.html" if ann_id else ""
            uid = hashlib.md5(f"{code}{ann_id}{title}".encode()).hexdigest()
            result.append({
                "id":    uid,
                "code":  code,
                "name":  name,
                "title": title,
                "time":  ann_time_str[:16],
                "url":   art_url,
            })
        print(f"  {code}（{name}）：找到 {len(result)} 条公告")
        return result
    except Exception as e:
        print(f"  {code} 查询失败：{e}")
        return []

def fetch_all(stocks):
    all_anns = []
    for stock in stocks:
        all_anns.extend(fetch_eastmoney(stock))
        sleep(0.5)
    return all_anns

# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"🚀 开始检查公告 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📡 数据源：东方财富（无需Token，HTTPS）")
    print(f"{'='*50}")

    stocks, _ = read_github_file(STOCKS_FILE)
    if not stocks:
        print("⚠️  stocks.json 为空，请先在 App 里添加股票")
        return
    print(f"📌 监控股票（{len(stocks)} 只）：{', '.join(s['name'] for s in stocks)}")

    cache, cache_sha = read_github_file(CACHE_FILE)
    if cache is None:
        cache = {}
    print(f"📦 已缓存公告数：{len(cache)}")

    print("\n🔍 查询公告中...")
    all_anns = fetch_all(stocks)
    print(f"\n共获取 {len(all_anns)} 条公告")

    new_anns = []
    for ann in all_anns:
        aid = str(ann["id"])
        if aid not in cache:
            new_anns.append(ann)
            cache[aid] = {"title": ann["title"], "seen_at": datetime.now().isoformat()}

    print(f"🔔 新公告：{len(new_anns)} 条")

    if new_anns:
        print("\n📱 推送微信...")
        for ann in new_anns:
            print(f"  · {ann['name']} - {ann['title']}")
        title = f"📋 {len(new_anns)} 条新公告｜{', '.join(set(a['name'] for a in new_anns))}"
        send_wechat(title, build_wechat_content(new_anns))
        print("\n💾 更新缓存...")
        ok = write_github_file(CACHE_FILE, cache, cache_sha)
        print(f"  缓存更新 {'✅ 成功' if ok else '❌ 失败'}")
    else:
        print("✅ 暂无新公告，无需推送")

    print(f"\n{'='*50}")
    print("✅ 检查完成")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
