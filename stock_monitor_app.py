import streamlit as st
import requests
import hashlib
import time
import json
from datetime import datetime, timedelta
from time import sleep

st.set_page_config(page_title="股票公告监控", page_icon="📋", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap');
html,body,[class*="css"]{font-family:'Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif;}
.stApp{background:#0d1117;}
section[data-testid="stSidebar"]{background:#161b22;border-right:1px solid #21262d;}
.ann-card{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:16px 20px;margin-bottom:10px;}
.ann-card.new{border-left:3px solid #00d4ff;background:#0d1f33;}
.ann-title{font-size:14px;color:#e6edf3;font-weight:500;line-height:1.6;}
.ann-meta{font-size:12px;color:#7d8590;margin-top:6px;}
.badge-new{background:#00d4ff22;color:#00d4ff;border:1px solid #00d4ff44;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;}
.badge-code{background:#1f2937;color:#9ca3af;border:1px solid #374151;border-radius:4px;padding:2px 8px;font-size:11px;font-family:monospace;}
.stock-tag{display:inline-flex;align-items:center;gap:6px;background:#1f2937;border:1px solid #374151;border-radius:20px;padding:4px 12px;font-size:13px;color:#e6edf3;margin:3px;}
.dot-green{width:7px;height:7px;background:#00e676;border-radius:50%;display:inline-block;}
#MainMenu,footer,header{visibility:hidden;}
.stButton>button{background:linear-gradient(135deg,#00d4ff,#0066ff)!important;color:#000!important;border:none!important;border-radius:8px!important;font-weight:700!important;}
.stTextInput>div>div>input,.stTextArea>div>div>textarea{background:#0d1117!important;border:1px solid #30363d!important;color:#e6edf3!important;border-radius:8px!important;}
div[data-testid="stMetricValue"]{color:#00d4ff;}
.tip-box{background:#1a2744;border:1px solid #00d4ff33;border-radius:8px;padding:12px 16px;font-size:13px;color:#a0b4c8;margin-bottom:12px;}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 东方财富公告接口
# ─────────────────────────────────────────────
EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/notices/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

def fetch_eastmoney(stock: dict, days: int = 1) -> list:
    code  = stock["code"]
    pure  = code.split(".")[0]
    name  = stock.get("name", code)
    url   = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "sr": -1, "page_size": 50, "page_index": 1,
        "ann_type": "A", "client_source": "web",
        "stock_list": pure, "f_node": 0, "s_node": 0,
    }
    try:
        r      = requests.get(url, params=params, headers=EM_HEADERS, timeout=15)
        items  = r.json().get("data", {}).get("list", [])
        cutoff = datetime.now() - timedelta(days=days)
        result = []
        for item in items:
            t_str = item.get("notice_date", "") or item.get("create_time", "")
            try:
                t_dt = datetime.strptime(t_str[:10], "%Y-%m-%d")
            except Exception:
                t_dt = datetime.now()
            if t_dt < cutoff:
                continue
            title  = item.get("title", "").strip()
            ann_id = str(item.get("art_code", "") or item.get("notice_id", ""))
            art_url = f"https://data.eastmoney.com/notices/detail/{pure}/{ann_id}.html" if ann_id else ""
            uid = hashlib.md5(f"{code}{ann_id}{title}".encode()).hexdigest()
            result.append({"id": uid, "code": code, "name": name,
                           "title": title, "time": t_str[:16], "url": art_url})
        return result
    except Exception as e:
        st.warning(f"⚠️ {code} 查询失败：{e}")
        return []

def fetch_all(stocks: list, days: int = 1) -> list:
    all_anns = []
    for stock in stocks:
        all_anns.extend(fetch_eastmoney(stock, days))
        sleep(0.3)
    return all_anns

# ─────────────────────────────────────────────
# GitHub 持久化
# ─────────────────────────────────────────────
GITHUB_REPO = "panxiaochen001/Stock_monitor_01"
STOCKS_FILE = "stocks.json"

def _gh_headers(token):
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

def load_stocks_from_github(token: str) -> list:
    if not token: return []
    try:
        import base64
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STOCKS_FILE}"
        r = requests.get(url, headers=_gh_headers(token), timeout=10)
        if r.status_code == 200:
            return json.loads(base64.b64decode(r.json()["content"]).decode("utf-8"))
    except Exception as e:
        st.warning(f"⚠️ 读取股票列表失败：{e}")
    return []

def save_stocks_to_github(token: str, stocks: list) -> bool:
    if not token: return False
    try:
        import base64
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STOCKS_FILE}"
        r   = requests.get(url, headers=_gh_headers(token), timeout=10)
        sha = r.json().get("sha", "") if r.status_code == 200 else ""
        content_b64 = base64.b64encode(
            json.dumps(stocks, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")
        payload = {"message": f"update stocks {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                   "content": content_b64}
        if sha: payload["sha"] = sha
        resp = requests.put(url, headers=_gh_headers(token), json=payload, timeout=15)
        return resp.status_code in (200, 201)
    except Exception as e:
        st.warning(f"⚠️ 保存失败：{e}")
        return False

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────
def load_cache():
    if "seen_cache" not in st.session_state:
        st.session_state.seen_cache = {}
    return st.session_state.seen_cache

def save_cache(cache): st.session_state.seen_cache = cache

def send_wechat(sendkeys, title, content):
    if not sendkeys: return 0, 0
    keys = [k.strip() for k in sendkeys.replace("\n",",").split(",") if k.strip()]
    ok_n, fail_n = 0, 0
    for key in keys:
        try:
            r   = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                                data={"title": title, "desp": content}, timeout=10)
            res = r.json()
            if res.get("data",{}).get("errno",-1)==0 or res.get("code")==0: ok_n += 1
            else: fail_n += 1
        except Exception: fail_n += 1
    return ok_n, fail_n

def build_wechat_content(anns):
    lines = ["# 📋 持仓股票新公告提醒\n"]
    for a in anns:
        lines.append(f"## {a['name']}（{a['code']}）\n**{a['title']}**\n⏰ {a['time']}")
        if a.get("url"): lines.append(f"[🔗 查看原文]({a['url']})")
        lines.append("---")
    lines.append(f"\n*检查时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    return "\n\n".join(lines)

def _is_chinese(s): return any("\u4e00" <= c <= "\u9fff" for c in s)
def _is_code(s):
    s = s.strip()
    return (s.isdigit() and len(s)==6) or ("." in s and s.split(".")[-1].upper() in ("SH","SZ"))

def search_stock_by_name_em(name: str) -> dict:
    """用东方财富搜索接口，中文名转股票代码"""
    try:
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {"input": name, "type": "14", "token": "D43BF722C8E33BDC906FB84D85E326278B14A8B0", "count": 5}
        r = requests.get(url, params=params, headers=EM_HEADERS, timeout=8)
        items = r.json().get("QuotationCodeTable", {}).get("Data", [])
        if items:
            item = items[0]
            raw  = item.get("Code", "")
            mkt  = item.get("MktNum", "0")
            suffix = "SH" if str(mkt) == "1" else "SZ"
            return {"code": f"{raw}.{suffix}", "name": item.get("Name", name)}
    except Exception:
        pass
    return None

def parse_stock_input(raw: str) -> list:
    result, seen = [], set()
    raw_clean = raw.replace("，",",").replace("；","\n").replace(";","\n").replace("、","\n")
    tokens = []
    for line in raw_clean.splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        for part in line.split(","):
            part = part.strip()
            if part: tokens.append(part)
    for token in tokens:
        words = token.split()
        for i, word in enumerate(words):
            word = word.strip()
            if not word: continue
            if "." in word and word.split(".")[-1].upper() in ("SH","SZ"):
                code = word.upper()
                name = words[i+1] if i+1<len(words) and not _is_code(words[i+1]) else code
                if code not in seen: seen.add(code); result.append({"code":code,"name":name})
            elif word.isdigit() and len(word)==6:
                suffix = "SH" if word.startswith("6") else "SZ"
                code   = f"{word}.{suffix}"
                name   = words[i+1] if i+1<len(words) and not _is_code(words[i+1]) else code
                if code not in seen: seen.add(code); result.append({"code":code,"name":name})
            elif _is_chinese(word):
                matched = search_stock_by_name_em(word)
                if matched and matched["code"] not in seen:
                    seen.add(matched["code"]); result.append(matched)
                elif not matched:
                    if "_unresolved" not in st.session_state: st.session_state["_unresolved"] = []
                    st.session_state["_unresolved"].append(word)
    return result

# ─────────────────────────────────────────────
# Session State 初始化
# ─────────────────────────────────────────────
for k, v in {
    "watch_stocks":  [], "announcements": [], "new_ids": set(),
    "last_check":    None, "total_new": 0, "check_days": 1,
    "ann_type_filter": "全部", "push_log": [], "stocks_loaded": False,
}.items():
    if k not in st.session_state: st.session_state[k] = v

if not st.session_state.stocks_loaded:
    try:    _gh_token = st.secrets.get("GITHUB_TOKEN", "")
    except: _gh_token = ""
    if _gh_token:
        _saved = load_stocks_from_github(_gh_token)
        if _saved: st.session_state.watch_stocks = _saved
    st.session_state.stocks_loaded = True

# ─────────────────────────────────────────────
# 检查公告
# ─────────────────────────────────────────────
def do_check(sendkey=""):
    if not st.session_state.watch_stocks:
        st.warning("请先添加要监控的股票"); return 0
    anns  = fetch_all(st.session_state.watch_stocks, days=st.session_state.check_days)
    cache = load_cache()
    new_anns, new_ids = [], set()
    for ann in anns:
        aid = str(ann["id"])
        if aid not in cache:
            new_ids.add(aid); new_anns.append(ann)
            cache[aid] = {"title": ann["title"], "seen_at": datetime.now().isoformat()}
    save_cache(cache)
    st.session_state.announcements = anns
    st.session_state.new_ids       = new_ids
    st.session_state.last_check    = datetime.now()
    st.session_state.total_new    += len(new_ids)
    if new_anns and sendkey:
        title = f"📋 {len(new_anns)} 条新公告｜{', '.join(set(a['name'] for a in new_anns))}"
        ok_n, fail_n = send_wechat(sendkey, title, build_wechat_content(new_anns))
        st.session_state.push_log.append(
            f"[{datetime.now().strftime('%H:%M:%S')}] 推送{len(new_anns)}条 · {ok_n}/{ok_n+fail_n}成功")
    return len(new_ids)

# ═══════════════════════════════════════════════
# 侧边栏
# ═══════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 📋 股票公告监控")
    st.markdown("---")

    try:
        default_sendkey  = st.secrets.get("SENDKEY", "")
        default_sendkey2 = st.secrets.get("SENDKEY2", "")
        gh_token         = st.secrets.get("GITHUB_TOKEN", "")
    except:
        default_sendkey = default_sendkey2 = gh_token = ""

    st.markdown("### 📱 微信推送")
    st.markdown('<small style="color:#7d8590">👉 <a href="https://sct.ftqq.com" target="_blank" style="color:#00d4ff">获取免费 SendKey</a></small>', unsafe_allow_html=True)
    sendkey  = st.text_input("微信1 SendKey", type="password", value=default_sendkey,  placeholder="SCT开头")
    sendkey2 = st.text_input("微信2 SendKey（可选）", type="password", value=default_sendkey2, placeholder="留空跳过")
    all_sendkeys = ",".join(k for k in [sendkey, sendkey2] if k.strip())

    if all_sendkeys:
        if st.button("🧪 测试推送", use_container_width=True):
            ok_n, fail_n = send_wechat(all_sendkeys, "✅ 股票监控测试", "推送成功！有新公告会自动通知你 📋")
            if ok_n == ok_n + fail_n: st.success(f"✅ {ok_n} 个微信推送成功！")
            elif ok_n > 0:            st.warning(f"⚠️ {ok_n} 成功 {fail_n} 失败")
            else:                     st.error("❌ 失败，检查 SendKey 是否正确")

    st.markdown("---")
    st.markdown("### ➕ 批量输入股票")
    st.markdown("""<div class="tip-box">
    支持以下格式（每行一个，逗号分隔均可）：<br>
    <code>生益科技</code> ← 中文名直接搜 ✅<br>
    <code>600036.SH 招商银行</code><br>
    <code>000858 五粮液</code><br>
    <code>600036,000858,300750</code>
    </div>""", unsafe_allow_html=True)

    batch_input = st.text_area("", height=130,
        placeholder="600036.SH 招商银行\n000858.SZ 五粮液\n生益科技",
        label_visibility="collapsed")

    if st.button("✅ 确认添加", use_container_width=True):
        if batch_input.strip():
            st.session_state["_unresolved"] = []
            parsed = parse_stock_input(batch_input)
            added, skipped = 0, 0
            for s in parsed:
                if not any(x["code"]==s["code"] for x in st.session_state.watch_stocks):
                    st.session_state.watch_stocks.append(s); added += 1
                else: skipped += 1
            if added:
                if gh_token: save_stocks_to_github(gh_token, st.session_state.watch_stocks)
                msg = f"✅ 成功添加 {added} 只！"
                if skipped: msg += f"（{skipped} 只已存在跳过）"
                st.success(msg); st.rerun()
            elif skipped: st.info(f"ℹ️ {skipped} 只已在列表中")
            unresolved = st.session_state.get("_unresolved", [])
            if unresolved: st.warning(f"⚠️ 未识别，请改用代码：**{'、'.join(unresolved)}**")
        else: st.warning("请先输入内容")

    if st.button("🗑 清空全部股票", use_container_width=True):
        st.session_state.watch_stocks = []
        if gh_token: save_stocks_to_github(gh_token, [])
        st.rerun()

    if st.session_state.watch_stocks:
        st.markdown("---")
        st.markdown(f"### 📌 监控中（{len(st.session_state.watch_stocks)} 只）")
        for i, s in enumerate(st.session_state.watch_stocks):
            c1, c2 = st.columns([4,1])
            with c1:
                st.markdown(f'<span class="stock-tag"><span class="dot-green"></span>{s["name"]} '
                            f'<span style="color:#7d8590;font-size:11px">{s["code"]}</span></span>',
                            unsafe_allow_html=True)
            with c2:
                if st.button("×", key=f"del_{i}"):
                    st.session_state.watch_stocks.pop(i)
                    if gh_token: save_stocks_to_github(gh_token, st.session_state.watch_stocks)
                    st.rerun()

    st.markdown("---")
    st.session_state.check_days = st.selectbox("查询最近几天", [1,3,7,14,30])

# ═══════════════════════════════════════════════
# 主界面
# ═══════════════════════════════════════════════
st.markdown('<h1 style="color:#e6edf3;font-size:26px;font-weight:800;margin-bottom:4px;">📋 股票公告实时监控</h1>'
            '<p style="color:#7d8590;font-size:13px;margin-top:0;">数据源：东方财富 · 微信实时推送</p>',
            unsafe_allow_html=True)

c1,c2,c3,c4 = st.columns(4)
with c1: st.metric("监控股票", f"{len(st.session_state.watch_stocks)} 只")
with c2: st.metric("本次公告", f"{len(st.session_state.announcements)} 条")
with c3: st.metric("新增公告", f"{len(st.session_state.new_ids)} 条",
                   delta=f"+{len(st.session_state.new_ids)}" if st.session_state.new_ids else None)
with c4: st.metric("最后检查", st.session_state.last_check.strftime("%H:%M:%S") if st.session_state.last_check else "—")

st.markdown("---")

b1,b2,b3,_ = st.columns([2,2,2,4])
with b1:
    if st.button("🔍 立即检查公告", use_container_width=True):
        with st.spinner("查询中..."): n = do_check(all_sendkeys)
        if n > 0: st.success(f"🎉 {n} 条新公告！{'已推送微信 📱' if all_sendkeys else ''}")
        else:     st.info("✅ 暂无新公告")
        st.rerun()
with b2:
    auto_refresh = st.toggle("⏱ 每1分钟自动刷新", value=False)
with b3:
    if st.button("🗑 清空公告记录", use_container_width=True):
        st.session_state.announcements = []; st.session_state.new_ids = set(); st.rerun()

if auto_refresh:
    last    = st.session_state.last_check
    elapsed = (datetime.now()-last).seconds if last else 9999
    if elapsed >= 60:
        with st.spinner("🔄 自动检查中..."): do_check(all_sendkeys)
        st.rerun()
    else:
        st.info(f"⏳ 下次自动检查：{60-elapsed} 秒后")
        time.sleep(min(60-elapsed, 5)); st.rerun()

if st.session_state.push_log:
    with st.expander("📬 推送日志"):
        for log in reversed(st.session_state.push_log[-10:]):
            st.markdown(f'<small style="color:#7d8590">{log}</small>', unsafe_allow_html=True)

st.markdown("---")
ANN_TYPES = ["全部","定期报告","业绩预告","业绩快报","重大事项","股权变动","增减持","分红"]
st.session_state.ann_type_filter = st.radio("", ANN_TYPES, horizontal=True, label_visibility="collapsed")

anns = st.session_state.announcements
if st.session_state.ann_type_filter != "全部":
    anns = [a for a in anns if st.session_state.ann_type_filter in a["title"]]

if not anns:
    st.markdown('<div style="text-align:center;padding:60px;color:#7d8590;background:#161b22;'
                'border-radius:12px;border:1px solid #21262d;">'
                '<div style="font-size:40px;margin-bottom:12px;">📭</div>'
                '<div style="font-size:15px;">点击「立即检查」获取公告数据</div></div>',
                unsafe_allow_html=True)
else:
    for ann in anns:
        is_new   = str(ann["id"]) in st.session_state.new_ids
        card_cls = "ann-card new" if is_new else "ann-card"
        badge    = '<span class="badge-new">NEW</span>&nbsp;' if is_new else ""
        url_part = f'<a href="{ann["url"]}" target="_blank" style="color:#00d4ff;font-size:12px;">🔗 查看原文</a>' if ann.get("url") else ""
        st.markdown(
            f'<div class="{card_cls}">'
            f'<div style="margin-bottom:6px;"><b style="color:#e6edf3;font-size:14px;">{ann["name"]}</b>&nbsp;'
            f'<span class="badge-code">{ann["code"]}</span>&nbsp;{badge}</div>'
            f'<div class="ann-title">{ann["title"]}</div>'
            f'<div class="ann-meta">⏰ {ann["time"]} &nbsp;·&nbsp; {url_part}</div>'
            f'</div>', unsafe_allow_html=True)

st.markdown('<p style="color:#7d8590;font-size:12px;text-align:center;margin-top:20px;">仅供参考，不构成投资建议</p>',
            unsafe_allow_html=True)
