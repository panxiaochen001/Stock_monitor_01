#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台公告检查脚本 - 由 GitHub Actions 定时调用
读取 stocks.json → 查询 Tushare 公告 → 发现新公告推送微信
所有配置通过环境变量传入（在 GitHub Secrets 里设置）
"""

import os
import json
import hashlib
import requests
from datetime import datetime, timedelta

# ── 从环境变量读取配置（GitHub Actions Secrets）──
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
SENDKEY       = os.environ.get("SENDKEY", "")
SENDKEY2      = os.environ.get("SENDKEY2", "")
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO   = os.environ.get("GITHUB_REPO", "panxiaochen001/Stock_monitor_01")

STOCKS_FILE   = "stocks.json"
CACHE_FILE    = "seen_cache.json"
CHECK_DAYS    = 1  # 查最近1天的公告

# ─────────────────────────────────────────────
# GitHub 文件读写
# ─────────────────────────────────────────────
def github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

def read_github_file(filename: str) -> tuple:
    """读取 GitHub 文件，返回 (内容, sha)"""
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
        r = requests.get(url, headers=github_headers(), timeout=10)
        if r.status_code == 404:
            return None, ""
        if r.status_code == 200:
            import base64
            data = r.json()
            decoded = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(decoded), data.get("sha", "")
    except Exception as e:
        print(f"❌ 读取 {filename} 失败：{e}")
    return None, ""

def write_github_file(filename: str, data, sha: str = "") -> bool:
    """写入 GitHub 文件"""
    try:
        import base64
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
        content_b64 = base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")
        payload = {
            "message": f"auto update {filename} {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "content": content_b64,
        }
        if sha:
            payload["sha"] = sha
        resp = requests.put(url, headers=github_headers(), json=payload, timeout=15)
        return resp.status_code in (200, 201)
    except Exception as e:
        print(f"❌ 写入 {filename} 失败：{e}")
        return False

# ─────────────────────────────────────────────
# 微信推送
# ─────────────────────────────────────────────
def send_wechat(title: str, content: str):
    """同时推送给多个微信"""
    keys = [k.strip() for k in [SENDKEY, SENDKEY2] if k.strip()]
    if not keys:
        print("⚠️  未配置 SendKey，跳过微信推送")
        return
    for key in keys:
        try:
            r = requests.post(
                f"https://sctapi.ftqq.com/{key}.send",
                data={"title": title, "desp": content},
                timeout=10,
            )
            res = r.json()
            ok = res.get("data", {}).get("errno", -1) == 0 or res.get("code") == 0
            print(f"  微信推送 {'✅ 成功' if ok else '❌ 失败'} (key: {key[:8]}...)")
        except Exception as e:
            print(f"  微信推送异常：{e}")

def build_wechat_content(anns: list) -> str:
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
# Tushare 公告查询
# ─────────────────────────────────────────────
def fetch_announcements(stock_codes: list) -> list:
    if not TUSHARE_TOKEN:
        print("❌ 未配置 TUSHARE_TOKEN")
        return []
    try:
        import tushare as ts
        pro = ts.pro_api(TUSHARE_TOKEN)
    except ImportError:
        print("❌ 请安装 tushare: pip install tushare")
        return []
    except Exception as e:
        print(f"❌ Tushare 初始化失败：{e}")
        return []

    announcements = []
    start_date = (datetime.now() - timedelta(days=CHECK_DAYS)).strftime("%Y%m%d")
    end_date   = datetime.now().strftime("%Y%m%d")

    for code in stock_codes:
        try:
            df = pro.anns_d(ts_code=code, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                print(f"  {code}：无公告")
                continue
            for _, row in df.iterrows():
                uid = hashlib.md5(
                    f"{row.get('ts_code','')}{row.get('ann_date','')}{row.get('title','')}".encode()
                ).hexdigest()
                announcements.append({
                    "id":    uid,
                    "code":  row.get("ts_code", code),
                    "name":  row.get("name", code),
                    "title": row.get("title", ""),
                    "time":  row.get("rec_time") or row.get("ann_date", ""),
                    "url":   row.get("url", ""),
                })
            print(f"  {code}：找到 {len(df)} 条公告")
        except Exception as e:
            print(f"  {code} 查询失败：{e}")

    return announcements

# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"🚀 开始检查公告 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    # 1. 读取股票列表
    stocks, _ = read_github_file(STOCKS_FILE)
    if not stocks:
        print("⚠️  stocks.json 为空或不存在，请先在 App 里添加股票")
        return

    codes = [s["code"] for s in stocks]
    print(f"📌 监控股票（{len(codes)} 只）：{', '.join(s['name'] for s in stocks)}")

    # 2. 读取已见公告缓存
    cache, cache_sha = read_github_file(CACHE_FILE)
    if cache is None:
        cache = {}
    print(f"📦 已缓存公告数：{len(cache)}")

    # 3. 查询公告
    print("\n🔍 查询公告中...")
    all_anns = fetch_announcements(codes)
    print(f"\n共获取 {len(all_anns)} 条公告")

    # 4. 找出新公告
    new_anns = []
    for ann in all_anns:
        aid = str(ann["id"])
        if aid not in cache:
            new_anns.append(ann)
            cache[aid] = {
                "title":   ann["title"],
                "seen_at": datetime.now().isoformat(),
            }

    print(f"🔔 新公告：{len(new_anns)} 条")

    # 5. 推送微信
    if new_anns:
        print("\n📱 推送微信...")
        for ann in new_anns:
            print(f"  · {ann['name']} - {ann['title']}")
        title   = f"📋 {len(new_anns)} 条新公告｜{', '.join(set(a['name'] for a in new_anns))}"
        content = build_wechat_content(new_anns)
        send_wechat(title, content)

        # 6. 更新缓存到 GitHub
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
