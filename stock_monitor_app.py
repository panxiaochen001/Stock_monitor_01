import streamlit as st
import requests
import hashlib
import time
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
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
.ann-link{font-size:12px;color:#00d4ff;text-decoration:none;}
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
# 工具函数
# ─────────────────────────────────────────────
def load_cache():
    if "seen_cache" not in st.session_state:
        st.session_state.seen_cache = {}
    return st.session_state.seen_cache

def save_cache(cache):
    st.session_state.seen_cache = cache

def send_wechat(sendkey, title, content):
    if not sendkey: return False
    try:
        r = requests.post(f"https://sctapi.ftqq.com/{sendkey}.send",
                          data={"title": title, "desp": content}, timeout=10)
        res = r.json()
        return res.get("data", {}).get("errno", -1) == 0 or res.get("code") == 0
    except Exception:
        return False

def build_wechat_content(anns):
    lines = ["# 📋 持仓股票新公告提醒\n"]
    for a in anns:
        lines.append(f"## {a['name']}（{a['code']}）\n**{a['title']}**\n⏰ {a['time']}")
        if a.get("url"):
            lines.append(f"[🔗 查看原文]({a['url']})")
        lines.append("---")
    lines.append(f"\n*检查时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    return "\n\n".join(lines)

def parse_stock_input(raw: str, token: str = "") -> list:
    """
    解析批量输入，支持：
    - 数字代码：600036.SH / 600036 / 000858
    - 代码+名称：600036.SH 招商银行
    - 逗号分隔：600036,000858,300750
    - 纯中文名称：生益科技、生益电子（通过 Tushare 本地对照表匹配）
    返回 [{"code": "600036.SH", "name": "招商银行"}, ...]
    """
    result = []
    seen   = set()

    # 扁平化：把所有内容按行+逗号拆开，每个 token 单独处理
    raw_clean = raw.replace("，", ",").replace("；", "\n").replace(";", "\n").replace("、", "\n")
    tokens = []
    for line in raw_clean.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for part in line.split(","):
            part = part.strip()
            if part:
                tokens.append(part)

    i = 0
    while i < len(tokens):
        token = tokens[i]
        words = token.split()  # 处理 "600036 招商银行" 这种空格分隔

        for w_idx, word in enumerate(words):
            word = word.strip()
            if not word:
                continue

            # ── 情况1：带后缀代码，如 600036.SH ──
            if "." in word and word.split(".")[-1].upper() in ("SH", "SZ"):
                code = word.upper()
                # 看下一个词是否是名称
                name = word
                if w_idx + 1 < len(words) and not _is_code(words[w_idx + 1]):
                    name = words[w_idx + 1]
                if code not in seen:
                    seen.add(code)
                    result.append({"code": code, "name": name})

            # ── 情况2：纯数字6位代码，如 600036 ──
            elif word.isdigit() and len(word) == 6:
                suffix = "SH" if word.startswith("6") else "SZ"
                code   = f"{word}.{suffix}"
                name   = word
                if w_idx + 1 < len(words) and not _is_code(words[w_idx + 1]):
                    name = words[w_idx + 1]
                if code not in seen:
                    seen.add(code)
                    result.append({"code": code, "name": name})

            # ── 情况3：中文名称，通过 Tushare 本地对照表查找 ──
            elif _is_chinese(word):
                matched = search_stock_by_name(word, token=token)
                if matched and matched["code"] not in seen:
                    seen.add(matched["code"])
                    result.append(matched)
                elif not matched:
                    # 放入待处理列表，给用户提示
                    if "_unresolved" not in st.session_state:
                        st.session_state["_unresolved"] = []
                    st.session_state["_unresolved"].append(word)
        i += 1

    return result

def _is_code(s):
    s = s.strip()
    return (s.isdigit() and len(s) == 6) or ("." in s and s.split(".")[-1].upper() in ("SH", "SZ"))

def _is_chinese(s):
    """判断是否包含中文字符"""
    return any("\u4e00" <= c <= "\u9fff" for c in s)

def get_stock_dict(token: str) -> dict:
    """
    从 Tushare 获取全量A股名称→代码对照表，缓存在 session_state。
    调用 stock_basic 接口，无需积分，所有用户均可用。
    返回 {"招商银行": "600036.SH", "生益科技": "600183.SZ", ...}
    """
    if "stock_dict" in st.session_state and st.session_state.stock_dict:
        return st.session_state.stock_dict

    if not token:
        return {}
    try:
        import tushare as ts
        pro = ts.pro_api(token)
        # 拉取全量股票基础信息（无需积分）
        df = pro.stock_basic(exchange="", list_status="L",
                             fields="ts_code,symbol,name,market")
        if df is None or df.empty:
            return {}
        stock_dict = {}
        for _, row in df.iterrows():
            name    = str(row.get("name", "")).strip()
            ts_code = str(row.get("ts_code", "")).strip()
            if name and ts_code:
                stock_dict[name] = ts_code
        st.session_state.stock_dict = stock_dict
        return stock_dict
    except Exception as e:
        st.warning(f"⚠️ 获取股票列表失败：{e}")
        return {}


def search_stock_by_name(name: str, token: str = "") -> dict:
    """
    用中文名称在本地对照表中查找股票代码（精确匹配 + 模糊匹配）。
    依赖 get_stock_dict() 缓存的对照表，完全不需要额外网络请求。
    """
    stock_dict = get_stock_dict(token)
    if not stock_dict:
        return None

    name = name.strip()

    # 1. 精确匹配
    if name in stock_dict:
        ts_code = stock_dict[name]
        return {"code": ts_code, "name": name}

    # 2. 模糊匹配（包含关系）
    candidates = [(n, c) for n, c in stock_dict.items() if name in n or n in name]
    if candidates:
        # 优先选名称长度最接近的
        candidates.sort(key=lambda x: abs(len(x[0]) - len(name)))
        matched_name, matched_code = candidates[0]
        return {"code": matched_code, "name": matched_name}

    return None

# ─────────────────────────────────────────────
# 数据抓取
# ─────────────────────────────────────────────
def fetch_tushare(stock_codes, token, days=1):
    """
    Tushare 公告接口
    接口名：anns_d（按日期查询）
    字段：ann_date, ts_code, name, title, url, rec_time
    """
    try:
        import tushare as ts
    except ImportError:
        st.error("请先安装 tushare：在 requirements.txt 中加入 tushare 并重新部署")
        return []
    if not token:
        st.error("请填写 Tushare Token")
        return []
    try:
        pro = ts.pro_api(token)
    except Exception as e:
        st.error(f"Tushare 初始化失败：{e}")
        return []

    announcements = []
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    end_date   = datetime.now().strftime("%Y%m%d")

    for code in stock_codes:
        try:
            # 正确接口：anns_d，按 ts_code + 日期范围查询
            df = pro.anns_d(ts_code=code, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                # 用 ts_code + ann_date + title 生成唯一ID
                uid = hashlib.md5(
                    f"{row.get('ts_code','')}{row.get('ann_date','')}{row.get('title','')}".encode()
                ).hexdigest()
                announcements.append({
                    "id":    uid,
                    "code":  row.get("ts_code", code),
                    "name":  row.get("name", code),
                    "title": row.get("title", ""),
                    "time":  row.get("rec_time") or row.get("ann_date", ""),  # 优先用发布时间
                    "url":   row.get("url", ""),
                })
        except Exception as e:
            st.warning(f"⚠️ {code} 获取失败：{e}")

    return announcements

def fetch_cninfo(stock_codes, days=1):
    """巨潮资讯（备用）"""
    announcements = []
    end_date   = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    for code in stock_codes:
        pure_code = code.split(".")[0]
        market    = code.split(".")[1].lower() if "." in code else "sh"
        try:
            resp = requests.post("http://www.cninfo.com.cn/new/information/topSearch/query",
                data={"keyWord": pure_code, "maxNum": 5}, headers=headers, timeout=10)
            org_id, stock_name = None, pure_code
            for item in resp.json().get("keyBoardList", []):
                if item.get("code") == pure_code:
                    org_id, stock_name = item.get("orgId"), item.get("zwjc", pure_code)
                    break
            if not org_id:
                continue
            ann_resp = requests.post("http://www.cninfo.com.cn/new/hisAnnouncement/query",
                data={"stock": f"{pure_code},{org_id}", "tabName": "fulltext", "pageSize": 30,
                      "pageNum": 1, "column": "szse" if market=="sz" else "sse",
                      "category": "", "plate": market, "seDate": f"{start_date}~{end_date}",
                      "searchkey": "", "isHLtitle": True},
                headers=headers, timeout=15)
            for ann in ann_resp.json().get("announcements", []):
                aid = ann.get("announcementId", "")
                announcements.append({
                    "id":    aid, "code": code, "name": stock_name,
                    "title": ann.get("announcementTitle", ""),
                    "time":  ann.get("announcementTime", ""),
                    "url":   f"http://www.cninfo.com.cn/new/announcement/detail?announcementId={aid}&orgId={org_id}",
                })
        except Exception as e:
            st.warning(f"⚠️ {code} 巨潮获取失败：{e}")
    return announcements

# ─────────────────────────────────────────────
# Session State 初始化
# ─────────────────────────────────────────────
for k, v in {
    "watch_stocks":    [],
    "announcements":   [],
    "new_ids":         set(),
    "last_check":      None,
    "total_new":       0,
    "check_days":      1,
    "ann_type_filter": "全部",
    "push_log":        [],
    "data_source":     "tushare",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─────────────────────────────────────────────
# 检查公告
# ─────────────────────────────────────────────
def do_check(sendkey="", tushare_token=""):
    codes = [s["code"] for s in st.session_state.watch_stocks]
    if not codes:
        st.warning("请先添加要监控的股票")
        return 0

    if st.session_state.data_source == "tushare":
        anns = fetch_tushare(codes, tushare_token, days=st.session_state.check_days)
    else:
        anns = fetch_cninfo(codes, days=st.session_state.check_days)

    cache = load_cache()
    new_anns, new_ids = [], set()
    for ann in anns:
        aid = str(ann["id"])
        if aid not in cache:
            new_ids.add(aid)
            new_anns.append(ann)
            cache[aid] = {"title": ann["title"], "seen_at": datetime.now().isoformat()}
    save_cache(cache)

    st.session_state.announcements = anns
    st.session_state.new_ids       = new_ids
    st.session_state.last_check    = datetime.now()
    st.session_state.total_new    += len(new_ids)

    if new_anns and sendkey:
        title = f"📋 {len(new_anns)} 条新公告｜{', '.join(set(a['name'] for a in new_anns))}"
        ok    = send_wechat(sendkey, title, build_wechat_content(new_anns))
        st.session_state.push_log.append(
            f"[{datetime.now().strftime('%H:%M:%S')}] {'✅' if ok else '❌'} 微信推送 {len(new_anns)} 条")
    return len(new_ids)

# ═══════════════════════════════
# 侧边栏
# ═══════════════════════════════
with st.sidebar:
    st.markdown("## 📋 股票公告监控")
    st.markdown("---")

    # ── 数据源 ──
    st.markdown("### 📡 数据源")
    src = st.radio("", ["Tushare（推荐）", "巨潮资讯（备用）"], label_visibility="collapsed")
    st.session_state.data_source = "tushare" if "Tushare" in src else "cninfo"

    default_ts_token = ""
    default_sendkey  = ""
    try:
        default_ts_token = st.secrets.get("TUSHARE_TOKEN", "")
        default_sendkey  = st.secrets.get("SENDKEY", "")
    except Exception:
        pass

    tushare_token = ""
    if st.session_state.data_source == "tushare":
        tushare_token = st.text_input("Tushare Token", type="password",
            value=default_ts_token, placeholder="粘贴你的 Token")
        st.markdown('<small style="color:#7d8590">👉 <a href="https://tushare.pro/register" target="_blank" style="color:#00d4ff">注册 Tushare</a> 免费获取Token（公告接口需积分≥120）</small>', unsafe_allow_html=True)

    st.markdown("---")

    # ── 微信推送 ──
    st.markdown("### 📱 微信推送")
    sendkey = st.text_input("Server酱 SendKey", type="password",
        value=default_sendkey, placeholder="SCT开头，留空不推送")
    st.markdown('<small style="color:#7d8590">👉 <a href="https://sct.ftqq.com" target="_blank" style="color:#00d4ff">获取免费 SendKey</a></small>', unsafe_allow_html=True)
    if sendkey:
        if st.button("🧪 测试微信推送", use_container_width=True):
            ok = send_wechat(sendkey, "✅ 股票监控测试", "推送成功！有新公告时会自动通知你 📋")
            st.success("✅ 推送成功！检查微信") if ok else st.error("❌ 失败，检查 SendKey")

    st.markdown("---")

    # ── 批量输入股票 ──
    st.markdown("### ➕ 批量输入股票")
    # 有 token 时预热股票字典缓存
    if tushare_token and "stock_dict" not in st.session_state:
        with st.spinner("首次加载股票列表..."):
            d = get_stock_dict(tushare_token)
        if d:
            st.success(f"✅ 已加载 {len(d)} 只股票，支持中文名称搜索")

    st.markdown("""<div class="tip-box">
    支持以下所有格式（每行一个，也可逗号分隔）：<br>
    <code>生益科技</code> ← 直接输中文名 ✅<br>
    <code>生益电子</code> ← 模糊匹配 ✅<br>
    <code>600036.SH 招商银行</code><br>
    <code>000858 五粮液</code><br>
    <code>600036,000858,300750</code><br>
    <small>6开头→沪市，0/3开头→深市（自动识别）</small>
    </div>""", unsafe_allow_html=True)

    batch_input = st.text_area("", height=140,
        placeholder="600036.SH 招商银行\n000858.SZ 五粮液\n300750,宁德时代\n601318",
        label_visibility="collapsed")

    if st.button("✅ 确认添加", use_container_width=True):
        if batch_input.strip():
            st.session_state["_unresolved"] = []
            parsed = parse_stock_input(batch_input, token=tushare_token)
            added, skipped = 0, 0
            for s in parsed:
                if not any(x["code"] == s["code"] for x in st.session_state.watch_stocks):
                    st.session_state.watch_stocks.append(s)
                    added += 1
                else:
                    skipped += 1
            unresolved = st.session_state.get("_unresolved", [])
            if added:
                msg = f"✅ 成功添加 {added} 只股票！"
                if skipped: msg += f"（{skipped} 只已在列表中跳过）"
                st.success(msg)
                st.rerun()
            elif skipped and not unresolved:
                st.info(f"ℹ️ {skipped} 只股票已在监控列表中，无需重复添加")
            if unresolved:
                st.warning(f"⚠️ 以下名称未能识别，请改用股票代码：**{'、'.join(unresolved)}**")
        else:
            st.warning("请先输入股票代码或名称")

    if st.button("🗑 清空全部股票", use_container_width=True):
        st.session_state.watch_stocks = []
        st.rerun()

    # ── 当前监控列表 ──
    if st.session_state.watch_stocks:
        st.markdown("---")
        st.markdown(f"### 📌 监控中（{len(st.session_state.watch_stocks)} 只）")
        for i, s in enumerate(st.session_state.watch_stocks):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f'<span class="stock-tag"><span class="dot-green"></span>{s["name"]} <span style="color:#7d8590;font-size:11px">{s["code"]}</span></span>', unsafe_allow_html=True)
            with c2:
                if st.button("×", key=f"del_{i}"):
                    st.session_state.watch_stocks.pop(i); st.rerun()

    st.markdown("---")
    st.session_state.check_days = st.selectbox("查询最近几天", [1, 3, 7, 14, 30])

# ═══════════════════════════════
# 主界面
# ═══════════════════════════════
st.markdown('<h1 style="color:#e6edf3;font-size:26px;font-weight:800;margin-bottom:4px;">📋 股票公告实时监控</h1>'
            '<p style="color:#7d8590;font-size:13px;margin-top:0;">支持 Tushare · 巨潮资讯 · 微信实时推送</p>',
            unsafe_allow_html=True)

# 统计
c1, c2, c3, c4 = st.columns(4)
with c1: st.metric("监控股票",  f"{len(st.session_state.watch_stocks)} 只")
with c2: st.metric("本次公告",  f"{len(st.session_state.announcements)} 条")
with c3: st.metric("新增公告",  f"{len(st.session_state.new_ids)} 条",
                   delta=f"+{len(st.session_state.new_ids)}" if st.session_state.new_ids else None)
with c4: st.metric("最后检查",  st.session_state.last_check.strftime("%H:%M:%S") if st.session_state.last_check else "—")

st.markdown("---")

# 操作栏
b1, b2, b3, _ = st.columns([2, 2, 2, 4])
with b1:
    if st.button("🔍 立即检查公告", use_container_width=True):
        with st.spinner("正在获取公告..."):
            n = do_check(sendkey, tushare_token)
        if n > 0:
            st.success(f"🎉 发现 {n} 条新公告！{'已推送微信 📱' if sendkey else ''}")
        else:
            st.info("✅ 暂无新公告")
        st.rerun()

with b2:
    auto_refresh = st.toggle("⏱ 每1分钟自动刷新", value=False)

with b3:
    if st.button("🗑 清空公告记录", use_container_width=True):
        st.session_state.announcements = []
        st.session_state.new_ids = set()
        st.rerun()

# 自动刷新（1分钟 = 60秒）
if auto_refresh:
    last = st.session_state.last_check
    elapsed = (datetime.now() - last).seconds if last else 9999
    if elapsed >= 60:
        with st.spinner("🔄 自动检查中..."):
            do_check(sendkey, tushare_token)
        st.rerun()
    else:
        remaining = 60 - elapsed
        st.info(f"⏳ 下次自动检查：{remaining} 秒后")
        # 用 st.empty + time.sleep 实现倒计时刷新
        time.sleep(min(remaining, 5))
        st.rerun()

# 推送日志
if st.session_state.push_log:
    with st.expander("📬 推送日志"):
        for log in reversed(st.session_state.push_log[-10:]):
            st.markdown(f'<small style="color:#7d8590">{log}</small>', unsafe_allow_html=True)

st.markdown("---")

# 公告类型筛选
ANN_TYPES = ["全部", "定期报告", "业绩预告", "业绩快报", "重大事项", "股权变动", "增减持", "分红"]
st.session_state.ann_type_filter = st.radio("", ANN_TYPES, horizontal=True, label_visibility="collapsed")

# 公告列表
anns = st.session_state.announcements
if st.session_state.ann_type_filter != "全部":
    anns = [a for a in anns if st.session_state.ann_type_filter in a["title"]]

if not anns:
    st.markdown(
        '<div style="text-align:center;padding:60px;color:#7d8590;background:#161b22;'
        'border-radius:12px;border:1px solid #21262d;">'
        '<div style="font-size:40px;margin-bottom:12px;">📭</div>'
        '<div style="font-size:15px;">点击「立即检查」获取公告数据</div></div>',
        unsafe_allow_html=True)
else:
    for ann in anns:
        is_new   = str(ann["id"]) in st.session_state.new_ids
        card_cls = "ann-card new" if is_new else "ann-card"
        badge    = '<span class="badge-new">NEW</span>&nbsp;' if is_new else ""
        url_part = f'<a href="{ann["url"]}" target="_blank" class="ann-link">🔗 查看原文</a>' if ann.get("url") else ""
        st.markdown(
            f'<div class="{card_cls}">'
            f'<div style="margin-bottom:6px;"><b style="color:#e6edf3;font-size:14px;">{ann["name"]}</b>&nbsp;'
            f'<span class="badge-code">{ann["code"]}</span>&nbsp;{badge}</div>'
            f'<div class="ann-title">{ann["title"]}</div>'
            f'<div class="ann-meta">⏰ {ann["time"]} &nbsp;·&nbsp; {url_part}</div>'
            f'</div>', unsafe_allow_html=True)

st.markdown('<p style="color:#7d8590;font-size:12px;text-align:center;margin-top:20px;">仅供参考，不构成投资建议</p>',
            unsafe_allow_html=True)
