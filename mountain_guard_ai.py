import os
import time
import json
import base64
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# =========================================================
# 0. 環境變數與常數設定
# =========================================================
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

RESOURCE_TYPES = {
    "有形資源": ["食物", "飲用水", "醫療用品", "保暖衣物", "救災工具", "通訊設備", "四輪傳動車", "重型機具", "其他"],
    "無形資源": ["人力", "搜救志工", "專業技術", "醫療支援", "心理諮詢", "運輸協助", "災情回報", "其他"],
    "金流資源": ["現金捐款", "物資採購金", "專案補助", "其他"],
}
ROLE_LABELS = {
    "citizen": "一般民眾 / 村里長",
    "company": "公私企業 / NGO",
    "government": "南投應變中心 / 決策長官",
    "admin": "系統管理員"
}

# =========================================================
# 1. 輔助函數 (Utils)
# =========================================================
def make_id(prefix): return f"{prefix}{int(time.time()*1000)}"
def now_str(): return datetime.now().strftime("%Y-%m-%d %H:%M")
def get_current_user(): return st.session_state.current_user
def is_logged_in(): return st.session_state.get("logged_in", False)
def check_duplicate_demand(district, item):
    for d in st.session_state.demands:
        if d["district"] == district and d["item"] == item and d["status"] != "已處理": return d
    return None

def get_status_badge(status):
    badges = {
        "verified": "<span style='background-color:#d4edda; color:#155724; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>✅ 已認證</span>",
        "pending": "<span style='background-color:#fff3cd; color:#856404; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>⏳ 待審核</span>",
        "可調派": "<span style='background-color:#d4edda; color:#155724; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>🟢 可調派</span>",
        "未處理": "<span style='background-color:#f8d7da; color:#721c24; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>🚨 未處理</span>",
    }
    return badges.get(status, f"<span style='background-color:#e2e3e5; color:#383d41; padding:3px 8px; border-radius:12px; font-size:12px;'>{status}</span>")

# =========================================================
# 2. 系統初始化 (載入南投專屬 Demo 資料)
# =========================================================
def init_session_state():
    now = datetime.now()
    if "logged_in" not in st.session_state: st.session_state.logged_in = False
    if "current_user" not in st.session_state: st.session_state.current_user = None

    if "users" not in st.session_state:
        st.session_state.users = [
            {"id": "U_ADMIN", "name": "系統管理員", "role": "admin", "email": "admin@resq.tw", "district": "全區", "verified": True},
            {"id": "U_GOV_001", "name": "林應變指揮官", "role": "government", "email": "commander@nantou.gov.tw", "district": "南投縣", "verified": True},
            {"id": "U_CIT_001", "name": "南豐村通報員", "role": "citizen", "email": "citizen@nantou.tw", "district": "南投縣仁愛鄉", "verified": False},
            {"id": "U_COM_001", "name": "賑災基金會", "role": "company", "email": "contact@ngo.org.tw", "district": "南投市", "verified": True},
        ]

    if "demands" not in st.session_state:
        st.session_state.demands = [
            {
                "id": "D001", "time": (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M"), "source": "AI通報",
                "requester_id": "U_CIT_001", "requester_name": "南豐村通報員", "requester_email": "citizen@nantou.tw",
                "district": "南投縣仁愛鄉", "village": "南豐村", "location": "南投縣仁愛鄉南豐村中正路",
                "lat": 24.004, "lon": 121.115, "resource_type": "有形資源", "category": "醫療用品",
                "item": "急救包與慢性病藥物", "qty": 20, "urgency": 5, "status": "未處理", 
                "verification_status": "pending", "island_effect": True, "affected_people": 150
            }
        ]

    if "supplies" not in st.session_state:
        st.session_state.supplies = [
            {
                "id": "S001", "time": (now - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M"), "source": "企業登錄",
                "provider_id": "U_COM_001", "provider": "賑災基金會", "provider_email": "contact@ngo.org.tw",
                "district": "南投市", "village": "全區", "location_current": "南投市物資集散中心",
                "lat": 23.916, "lon": 120.683, "resource_type": "有形資源", "category": "醫療用品",
                "item": "急救包與慢性病藥物", "qty": 100, "status": "可調派", "verification_status": "verified"
            }
        ]
        
    if "disasters" not in st.session_state: 
        st.session_state.disasters = [
            {
                "id": "E001", "time": (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M"), "source": "AI通報",
                "reporter_id": "U_CIT_001", "reporter_name": "南豐村通報員", "district": "南投縣仁愛鄉",
                "location": "台14線 75K 處", "lat": 24.015, "lon": 121.130, "description": "嚴重土石流，雙向道路完全阻斷",
                "status": "未處理", "island_effect": True
            }
        ]
        
    if "claims" not in st.session_state: st.session_state.claims = []
    if "notifications" not in st.session_state: st.session_state.notifications = []
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [{"role": "assistant", "content": "您好！我是 MountainGuard AI。請問南投山區目前有什麼需要協助的災情或物資需求？"}]

# =========================================================
# 3. 核心 AI 引擎 (針對孤島與災情特化)
# =========================================================
def extract_info_with_ai(raw_text=None, image_bytes=None, mime_type="image/jpeg"):
    if not GROQ_API_KEY: return {"error": "尚未設定 GROQ_API_KEY"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1", max_retries=1, timeout=15.0)
        
        system_prompt = """
        你是一個 MountainGuard AI 南投山區防災調度大腦。請將輸入精準萃取為 JSON 格式。
        
        ⚠️【任務導向分類 (info_type)】：
        1. "Demand"：要求物資或救援。
        2. "Supply"：提供物資或救援。
        3. "Disaster"：僅回報山區災情（如土石流、道路坍方）。
        4. "Irrelevant"：無關內容。

        ⚠️【山區風險評估模組 (Risk Assessment)】：
        請判斷文本中是否提及「道路中斷」、「橋樑損毀」、「坍方」等。若有，請將 "island_effect" 設為 true (孤島效應)。
        並盡可能估算 "affected_people" (受影響人數整數，若無則填 0)。

        回傳格式嚴格遵循以下 JSON：
        {
          "info_type": "Demand 或 Supply 或 Disaster 或 Irrelevant",
          "data": {
              "resource_type": "有形資源 或 無形資源 或 金流資源",
              "category": "次要物資類別",
              "item": "具體物品或災情", 
              "qty": 數量, 
              "urgency": 緊急度1-5,
              "location_current": "所在地",
              "lat": 緯度浮點數, 
              "lon": 經度浮點數,
              "district": "南投縣行政區(如:南投縣仁愛鄉)",
              "risk_flag": "敏感警告或空字串",
              "island_effect": true 或 false,
              "affected_people": 影響人數
          }
        }
        """
        messages = [{"role": "system", "content": system_prompt}]
        if image_bytes:
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            messages.append({"role": "user", "content": [{"type": "text", "text": str(raw_text)}, {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}]})
            model_name = "meta-llama/llama-4-scout-17b-16e-instruct"
        else:
            messages.append({"role": "user", "content": str(raw_text)})
            model_name = "llama-3.3-70b-versatile"
            
        res = client.chat.completions.create(model=model_name, messages=messages, temperature=0.0)
        raw_output = res.choices[0].message.content
        start_idx = raw_output.find('{')
        end_idx = raw_output.rfind('}')
        if start_idx != -1 and end_idx != -1: return json.loads(raw_output[start_idx:end_idx+1])
        return {"error": "格式異常", "raw": raw_output}
    except Exception as e: 
        error_msg = str(e).lower()
        if "429" in error_msg or "rate limit" in error_msg or "timeout" in error_msg: return {"error": "API_RATE_LIMIT"}
        return {"error": str(e)}

# =========================================================
# 4. 登入介面 (MountainGuard UI)
# =========================================================
def login_panel():
    st.title("🏔️ MountainGuard AI")
    st.subheader("南投山區韌性救援與智慧治理平台")
    st.markdown("結合 AI 災情分析與開放資料，解決山區孤島效應，實踐「數位治理、永續南投」。")
    
    if "selected_login_role" not in st.session_state: st.session_state.selected_login_role = None
    st.markdown("<br>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### 👨‍👩‍👧‍👦 居民/村里長通報")
        st.caption("AI 災情解析 / 孤島求援 / 語音通報")
        if st.button("由此登入 ➡️", key="btn_role_citizen", use_container_width=True):
            st.session_state.selected_login_role = "citizen"; st.rerun()
    with col2:
        st.markdown("### 🏢 企業與NGO")
        st.caption("資源智慧媒合 / 志工調派 / 永續參與")
        if st.button("由此登入 ➡️", key="btn_role_company", use_container_width=True):
            st.session_state.selected_login_role = "company"; st.rerun()
    with col3:
        st.markdown("### 🏛️ 南投應變中心")
        st.caption("風險決策儀表板 / 資源調度 / 開放資料")
        if st.button("由此登入 ➡️", key="btn_role_government", use_container_width=True):
            st.session_state.selected_login_role = "government"; st.rerun()

    st.divider()
    current_role = st.session_state.selected_login_role

    if current_role == "citizen":
        with st.container(border=True):
            st.subheader("👨‍👩‍👧‍👦 居民/村里長 登入 (Demo 已預填)")
            with st.form("citizen_login_form"):
                col_a, col_b = st.columns(2)
                with col_a:
                    login_email = st.text_input("📧 電子信箱", value="citizen@nantou.tw")
                    login_name = st.text_input("👤 姓名", value="南豐村通報員")
                with col_b:
                    login_district = st.text_input("📍 所在鄉鎮", value="南投縣仁愛鄉")
                    login_village = st.text_input("🏘️ 所在村里", value="南豐村")
                submitted = st.form_submit_button("🚀 登入系統", type="primary", use_container_width=True)
                if submitted:
                    user = next((u for u in st.session_state.users if u["email"] == login_email), {"id": make_id("U"), "email": login_email, "name": login_name, "role": "citizen", "district": login_district, "village": login_village, "verified": False})
                    st.session_state.current_user = user; st.session_state.logged_in = True
                    st.success("✅ 登入成功！"); time.sleep(1); st.rerun()

    elif current_role == "company":
        with st.container(border=True):
            st.subheader("🏢 企業/NGO 登入 (Demo 已預填)")
            with st.form("company_login_form"):
                col_a, col_b = st.columns(2)
                with col_a:
                    login_email = st.text_input("📧 聯絡信箱", value="contact@ngo.org.tw")
                    login_name = st.text_input("🏢 組織名稱", value="賑災基金會")
                with col_b:
                    login_district = st.text_input("📍 總部所在", value="南投市")
                    tax_id = st.text_input("🧾 統一編號", value="12345678", max_chars=8)
                submitted = st.form_submit_button("🚀 登入企業戰情中心", type="primary", use_container_width=True)
                if submitted:
                    user = next((u for u in st.session_state.users if u["email"] == login_email), {"id": make_id("U"), "email": login_email, "name": login_name, "role": "company", "district": login_district, "village": "全區", "verified": True})
                    st.session_state.current_user = user; st.session_state.logged_in = True
                    st.success("✅ 登入成功！"); time.sleep(1); st.rerun()

    elif current_role == "government":
        with st.container(border=True):
            st.subheader("🏛️ 南投縣災害應變中心 登入 (Demo 已預填)")
            with st.form("gov_login_form"):
                col_a, col_b = st.columns(2)
                with col_a:
                    login_email = st.text_input("📧 公務信箱", value="commander@nantou.gov.tw")
                    login_name = st.text_input("👤 長官職稱", value="林應變指揮官")
                with col_b:
                    login_district = st.text_input("📍 管轄範圍", value="南投縣")
                    auth_code = st.text_input("🔑 授權碼", type="password", value="admin")
                submitted = st.form_submit_button("🛡️ 進入決策儀表板", type="primary", use_container_width=True)
                if submitted and auth_code == "admin":
                    user = next((u for u in st.session_state.users if u["email"] == login_email), {"id": make_id("U"), "email": login_email, "name": login_name, "role": "government", "district": login_district, "village": "全區", "verified": True})
                    st.session_state.current_user = user; st.session_state.logged_in = True
                    st.success("✅ 授權成功！"); time.sleep(1); st.rerun()
                    
    if not current_role:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        col_x, col_y, col_z = st.columns([1,1,1])
        with col_y:
            if st.button("⚙️ 系統管理員登入通道", use_container_width=True):
                st.session_state.selected_login_role = "admin"; st.rerun()
    elif current_role == "admin":
        with st.container(border=True):
            with st.form("admin_form"):
                login_email = st.text_input("📧 帳號", value="admin@resq.tw")
                auth_code = st.text_input("🔑 密碼", type="password", value="admin")
                if st.form_submit_button("登入", type="primary", use_container_width=True):
                    user = {"id": "A001", "email": login_email, "name": "系統管理員", "role": "admin", "district": "全區", "verified": True}
                    st.session_state.current_user = user; st.session_state.logged_in = True; st.rerun()

# =========================================================
# 5. 各角色功能頁面 (政府端)
# =========================================================
def page_gov_inbox():
    user = get_current_user()
    st.title(f"📊 {user.get('district')} - 智慧決策儀表板")
    st.caption(" MountainGuard AI 結合環境感測與大數據，提供山區災害風險分級與資源缺口分析。")

    st.subheader("📡 環境感測與風險評估模組 (Open Data)")
    col_w1, col_w2, col_w3 = st.columns(3)
    with col_w1: st.metric("🌧️ 氣象署 24H 累積雨量", "452 mm", "超大豪雨警戒", delta_color="inverse")
    with col_w2: st.metric("⛰️ 水保署土石流潛勢", "12 條紅黃色警戒", "仁愛鄉、信義鄉", delta_color="inverse")
    with col_w3: st.metric("🚧 公路局省道災阻", "3 處完全中斷", "台14線、台21線", delta_color="inverse")

    st.divider()

    island_demands = [d for d in st.session_state.demands if d.get("island_effect", False) and d.get("status") != "已處理"]
    st.subheader("🚨 AI 災情總覽與高風險孤島")
    if island_demands:
        st.error(f"⚠️ **高風險警告 (孤島效應)**：偵測到 {len(island_demands)} 處聚落因道路中斷受困！建議優先啟動空投。")
        df_island = pd.DataFrame(island_demands)[["location", "item", "affected_people", "urgency"]]
        df_island.columns = ["受困地點", "急需物資", "預估受困人數", "緊急度"]
        st.dataframe(df_island, hide_index=True, use_container_width=True)
    else:
        st.success("🎉 目前轄區內尚未偵測到因交通中斷導致的孤島效應。")

def page_map_pool():
    st.title("🗺️ 災情與全局資源戰情地圖")
    st.caption("同步整合現場純災情、前線物資需求與後勤庫存供給，提供指揮官全局空間調配視野。")

    st.markdown("### 🛠️ 地圖戰情圖層控制")
    col1, col2, col3 = st.columns(3)
    with col1: view_disaster = st.checkbox("🚨 顯示現場純災情通報 (🟠 橘色標記)", value=True)
    with col2: view_demand = st.checkbox("🔴 顯示前線物資需求池 (🔴 紅色標記)", value=True)
    with col3: view_supply = st.checkbox("🟢 顯示後勤可用供給庫存 (🟢 綠色標記)", value=True)

    map_data = []
    if view_disaster:
        for d in st.session_state.disasters:
            map_data.append({"latitude": float(d.get("lat", 23.5)), "longitude": float(d.get("lon", 121.0)), "color": "#FF8C00"})
    if view_demand:
        for d in st.session_state.demands:
            if d.get("status") in ["未處理", "部分配對 (尚缺)"]:
                map_data.append({"latitude": float(d.get("lat", 23.5)), "longitude": float(d.get("lon", 121.0)), "color": "#FF0000"})
    if view_supply:
        for s in st.session_state.supplies:
            if s.get("status") == "可調派":
                map_data.append({"latitude": float(s.get("lat", 23.5)), "longitude": float(s.get("lon", 121.0)), "color": "#008000"})

    if map_data:
        st.map(pd.DataFrame(map_data), latitude="latitude", longitude="longitude", color="color", size=30)
    else:
        st.info("💡 目前所選圖層內無資料。")

# =========================================================
# 6. 民眾與企業端功能
# =========================================================
def page_chatbot():
    user = get_current_user()
    st.title("💬 智慧對話通報 (AI 災情分析)")
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])
            
    if user_input := st.chat_input("輸入範例：台14線道路坍方，南豐村急需 50 份糧食！"):
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"): st.markdown(user_input)
            
        with st.chat_message("assistant"):
            with st.spinner("AI 正在分析災情與孤島風險..."):
                result = extract_info_with_ai(raw_text=user_input)
                if "error" in result:
                    reply = "❌ 系統解析發生錯誤，請稍後重試。"
                else:
                    info_type = result.get("info_type", "").lower()
                    if "irrelevant" in info_type:
                        reply = "⚠️ 無法辨識災情或物資內容，請具體說明狀況。"
                    else:
                        ext = result.get("data", result)
                        lat, lon = float(ext.get("lat", 23.8)), float(ext.get("lon", 121.0))
                        district = ext.get("district", user.get("district"))
                        
                        if "disaster" in info_type:
                            st.session_state.disasters.insert(0, {
                                "id": make_id("E"), "time": now_str(), "district": district, 
                                "lat": lat, "lon": lon, "description": ext.get("item", "純災情"),
                                "status": "未處理", "island_effect": ext.get("island_effect", False)
                            })
                            reply = f"🚨 **災情已記錄**！標記於防災地圖 (AI定位: {district} / 孤島效應: {ext.get('island_effect')})"
                        elif "demand" in info_type:
                            st.session_state.demands.insert(0, {
                                "id": make_id("D"), "time": now_str(), "district": district, "item": ext.get("item"), 
                                "qty": ext.get("qty", 1), "lat": lat, "lon": lon, "status": "未處理", 
                                "verification_status": "pending", "island_effect": ext.get("island_effect", False),
                                "affected_people": ext.get("affected_people", 0)
                            })
                            reply = f"✅ **需求立案**：{ext.get('item')} x {ext.get('qty')} (AI定位: {district} / 孤島警示: {ext.get('island_effect')})"
                        else:
                            reply = "✅ 已為您建立供給紀錄。"
                            
            st.markdown(reply)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})

def page_company_supply_center():
    user = get_current_user()
    st.title("📦 企業資源供給中心 (AI 優先)")
    st.caption("透過對話快速輸入可支援南投山區的物資與載具。")
    if "comp_supply_chat" not in st.session_state: st.session_state.comp_supply_chat = []
    
    for msg in st.session_state.comp_supply_chat:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])
            
    if user_input := st.chat_input("範例：我們基金會可提供 100 份保暖衣物，存放在埔里鎮。"):
        st.session_state.comp_supply_chat.append({"role": "user", "content": user_input})
        with st.chat_message("user"): st.markdown(user_input)
        with st.chat_message("assistant"):
            with st.spinner("AI 解析中..."):
                result = extract_info_with_ai(raw_text=f"請以 Supply 解析：{user_input}")
                if "error" not in result and "irrelevant" not in result.get("info_type", "").lower():
                    ext = result.get("data", result)
                    record = {
                        "id": make_id("S"), "time": now_str(), "provider_id": user.get("id"),
                        "provider": user.get("name"), "item": ext.get("item"), "qty": ext.get("qty", 1),
                        "district": ext.get("district", user.get("district")), "status": "可調派",
                        "verification_status": "verified" if user.get("verified") else "pending",
                        "lat": float(ext.get("lat", 23.8)), "lon": float(ext.get("lon", 121.0))
                    }
                    st.session_state.supplies.insert(0, record)
                    reply = f"✅ **成功建立供給**：{record['item']} x {record['qty']} (倉儲：{record['district']})"
                else:
                    reply = "⚠️ 無法辨識供給內容。"
            st.markdown(reply)
            st.session_state.comp_supply_chat.append({"role": "assistant", "content": reply})

def page_company_claim_center():
    st.title("🤝 企業智慧認領中心")
    st.caption("瀏覽並認領南投山區的物資需求。")
    public_demands = [d for d in st.session_state.demands if d.get("status") in ["未處理", "部分配對 (尚缺)"]]
    
    if public_demands:
        for d in public_demands:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    island_tag = "⚠️ **[孤島重災區]** " if d.get("island_effect") else ""
                    st.markdown(f"#### {island_tag}{d['item']} (需 {d['qty']})")
                    st.write(f"📍 {d.get('district', '')} | 影響人數: {d.get('affected_people', 0)}")
                with col2:
                    if st.button("我要認領", key=f"claim_{d['id']}", use_container_width=True):
                        st.success(f"已送出 {d['item']} 的認領申請，待中心核准！")
    else:
        st.info("目前無待處理需求。")

def page_placeholder(title):
    st.title(title)
    st.info("功能開發中，敬請期待！")

# =========================================================
# 7. Main App 與 側邊欄路由
# =========================================================
st.set_page_config(page_title="MountainGuard AI", layout="wide", page_icon="🏔️")
init_session_state()

if not is_logged_in():
    login_panel()
    st.stop()

user = get_current_user()
role = user.get("role")

with st.sidebar:
    st.markdown(f"""
    <div style="padding: 15px; border-radius: 10px; background-color: #f0f2f6; margin-bottom: 20px;">
        <h4 style="margin:0; color: #31333F;">👤 {user.get('name')}</h4>
        <p style="margin:0; font-size: 14px; color: #5c5c5c; line-height: 1.5;">
            🏷️ 角色：{ROLE_LABELS.get(role, '未知')}<br>
            📍 轄區：{user.get('district', '全區')}
        </p>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    role_pages = {
        "citizen": ["💬 AI 災情與需求通報", "🗺️ 災情與資源地圖", "📌 我的紀錄", "👤 個人設定"],
        "company": ["📦 提供供給 (AI 優先)", "🤝 認領需求 (AI 優先)", "🗺️ 公開資源池", "👤 個人設定"],
        "government": ["📊 智慧決策儀表板", "🗺️ 災情與資源地圖", "✅ 資源核准與調度", "👤 個人設定"],
        "admin": ["⚙️ 系統總覽"]
    }

    page = st.radio("功能選單", role_pages.get(role, ["首頁"]))

    st.divider()
    if st.button("🚪 登出系統", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.current_user = None
        st.rerun()

# 路由綁定
if page == "💬 AI 災情與需求通報": page_chatbot()
elif page == "📦 提供供給 (AI 優先)": page_company_supply_center()
elif page == "🤝 認領需求 (AI 優先)": page_company_claim_center()
elif page == "📊 智慧決策儀表板": page_gov_inbox()
elif page in ["🗺️ 災情與資源地圖", "🗺️ 公開資源池"]: page_map_pool()
elif page == "✅ 資源核准與調度": page_placeholder("✅ 資源核准與調度 (審核中心)")
elif page == "📌 我的紀錄": page_placeholder("📌 我的紀錄")
elif page == "👤 個人設定": page_placeholder("👤 個人設定")
elif page == "⚙️ 系統總覽": page_placeholder("⚙️ 系統管理員後台")
else:
    st.title("歡迎使用 MountainGuard AI")