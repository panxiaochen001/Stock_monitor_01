import streamlit as st
import requests
import json
import hashlib
from datetime import datetime, timedelta

st.set_page_config(page_title="股票公告监控", page_icon="📋", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap');
    html, body, [class*="css"] { font-family: 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif; }
    .stApp { background-color: #0d1117; }
    section[data-testid="stSidebar"] { background-color: #161b22; border-right: 1px solid #21262d; }
    .ann-card { background:#161b22; border:1px solid #21262d; border-radius:10px; padding:16px 20px; margin-bottom:10px; }
    .ann-card.new { border-left:3px solid #00d4ff; background:#0d1f33; }
    .ann-title { font-size:14px; color:#e6edf3; font-weight:500; line-height:1.6; }
    .ann-meta  { font-size:12px; color:#7d8590; margin-top:6px; }
    .ann-link  { font-size:12px; color:#00d4ff; text-decoration:none; }
    .badge-new  { background:#00d4ff22; color:#00d4ff; border:1px solid #00d4ff44; border-radius:4px; padding:2px 8px; font-size:11px; font-weight:700; }
    .badge-code { background:#1f2937; color:#9ca3af; border:1px solid #374151; border-radius:4px; padding:2px 8px; font-size:11px; font-family:monospace; }
    .stock-tag  { display:inline-flex; align-items:center; gap:6px; background:#1f2937; border:1px solid #374151; border-radius:20px; padding:4px 12px; font-size:13px; color:#e6edf3; margin:3px; }
    .dot-green  { width:7px; height:7px; background:#00e676; border-radius:50%; display:inline-block; }
    #MainMenu{visibility:hidden;} footer{visibility:hidden;} header{visibility:hidden;}
    .stButton>button { background:linear-gradient(135deg,#00d4ff,#0066ff)!important; color:#000!important; border:none!important; border-radius:8px!important; font-weight:700!important; }
    .stTextInput>div>div>input { background:#0d1117!important; border:1px solid #30363d!important; color:#e6edf3!important; border-radius:8px!important; }
    div[data-testid="stMetricValue"] { color:#00d4ff; }
</style>
""", unsafe_allow_html=True)

# ── 缓存（用 session_state，适配 Streamlit Cloud）──
def load_cache():
    if "seen_cache" not in st.session_state:
        st.session_state.seen_cache = {}
    return st.session_state.seen_cache

def save_cache(cache):
    st.session_state.seen_cache = cache

# ── 微信推送 Server酱 ──
def send_wechat(sendkey, title, content):
    if not sendkey:
        return False
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

# ── 巨潮资讯抓取 ──
def fetch_cninfo(stock_codes, days=1):
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
                st.warning(f"⚠️ 未找到 {code}，请检查格式（如 600036.SH）")
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
                    "id": aid, "code": code, "name": stock_name,
                    "title": ann.get("announcementTitle", ""),
                    "time":  ann.get("announcementTime", ""),
                    "url":   f"http://www.cninfo.com.cn/new/announcement/detail?announcementId={aid}&orgId={org_id}",
                })
        except Exception as e:
            st.error(f"❌ 获取 {code} 失败：{e}")
    return announcements

# ── Session State 初始化 ──
for k, v in {"watch_stocks":[],"announcements":[],"new_ids":set(),"last_check":None,
              "total_new":0,"check_days":1,"ann_type_filter":"全部","push_log":[]}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── 检查公告主函数 ──
def do_check(sendkey=""):
    codes = [s["code"] for s in st.session_state.watch_stocks]
    if not codes:
        st.warning("请先在左侧添加股票")
        return 0
    anns  = fetch_cninfo(codes, days=st.session_state.check_days)
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
            f"[{datetime.now().strftime('%H:%M:%S')}] 微信推送 {'✅ 成功' if ok else '❌ 失败'} · {len(new_anns)} 条")
    return len(new_ids)

# ════════════════════════════════
# 侧边栏
# ════════════════════════════════
with st.sidebar:
    st.markdown("## 📋 股票公告监控")
    st.markdown("---")

    st.markdown("### 📱 微信推送")
    st.markdown('<small style="color:#7d8590">需要 <a href="https://sct.ftqq.com" target="_blank" style="color:#00d4ff">Server酱</a> SendKey</small>', unsafe_allow_html=True)
    default_key = ""
    try:
        default_key = st.secrets.get("SENDKEY", "")
    except Exception:
        pass
    sendkey = st.text_input("SendKey", type="password", value=default_key,
                             placeholder="SCT开头的Key，留空则不推送")
    if sendkey:
        if st.button("🧪 测试推送", use_container_width=True):
            ok = send_wechat(sendkey, "✅ 股票监控测试", "微信推送配置成功！有新公告时会自动通知你。")
            st.success("推送成功！检查微信 🎉") if ok else st.error("失败，检查 SendKey 是否正确")

    st.markdown("---")
    st.markdown("### ➕ 添加股票")
    c1, c2 = st.columns([3,2])
    with c1: new_code = st.text_input("代码", placeholder="600036.SH", label_visibility="collapsed")
    with c2: new_name = st.text_input("名称", placeholder="招商银行",  label_visibility="collapsed")
    if st.button("添加", use_container_width=True):
        code = new_code.strip().upper()
        if code and not any(s["code"]==code for s in st.session_state.watch_stocks):
            st.session_state.watch_stocks.append({"code":code,"name":new_name.strip() or code})
            st.rerun()

    st.markdown("**快速添加：**")
    for code, name in [("600036.SH","招商银行"),("600519.SH","贵州茅台"),
                        ("000858.SZ","五粮液"),  ("300750.SZ","宁德时代"),("601318.SH","中国平安")]:
        exists = any(s["code"]==code for s in st.session_state.watch_stocks)
        if st.button(f"{'✓ ' if exists else '+ '}{name}", key=f"p_{code}", use_container_width=True, disabled=exists):
            st.session_state.watch_stocks.append({"code":code,"name":name})
            st.rerun()

    if st.session_state.watch_stocks:
        st.markdown("---")
        st.markdown("### 📌 监控中")
        for i, s in enumerate(st.session_state.watch_stocks):
            c1, c2 = st.columns([4,1])
            with c1:
                st.markdown(f'<span class="stock-tag"><span class="dot-green"></span>{s["name"]} <span style="color:#7d8590;font-size:11px">{s["code"]}</span></span>', unsafe_allow_html=True)
            with c2:
                if st.button("×", key=f"del_{i}"):
                    st.session_state.watch_stocks.pop(i); st.rerun()

    st.markdown("---")
    st.session_state.check_days = st.selectbox("查询最近几天", [1,3,7,14,30])

# ════════════════════════════════
# 主界面
# ════════════════════════════════
st.markdown('<h1 style="color:#e6edf3;font-size:26px;font-weight:800;margin-bottom:4px;">📋 股票公告实时监控</h1>'
            '<p style="color:#7d8590;font-size:13px;margin-top:0;">数据来源：巨潮资讯网 · 免费 · 微信实时推送</p>', unsafe_allow_html=True)

c1,c2,c3,c4 = st.columns(4)
with c1: st.metric("监控股票", f"{len(st.session_state.watch_stocks)} 只")
with c2: st.metric("本次公告", f"{len(st.session_state.announcements)} 条")
with c3: st.metric("新增公告", f"{len(st.session_state.new_ids)} 条", delta=f"+{len(st.session_state.new_ids)}" if st.session_state.new_ids else None)
with c4: st.metric("最后检查", st.session_state.last_check.strftime("%H:%M:%S") if st.session_state.last_check else "—")

st.markdown("---")

b1,b2,b3,_ = st.columns([2,2,2,4])
with b1:
    if st.button("🔍 立即检查公告", use_container_width=True):
        with st.spinner("正在获取公告..."):
            n = do_check(sendkey)
        st.success(f"发现 {n} 条新公告！{'已推送微信 📱' if sendkey and n else ''}") if n else st.info("暂无新公告")
        st.rerun()
with b2:
    auto = st.toggle("⏱ 自动刷新(15分钟)")
with b3:
    if st.button("🗑 清空记录", use_container_width=True):
        st.session_state.announcements=[]; st.session_state.new_ids=set(); st.rerun()

if auto:
    last = st.session_state.last_check
    if last is None or (datetime.now()-last).seconds >= 900:
        with st.spinner("自动检查中..."): do_check(sendkey)
        st.rerun()
    else:
        remaining = 900 - (datetime.now()-last).seconds
        st.info(f"⏳ 下次自动检查：{remaining//60} 分 {remaining%60} 秒后")

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
    st.markdown('<div style="text-align:center;padding:60px;color:#7d8590;background:#161b22;border-radius:12px;border:1px solid #21262d;"><div style="font-size:40px;margin-bottom:12px;">📭</div><div>点击「立即检查」获取公告数据</div></div>', unsafe_allow_html=True)
else:
    for ann in anns:
        is_new   = str(ann["id"]) in st.session_state.new_ids
        card_cls = "ann-card new" if is_new else "ann-card"
        badge    = '<span class="badge-new">NEW</span>&nbsp;' if is_new else ""
        url_part = f'<a href="{ann["url"]}" target="_blank" class="ann-link">🔗 查看原文</a>' if ann.get("url") else ""
        st.markdown(f'<div class="{card_cls}"><div style="margin-bottom:6px;"><b style="color:#e6edf3;font-size:14px;">{ann["name"]}</b>&nbsp;<span class="badge-code">{ann["code"]}</span>&nbsp;{badge}</div><div class="ann-title">{ann["title"]}</div><div class="ann-meta">⏰ {ann["time"]} &nbsp;·&nbsp; {url_part}</div></div>', unsafe_allow_html=True)

st.markdown('<p style="color:#7d8590;font-size:12px;text-align:center;margin-top:20px;">数据来源：巨潮资讯网 · 仅供参考，不构成投资建议</p>', unsafe_allow_html=True)
