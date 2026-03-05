#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台公告检查脚本 - 由 GitHub Actions 定时调用
数据源：巨潮资讯（cninfo.com.cn）- 免费，不限IP，无需Token
读取 stocks.json → 查询巨潮公告 → 发现新公告推送微信
"""

import os
import json
import hashlib
import requests
import base64
from datetime import datetime, timedelta
from time import sleep

# ── 从环境变量读取配置 ──
SENDKEY      = os.environ.get("SENDKEY", "")
SENDKEY2     = os.environ.get("SENDKEY2", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "panxiaochen001/Stock_monitor_01")

STOCKS_FILE  = "stocks.json"
CACHE_FILE   = "seen_cache.json"
CHECK_DAYS   = 2  # 查最近2天，避免跨天漏公告

CNINFO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Origin": "http://www.cninfo.com.cn",
}

# ─────────────────────────────────────────────
# GitHub 文件读写
# ─────────────────────────────────────────────
def github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

def read_github_file(filename):
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
        r = requests.get(url, headers=github_headers(), timeout=10)
        if r.status_code == 404:
            return None, ""
        if r.status_code == 200:
            data = r.json()
            decoded = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(decoded), data.get("sha", "")
    except Exception as e:
        print(f"❌ 读取 {filename} 失败：{e}")
    return None, ""

def write_github_file(filename, data, sha=""):
    try:
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
def send_wechat(title, content):
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
# 巨潮资讯接口
# ─────────────────────────────────────────────
def get_org_id(code):
    """通过股票代码获取巨潮 orgId 和股票名称"""
    pure_code = code.split(".")[0]
    try:
        r = requests.post(
            "http://www.cninfo.com.cn/new/information/topSearch/query",
            data={"keyWord": pure_code, "maxNum": 5},
            headers=CNINFO_HEADERS,
            timeout=10,
        )
        for item in r.json().get("keyBoardList", []):
            if item.get("code") == pure_code:
                return item.get("orgId", ""), item.get("zwjc", pure_code)
    except Exception as e:
        print(f"  {code} 获取orgId失败：{e}")
    return "", pure_code

def fetch_cninfo_announcements(stock):
    """查询单只股票的巨潮公告"""
    code      = stock["code"]
    pure_code = code.split(".")[0]
    market    = code.split(".")[1].lower() if "." in code else "sh"
    column    = "szse" if market == "sz" else "sse"

    org_id, name = get_org_id(code)
    if not org_id:
        print(f"  {code}：未找到 orgId，跳过")
        return []

    start_date = (datetime.now() - timedelta(days=CHECK_DAYS)).strftime("%Y-%m-%d")
    end_date   = datetime.now().strftime("%Y-%m-%d")

    try:
        r = requests.post(
            "http://www.cninfo.com.cn/new/hisAnnouncement/query",
            data={
                "stock":     f"{pure_code},{org_id}",
                "tabName":   "fulltext",
                "pageSize":  30,
                "pageNum":   1,
                "column":    column,
                "category":  "",
                "plate":     market,
                "seDate":    f"{start_date}~{end_date}",
                "searchkey": "",
                "isHLtitle": True,
            },
            headers=CNINFO_HEADERS,
            timeout=15,
        )
        anns   = r.json().get("announcements", [])
        result = []
        for ann in anns:
            aid   = str(ann.get("announcementId", ""))
            title = ann.get("announcementTitle", "").strip()
            ts    = ann.get("announcementTime", 0)
            try:
                t = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
            except Exception:
                t = str(ts)
            url = (f"http://www.cninfo.com.cn/new/announcement/detail?"
                   f"announcementId={aid}&orgId={org_id}")
            uid = hashlib.md5(f"{code}{aid}{title}".encode()).hexdigest()
            result.append({
                "id":    uid,
                "code":  code,
                "name":  name,
                "title": title,
                "time":  t,
                "url":   url,
            })
        print(f"  {code}（{name}）：找到 {len(result)} 条公告")
        return result
    except Exception as e:
        print(f"  {code} 查询公告失败：{e}")
        return []

def fetch_all_announcements(stocks):
    all_anns = []
    for stock in stocks:
        anns = fetch_cninfo_announcements(stock)
        all_anns.extend(anns)
        sleep(0.8)  # 礼貌性延迟，避免被封IP
    return all_anns

# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"🚀 开始检查公告 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📡 数据源：巨潮资讯（无需Token，不限IP）")
    print(f"{'='*50}")

    # 1. 读取股票列表
    stocks, _ = read_github_file(STOCKS_FILE)
    if not stocks:
        print("⚠️  stocks.json 为空，请先在 App 里添加股票")
        return

    print(f"📌 监控股票（{len(stocks)} 只）：{', '.join(s['name'] for s in stocks)}")

    # 2. 读取已见公告缓存
    cache, cache_sha = read_github_file(CACHE_FILE)
    if cache is None:
        cache = {}
    print(f"📦 已缓存公告数：{len(cache)}")

    # 3. 查询公告
    print("\n🔍 查询公告中...")
    all_anns = fetch_all_announcements(stocks)
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

    # 5. 推送微信 + 更新缓存
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
