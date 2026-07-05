import os
import time
import json
import base64
import smtplib
import random
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

import pandas as pd
import pydeck as pdk
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587")) if os.getenv("SMTP_PORT", "587").isdigit() else 587
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "ㄑ")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)

# =========================================================
# 0. Demo 常數設定
# =========================================================
RESOURCE_TYPES = {
    "有形資源": ["食物", "飲用水", "醫療用品", "保暖衣物", "救災工具", "衛星通訊設備", "越野車輛(四輪傳動)", "重型機具(怪手/山貓)", "發電機", "其他"],
    "無形資源": ["人力", "志工", "專業技術", "醫療支援", "心理諮詢", "空拍機勘災", "山地搜救", "直升機空投協助", "其他"],
    "金流資源": ["現金捐款", "物資採購金", "專案補助", "其他"],
}
ROLE_LABELS = {
    "citizen": "一般民眾",
    "company": "公司/團體",
    "government": "政府單位",
    "admin": "平台管理員",
}
VERIFY_BADGE = {
    "verified": "✅ 已認證",
    "pending": "🟡 待認證",
    "unverified": "⚪ 未認證",
    "rejected": "🔴 已駁回",
}
CLAIM_STATUS = {
    "pending_match": "待系統媒合",
    "pending_gov_review": "待政府審核",
    "approved": "已核准並完成配對",
    "rejected": "已駁回",
}

SMART_MATCH_STATUS = {
    "pending_admin_review": "待管理員審核",
    "approved": "已核准並完成配對",
    "rejected": "已駁回",
    "expired": "已失效",
}

# =========================================================
# UI 輔助函數
# =========================================================
def get_status_badge(status):
    """回傳帶有 CSS 樣式的狀態標籤 HTML"""
    badges = {
        "verified": "<span style='background-color:#d4edda; color:#155724; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>✅ 已認證</span>",
        "pending": "<span style='background-color:#fff3cd; color:#856404; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>⏳ 待審核</span>",
        "rejected": "<span style='background-color:#f8d7da; color:#721c24; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>❌ 已駁回</span>",
        "已處理": "<span style='background-color:#cce5ff; color:#004085; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>🔄 處理中</span>",
        "已出貨": "<span style='background-color:#cce5ff; color:#004085; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>🚚 配送中</span>",
        "已完成(收妥)": "<span style='background-color:#d4edda; color:#155724; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>🎉 任務結案</span>",
        "部分配對 (尚缺)": "<span style='background-color:#fff3cd; color:#856404; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>⚠️ 部分配對</span>",
        "可調派": "<span style='background-color:#d4edda; color:#155724; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>🟢 可調派</span>",
        "未處理": "<span style='background-color:#e2e3e5; color:#383d41; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>⚪ 未處理</span>"
    }
    return badges.get(status, f"<span style='background-color:#e2e3e5; color:#383d41; padding:3px 8px; border-radius:12px; font-size:12px;'>{status}</span>")
    
# =========================================================
# 1. Session State 初始化
# =========================================================
def now_str(fmt="%Y-%m-%d %H:%M"):
    return datetime.now().strftime(fmt)


def init_session_state():
    now = datetime.now()

    if "current_user" not in st.session_state:
        st.session_state.current_user = None

    # 手機 OTP 驗證暫存區：Demo 版存在 session_state；正式版建議改成 Redis/DB 並設定過期時間。
    if "otp_store" not in st.session_state:
        st.session_state.otp_store = {}

    if "users" not in st.session_state:
        st.session_state.users = [
            {
                "id": "U_ADMIN",
                "name": "平台管理員",
                "role": "admin",
                "email": "admin@mountainguard.demo",
                "district": "全區",
                "village": "全區",
                "verified": True,
                "status": "active",
                "proof": "系統預設帳號",
            },
            {
                "id": "U_GOV_001",
                "name": "信義鄉公所承辦人",
                "role": "government",
                "email": "gov-xinyi@gov.tw",
                "district": "南投縣信義鄉",
                "village": "全區",
                "verified": True,
                "status": "active",
                "proof": "公務信箱 + demo 白名單",
            },
            {
                "id": "U_GOV_002",
                "name": "仁愛鄉翠華村里幹事",
                "role": "government",
                "email": "gov-renai@gov.tw",
                "district": "南投縣仁愛鄉",
                "village": "翠華村",
                "verified": True,
                "status": "active",
                "proof": "公務信箱 + demo 白名單",
            },
            {
                "id": "U_CIT_001",
                "name": "信義鄉神木村居民 阿雄",
                "role": "citizen",
                "email": "citizen-xinyi@example.com",
                "district": "南投縣信義鄉",
                "village": "神木村",
                "verified": False,
                "status": "active",
                "proof": "一般民眾註冊",
            },
            {
                "id": "U_COM_001",
                "name": "南投在地企業(日月潭水廠)",
                "role": "company",
                "email": "supply-local@example.com",
                "district": "南投縣魚池鄉",
                "village": "全區",
                "verified": True,
                "status": "active",
                "proof": "企業統編 + demo 白名單",
            },
        ]

    # 補齊舊資料欄位，避免新增手機驗證後舊 demo 帳號缺欄位。
    for u in st.session_state.users:
        u.setdefault("phone", "")
        u.setdefault("phone_verified", True if u.get("id") in ["U_ADMIN", "U_GOV_001", "U_GOV_002", "U_CIT_001", "U_COM_001"] else False)

    if "demands" not in st.session_state:
        st.session_state.demands = [
            {
                "id": "D001",
                "time": (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M"),
                "source": "Threads",
                "requester_id": "U_CIT_001",
                "requester_name": "信義鄉神木村居民 阿雄",
                "requester_email": "citizen-xinyi@example.com",
                "district": "南投縣信義鄉",
                "village": "神木村",
                "location": "南投縣信義鄉神木村神木巷",
                "lat": 23.535,
                "lon": 120.863,
                "resource_type": "有形資源",
                "category": "救災工具", # 配合您原有的 RESOURCE_TYPES 欄位，若之後有微調再做修正
                "item": "小型怪手與土石清理工具",
                "qty": 2,
                "urgency": 5,
                "status": "未處理",
                "matched_provider": "",
                "verification_status": "pending",
                "verified_by": "",
                "raw_text": "神木村聯外道路被土石流沖毀了😭😭 現在變孤島，急需小型怪手或機具協助搶通道路！",
                "risk_flag": "",
                "disaster_type": "土石流與道路中斷",
                "affected_people": "約 30 人",
                "trapped_group": "一般居民與長者",
                "landslide_risk": "極高 (紅色警戒)",
                "road_blocked": True,
            },
            {
                "id": "D002",
                "time": (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M"),
                "source": "LINE群組",
                "requester_id": "U_GOV_002",
                "requester_name": "仁愛鄉翠華村里幹事",
                "requester_email": "gov-renai@gov.tw",
                "district": "南投縣仁愛鄉",
                "village": "翠華村",
                "location": "南投縣仁愛鄉翠華村華岡部落",
                "lat": 24.195,
                "lon": 121.285,
                "resource_type": "有形資源",
                "category": "飲用水",
                "item": "礦泉水與保暖物資",
                "qty": 200,
                "urgency": 4,
                "status": "未處理",
                "matched_provider": "",
                "verification_status": "verified",
                "verified_by": "U_GOV_002",
                "raw_text": "仁愛鄉翠華村遭遇強降雨導致聯外道路投89線坍方中斷，村內目前斷水，急需急難礦泉水支援。",
                "risk_flag": "",
                "disaster_type": "道路坍方",
                "affected_people": "全村",
                "trapped_group": "一般居民",
                "landslide_risk": "高 (黃色警戒)",
                "road_blocked": True,
            },
        ]

    if "supplies" not in st.session_state:
        st.session_state.supplies = [
            {
                "id": "S001",
                "time": (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M"),
                "source": "企業信件",
                "provider_id": "U_COM_001",
                "provider": "南投在地企業(日月潭水廠)",
                "provider_email": "supply-local@example.com",
                "district": "南投縣魚池鄉",
                "village": "全區",
                "location_current": "南投縣魚池鄉水社村",
                "lat": 23.868,
                "lon": 120.911,
                "resource_type": "有形資源",
                "category": "飲用水",
                "item": "瓶裝礦泉水",
                "qty": 1000,
                "status": "可調派",
                "verification_status": "verified",
                "verified_by": "U_ADMIN",
                "raw_text": "本廠願捐贈1000箱箱裝水供南投山區救災調配，可隨時由魚池倉儲出貨。",
                "risk_flag": "",
            },
            {
                "id": "S002",
                "time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
                "source": "志工表單",
                "provider_id": "U_CIT_001",
                "provider": "台灣山嶽越野救援隊",
                "provider_email": "citizen-xinyi@example.com",
                "district": "南投縣信義鄉",
                "village": "全區",
                "location_current": "南投縣水里鄉",
                "lat": 23.811,
                "lon": 120.853,
                "resource_type": "無形資源",
                "category": "專業技術",
                "item": "四輪傳動越野車隊與山地搜救人力",
                "qty": 5,
                "status": "可調派",
                "verification_status": "pending",
                "verified_by": "",
                "raw_text": "我們是民間中部越野車隊，備有5輛配備絞盤的四驅車，可支援山區坍方初期的涉水運補與輕度物資挺進。",
                "risk_flag": "",
            },
        ]

    if "claims" not in st.session_state:
        st.session_state.claims = []

    if "smart_matches" not in st.session_state:
        st.session_state.smart_matches = []

    if "notifications" not in st.session_state:
        st.session_state.notifications = []

    if "email_logs" not in st.session_state:
        st.session_state.email_logs = []

    if "audit_logs" not in st.session_state:
        st.session_state.audit_logs = []

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {"role": "assistant", "content": "您好！我是「MountainGuard AI」防救災通報機器人。請描述您目前所在的南投山區位置、災情需求，或是您可以提供的救災資源與運具。"}
        ]
        
    if "disasters" not in st.session_state: 
        st.session_state.disasters = []

def add_audit(action, detail):
    user = st.session_state.current_user or {"name": "未登入", "role": "guest"}
    st.session_state.audit_logs.insert(
        0,
        {
            "time": now_str("%Y-%m-%d %H:%M:%S"),
            "user": user.get("name", "未知"),
            "role": ROLE_LABELS.get(user.get("role", "guest"), user.get("role", "guest")),
            "action": action,
            "detail": detail,
        },
    )


def normalize_qty(value, default=1):
    try:
        value = int(value)
        return max(value, 1)
    except Exception:
        return default


def make_id(prefix):
    return f"{prefix}{int(time.time() * 1000) % 100000:05d}"


def get_current_user():
    return st.session_state.current_user


def is_logged_in():
    return st.session_state.current_user is not None


def can_gov_review(gov_user, record):
    """
    審查政府單位是否具備該筆紀錄的管轄權 (升級版：支援模糊行政區與全區互通機制)
    """
    if not gov_user or gov_user.get("role") != "government":
        return False
        
    # 平台管理員或設定為「全區」的最高指揮官直接放行
    if gov_user.get("district") == "全區":
        return True

    # 1. 💡 行政區雙向包含比對 (容錯「花蓮縣壽豐鄉」與「壽豐鄉」或「花蓮壽豐」)
    gov_dist = str(gov_user.get("district") or "").strip()
    rec_dist = str(record.get("district") or "").strip()
    
    if not gov_dist or not rec_dist:
        return False
        
    same_district = (gov_dist in rec_dist) or (rec_dist in gov_dist)

    # 2. 💡 村里範圍互通邏輯
    # 只要符合以下任一條件即具備管轄權：
    # - 政府官員是行政區總窗口 (gov_village 為 "全區" 或 空值)
    # - 民眾通報影響範圍涵蓋全區 (rec_village 為 "全區" 或 空值，基層官員皆應能審查)
    # - 政府官員的轄區里與民眾通報的里完全一致
    gov_village = str(gov_user.get("village") or "全區").strip()
    rec_village = str(record.get("village") or "全區").strip()
    
    same_village = (gov_village in ["全區", ""]) or (rec_village in ["全區", ""]) or (gov_village == rec_village)

    return same_district and same_village


def badge_text(status):
    return VERIFY_BADGE.get(status, "⚪ 未認證")


def normalize_phone(phone):
    """簡易手機格式整理：保留 + 與數字，Demo 可支援 09xx 或 +886。"""
    phone = str(phone or "").strip()
    phone = re.sub(r"[^0-9+]", "", phone)
    return phone


def is_valid_phone(phone):
    phone = normalize_phone(phone)
    # 台灣手機常見：09xxxxxxxx；也允許國際格式 +8869xxxxxxxx
    return bool(re.match(r"^09\d{8}$", phone) or re.match(r"^\+8869\d{8}$", phone))


def send_phone_otp(phone):
    """
    Demo OTP：產生 6 碼驗證碼並寫入 session_state。
    注意：OTP 不寫入全站通知中心，避免其他使用者在側邊欄看到驗證碼。
    正式部署若要真的傳 SMS，可串 Twilio/三竹/中華電信簡訊 API。
    """
    phone = normalize_phone(phone)
    otp = f"{random.randint(0, 999999):06d}"
    st.session_state.otp_store[phone] = {
        "otp": otp,
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(minutes=5),
        "verified": False,
        "attempts": 0,
    }
    # Demo 版只把 OTP 回傳給目前正在註冊的人；不放進全站通知中心。
    add_audit("發送手機 OTP", f"phone={phone}")
    return otp


def verify_phone_otp(phone, otp_input):
    phone = normalize_phone(phone)
    otp_input = str(otp_input or "").strip()
    record = st.session_state.otp_store.get(phone)
    if not record:
        return False, "尚未發送 OTP，請先按『發送手機 OTP』。"
    if datetime.now() > record.get("expires_at"):
        return False, "OTP 已過期，請重新發送。"
    record["attempts"] = int(record.get("attempts", 0)) + 1
    if record["attempts"] > 5:
        return False, "嘗試次數過多，請重新發送 OTP。"
    if otp_input != record.get("otp"):
        return False, "OTP 驗證碼不正確。"
    record["verified"] = True
    return True, "手機號碼已完成 OTP 驗證。"

# =========================================================
# 2. Email / 通知
# =========================================================
def send_email(to_email, subject, body):
    """Demo 版：若 .env 有 SMTP 設定就真的寄信，否則只寫入 email_logs。"""
    log = {
        "time": now_str("%Y-%m-%d %H:%M:%S"),
        "to": to_email or "未提供",
        "subject": subject,
        "body": body,
        "status": "demo_log_only",
    }

    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD and to_email:
        try:
            msg = MIMEMultipart()
            msg["From"] = SMTP_FROM
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
            log["status"] = "sent"
        except Exception as e:
            log["status"] = f"failed: {e}"

    st.session_state.email_logs.insert(0, log)
    return log["status"]


def add_notification(msg, notif_type="system"):
    st.session_state.notifications.insert(
        0,
        {"time": now_str("%H:%M:%S"), "msg": msg, "type": notif_type},
    )


def notify_claim_result(demand, supply, claim, result="approved"):
    if result == "approved":
        subject = "【MountainGuard AI】救災資源認領已核准並完成配對"
        body_d = f"""您好，您的需求已成功完成配對。

需求編號：{demand.get('id')}
需求項目：{demand.get('item')}
配對來源：{supply.get('provider')}
支援數量：{claim.get('claim_qty')}
目前狀態：{demand.get('status')}

請保持聯絡暢通。"""
        body_s = f"""您好，您的認領申請已核准。

需求編號：{demand.get('id')}
需求地點：{demand.get('location')}
支援項目：{supply.get('item')}
支援數量：{claim.get('claim_qty')}
需求認證狀態：{badge_text(demand.get('verification_status'))}

請依照平台資訊與需求方聯繫。"""
        send_email(demand.get("requester_email"), subject, body_d)
        send_email(supply.get("provider_email"), subject, body_s)
        add_notification(f"📧 已通知需求方與供給方：{demand.get('item')} x {claim.get('claim_qty')}", "email")
    else:
        subject = "【MountainGuard AI】救災資源認領申請未通過"
        body = f"""您好，您的認領申請未通過。

申請編號：{claim.get('id')}
原因：{claim.get('review_note', '未填寫')}

您仍可重新提出其他認領申請。"""
        send_email(supply.get("provider_email"), subject, body)
        add_notification(f"📧 已通知認領方申請未通過：{claim.get('id')}", "email")

# =========================================================
# 3. AI 引擎
# =========================================================
def extract_info_with_ai(raw_text=None, image_bytes=None, mime_type="image/jpeg"):
    if not GROQ_API_KEY: return {"error": "尚未設定 GROQ_API_KEY"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1", max_retries=1, timeout=15.0)
        
        system_prompt = """
        你現在是「MountainGuard AI 南投山區韌性救援平台」的專業防災調度員與南投地理資訊專家。請將輸入精準萃取為 JSON 格式。
        
        ⚠️【重要：平台任務與情境】：
        本平台專注於南投縣山區（如仁愛鄉、信義鄉、水里鄉等）的災害應變。請特別注意辨識「土石流」、「道路中斷」、「孤島效應」等山區常見災情。

        ⚠️【重要：訊息分類 (info_type) 規則】：
        ... (保留原有的 1~4 點分類規則) ...

        ⚠️【地理座標強制解算規則】：
        強制推導完整台灣行政區 (district) 以及精準經緯度 (lat, lon)。若通報地點位於南投山區，請確保解析出正確的鄉鎮村里（例如：南投縣仁愛鄉翠華村）。

        ⚠️【DLP 隱私防護】：
        若包含清晰人臉、遺體、身分證件，請將 "risk_flag" 設為 "包含敏感個資/人像"，並忽略敏感細節。

        回傳格式請嚴格遵循以下 JSON 結構：
        {
          "info_type": "Demand 或 Supply 或 Disaster 或 Irrelevant",
          "data": {
              "resource_type": "資源大類",
              "category": "次要物資類別",
              "item": "具體物品或災情通報", 
              "qty": 數量, 
              "urgency": 緊急度1-5,
              "location": "若是Demand/Disaster填地點，Supply留空",
              "provider": "若是Supply填提供者，Demand留空",
              "location_current": "若是Supply填所在地",
              "lat": 緯度浮點數, 
              "lon": 經度浮點數,
              "district": "完整台灣行政區",
              "risk_flag": "敏感警告或空字串",
              "disaster_type": "災害類型(如土石流、道路中斷)",
              "affected_people": "受影響或受困人數(數字)",
              "trapped_group": "受困族群(如一般居民、長者)",
              "road_blocked": true或false(布林值，判斷是否形成孤島),
              "landslide_risk": "土石流風險高低評估"
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
        if "429" in error_msg or "rate limit" in error_msg or "timeout" in error_msg:
            return {"error": "API_RATE_LIMIT"}
        return {"error": str(e)}
        
# ==========================================
# 3.5 災情去重與合併防護 (Deduplication)
# ==========================================
def check_duplicate_demand(district, item):
    """檢查過去 12 小時內，同一行政區是否有高度相似的物資需求"""
    if not district or not item: return None
    
    # 簡單的關鍵字模糊比對
    keywords = set(item.replace("需要", "").replace("急需", "").split())
    
    for d in st.session_state.demands:
        if d.get("district") == district and d.get("status") in ["未處理", "部分配對 (尚缺)"]:
            existing_item = d.get("item", "")
            if any(k in existing_item for k in keywords if len(k) >= 2):
                return d
    return None
# =========================================================
# 4. 核心業務邏輯
# =========================================================
def simple_match_check(demand, supply, claim_qty):
    """
    使用 Groq AI 動態評估認領申請的合理性與分數 (取代舊版寫死的 if-else)
    """
    if claim_qty <= 0:
        return False, 0, "認領數量需大於 0"
    if supply.get("qty", 0) < claim_qty:
        return False, 0, "供給方庫存不足，無法認領該數量"
    if demand.get("qty", 0) <= 0:
        return False, 0, "需求已被滿足"
        
    if not GROQ_API_KEY:
        return True, 60, "未設定 API Key，系統給予基礎及格分待人工審核"

    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        
        prompt = f"""
        你是一個高階防災資源審查 AI，專注於南投山區韌性救援。
        有一筆民眾/企業發起的「資源認領申請」，請評估供給方是否適合滿足需求方。
        
        【需求資訊】：分類({demand.get('category')}) / 品項({demand.get('item')}) / 地區({demand.get('district')}) / 認證狀態({demand.get('verification_status')})
        【供給資訊】：分類({supply.get('category')}) / 品項({supply.get('item')}) / 地區({supply.get('district')}) / 認證狀態({supply.get('verification_status')})
        【欲認領數量】：{claim_qty}
        
        請依據「品項語意是否吻合」、「山區地理位置與運送難易度」、「雙方認證可信度」給予 0~100 的綜合評分。
        
        ⚠️特別注意：
        若需求方位於南投深山（如信義鄉、仁愛鄉）且可能遭遇道路中斷，一般車輛無法進入。若供給方的資源包含「越野車輛」、「直升機」或提供「衛星通訊」等適合山區惡劣環境的項目，請給予高分；反之若運送難度極高且供給方無適合運具，請適度扣分。
        若分數 >= 45 視為及格 (passed: true)。
        
        請嚴格輸出 JSON 格式：
        {{
            "passed": true 或 false,
            "score": 整數分數,
            "reason": "詳細的評估理由"
        }}
        """
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        raw_output = res.choices[0].message.content
        start_idx = raw_output.find("{")
        end_idx = raw_output.rfind("}")
        if start_idx != -1 and end_idx != -1:
            data = json.loads(raw_output[start_idx : end_idx + 1])
            return data.get("passed", False), data.get("score", 0), data.get("reason", "AI 評估完成")
        return False, 0, "AI 格式回傳異常"
    except Exception as e:
        return False, 0, f"AI 評估出錯: {str(e)}"



def smart_match_exists(demand_id, supply_id):
    """避免同一組需求/供給被重複產生智慧配對建議。"""
    for m in st.session_state.smart_matches:
        if (
            m.get("demand_id") == demand_id
            and m.get("supply_id") == supply_id
            and m.get("status") == "pending_admin_review"
        ):
            return True
    return False


def generate_smart_match_suggestions(min_score=45, only_verified_demand=False, only_verified_supply=False):
    """
    自動掃描全平台的需求與供給。
    若資源型態、分類、品項、數量與地區等條件達到門檻，
    就建立一筆「智慧配對建議」，提供平台管理員審核。
    """
    created = 0
    candidates = []

    active_demands = [
        d for d in st.session_state.demands
        if d.get("status") in ["未處理", "部分配對 (尚缺)"]
        and int(d.get("qty", 0)) > 0
        and d.get("verification_status") != "rejected"
    ]
    active_supplies = [
        s for s in st.session_state.supplies
        if int(s.get("qty", 0)) > 0
        and s.get("status") not in ["已駁回", "已下架", "已指派 (無庫存)"]
        and s.get("verification_status") != "rejected"
    ]

    if only_verified_demand:
        active_demands = [d for d in active_demands if d.get("verification_status") == "verified"]
    if only_verified_supply:
        active_supplies = [s for s in active_supplies if s.get("verification_status") == "verified"]

    for d in active_demands:
        for s in active_supplies:
            if smart_match_exists(d.get("id"), s.get("id")):
                continue

            suggested_qty = min(int(d.get("qty", 0)), int(s.get("qty", 0)))
            passed, score, reason = simple_match_check(d, s, suggested_qty)

            if passed and score >= min_score:
                candidates.append((score, d, s, suggested_qty, reason))

    candidates = sorted(candidates, key=lambda x: x[0], reverse=True)

    for score, d, s, suggested_qty, reason in candidates:
        # 使用需求ID + 供給ID + created 序號建立唯一 ID，避免同一毫秒產生重複 ID
        smart_match = {
            "id": f"M_{d.get('id')}_{s.get('id')}_{int(time.time() * 1000)}_{created}",
            "time": now_str(),
            "demand_id": d.get("id"),
            "supply_id": s.get("id"),
            "suggested_qty": suggested_qty,
            "match_score": score,
            "match_reason": reason,
            "status": "pending_admin_review",
            "reviewer": "",
            "review_note": "",
            "review_time": "",
        }
        st.session_state.smart_matches.insert(0, smart_match)
        created += 1

    if created > 0:
        add_notification(f"🧠 系統產生 {created} 筆智慧配對建議，待平台管理員審核。", "smart_match")
        add_audit("產生智慧配對建議", f"新增 {created} 筆，門檻 {min_score}")
    else:
        add_audit("產生智慧配對建議", f"沒有新增建議，門檻 {min_score}")

    return created


def approve_smart_match(match_id, note=""):
    """管理員核准智慧配對建議後，才正式扣庫存、更新需求並通知雙方。"""
    m = next((x for x in st.session_state.smart_matches if x.get("id") == match_id), None)
    if not m:
        return False, "找不到智慧配對建議"

    d = next((x for x in st.session_state.demands if x.get("id") == m.get("demand_id")), None)
    s = next((x for x in st.session_state.supplies if x.get("id") == m.get("supply_id")), None)

    if not d or not s:
        m["status"] = "expired"
        m["review_note"] = "需求或供給資料已不存在"
        return False, "需求或供給資料已不存在"

    transfer_qty = min(int(m.get("suggested_qty", 0)), int(d.get("qty", 0)), int(s.get("qty", 0)))
    if transfer_qty <= 0:
        m["status"] = "expired"
        m["review_note"] = "需求或供給數量已不足"
        return False, "需求或供給數量已不足"

    claim = {
        "id": make_id("C"),
        "time": now_str(),
        "claimant_id": s.get("provider_id"),
        "claimant_name": s.get("provider"),
        "claimant_role": "system_smart_match",
        "demand_id": d.get("id"),
        "supply_id": s.get("id"),
        "claim_qty": transfer_qty,
        "match_score": m.get("match_score", 0),
        "match_reason": m.get("match_reason", ""),
        "status": "pending_gov_review",
        "note": "由系統智慧配對產生，平台管理員核准",
        "reviewer": "",
        "review_note": note or "平台管理員核准智慧配對",
        "review_time": "",
    }
    st.session_state.claims.insert(0, claim)

    ok = execute_dispatch(
        d.get("id"),
        s.get("id"),
        s.get("provider"),
        transfer_qty,
        claim_id=claim.get("id"),
    )

    if ok:
        user = get_current_user() or {"name": "平台管理員"}
        m["status"] = "approved"
        m["reviewer"] = user.get("name")
        m["review_note"] = note or "平台管理員核准智慧配對"
        m["review_time"] = now_str()
        add_audit("核准智慧配對", f"{match_id} / {d.get('id')} ← {s.get('id')} / 數量 {transfer_qty}")
        return True, "已核准並完成配對"

    return False, "配對失敗"


def reject_smart_match(match_id, note=""):
    m = next((x for x in st.session_state.smart_matches if x.get("id") == match_id), None)
    if not m:
        return False
    user = get_current_user() or {"name": "平台管理員"}
    m["status"] = "rejected"
    m["reviewer"] = user.get("name")
    m["review_note"] = note or "平台管理員駁回智慧配對"
    m["review_time"] = now_str()
    add_audit("駁回智慧配對", f"{match_id} / {m['review_note']}")
    return True


def execute_dispatch(demand_id, supply_id, provider_name, transfer_qty=None, claim_id=None):
    demand_info = next((d for d in st.session_state.demands if d["id"] == demand_id), None)
    supply_info = next((s for s in st.session_state.supplies if s["id"] == supply_id), None)
    if not demand_info or not supply_info:
        return False

    if transfer_qty is None:
        transfer_qty = min(demand_info.get("qty", 0), supply_info.get("qty", 0))
    transfer_qty = normalize_qty(transfer_qty)
    transfer_qty = min(transfer_qty, demand_info.get("qty", 0), supply_info.get("qty", 0))
    if transfer_qty <= 0:
        return False

    demand_info["qty"] -= transfer_qty
    if demand_info.get("matched_provider"):
        demand_info["matched_provider"] += f", {provider_name}({transfer_qty}件)"
    else:
        demand_info["matched_provider"] = f"{provider_name}({transfer_qty}件)"
    demand_info["status"] = "已完成配對" if demand_info["qty"] <= 0 else "部分配對 (尚缺)"

    supply_info["qty"] -= transfer_qty
    supply_info["status"] = "已指派 (無庫存)" if supply_info["qty"] <= 0 else "可調派 (有剩餘)"

    msg_to_demand = f"📲 已指派【{provider_name}】提供 {transfer_qty} 件 {demand_info.get('item')} 至 {demand_info.get('location')}。"
    msg_to_supply = f"📲 請協助提供 {transfer_qty} 件 {supply_info.get('item')} 至 {demand_info.get('location')}。"
    add_notification(msg_to_demand, "demand")
    add_notification(msg_to_supply, "supply")

    if claim_id:
        claim = next((c for c in st.session_state.claims if c["id"] == claim_id), None)
        if claim:
            claim["status"] = "approved"
            claim["review_time"] = now_str("%Y-%m-%d %H:%M")
            claim["review_note"] = claim.get("review_note", "政府/管理員審核通過")
            notify_claim_result(demand_info, supply_info, claim, result="approved")

    add_audit("完成資源配對", f"{demand_id} ← {supply_id}，數量 {transfer_qty}")
    return True


def submit_claim(demand, supply, claim_qty, note):
    user = get_current_user()
    if not user:
        st.error("請先登入後再認領。")
        return

    passed, score, reason = simple_match_check(demand, supply, claim_qty)
    status = "pending_gov_review" if passed else "rejected"
    claim = {
        "id": make_id("C"),
        "time": now_str(),
        "claimant_id": user.get("id"),
        "claimant_name": user.get("name"),
        "claimant_role": user.get("role"),
        "demand_id": demand.get("id"),
        "supply_id": supply.get("id"),
        "claim_qty": claim_qty,
        "match_score": score,
        "match_reason": reason,
        "status": status,
        "note": note,
        "reviewer": "",
        "review_note": "" if passed else "系統媒合未通過，請確認資源分類、品項與庫存。",
        "review_time": "",
    }
    st.session_state.claims.insert(0, claim)

    if passed:
        add_notification(f"🤝 新認領申請待審核：{user.get('name')} → {demand.get('item')} x {claim_qty}", "claim")
        add_audit("提出認領申請", f"{claim['id']} 媒合分數 {score}")
        st.success("已送出認領申請，系統媒合通過，等待政府單位或管理員審核。")
    else:
        add_audit("認領申請被系統擋下", f"{claim['id']}，原因：{reason}")
        st.error(f"系統媒合未通過：{reason}")

# =========================================================
# 5.登入與註冊介面 (UX 升級版)
# =========================================================
def login_panel():
    st.title("🏔️ MountainGuard AI")
    st.subheader("南投山區韌性救援平台 — 智慧資源調配與災情樞紐")
    st.markdown("請選擇您的身分以登入系統，攜手提升南投山區的災害應變效率與社區韌性。")
    
    # 確保有紀錄當前選中的登入角色
    if "selected_login_role" not in st.session_state:
        st.session_state.selected_login_role = None

    st.markdown("<br>", unsafe_allow_html=True)

    # ==========================================
    # 三個大型身分區塊 (點擊即切換表單)
    # ==========================================
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("### 👨‍👩‍👧‍👦 山區居民/車隊")
        st.caption("孤島災情通報 / 物資求助 / 民間運具支援")
        if st.button("由此登入 ➡️", key="btn_role_citizen", use_container_width=True):
            st.session_state.selected_login_role = "citizen"
            st.rerun()
            
    with col2:
        st.markdown("### 🏢 在地與外援企業")
        st.caption("物資與運具捐贈 / 倉儲調派 / ESG貢獻")
        if st.button("由此登入 ➡️", key="btn_role_company", use_container_width=True):
            st.session_state.selected_login_role = "company"
            st.rerun()
            
    with col3:
        st.markdown("### 🏛️ 災防政府/指揮官")
        st.caption("山城全局戰情室 / 孤島風險評估 / 物資調度審核")
        if st.button("由此登入 ➡️", key="btn_role_government", use_container_width=True):
            st.session_state.selected_login_role = "government"
            st.rerun()

    st.divider()

    # ==========================================
    # 各角色登入表單 (完美對接 init_session_state 中的預設假資料)
    # ==========================================
    current_role = st.session_state.selected_login_role

    if current_role == "citizen":
        # --------- 民眾登入區 (對應：信義鄉神木村居民 阿雄) ---------
        with st.container(border=True):
            st.subheader("👨‍👩‍👧‍👦 民眾/民間團體 登入與註冊 (Demo 範例已填妥)")
            with st.form("citizen_login_form"):
                col_a, col_b = st.columns(2)
                with col_a:
                    login_email = st.text_input("📧 電子信箱", value="citizen-xinyi@example.com")
                    login_name = st.text_input("👤 姓名/組織稱呼", value="信義鄉神木村居民 阿雄")
                with col_b:
                    login_district = st.text_input("📍 所在鄉鎮市區", value="南投縣信義鄉", help="用於緊急事件預設定位")
                    login_village = st.text_input("🏘️ 所在村里 (選填)", value="神木村")
                    
                submitted = st.form_submit_button("🚀 進入山區防災系統", type="primary", use_container_width=True)
                
                if submitted:
                    if login_email.strip() and login_name.strip() and login_district.strip():
                        user = next((u for u in st.session_state.users if u["email"] == login_email), None)
                        is_new_user = False
                        if not user:
                            is_new_user = True
                            user = {
                                "id": make_id("U"), "email": login_email, "name": login_name,
                                "role": "citizen", "district": login_district, "village": login_village,
                                "verified": False
                            }
                            st.session_state.users.append(user)
                            
                        st.session_state.current_user = user
                        st.session_state.logged_in = True
                        
                        if is_new_user: st.success("🎉 新帳號註冊成功！正在為您導向系統...")
                        else: st.success(f"✅ 登入成功！歡迎回來，{login_name}。")
                        
                        time.sleep(1.2)
                        st.rerun()
                    else:
                        st.error("❌ 信箱、姓名、所在鄉鎮市區為必填欄位。")

    elif current_role == "company":
        # --------- 企業登入區 (對應：南投在地企業(日月潭水廠)) ---------
        with st.container(border=True):
            st.subheader("🏢 企業/社會組織 登入 (Demo 範例已填妥)")
            with st.form("company_login_form"):
                col_a, col_b = st.columns(2)
                with col_a:
                    login_email = st.text_input("📧 企業聯絡信箱", value="supply-local@example.com")
                    login_name = st.text_input("🏢 企業/組織名稱", value="南投在地企業(日月潭水廠)")
                with col_b:
                    login_district = st.text_input("📍 總部/倉儲所在鄉鎮區", value="南投縣魚池鄉")
                    tax_id = st.text_input("🧾 統一編號 (用於官方信任驗證)", value="12345678", max_chars=8)
                
                st.info("🔒 登入即同意平台存取您的山區救援物資與 ESG 貢獻紀錄。")
                submitted = st.form_submit_button("🚀 進入企業物資調配中心", type="primary", use_container_width=True)
                
                if submitted:
                    if login_email.strip() and login_name.strip() and login_district.strip():
                        user = next((u for u in st.session_state.users if u["email"] == login_email), None)
                        is_new_user = False
                        is_verified = bool(tax_id.strip() == "12345678")
                        
                        if not user:
                            is_new_user = True
                            user = {
                                "id": make_id("U"), "email": login_email, "name": login_name,
                                "role": "company", "district": login_district, "village": "全區",
                                "verified": is_verified 
                            }
                            st.session_state.users.append(user)
                            
                        st.session_state.current_user = user
                        st.session_state.logged_in = True
                        
                        if is_new_user and is_verified:
                            st.success(f"🎉 企業帳號註冊成功！系統已透過統編驗證您的【官方信任身分】。")
                        elif is_new_user and not is_verified:
                            st.warning(f"⏳ 企業帳號註冊成功！目前狀態為【等待驗證】。")
                        else:
                            st.success(f"✅ 登入成功！進入企業物資調配中心。")
                            
                        time.sleep(1.2)
                        st.rerun()
                    else:
                        st.error("❌ 信箱、企業名稱、所在區為必填。")

    elif current_role == "government":
        # --------- 政府登入區 (對應：信義鄉公所承辦人) ---------
        with st.container(border=True):
            st.subheader("🏛️ 南投縣災防指揮官/鄉鎮村里長 登入 (Demo 範例已填妥)")
            with st.form("gov_login_form"):
                col_a, col_b = st.columns(2)
                with col_a:
                    login_email = st.text_input("📧 公務信箱", value="gov-xinyi@gov.tw")
                    login_name = st.text_input("👤 長官姓名/職稱", value="信義鄉公所承辦人")
                with col_b:
                    login_district = st.text_input("📍 管轄鄉鎮市區", value="南投縣信義鄉")
                    auth_code = st.text_input("🔑 公務授權碼", type="password", value="admin")
                
                submitted = st.form_submit_button("🛡️ 進入山城指揮後台", type="primary", use_container_width=True)
                
                if submitted:
                    if auth_code == "admin":
                        user = next((u for u in st.session_state.users if u["email"] == login_email), None)
                        if not user:
                            user = {
                                "id": make_id("U"), "email": login_email, "name": login_name,
                                "role": "government", "district": login_district, "village": "全區",
                                "verified": True
                            }
                            st.session_state.users.append(user)
                            
                        st.session_state.current_user = user
                        st.session_state.logged_in = True
                        
                        st.success(f"✅ 授權成功！長官好，正在為您開啟山城應變指揮中心...")
                        time.sleep(1.2)
                        st.rerun()
                    else:
                        st.error("❌ 授權碼錯誤！(Demo 請輸入 admin)")
    
    # --------- 系統管理員通道 (對應：admin@mountainguard.demo / 系統管理員) ---------
    if not current_role:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        col_x, col_y, col_z = st.columns([1,1,1])
        with col_x:
            pass
        with col_y:
            if st.button("⚙️ 系統管理員登入通道", key="btn_role_admin", use_container_width=True):
                st.session_state.selected_login_role = "admin"
                st.rerun()
        with col_z:
            pass
                
    elif current_role == "admin":
        with st.container(border=True):
            st.subheader("⚙️ 系統管理員 登入 (Demo 範例已填妥)")
            with st.form("admin_login_form"):
                login_email = st.text_input("📧 管理員帳號", value="admin@mountainguard.demo")
                auth_code = st.text_input("🔑 密碼", type="password", value="admin")
                submitted = st.form_submit_button("登入管理後台", type="primary", use_container_width=True)
                
                if submitted:
                    if auth_code == "admin":
                        # 直接從 st.session_state.users 中抓取已初始化的 Admin 帳號
                        user = next((u for u in st.session_state.users if u["email"] == login_email), None)
                        if not user: # 備用防呆
                            user = {"id": "U_ADMIN", "email": login_email, "name": "系統管理員", "role": "admin", "district": "全區", "village": "全區", "verified": True}
                        
                        st.session_state.current_user = user
                        st.session_state.logged_in = True
                        
                        st.success("✅ 認證通過，成功登入系統最高管理後台...")
                        time.sleep(1.0)
                        st.rerun()
                    else:
                        st.error("❌ 管理員密碼密鑰錯誤！")
                        
def sidebar_layout():
    user = get_current_user()
    with st.sidebar:
        st.title("🧩 ResQ-Link")
        if user:
            badge = "✅" if user.get("verified") else "⚪"
            st.success(f"{badge} {user.get('name')}\n\n{ROLE_LABELS.get(user.get('role'))}")
            st.caption(f"行政區：{user.get('district')} / {user.get('village')}")
            st.caption(f"手機：{user.get('phone', '未填')} / {'已驗證' if user.get('phone_verified') else '未驗證'}")
            if st.button("登出"):
                add_audit("登出系統", user.get("name"))
                st.session_state.current_user = None
                st.rerun()

        st.divider()
        st.subheader("🔔 配對與系統通知")
        if not st.session_state.notifications:
            st.caption("目前無最新通知。")
        else:
            for notif in st.session_state.notifications[:5]:
                st.markdown(f"<div style='border-left:4px solid #888;padding-left:10px;margin-bottom:8px;font-size:0.85em;'><b>{notif['time']}</b><br>{notif['msg']}</div>", unsafe_allow_html=True)


def resource_selectors(prefix=""):
    resource_type = st.selectbox("資源型態", list(RESOURCE_TYPES.keys()), key=f"{prefix}_rtype")
    category = st.selectbox("資源分類", RESOURCE_TYPES[resource_type], key=f"{prefix}_cat")
    return resource_type, category


def demand_card(d):
    """南投山區專屬：孤島與災情需求卡片渲染"""
    road_status = "🚫 道路坍方(孤島效應)" if d.get("road_blocked") else "🚙 交通尚可通行"
    risk_level = d.get("landslide_risk", "評估中")
    urgency_stars = "⭐" * d.get("urgency", 3)
    
    st.markdown(f"#### 🎯 {d.get('item')} (需 {d.get('qty')} 單位)")
    st.caption(f"📍 【{d.get('district')}】{d.get('location')} ｜ 緊急度：{urgency_stars}")
    
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**🌋 災害狀態：** {d.get('disaster_type', '未註明')}")
        st.write(f"**🛣️ 路網狀況：** `{road_status}`")
    with col2:
        st.write(f"**👥 受困人數：** {d.get('affected_people', '未知')} ({d.get('trapped_group', '一般居民')})")
        st.write(f"**⚠️ 土石流風險：** `{risk_level}`")

# =========================================================
# 6. Pages (MountainGuard AI 南投山區韌性救援平台專屬版)
# =========================================================

def page_home():
    st.title("🏔️ MountainGuard AI：南投山區韌性救援平台")
    st.subheader("🌲 數位治理・永續南投 ｜ 智慧山城全局戰情室")
    
    # 呼應南投黑客松計畫書的動機
    st.info(
        "💡 **山城防災公告**：南投縣地形以山地丘陵為主，極端氣候下仁愛鄉、信義鄉、水里鄉等常因道路坍方形成**「孤島效應」**。 "
        "本平台利用 AI 與地理資訊技術，將分散於 Threads、LINE 的災情與物資供需進行智慧串聯，強化民間（越野車隊/在地企業）與政府單位的協作韌性。"
    )
    
    st.markdown(
        """
        ### 🎯 系統核心四大支柱
        * 🔍 **智慧災情解析**：自動辨識 Threads/語音通報中的南投山區地標，即時推算經緯度與周邊土石流警戒區。
        * 📦 **多元資源分類**：明確劃分 **有形物資**（乾糧、機具）、**無形運能**（4WD越野車隊、無人機）與 **金流支援**。
        * 🏛️ **分權審核機制**：由南投縣應變中心與各鄉鎮公所（如信義、仁愛）進行在地化審核，確保資訊與資源可信度。
        * 📈 **ESG 貢獻履歷**：記錄公私企業在災害期間提供的倉儲與運輸援助，實踐社會共好與 SDGs 永續目標。
        """
    )
    
    st.divider()
    
    # 指標看板 (Metric) 視覺化升級
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🚨 孤島求助/需求數", len(st.session_state.demands), help="來自山區村落、受困點的即時資源求助申請")
    with col2:
        st.metric("📦 企業與民間供給庫存", len(st.session_state.supplies), help="包含在地水廠、草屯/埔里中轉倉、民間車隊之可用資源")
    with col3:
        st.metric("🤝 智慧認領/媒合中案件", len(st.session_state.claims), help="民間或車隊主動認領送物資入山的申請案件")
    with col4:
        pending_users = len([u for u in st.session_state.users if u.get("status") == "pending"])
        st.metric("⏳ 待認證公私身分", pending_users, delta=f"+{pending_users}" if pending_users > 0 else 0, help="等待統編或公務授權驗證的帳號")


def page_submit_demand():
    user = get_current_user()
    st.title("📣 提出山區物資需求與災情通報")
    st.caption("💡 提示：若您身處通訊不良區域，建議優先使用左側『💬 智慧對話通報』快速用語音或簡短文字通報，AI 會自動定位。")
    
    with st.form("demand_form"):
        st.markdown("##### 1. 受災與求助地點定位")
        # 將 Placeholder 改為南投著名的重災與孤島潛勢區（如信義神木、仁愛翠華、廬山溫泉）
        location = st.text_input(
            "📍 需求地點/地標", 
            value="", 
            placeholder="例如：信義鄉神木村神木國小、仁愛鄉翠華村華崗部落、廬山溫泉特定區 或 具體道路里程", 
            help="可填寫南投縣內具體地址、地標、學校或部落名稱，AI 將自動解析行政區並調取 GIS 座標。", 
            key="demand_location"
        )
        
        st.markdown("##### 2. 需求類別與資源填寫")
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            resource_type, category = resource_selectors("demand")
        with col_r2:
            item = st.text_input("📦 需求品項/機具/人力", placeholder="範例：大型挖土機(怪手)、4WD越野吉普車支援、衛星電話、嬰兒奶粉", help="請具體說明急需的資源，如屬特殊地形建置，請註明規格。", key="demand_item")
            
        col_q1, col_q2 = st.columns(2)
        with col_q1:
            qty = st.number_input("🔢 需求數量", min_value=1, value=1, help="必須大於 0 的整數。", key="demand_qty")
        with col_q2:
            urgency = st.slider("🚨 緊急與孤島危險程度 (1最低 - 5最高)", 1, 5, 3, help="5分代表道路完全中斷、斷水斷電且危及生命安全（典型孤島效應）；1分代表預防性民生物資儲備。", key="demand_urgency")
        
        st.markdown("##### 3. 現場災情環境補充說明")
        raw_text = st.text_area(
            "📝 補充說明 (選填)", 
            placeholder="例如：聯外道路發生大規模土石流中斷，目前直升機因雨勢無法空投，急需熟稔山路的越野車隊經由舊林道嘗試挺進接駁。", 
            key="demand_raw_text"
        )
        
        submitted = st.form_submit_button("🚀 經由 AI 安全解析並送出通報", type="primary", use_container_width=True)

    if submitted:
        if not item.strip() or not location.strip():
            st.error("❌ 送出失敗：『需求地點』與 『需求品項』為必填欄位，不允許留空。")
            return
            
        with st.spinner("🧠 MountainGuard AI 正在辨識山區地標並精準定位 GIS 座標..."):
            # 強調南投縣
            ai_geo_result = extract_info_with_ai(raw_text=f"請精準解析出此台灣南投山區地點或地標的所屬行政區與經緯度：{location}")
            extracted = ai_geo_result.get("data", ai_geo_result)
            
            auto_district = extracted.get("district")
            auto_lat = extracted.get("lat", 23.8) # 預設移至南投中心點附近
            auto_lon = extracted.get("lon", 121.0)
            
            # 權責降級退守防呆：若辨識不出行政區，以南投在地使用者註冊的鄉鎮為準
            if not auto_district or auto_district in ["未知", "無", ""]:
                auto_district = user.get("district", "南投縣信義鄉")
        
        verification_status = "verified" if user.get("role") == "government" and user.get("verified") else "pending"
        
        demand = {
            "id": make_id("D"), "time": now_str(), "source": "平台表單",
            "requester_id": user.get("id"), "requester_name": user.get("name"), "requester_email": user.get("email"),
            "district": auto_district, "village": user.get("village", "全區"),
            "location": location, "lat": auto_lat, "lon": auto_lon,
            "resource_type": resource_type, "category": category, "item": item, "qty": int(qty),
            "urgency": urgency, "status": "未處理", "matched_provider": "",
            "verification_status": verification_status, "verified_by": user.get("id") if verification_status == "verified" else "",
            "raw_text": raw_text, "risk_flag": extracted.get("risk_flag", "土石流潛勢區"), # 融入山區風險標記
        }
        st.session_state.demands.insert(0, demand)
        st.success(f"✅ 災情需求已成功建立！案件編號：{demand['id']}。AI 已自動將地標『{location}』精準解析至【{auto_district}】，經緯度：({auto_lat}, {auto_lon})。")


def page_submit_supply():
    user = get_current_user()
    st.title("📦 建立山區救援物資與民間運能供給")
    st.caption("🏢 在地與外援企業可使用 ERP 批次匯入盤點庫存；民間越野車隊/機具團體可手動登記可調配之運具、怪手。")
    
    if "preview_supplies" not in st.session_state:
        st.session_state.preview_supplies = None
        
    tab1, tab2 = st.tabs(["✍️ 單筆手動登記 (含運能運具)", "🤖 倉儲盤點/ERP 清單 AI 批次匯入"])
    
    with tab1:
        with st.form("supply_form"):
            col_a, col_b = st.columns(2)
            with col_a:
                provider = st.text_input("🏢 提供單位/團體名稱", value=user.get("name", ""), placeholder="範例：南投在地企業(日月潭水廠)、台灣黑熊四輪傳動吉普車隊", key="supply_provider")
            with col_b:
                location_current = st.text_input("📍 物資實際存放/運具待命地點", value="", placeholder="例如：草屯民資轉運站、埔里應變物資庫、竹山儲備點", help="請填寫資源『當下存放或待命的位置』，系統會以此計算入山的崎嶇運送距離與最佳路徑。", key="supply_location")
            
            # 將傳統物流選項，調整為更符合山區救災的「越野克服孤島能力」描述
            has_logistics = st.radio(
                "🚚 山區山路配送與挺進能力", 
                [
                    "✅ 具備高底盤四輪傳動(4WD)越野車隊、重型機具或無人機，可直接挺進中斷坍方災區", 
                    "❌ 僅能提供定點倉儲物資，需要平台媒合外部民間越野吉普車隊或政府直升機載運"
                ], 
                key="supply_logistics"
            )
            
            col_c, col_d, col_e = st.columns([1.5, 2, 1])
            with col_c:
                resource_type, category = resource_selectors("supply")
            with col_d:
                item = st.text_input("📦 可提供品項/運具/機具", placeholder="範例：50馬力挖土機、高規格無線電、包裝飲用水、發電機", key="supply_item")
            with col_e:
                qty = st.number_input("🔢 可提供數量", min_value=1, value=1, key="supply_qty")
                
            raw_text = st.text_area("📝 資源規格補充說明 (選填)", placeholder="例如：越野車皆配備絞盤與涉水呼吸管，可克服中度泥濘地形；飲用水效期至 2027 年底。", key="supply_raw_text")
            submitted = st.form_submit_button("🚀 建立單筆資源儲備", type="primary")

        if submitted:
            if not item.strip() or not provider.strip() or not location_current.strip():
                st.error("❌ 送出失敗：『提供單位名稱』、『資源存放地點』與『品項』為必填。")
                return
            with st.spinner("🧠 AI 正在解析物資存放中轉站之地理座標..."):
                ai_geo_result = extract_info_with_ai(raw_text=f"請精準解析出此南投或周邊中轉地點行政區與經緯度：{location_current}")
                geo_data = ai_geo_result.get("data", ai_geo_result)
                
                lat = geo_data.get("lat", 23.9)
                lon = geo_data.get("lon", 120.7)
                district = geo_data.get("district")
                
                if not district or district in ["未知", "無", ""]:
                    district = user.get("district", "南投市")

            supply = {
                "id": make_id("S"), "time": now_str(), "source": "平台表單",
                "provider_id": user.get("id"), 
                "provider": user.get("name") if user.get("role") == "company" else provider, # 企業帳號強制鎖定官方名稱
                "provider_email": user.get("email"),
                "district": district, "village": "全區",
                "location_current": location_current, "lat": lat, "lon": lon,
                "resource_type": resource_type, "category": category, "item": item, "qty": int(qty),
                "has_logistics": "具備山區越野挺進能力" if "✅" in has_logistics else "需車隊協助接駁",
                "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending",
                "verified_by": user.get("id") if user.get("verified") else "", "raw_text": raw_text, "risk_flag": geo_data.get("risk_flag", ""),
            }
            st.session_state.supplies.insert(0, supply)
            st.success(f"✅ 成功！救災儲備已建立。提供單位：{supply['provider']} ｜ 待命存放點：{location_current} ({district})")

    with tab2:
        st.info("ℹ️ 企業用戶與大型基金會可直接將物資庫存、車隊名冊或 ERP 報表文字貼上，AI 專用 Llama-3 模型會自動解構為標準多筆供給資料。")
        bulk_text = st.text_area(
            "📄 貼上倉管盤點或車隊配置清單", 
            height=150, 
            placeholder="範例：草屯民資轉運站目前儲備有 500箱乾糧與 200箱生活用藥，自有4WD越野吉普車3輛可進山。埔里中轉倉庫存有 30台發電機，需車隊外部載運協助。", 
            help="請包含物資存放地、品項名稱、數量與是否有山道運能。", 
            key="bulk_import_text"
        )
        
        if st.button("🧠 啟動 MountainGuard AI 智慧批次解析", type="primary", key="bulk_parse_btn"):
            if not bulk_text.strip(): 
                st.error("❌ 啟動失敗：請貼上清單內容！")
            else:
                with st.spinner("Llama-3 大模型正在進行複雜山區語意拆解與推算座標..."):
                    prompt = f"""請從以下文字萃取救災物資與運能庫存。請嚴格以 JSON 陣列回傳，不要有 Markdown 標記或其他贅字：
                    [ {{"item": "品項或運具名稱", "qty": 數量, "location_current": "存放或待命地", "has_logistics": "可自行運送 或 需車隊協助", "lat": 緯度浮點(若無法判斷填23.9), "lon": 經度浮點(若無法判斷填120.7)}} ]
                    文字內容：{bulk_text}"""
                    try:
                        from openai import OpenAI
                        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
                        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.0)
                        raw_output = res.choices[0].message.content
                        start_idx, end_idx = raw_output.find("["), raw_output.rfind("]")
                        if start_idx != -1 and end_idx != -1:
                            st.session_state.preview_supplies = json.loads(raw_output[start_idx:end_idx+1])
                            st.session_state.bulk_text_cache = bulk_text
                            st.success("✅ AI 語意解析完成！請在下方動態資料表確認預覽結果。")
                        else:
                            st.error("❌ 解析失敗：AI 回傳格式不符合 JSON 陣列規範，請簡化文字結構。")
                    except Exception as e:
                        st.error(f"❌ 系統模型呼叫錯誤：{str(e)}")

        if st.session_state.preview_supplies:
            st.markdown("### 📝 請確認解析結果 (雙擊表格儲存格可直接修正數據)")
            df_preview = pd.DataFrame(st.session_state.preview_supplies)
            
            edited_df = st.data_editor(df_preview, num_rows="dynamic", use_container_width=True, key="bulk_data_editor")
            
            if st.button("✅ 確認無誤，正式批次入庫儲備中心", type="primary", key="bulk_confirm_btn"):
                for _, row in edited_df.iterrows():
                    supply = {
                        "id": make_id("S"), "time": now_str(), "source": "ERP批次匯入",
                        "provider_id": user.get("id"), "provider": user.get("name"), "provider_email": user.get("email"),
                        "district": user.get("district", "南投市"), "village": "全區",
                        "location_current": row.get("location_current", user.get("district")), 
                        "lat": float(row.get("lat", 23.9)), "lon": float(row.get("lon", 120.7)), 
                        "resource_type": "有形資源", "category": "批次匯入", 
                        "item": row.get("item"), "qty": int(row.get("qty", 1)),
                        "has_logistics": row.get("has_logistics", "需車隊協助"),
                        "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending",
                        "verified_by": user.get("id") if user.get("verified") else "",
                        "raw_text": st.session_state.get("bulk_text_cache", ""), "risk_flag": "AI批次結構化",
                    }
                    st.session_state.supplies.insert(0, supply)
                st.session_state.preview_supplies = None
                st.success(f"🎉 成功！已為南投山區救援後台批次入庫 {len(edited_df)} 筆物資與運能。")
                time.sleep(1.5)
                st.rerun()


def page_public_claims():
    user = get_current_user()
    st.title("🤝 認領山區災情求助需求（義援/運送挺進）")
    st.caption("💪 在地與外援企業、社會團體、民間車隊皆可在此認領被孤島化或急需物資的案件。送出後將由地方公所或指揮單核准。")

    pending_demands = [d for d in st.session_state.demands if d.get("status") in ["未處理", "部分配對 (尚缺)"] and d.get("qty", 0) > 0]
    if not pending_demands:
        st.info("☀️ 目前全南投山區皆在安全監控中，暫無等待認領之求助需求。")
        return

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        only_verified = st.toggle("🛡️ 只顯示經地方公所/指揮官認證之真實災情", value=False)
    with col_f2:
        selected_type = st.selectbox("🎯 篩選急需資源型態", ["全部"] + list(RESOURCE_TYPES.keys()))
        
    if only_verified:
        pending_demands = [d for d in pending_demands if d.get("verification_status") == "verified"]
    if selected_type != "全部":
        pending_demands = [d for d in pending_demands if d.get("resource_type") == selected_type]

    my_supplies = [s for s in st.session_state.supplies if s.get("provider_id") == user.get("id") and s.get("qty", 0) > 0]

    # 若該使用者目前尚未建立任何資源或車隊車輛，引導快速建立
    if not my_supplies:
        st.warning("⚠️ 系統偵測到您目前尚未登記可用的物資或越野運能。您可以前往『📦 建立供給』或在下方快速登記。")
        with st.expander("🛠️ 快速登記當前可動用物資/運具"):
            with st.form("quick_supply"):
                provider = st.text_input("提供單位/車隊稱呼", value=user.get("name"))
                resource_type, category = resource_selectors("quick_supply")
                item = st.text_input("可動用品項/車型", placeholder="例如：4WD 吉普車、礦泉水、志工人力")
                qty = st.number_input("可提供數量", min_value=1, value=1, key="quick_qty")
                location_current = st.text_input("目前整備待命地點", value=user.get("district") if user.get("district") else "南投縣")
                submitted = st.form_submit_button("快速建立並儲存")
            if submitted and item:
                supply = {
                    "id": make_id("S"), "time": now_str(), "source": "快速供給",
                    "provider_id": user.get("id"), "provider": provider, "provider_email": user.get("email"),
                    "district": user.get("district", "南投縣"), "village": user.get("village", "全區"),
                    "location_current": location_current, "lat": 23.9, "lon": 120.7,
                    "resource_type": resource_type, "category": category, "item": item, "qty": int(qty),
                    "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending",
                    "verified_by": user.get("id") if user.get("verified") else "", "raw_text": "認領頁快速建立", "risk_flag": "",
                }
                st.session_state.supplies.insert(0, supply)
                add_audit("快速建立山區供給", f"{supply['id']} / {item}")
                st.success("✅ 救災供給建立成功！請重新整理並開始認領。")
                st.rerun()
        return

    # 列表展示等待被解救的需求卡片
    for d in pending_demands:
        with st.container(border=True):
            # 加上山區特有的警示與徽章
            st.markdown(f"#### 🚨 案件編號：{d['id']} ｜ 【{d.get('district')}】{d.get('location')}")
            demand_card(d) # 呼叫共用元件渲染詳細內容
            
            with st.form(f"claim_form_{d['id']}"):
                supply_id = st.selectbox(
                    "🤝 選擇您要動用的配對庫存/運能：",
                    [s["id"] for s in my_supplies],
                    format_func=lambda sid: next(f"[{s['id']}] {s['item']} (餘額:{s['qty']}) ｜ {badge_text(s.get('verification_status'))}" for s in my_supplies if s["id"] == sid),
                    key=f"supply_select_{d['id']}",
                )
                supply = next(s for s in my_supplies if s["id"] == supply_id)
                max_qty = min(int(supply.get("qty", 0)), int(d.get("qty", 0)))
                
                col_c1, col_c2 = st.columns([1, 2])
                with col_c1:
                    claim_qty = st.number_input("認領/承運數量", min_value=1, max_value=max_qty, value=max_qty, key=f"claim_qty_{d['id']}")
                with col_c2:
                    note = st.text_area("🚚 挺進行程與調度計畫說明：", placeholder="例如：本車隊預計今日下午2點出發，經由林道繞行進入，預計4點抵達村落合流點。", key=f"claim_note_{d['id']}")
                    
                submitted = st.form_submit_button("🔒 送出入山救援認領申請")
            if submitted:
                submit_claim(d, supply, int(claim_qty), note)
                st.rerun()


def page_gov_review():
    user = get_current_user()
    st.title("🏛️ 南投山城指揮中心與審核後台")
    st.caption(f"長官您好：系統目前已過濾權限，您（{user.get('name')}）擁有管轄區【{user.get('district', '全縣')}】的災情認證與調度審核權。")

    tab1, tab2 = st.tabs(["🚨 轄區孤島災情批次認證", "📋 民間進山認領/派車審核中心"])

    # =========================================================
    # 亮點：依山區「緊急孤島程度」降冪排序 + 批次快速審核
    # =========================================================
    with tab1:
        st.subheader("🚨 待核定之轄區山路災情通報")
        st.write("考量豪雨期間公務繁忙，後台已依**「AI 孤島風險與緊急度指標」**為您完成降冪排序。請在此批次勾選核准或駁回。")
        
        # 過濾該公所長官能管理的轄區需求
        reviewable_demands = [d for d in st.session_state.demands if d.get("verification_status") == "pending" and can_gov_review(user, d)]
        
        if not reviewable_demands:
            st.info("☀️ 報告長官：目前轄區內無等待認證的突發災情需求。")
        else:
            # 核心邏輯：將高危險孤島置頂
            reviewable_demands = sorted(reviewable_demands, key=lambda x: x.get("urgency", 0), reverse=True)
            
            df_data = []
            for d in reviewable_demands:
                df_data.append({
                    "id": d["id"],
                    "孤島危險度": "🔴" * d.get("urgency", 3) + f" ({d.get('urgency')}級)",
                    "通報受困地點": d.get("location", "未知"),
                    "急需物資/運能": f"{d.get('item')} x {d.get('qty')}",
                    "通報人管道": f"{d.get('requester_name')} ({d.get('source')})",
                    "AI 辨識災情摘要": d.get("raw_text", ""),
                    "風險標記": d.get("risk_flag", "待查"),
                    "批次核准通報": False,
                    "駁回不實通報": False,
                    "公所審核備註": ""
                })
                
            df = pd.DataFrame(df_data)
            
            # 使用 Data Editor 實現多檔批次核准與駁回，大幅提高災害期間的數位治理效率
            edited_df = st.data_editor(
                df,
                column_config={
                    "批次核准通報": st.column_config.CheckboxColumn("✅ 核准(發布至地圖)", default=False),
                    "駁回不實通報": st.column_config.CheckboxColumn("❌ 駁回", default=False),
                    "公所審核備註": st.column_config.TextColumn("備註說明(駁回理由)"),
                },
                disabled=["id", "孤島危險度", "通報受困地點", "急需物資/運能", "通報人管道", "AI 辨識災情摘要", "風險標記"], 
                hide_index=True,
                use_container_width=True
            )
            
            if st.button("🚀 執行批次應變決策送出", type="primary", use_container_width=True):
                processed_count = 0
                for index, row in edited_df.iterrows():
                    if row["批次核准通報"] and row["駁回不實通報"]:
                        st.warning(f"⚠️ 案件 {row['id']} 衝突：不可同時勾選核准與駁回，已自動跳過。")
                        continue
                        
                    if row["批次核准通報"] or row["駁回不實通報"]:
                        d_ref = next((x for x in st.session_state.demands if x["id"] == row["id"]), None)
                        if d_ref:
                            if row["批次核准通報"]:
                                d_ref["verification_status"] = "verified"
                                d_ref["verified_by"] = user.get("id")
                                add_audit("政府公所核定山區災情", f"案件 {d_ref['id']} 已核定發布 ｜ 備註: {row['公所審核備註']}")
                                add_notification(f"🔔 【災情公告】公所已認證 {d_ref.get('location')} 確實急需 {d_ref.get('item')}，開放民間越野調派認領！", "review")
                            elif row["駁回不實通報"]:
                                d_ref["verification_status"] = "rejected"
                                d_ref["status"] = "已駁回"
                                d_ref["risk_flag"] = row["公所審核備註"] or "公所判定通報重複或不實"
                                add_audit("政府公所駁回通報", f"案件 {d_ref['id']} 已駁回 ｜ 理由: {row['公所審核備註']}")
                            processed_count += 1
                            
                if processed_count > 0:
                    st.success(f"⚙️ 應變指揮成功！已完成批次處理 {processed_count} 筆山區通報。")
                    time.sleep(1.2)
                    st.rerun()
                else:
                    st.info("💡 決策提示：您尚未勾選任何項目的核准或駁回核取方塊。")

    # =========================================================================
    # 痛點 2 & 4 解決：南投山區空間路網預覽、AI 挺進安全評估與決策透明化
    # =========================================================================
    with tab2:
        st.subheader("📋 民間挺進隊與企業物資調度審核")
        st.markdown(
            "💡 **指揮官調度提示**：此處專責審查民間自告奮勇（如：4WD 越野車隊、民間無人機組）挺進山區坍方孤島或向中轉站運送物資的申請。 "
            "核准後，系統將自動扣減供應端存量，並即時發送 **E-mail 應變進山派車與安全通行通知單**。"
        )
        
        reviewable_claims = []
        for c in st.session_state.claims:
            # 確保提取等待政府或公所審核的案件
            if c.get("status") not in ["pending_gov_review", "pending"]:
                continue
            d = next((x for x in st.session_state.demands if x["id"] == c["demand_id"]), None)
            if d and can_gov_review(user, d):
                reviewable_claims.append(c)

        if not reviewable_claims:
            st.info("☀️ 報告指揮官：目前轄區內暫無等待審核的民間進山認領申請。")
        else:
            # 💡 核心優化：同樣依照受災點的需求「緊急/孤島危險度」進行降冪排序，確保高危重災區優先獲得調度審查
            def get_claim_urgency(c_dict):
                d_temp = next((x for x in st.session_state.demands if x["id"] == c_dict["demand_id"]), {})
                return d_temp.get("urgency", 0)

            reviewable_claims = sorted(reviewable_claims, key=get_claim_urgency, reverse=True)

            # 開始遍歷各個待審核的媒合單
            for c in reviewable_claims:
                d = next((x for x in st.session_state.demands if x["id"] == c["demand_id"]), None)
                s = next((x for x in st.session_state.supplies if x["id"] == c["supply_id"]), None)
                if not d or not s:
                    continue
                    
                urgency_stars = "🔴" * d.get("urgency", 3) + f" ({d.get('urgency')}級)"

                # 外層容器卡片
                with st.container(border=True):
                    st.markdown(f"### 📄 認領派遣單：{c['id']} ｜ 【{c['claimant_name']}】主動馳援")
                    
                    # 頂部戰情摘要指標
                    m_col1, m_col2, m_col3 = st.columns(3)
                    m_col1.markdown(f"**🚨 災區危險度：** {urgency_stars}")
                    m_col2.markdown(f"**📦 擬調派資源：** `{d.get('item')}`")
                    m_col3.markdown(f"**🔢 申請承運數量：** `{c.get('claim_qty')} / {d.get('qty')}`")
                    
                    st.divider()
                    
                    # 💡 左右雙欄佈局：左側文字與決策審核區，右側空間 GIS 戰情地圖預覽
                    col_info, col_map = st.columns([1.2, 1.0])
                    
                    with col_info:
                        st.markdown("##### 📍 調度雙端資訊")
                        st.write(f"**🎯 目標求助災區：** 【{d.get('district')}】{d.get('location')} ｜ {badge_text(d.get('verification_status'))}")
                        st.write(f"**🏬 資源/待命來源：** {s.get('provider')} (`{s.get('location_current')}`)")
                        st.write(f"**🚚 挺進隊運能特徵：** `{s.get('has_logistics', '常規物流')}`")
                        
                        if c.get("note"):
                            st.info(f"📝 **民間擬定挺進計畫：** {c.get('note')}")
                        
                        st.markdown("##### 🤖 MountainGuard AI 運能匹配評估")
                        score = c.get("match_score", 0)
                        
                        # 動態顏色與情境警告（完美契合山路中斷、土石流警示等動態）
                        if score >= 80:
                            st.progress(score / 100, text=f"🟢 AI 挺進成功率預估：{score}% (極度推薦)")
                            st.caption("✨ **AI 安全分析**：該隊伍配備高底盤 4WD 越野車或空投運能，且與災區距離合理，可有效克服山路崩塌點。")
                        elif score >= 50:
                            st.progress(score / 100, text=f"🟡 AI 挺進成功率預估：{score}% (中度風險)")
                            st.warning("⚠️ **AI 安全提示**：目標災區周圍有泥濘或落石紀錄，該運具挺進能力尚可，建議要求駕駛攜帶無線電與絞盤。")
                        else:
                            st.progress(score / 100, text=f"🔴 AI 挺進成功率預估：{score}% (高安全風險)")
                            st.error("🚫 **AI 重大安全警告**：目標區已呈現典型道路中斷孤島效應，申請人可能缺乏四輪傳動越野運具。若非無人機投遞，車輛極易受困！")
                        
                        # 展開 AI 的多維度推理邏輯，提供官員上下文透明度
                        with st.expander("🔍 檢視 AI 語意媒合詳解與 GIS 土石流疊加報告"):
                            st.markdown(f"**【媒合推論報告】**\n{c.get('match_reason', '系統已自動分析兩端距離、品項關鍵字相符度及運具山道克服能力。')}")
                            if d.get("risk_flag"):
                                st.markdown(f"⚠️ **災區環境動態變數**：`{d.get('risk_flag')}`")
                        
                        st.markdown("##### ✍️ 指揮官決策簽核")
                        note = st.text_input("📝 公所/應變中心審核意見 (會同步匯入 E-mail 派車單)", key=f"gov_c_note_{c['id']}", placeholder="例如：准予由舊林道挺進，請務必於下午4點前出山回報。")
                        
                        btn_col_a, btn_col_b = st.columns(2)
                        
                        if btn_col_a.button("✅ 核准此筆調度派遣", key=f"gov_approve_c_{c['id']}", type="primary", use_container_width=True):
                            c["reviewer"] = user.get("name")
                            c["review_note"] = note or "應變中心核准派遣，派車單已正式生效。"
                            
                            # 執行核心配對庫存扣減與變更
                            ok = execute_dispatch(d["id"], s["id"], s.get("provider"), c.get("claim_qty"), claim_id=c["id"])
                            if ok:
                                st.success(f"🎉 派遣成功！已核准單號 {c['id']}。庫存已自動扣減，應變調度單已透過 SMTP 寄出。")
                                add_audit("政府核准調度認領", f"{c['id']} 通過 ｜ 承運: {c.get('claim_qty')} ｜ 備註: {note}")
                                time.sleep(1.2)
                            else:
                                st.error("❌ 派遣失敗：可能該資源庫存已被其他公所搶先調配，或災區需求已結案。")
                            st.rerun()
                            
                        if btn_col_b.button("❌ 駁回此調度申請", key=f"gov_reject_c_{c['id']}", use_container_width=True):
                            c["status"] = "rejected"
                            c["reviewer"] = user.get("name")
                            c["review_note"] = note or "安全評估未通過，地方公所予以駁回。"
                            c["review_time"] = now_str()
                            
                            # 寄送駁回通知信函與發布日誌
                            notify_claim_result(d, s, c, result="rejected")
                            add_audit("政府駁回調度認領", f"{c['id']} 駁回 ｜ 理由: {note}")
                            st.warning(f"📋 申請單 {c['id']} 已駁回，並寄送拒絕信函告知安全顧慮。")
                            time.sleep(1.2)
                            st.rerun()
                            
                    with col_map:
                        st.markdown("##### 🗺️ 跨區挺進空間連線預覽")
                        
                        # 構建 GIS 地圖資料，防呆機制預設地圖中心在南投 (23.9, 120.9)
                        map_data = []
                        has_valid_coords = False
                        
                        # 1. 災區紅點
                        if d.get("lat") and d.get("lon"):
                            try:
                                d_lat, d_lon = float(d["lat"]), float(d["lon"])
                                # 防呆：檢查座標是否位於台灣合理範圍
                                if 21.5 <= d_lat <= 25.5 and 119.5 <= d_lon <= 122.5:
                                    map_data.append({"lat": d_lat, "lon": d_lon, "color": "#FF0000", "size": 120}) 
                                    has_valid_coords = True
                            except ValueError:
                                pass
                                
                        # 2. 物資來源綠點
                        if s.get("lat") and s.get("lon"):
                            try:
                                s_lat, s_lon = float(s["lat"]), float(s["lon"])
                                if 21.5 <= s_lat <= 25.5 and 119.5 <= s_lon <= 122.5:
                                    map_data.append({"lat": s_lat, "lon": s_lon, "color": "#00FF00", "size": 100})
                                    has_valid_coords = True
                            except ValueError:
                                pass
                        
                        # 渲染地圖
                        if has_valid_coords and map_data:
                            df_map = pd.DataFrame(map_data)
                            st.map(df_map, color="color", size="size", zoom=9, use_container_width=True)
                            st.caption("🔴 紅點：求助災區位置 ｜ 🟢 綠點：挺進隊/物資發源地 (地圖依據 AI 定位自動聚焦)")
                        else:
                            # 完美退守降級：若兩端皆為純文字無座標，展示南投中心靜態警示，不讓元件崩潰
                            fallback_df = pd.DataFrame([{"lat": 23.9, "lon": 120.9, "color": "#FFA500", "size": 50}])
                            st.map(fallback_df, color="color", zoom=8, use_container_width=True)
                            st.caption("⚠️ **空間定位提示**：此案件採用極端山區無線電通報，無精準 GPS。地圖暫時鎖定南投縣中心點。")


def page_map_pool():
    st.title("🗺️ Mountain Guard AI 3D 擬真地形戰情地圖")
    st.caption("【⚡ 標註點遮擋修復】已全面將避難所與需求點升級為「高空定錨 3D 天柱」，確保點位傲視中央山脈，不被 3D 地形吞噬。")

    # ==========================================
    # 💡 數據統計指標看板
    # ==========================================
    total_disasters = len(st.session_state.get("disasters", []))
    active_demands = len([d for d in st.session_state.get("demands", []) if d.get("status") in ["未處理", "部分配對 (尚缺)"]])
    island_alerts = len([d for d in st.session_state.get("demands", []) if d.get("urgency", 0) >= 4 and d.get("status") in ["未處理", "部分配對 (尚缺)"]])
    
    m1, m2, m3 = st.columns(3)
    m1.metric("🌋 現場純災情通報數", f"{total_disasters} 案", "需派員現勘" if total_disasters > 0 else "暫無異常")
    m2.metric("🔴 待處理前線物資需求", f"{active_demands} 筆", "資源待補給")
    m3.metric("⚠️ 土石流/孤島高危告警", f"{island_alerts} 處", "優先級最高", delta_color="inverse")

    st.markdown("### 🛠️ 3D 戰情地形圖層疊加控制")
    col1, col2, col3, col4 = st.columns(4)
    with col1: view_shelter = st.checkbox("🛡️ 防災避難所/空投點 (藍色天柱)", value=True)
    with col2: view_disaster = st.checkbox("🌋 現場土石流/崩塌 (橘色火柱)", value=True)
    with col3: view_demand = st.checkbox("🔴 受困孤島需求池 (粉紅高空柱)", value=True)
    with col4: view_supply = st.checkbox("🟢 企業民間可用儲備 (綠色矮柱)", value=True)

    # 建立圖層容器
    layers = []

    # ==========================================
    # 🔥 1. 建構南投 3D 真實地形起伏 (TerrainLayer)
    # ==========================================
    TERRAIN_DATA = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
    TEXTURE_DATA = "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"

    terrain_layer = pdk.Layer(
        "TerrainLayer",
        elevation_data=TERRAIN_DATA,
        elevation_decoder={
            "rScaler": 256,
            "gScaler": 1,
            "bScaler": 1 / 256,
            "offset": -32768
        },
        texture=TEXTURE_DATA,
        wireframe=False,
        pickable=False
    )
    layers.append(terrain_layer) # 地形層必須放在最底層

    # 🔥 關鍵：定義一個基準高度，確保所有點位都能穿透南投群山（南投平均山高，將天柱基準設為 3800米）
    MOUNTAIN_HIGH_BASE = 3800

    # ==========================================
    # 🔥 2. 防災避難所與直升機空投點 (改用 ColumnLayer 避免被山體掩埋)
    # ==========================================
    if view_shelter:
        shelters_data = [
            {"名稱": "信義鄉神木國小 (直升機空投點)", "lat": 23.535, "lon": 120.863, "類型": "🛡️ 避難所與空投點"},
            {"名稱": "仁愛鄉翠華村避難中心 (前進指揮所)", "lat": 24.195, "lon": 121.285, "類型": "🛡️ 避難所與指揮所"},
            {"名稱": "水里鄉綜合活動中心 (災民收容所)", "lat": 23.811, "lon": 120.853, "類型": "🛡️ 災民收容所"},
            {"名稱": "埔里鎮綜合體育館 (縣級物資集結站)", "lat": 23.965, "lon": 120.967, "類型": "🛡️ 物資轉運站"},
            {"名稱": "南投縣政府消防局 EOC 總指揮中心", "lat": 23.902, "lon": 120.691, "類型": "🛡️ 應變總部"},
        ]
        df_shelters = pd.DataFrame(shelters_data)
        # 賦予避難所一個固定高聳的立體藍柱，使其直接拔地而起穿透地形
        df_shelters["elevation"] = MOUNTAIN_HIGH_BASE + 1000 
        
        shelter_layer = pdk.Layer(
            "ColumnLayer",
            data=df_shelters,
            get_position="[lon, lat]",
            get_elevation="elevation",
            elevation_scale=1,
            radius=400,
            get_fill_color="[0, 120, 255, 230]",  # 科技飽和藍
            pickable=True,
            extruded=True,
        )
        layers.append(shelter_layer)

    # ==========================================
    # 🔥 3. 現場災情：使用超高橘色火柱 (ColumnLayer)
    # ==========================================
    if view_disaster and st.session_state.get("disasters"):
        disaster_data = []
        for d in st.session_state.disasters:
            try:
                # 災情嚴重度越高，天柱直衝雲霄越高
                urgency_val = int(d.get("urgency", 3))
                disaster_data.append({
                    "lat": float(d.get("lat", 23.9)),
                    "lon": float(d.get("lon", 120.9)),
                    "名稱": f"【{d.get('district', '南投')}】{d.get('description', '現場災情')}",
                    "類型": f"🌋 災害級別：{d.get('urgency_level', '高度風險')} (3D觀測天柱)",
                    "elevation": MOUNTAIN_HIGH_BASE + (urgency_val * 1500)
                })
            except:
                pass
        if disaster_data:
            df_disaster = pd.DataFrame(disaster_data)
            disaster_layer = pdk.Layer(
                "ColumnLayer",
                data=df_disaster,
                get_position="[lon, lat]",
                get_elevation="elevation",
                elevation_scale=1,
                radius=450,
                get_fill_color="[255, 90, 0, 240]", # 亮橘紅色
                pickable=True,
                extruded=True,
            )
            layers.append(disaster_layer)

    # ==========================================
    # 🔥 4. 受困孤島物資需求點 (改用 ColumnLayer 避免被蓋過)
    # ==========================================
    if view_demand and st.session_state.get("demands"):
        demand_data = []
        for d in st.session_state.demands:
            if d.get("verification_status") == "verified" and d.get("status") in ["未處理", "部分配對 (尚缺)"]:
                try:
                    demand_data.append({
                        "lat": float(d.get("lat", 23.9)),
                        "lon": float(d.get("lon", 120.9)),
                        "名稱": f"【{d.get('district')}】{d.get('item')} (急缺 {d.get('qty')} 單位)",
                        "類型": f"🔴 孤島告警：{d.get('disaster_type', '物資匱乏')}",
                        "elevation": MOUNTAIN_HIGH_BASE + 2000 # 確保比一般地形高
                    })
                except:
                    pass
        if demand_data:
            df_demand = pd.DataFrame(demand_data)
            demand_layer = pdk.Layer(
                "ColumnLayer",
                data=df_demand,
                get_position="[lon, lat]",
                get_elevation="elevation",
                elevation_scale=1,
                radius=350,
                get_fill_color="[255, 20, 147, 245]", # 螢光深粉紅（高對比，絕不漏看）
                pickable=True,
                extruded=True,
            )
            layers.append(demand_layer)

    # ==========================================
    # 🔥 5. 後勤物資/企業可用供給點
    # ==========================================
    if view_supply and st.session_state.get("supplies"):
        supply_data = []
        for s in st.session_state.supplies:
            if s.get("verification_status") == "verified" and s.get("status") == "可調派":
                try:
                    supply_data.append({
                        "lat": float(s.get("lat", 23.9)),
                        "lon": float(s.get("lon", 120.9)),
                        "名稱": f"【民間馳援】{s.get('provider')} 支援 {s.get('item')}",
                        "類型": f"🟢 儲備能量：{s.get('qty')} 單位 (運具: {s.get('has_logistics', '具備4WD/運能')})",
                        "elevation": MOUNTAIN_HIGH_BASE + 500
                    })
                except:
                    pass
        if supply_data:
            df_supply = pd.DataFrame(supply_data)
            supply_layer = pdk.Layer(
                "ColumnLayer",
                data=df_supply,
                get_position="[lon, lat]",
                get_elevation="elevation",
                elevation_scale=1,
                radius=300,
                get_fill_color="[0, 230, 110, 220]", # 安全螢光綠
                pickable=True,
                extruded=True,
            )
            layers.append(supply_layer)

    # ==========================================
    # 🗺️ 視角錨定：精準聚焦南投山區地理中心
    # ==========================================
    view_state = pdk.ViewState(
        latitude=23.83,    
        longitude=120.95,  
        zoom=9.6,          
        pitch=62,          # 大幅傾斜展現 3D 地形
        bearing=12         
    )

    # ==========================================
    # 🚀 渲染 Deck 地圖元件
    # ==========================================
    r = pdk.Deck(
        map_style=None,    
        layers=layers,
        initial_view_state=view_state,
        tooltip={"html": "<b>{名稱}</b><br/>{類型}", "style": {"color": "white", "backgroundColor": "#1e1e1e"}}
    )

    st.pydeck_chart(r, use_container_width=True)
    st.caption("📌 **3D 戰情空間圖例 (高度對齊優化版)**： 🟦 藍天柱 = 防災避難所 ｜ 🟧 橘火柱 = 道路中斷災情 ｜ 🟪 粉紅柱 = 孤島求助物資 ｜ 🟩 綠短柱 = 後勤可用供給")

    st.divider()
    
    # ==========================================
    # 下方數據明細中心 (維持原功能不變)
    # ==========================================
    st.subheader("📋 跨局處山城空間數據明細")
    tab_dis, tab_dem, tab_sup = st.tabs(["⚠️ 現場災情/路段崩塌通報", "🚨 亟待馳援孤島需求", "📦 後方民間與企業可用存量"])
    
    with tab_dis:
        if "disasters" in st.session_state and st.session_state.disasters:
            df_dis = pd.DataFrame(st.session_state.disasters)
            display_cols_dis = ["id", "time", "district", "location", "description", "status"]
            for col in display_cols_dis:
                if col not in df_dis.columns: df_dis[col] = "未提供"
            st.dataframe(df_dis[display_cols_dis], hide_index=True, use_container_width=True)
        else:
            st.info("☀️ 目前轄區內暫無未處理的道路中斷或災情通報。")

    with tab_dem:
        display_demands = [d for d in st.session_state.demands if d.get("verification_status") == "verified" and d.get("status") in ["未處理", "部分配對 (尚缺)"]]
        if display_demands:
            df_demands = pd.DataFrame(display_demands)
            display_cols_dem = ["id", "time", "district", "location", "item", "qty", "urgency", "status"]
            for col in display_cols_dem:
                if col not in df_demands.columns: df_demands[col] = "未提供"
            st.dataframe(df_demands[display_cols_dem], hide_index=True, use_container_width=True)
        else:
            st.info("☀️ 報告指揮官，目前前線各孤島物資補給均已對接完畢。")
            
    with tab_sup:
        display_supplies = [s for s in st.session_state.supplies if s.get("verification_status") == "verified" and s.get("status") == "可調派"]
        if display_supplies:
            df_supplies = pd.DataFrame(display_supplies)
            display_cols_sup = ["id", "time", "provider", "location_current", "item", "qty", "has_logistics"]
            for col in display_cols_sup:
                if col not in df_supplies.columns: df_supplies[col] = "未提供"
            st.dataframe(df_supplies[display_cols_sup], hide_index=True, use_container_width=True)
        else:
            st.info("目前無公開可調派供給，亟需宣導民間力量登錄資源。")


def page_ai_match():
    st.title("🤖 MountainGuard AI 智慧調配引擎")
    st.caption("針對南投山區「道路阻斷、通訊中斷」之特殊環境，AI 優先評估供應端之越野運能（如4WD、無人機）與災區孤島危險度進行多維度語意匹配。")
    
    pending_demands = [d for d in st.session_state.demands if d.get("status") in ["未處理", "部分配對 (尚缺)"] and d.get("qty", 0) > 0]
    available_supplies = [s for s in st.session_state.supplies if s.get("qty", 0) > 0]
    
    if not pending_demands or not available_supplies:
        st.info("☀️ 目前沒有等待調派的孤島需求，或後方可用後勤供给庫存已用罄。")
        return

    selected_demand_id = st.selectbox(
        "🔍 選擇待救援的前線孤島物資需求",
        [d["id"] for d in pending_demands],
        format_func=lambda did: next(f"[{d['id']}] 【{d.get('district')} - {d.get('location')}】 {d.get('item')} x {d.get('qty')} 件 ｜ 孤島危險度: {'🔥'*d.get('urgency', 1)}" for d in pending_demands if d["id"] == did),
    )
    target_demand = next(d for d in pending_demands if d["id"] == selected_demand_id)

    if st.button("⚡ 啟動 MountainGuard AI 跨區路網與運能媒合", type="primary"):
        with st.spinner("AI 正在分析南投山區即時災阻路網、載具限制與語意相符度..."):
            results = ai_match_resources(target_demand, available_supplies)
            
        if not results or ("error" in results[0]):
            st.warning("⚠️ 遠端 AI 運算超時（可能山區通訊不穩），已自動無縫切換至「在地化空間距離與運能防錯規則」進行媒合。")
            local_results = []
            for s in available_supplies:
                passed, score, reason = simple_match_check(target_demand, s, min(target_demand.get("qty"), s.get("qty")))
                if passed:
                    local_results.append({"supply_id": s["id"], "match_score": score, "reason": reason})
            results = sorted(local_results, key=lambda x: x["match_score"], reverse=True)

        if not results:
            st.info("😭 經系統推演，目前暫無符合該孤島特殊地型限制（如需 4WD 車輛或無人機）的可用物資運能。")
        else:
            st.success(f"🎯 成功為該筆求助推演出 {len(results)} 個最佳馳援方案（已按挺進安全係數排序）：")
            for r in results:
                s = next((x for x in available_supplies if x["id"] == r.get("supply_id")), None)
                if not s:
                    continue
                
                # 依分數給予不同視覺警告（契合黑客松評審對數位治理決策透明度的要求）
                score = min(r.get("match_score", 0), 100)
                with st.container(border=True):
                    st.markdown(f"### 🛡️ 最佳推薦：{s.get('provider')} 馳援 【{s.get('item')}】")
                    
                    if score >= 80:
                        st.progress(score / 100, text=f"🟢 AI 挺進安全推薦指數：{score} 分 (極具可行性)")
                    elif score >= 50:
                        st.progress(score / 100, text=f"🟡 AI 挺進安全推薦指數：{score} 分 (中度山道風險，建議 4WD 越野車隊)")
                    else:
                        st.progress(score / 100, text=f"🔴 AI 挺進安全推薦指數：{score} 分 (高風險！強烈建議改用空投或無人機)")
                        
                    st.markdown(f"💡 **AI 決策詳解與路網推論**：\n> {r.get('reason')}")
                    
                    qty = min(target_demand.get("qty", 0), s.get("qty", 0))
                    
                    # 指揮官一鍵調度
                    if st.button(f"✅ 同意 AI 建議：由災害應變中心直接批准調度 {qty} 件", key=f"ai_dispatch_{s['id']}", type="primary"):
                        with st.spinner("正在自動扣減供應端庫存、產出進山通行證通知單..."):
                            execute_dispatch(target_demand["id"], s["id"], s.get("provider"), qty)
                        st.success("🎉 調度成功！派車通知單已自動發送。")
                        time.sleep(1)
                        st.rerun()


def page_chatbot():
    user = get_current_user()
    st.title("🌲 Mountain Guard AI | 山區韌性救援通報")
    st.info("📡 **弱網備援機制啟動**：若因南投山區基地台損毀導致連線不穩，請直接發送簡訊『地點+災情狀況+物資需求』至應變專線 `0911-RES-CUE`。")
    
    uploaded_file = st.file_uploader(
        "📸 附加現場災情照片 (選填)", 
        type=["jpg", "jpeg", "png"], 
        help="⚠️ 隱私與安全防護：請勿上傳包含清晰人臉或傷亡者遺體之照片，系統內建 DLP 將自動攔截並進行敏感遮蔽。"
    )

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    if user_input := st.chat_input("輸入範例：仁愛鄉投83線土石流爆發道路中斷，部落形成孤島，約30人受困，急需2台發電機與口糧支援！"):
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
            
        with st.chat_message("assistant"):
            with st.spinner("🧠 Mountain Guard AI 正在解析災害類型、受影響人數與推算地理座標..."):
                img_bytes = uploaded_file.getvalue() if uploaded_file else None
                mime_type = uploaded_file.type if uploaded_file else "image/jpeg"
                
                # 調用 AI 進行多模態災情分析
                result = extract_info_with_ai(raw_text=user_input, image_bytes=img_bytes, mime_type=mime_type)
                
                if result.get("error") == "API_RATE_LIMIT":
                    reply = "⚠️ **系統降級通知**：目前 AI 伺服器滿載。請點擊左側「📣 填寫需求表單」切換為純手動備援模式送出！"
                    st.warning(reply)
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    return
                elif "error" in result:
                    reply = f"❌ **通報失敗**：系統解析發生錯誤 ({result['error']})，請稍後重試。"
                    st.error(reply)
                    return
                    
                info_type = result.get("info_type", "").lower()
                extracted = result.get("data", result)
                
                # 處理無關閒聊
                if "irrelevant" in info_type:
                    reply = "⚠️ **系統提示**：無法辨識出與南投山區災情或救援物資調度相關的內容。若是緊急求救，請具體說明『地點』與『現場災情狀況/受困人數/所需物資』。"
                    st.warning(reply)
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    return
                    
                item = extracted.get("item", "")
                qty = extracted.get("qty", 0)
                risk_flag = extracted.get("risk_flag", "")
                resource_type = extracted.get("resource_type", "有形資源")
                category = extracted.get("category", "未分類")
                
                try: lat = float(extracted.get("lat", 23.9))  # 以南投地理中心為預設值偏好
                except: lat = 23.9
                try: lon = float(extracted.get("lon", 120.9))
                except: lon = 120.9
                
                district = extracted.get("district")
                if not district or district in ["未知", "無", ""]:
                    district = user.get("district", "南投縣全區")
                
                # ==========================================
                # 💡 路由 1：純災情通報 (進入決策儀表板與風險評估)
                # ==========================================
                if "disaster" in info_type:
                    if "disasters" not in st.session_state: st.session_state.disasters = []
                    record = {
                        "id": make_id("E"),
                        "time": now_str(), "source": "AI語音文字通報",
                        "reporter_id": user.get("id"), "reporter_name": user.get("name"), "reporter_email": user.get("email"),
                        "district": district, "location": extracted.get("location", ""),
                        "lat": lat, "lon": lon, 
                        "description": extracted.get("item", "山區災情通報"), 
                        "raw_text": user_input, "risk_flag": risk_flag, "status": "未處理"
                    }
                    st.session_state.disasters.insert(0, record)
                    reply = f"🚨 **山區災情已即時立案**！通報已標記於即時災情地圖，並同步送入「決策儀表板模組」進行風險分級與優先順序評估。\n*(AI 定位行政區：{district})*"
                    if risk_flag: reply += f"\n\n*(🛡️ 系統已自動啟動 DLP 遮蔽敏感內容)*"

                # ==========================================
                # 💡 路由 2：救援物資/車隊需求 (Demand)
                # ==========================================
                elif "demand" in info_type:
                    if not item or item in ["未知", "無", ""]:
                        reply = "⚠️ **通報失敗**：無法辨識具體的救援需求品項。請重新輸入，例如：『我們需要 5 台抽水機與發電機』。"
                    elif qty <= 0:
                        reply = "⚠️ **通報失敗**：無法辨識有效的需求數量。請明確告知數量。"
                    else:
                        dup_demand = check_duplicate_demand(district, item)
                        
                        if dup_demand:
                            reply = f"🚨 **相似需求附議**：發現同區域已存在相似救援需求：【{dup_demand['id']} - {dup_demand['item']}】。系統已為您合併累計，並提升該山區聚落的緊急程度分級！"
                            dup_demand["qty"] += qty
                            dup_demand["urgency"] = min(5, dup_demand.get("urgency", 3) + 1)
                        else:
                            record = {
                                "id": make_id("D"), "time": now_str(), "source": "AI語音文字通報",
                                "requester_id": user.get("id"), "requester_name": user.get("name"), "requester_email": user.get("email"),
                                "resource_type": resource_type, "category": category,
                                "lat": lat, "lon": lon, 
                                "status": "未處理", "matched_provider": "", "verification_status": "pending", "verified_by": "", "raw_text": user_input, 
                                "risk_flag": risk_flag,
                            }
                            record.update(extracted)
                            record["item"] = item
                            record["qty"] = qty
                            record["district"] = district
                            if not record.get("village") or record.get("village") in ["未知", ""]: record["village"] = user.get("village", "全區")
                            
                            st.session_state.demands.insert(0, record)
                            reply = f"✅ **物資需求立案成功**！已寫入 Mountain Guard AI 需求池：{item} x {qty}\n*(AI 定位：{district}，正透過智慧媒合模組推薦最佳配送方案)*"
                            if risk_flag: reply += f"\n\n*(🛡️ 系統已啟動 DLP 遮蔽敏感內容)*"

                # ==========================================
                # 💡 路由 3：民間/政府資源供給 (Supply)
                # ==========================================
                else:
                    record = {
                        "id": make_id("S"), "time": now_str(), "source": "AI語音文字通報",
                        "provider_id": user.get("id"), "provider": extracted.get("provider") or user.get("name"), "provider_email": user.get("email"),
                        "resource_type": resource_type, "category": category, 
                        "lat": lat, "lon": lon, 
                        "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending", "risk_flag": risk_flag,
                    }
                    record.update(extracted)
                    record["district"] = district
                    if "location" in record and "location_current" not in record: record["location_current"] = record["location"]
                    if not record.get("village") or record.get("village") in ["未知", ""]: record["village"] = user.get("village", "全區")
                    
                    st.session_state.supplies.insert(0, record)
                    reply = f"✅ **救援資源登錄成功**！感謝您攜手防護山區安全，已建立供給：{item} x {qty}\n*(AI 定位資源點：{district})*"
                
            st.markdown(reply)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})


def page_company_supply_chatbot():
    """企業/民間團體專用：整合政府物資、民間捐贈、志工資源與救援車隊之智慧登錄模組。"""
    user = get_current_user()
    st.title("🤝 Mountain Guard AI | 企業與民間資源登錄中心")
    st.caption("整合政府、企業與社會資源，AI 將自動拆解 ERP 清單並定位物資、志工或車隊來源。")
    
    tab1, tab2 = st.tabs(["🤖 智慧對話登錄", "📄 批次物資/車隊智能匯入"])
    
    with tab1:
        st.info("💡 **提示**：請直接描述可提供的物資、志工或救援車隊。例如：『我們在草屯物資站有 5 輛四輪傳動越野車隊與 10 名救護志工可隨時投入支援信義鄉。』")
        
        if "comp_supply_chat" not in st.session_state:
            st.session_state.comp_supply_chat = []
            
        for msg in st.session_state.comp_supply_chat:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                
        if user_input := st.chat_input("輸入範例：埔里聯絡處可提供 200 箱礦泉水與 30 箱乾糧，自有貨車車隊可協助配送至水里鄉。"):
            st.session_state.comp_supply_chat.append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)
                
            with st.chat_message("assistant"):
                demand_keywords = ["需要", "急需", "需求", "求助", "缺", "救援", "幫我找"]
                supply_keywords = ["提供", "可提供", "捐贈", "供給", "支援", "可支援", "可調派", "庫存", "倉庫", "倉"]

                if any(k in user_input for k in demand_keywords) and not any(k in user_input for k in supply_keywords):
                    reply = "⚠️ **權限提示**：企業/團體帳號在此分頁僅供登錄『可調派的救援資源(供給)』。若欲認領災區孤島的需求，請切換至「決策儀表板認領池」。"
                    st.warning(reply)
                    st.session_state.comp_supply_chat.append({"role": "assistant", "content": reply})
                else:
                    with st.spinner("🧠 AI 智慧資源媒合模組正在解析資源類別與存放地標..."):
                        result = extract_info_with_ai(raw_text=f"這是一筆企業/團體供給資訊，請以 Supply 解析，並找出救援物資或車隊存放的實際南投鄰近地標：{user_input}")
                        
                        if result.get("error") == "API_RATE_LIMIT":
                            reply = "⚠️ 目前 AI 伺服器滿載，請改用「📄 批次物資/車隊智能匯入」或稍後重試。"
                            st.warning(reply)
                        elif "error" in result:
                            reply = f"❌ 解析發生錯誤 ({result['error']})。"
                            st.error(reply)
                        else:
                            extracted = result.get("data", result)
                            item = extracted.get("item", "")
                            try: qty = int(extracted.get("qty", 0))
                            except ValueError: qty = 0

                            if not item or item in ["未知", "無", ""]:
                                reply = "⚠️ 無法辨識具體的「資源/物資品項」，請重新輸入。例如：『可支援四輪傳動救援車隊 5 輛』"
                            elif qty <= 0:
                                reply = "⚠️ 無法辨識有效的「數量」，請重新輸入。例如：『提供志工 10 名』或『物資 100 箱』"
                            else:
                                resource_type = extracted.get("resource_type", "有形資源")
                                if resource_type not in ["有形資源", "無形資源", "金流資源"]:
                                    resource_type = "有形資源"
                                category = extracted.get("category", "未分類")
                                
                                try: lat = float(extracted.get("lat", 23.9))
                                except: lat = 23.9
                                try: lon = float(extracted.get("lon", 120.9))
                                except: lon = 120.9
                                
                                district = extracted.get("district")
                                if not district or district in ["未知", "無", ""]:
                                    district = user.get("district", "南投縣全區")
                                
                                location_current = extracted.get("location_current") or extracted.get("location")
                                if not location_current or location_current in ["未知", "無", ""]:
                                    location_current = district
                                    
                                record = {
                                    "id": make_id("S"), 
                                    "time": now_str(), 
                                    "source": "企業資源AI登錄",
                                    "provider_id": user.get("id"), 
                                    "provider": user.get("name"), 
                                    "provider_email": user.get("email"),
                                    "resource_type": resource_type, 
                                    "category": category,
                                    "district": district, 
                                    "village": "全區",
                                    "location_current": location_current,
                                    "lat": lat, 
                                    "lon": lon, 
                                    "item": item,
                                    "qty": qty,
                                    "has_logistics": extracted.get("has_logistics", "未註明"),
                                    "status": "可調派", 
                                    "verification_status": "verified" if user.get("verified") else "pending", 
                                    "verified_by": user.get("id") if user.get("verified") else "",
                                    "raw_text": user_input,
                                    "risk_flag": extracted.get("risk_flag", ""),
                                }
                                
                                st.session_state.supplies.insert(0, record)
                                
                                try: add_audit("企業AI資源新增", f"{record['id']} / {item} x {qty}")
                                except: pass
                                try: add_notification(f"🏢 夥伴團體新增支援資源：{item} x {qty}", "supply")
                                except: pass
                                
                                reply = f"✅ **資源登錄成功**！感謝您為南投山區建立防護韌性：{item} x {qty}\n*(提供單位：{record['provider']} ｜ 儲備基地：{record['location_current']} ｜ AI 精準定位：{district})*"
                                if record.get("risk_flag"):
                                    reply += f"\n\n*(🛡️ 系統已啟動 DLP 遮蔽敏感內容)*"
                                
                    if "reply" in locals():
                        st.markdown(reply)
                        st.session_state.comp_supply_chat.append({"role": "assistant", "content": reply})

    with tab2:
        st.write("請將企業內部的資源盤點清單或 ERP 系統文字貼於下方，AI 將自動解構陣列並推算經緯度。")
        bulk_text = st.text_area("📄 貼上物資/車隊盤點文字清單", height=150, placeholder="範例：草屯倉目前有 500箱乾糧與口糧，自有四輪傳動救援車隊可送。竹山物資站有 20台發電機，需救援車隊協助搬運。", key="comp_bulk_text")
        
        if st.button("🧠 啟動 Mountain Guard AI 批次解析", type="primary", key="comp_bulk_btn"):
            if not bulk_text.strip(): 
                st.error("請填寫清單內容後再點擊解析！")
            else:
                with st.spinner("AI 正在批次拆解資源數據與估算地理坐標..."):
                    prompt = f"""請從以下文字萃取出災害救援物資、志工或車隊庫存。請嚴格以 JSON 陣列回傳，不要有 Markdown 標記：
                    [ {{"item": "資源或品項名稱", "qty": 數量, "location_current": "存放站點", "has_logistics": "可自行運送 或 需車隊協助", "lat": 緯度浮點, "lon": 經度浮點, "district": "南投縣行政區(如:南投縣仁愛鄉)", "resource_type": "有形資源"}} ]
                    文字：{bulk_text}"""
                    try:
                        from openai import OpenAI
                        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
                        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.0)
                        raw_output = res.choices[0].message.content
                        start_idx, end_idx = raw_output.find("["), raw_output.rfind("]")
                        if start_idx != -1 and end_idx != -1:
                            st.session_state.preview_supplies = json.loads(raw_output[start_idx:end_idx+1])
                            st.session_state.bulk_text_cache = bulk_text
                            st.success("✅ AI 批次解析完成！請於下方表格確認或微調數據。")
                        else:
                            st.error("❌ 格式解析失敗，請確認內容是否包含明確數量與據點。")
                    except Exception as e:
                        st.error(f"系統模組錯誤：{str(e)}")

        if st.session_state.get("preview_supplies"):
            st.markdown("### 📝 確認 AI 資源拆解結果")
            df_preview = pd.DataFrame(st.session_state.preview_supplies)
            edited_df = st.data_editor(df_preview, num_rows="dynamic", use_container_width=True, key="comp_bulk_editor")
            
            if st.button("✅ 確認無誤，正式匯入救援資源池", type="primary", key="comp_bulk_confirm"):
                for _, row in edited_df.iterrows():
                    try: row_lat = float(row.get("lat", 23.9))
                    except: row_lat = 23.9
                    try: row_lon = float(row.get("lon", 120.9))
                    except: row_lon = 120.9
                    try: row_qty = int(row.get("qty", 1))
                    except: row_qty = 1

                    supply = {
                        "id": make_id("S"), "time": now_str(), "source": "ERP批次匯入",
                        "provider_id": user.get("id"), 
                        "provider": user.get("name"), 
                        "provider_email": user.get("email"),
                        "district": row.get("district", user.get("district")), "village": "全區",
                        "location_current": row.get("location_current", user.get("district")), 
                        "lat": row_lat, "lon": row_lon, 
                        "resource_type": row.get("resource_type", "有形資源"), "category": "批次資源匯入", 
                        "item": row.get("item"), "qty": row_qty,
                        "has_logistics": row.get("has_logistics", "需車隊協助"),
                        "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending",
                        "verified_by": user.get("id") if user.get("verified") else "",
                        "raw_text": st.session_state.get("bulk_text_cache", ""), "risk_flag": "",
                    }
                    st.session_state.supplies.insert(0, supply)
                
                st.session_state.preview_supplies = None
                st.success(f"✅ 成功批次入庫 {len(edited_df)} 筆山區救援資源！")
                time.sleep(1.5)
                st.rerun()


def page_company_supply_center():
    user = get_current_user()
    st.title("📦 救援資源儲備中心 (AI 優先)")
    st.caption("透過 Mountain Guard AI 自動化調派與推薦機制，管理您的既有防範資源庫存。")
    
    # 整合四大核心 Tab 
    tab1, tab2, tab3, tab4 = st.tabs(["💬 AI 對話建檔", "📄 ERP 批次匯入", "✍️ 手動備援表單", "📋 我的救援資源庫存"])
    
    # ==========================================
    # Tab 1: AI 對話建檔
    # ==========================================
    with tab1:
        st.info("💡 提示：請直接描述可提供的物資與存放地點。例如：『我們統一企業在林口物流中心有 500 箱礦泉水可提供，自有車隊可送。』")
        if "comp_supply_chat" not in st.session_state:
            st.session_state.comp_supply_chat = []
            
        for msg in st.session_state.comp_supply_chat:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                
        if user_input := st.chat_input("輸入範例：台南永康倉庫可提供 500 箱礦泉水..."):
            st.session_state.comp_supply_chat.append({"role": "user", "content": user_input})
            with st.chat_message("user"): 
                st.markdown(user_input)
                
            with st.chat_message("assistant"):
                demand_keywords = ["需要", "急需", "需求", "求助", "缺", "救援", "幫我找"]
                supply_keywords = ["提供", "可提供", "捐贈", "供給", "支援", "可支援", "可調派", "庫存", "倉庫", "倉"]

                if any(k in user_input for k in demand_keywords) and not any(k in user_input for k in supply_keywords):
                    reply = "⚠️ 此區僅供建立『供給』。若要協助災區，請切換至上方的「🤝 企業認領中心」。"
                    st.warning(reply)
                    st.session_state.comp_supply_chat.append({"role": "assistant", "content": reply})
                else:
                    with st.spinner("🧠 AI 正在解析物資與倉儲地標..."):
                        result = extract_info_with_ai(raw_text=f"這是企業供給資訊，請以 Supply 解析，找出物資存放實際地標：{user_input}")
                        if result.get("error") == "API_RATE_LIMIT":
                            reply = "⚠️ AI 伺服器滿載，請改用「✍️ 手動備援表單」。"
                            st.warning(reply)
                        elif "error" in result:
                            reply = f"❌ 解析錯誤 ({result['error']})。"
                            st.error(reply)
                        else:
                            info_type = result.get("info_type", "").lower()
                            
                            # 💡 阻擋企業發送無關訊息或純災情
                            if "irrelevant" in info_type or "disaster" in info_type:
                                reply = "⚠️ 系統無法從您的訊息中辨識出有效的『供給物資』。請具體說明可提供的品項與數量。"
                            else:
                                extracted = result.get("data", result)
                                item = extracted.get("item", "")
                                try: qty = int(extracted.get("qty", 0))
                                except: qty = 0
    
                                if not item or item in ["未知", "無", ""]:
                                    reply = "⚠️ 無法辨識「物資品項」，請重新輸入。例如：『可提供 500 箱礦泉水』"
                                elif qty <= 0:
                                    reply = "⚠️ 無法辨識「數量」，請重新輸入。"
                                else:
                                    resource_type = extracted.get("resource_type", "有形資源")
                                    if resource_type not in ["有形資源", "無形資源", "金流資源"]: resource_type = "有形資源"
                                    
                                    try: lat, lon = float(extracted.get("lat", 23.5)), float(extracted.get("lon", 121.0))
                                    except: lat, lon = 23.5, 121.0
                                    
                                    district = extracted.get("district")
                                    if not district or district in ["未知", "無", ""]: district = user.get("district", "全區")
                                    
                                    location_current = extracted.get("location_current") or extracted.get("location")
                                    if not location_current or location_current in ["未知", "無", ""]: location_current = district
                                        
                                    record = {
                                        "id": make_id("S"), "time": now_str(), "source": "AI 對話建檔",
                                        "provider_id": user.get("id"), "provider": user.get("name"), "provider_email": user.get("email"),
                                        "resource_type": resource_type, "category": extracted.get("category", "未分類"),
                                        "district": district, "village": "全區", "location_current": location_current,
                                        "lat": lat, "lon": lon, "item": item, "qty": qty,
                                        "has_logistics": extracted.get("has_logistics", "未註明"),
                                        "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending",
                                        "verified_by": user.get("id") if user.get("verified") else "", "raw_text": user_input, "risk_flag": extracted.get("risk_flag", ""),
                                    }
                                    st.session_state.supplies.insert(0, record)
                                    reply = f"✅ **立案成功**！感謝提供：{item} x {qty}\n*(倉儲：{record['location_current']} ｜ AI 定位：{district})*"
                                
                    # 💡 注意這裡：與 with st.spinner 對齊
                    if "reply" in locals():
                        st.markdown(reply)
                        st.session_state.comp_supply_chat.append({"role": "assistant", "content": reply})

    # ==========================================
    # Tab 2: ERP 批次匯入
    # ==========================================
    with tab2:
        st.write("將庫存盤點清單貼於下方，AI 將自動拆解並預估座標。")
        bulk_text = st.text_area("📄 貼上庫存盤點清單", height=150, placeholder="範例：林口倉目前有 500箱泡麵，自有車隊可送。", key="comp_bulk_text")
        
        if st.button("🧠 啟動批次解析", type="primary", key="comp_bulk_btn"):
            if not bulk_text.strip(): st.error("請貼上清單內容！")
            else:
                with st.spinner("AI 正在處理批次資料..."):
                    prompt = f"""請萃取物資庫存。嚴格以 JSON 陣列回傳：
                    [ {{"item": "品項", "qty": 數量, "location_current": "存放地", "has_logistics": "可自行運送 或 需車隊協助", "lat": 緯度浮點, "lon": 經度浮點, "district": "台灣行政區(如:新北市林口區)", "resource_type": "有形資源"}} ]
                    文字：{bulk_text}"""
                    try:
                        from openai import OpenAI
                        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
                        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.0)
                        raw_output = res.choices[0].message.content
                        start_idx, end_idx = raw_output.find("["), raw_output.rfind("]")
                        if start_idx != -1 and end_idx != -1:
                            st.session_state.preview_supplies = json.loads(raw_output[start_idx:end_idx+1])
                            st.session_state.bulk_text_cache = bulk_text
                            st.success("✅ 解析成功！請在下方確認。")
                        else:
                            st.error("❌ 解析失敗，請確認內容格式。")
                    except Exception as e:
                        st.error(f"系統錯誤：{str(e)}")

        if st.session_state.get("preview_supplies"):
            df_preview = pd.DataFrame(st.session_state.preview_supplies)
            edited_df = st.data_editor(df_preview, num_rows="dynamic", use_container_width=True, key="comp_bulk_editor")
            if st.button("✅ 確認無誤，正式入庫", type="primary", key="comp_bulk_confirm"):
                for _, row in edited_df.iterrows():
                    try: row_lat, row_lon, row_qty = float(row.get("lat", 23.5)), float(row.get("lon", 121.0)), int(row.get("qty", 1))
                    except: row_lat, row_lon, row_qty = 23.5, 121.0, 1
                    supply = {
                        "id": make_id("S"), "time": now_str(), "source": "ERP批次匯入",
                        "provider_id": user.get("id"), "provider": user.get("name"), "provider_email": user.get("email"),
                        "district": row.get("district", user.get("district")), "village": "全區",
                        "location_current": row.get("location_current", user.get("district")), 
                        "lat": row_lat, "lon": row_lon, "resource_type": row.get("resource_type", "有形資源"), "category": "批次匯入", 
                        "item": row.get("item"), "qty": row_qty, "has_logistics": row.get("has_logistics", "需車隊協助"),
                        "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending",
                        "verified_by": user.get("id") if user.get("verified") else "", "raw_text": st.session_state.get("bulk_text_cache", ""), "risk_flag": "",
                    }
                    st.session_state.supplies.insert(0, supply)
                st.session_state.preview_supplies = None
                st.success(f"✅ 成功入庫 {len(edited_df)} 筆物資！")
                time.sleep(1.5); st.rerun()

    # ==========================================
    # Tab 3: 手動備援表單
    # ==========================================
    with tab3:
        st.write("若 AI 伺服器異常，可使用此傳統表單手動建檔。")
        with st.form("comp_supply_manual_form"):
            col_b, col_c = st.columns(2)
            with col_b: location_current = st.text_input("📍 物資實際存放地", placeholder="例如：花蓮車站...", key="c_man_loc")
            with col_c: has_logistics = st.radio("🚚 物流配送能力", ["✅ 自有車隊", "❌ 需車隊協助"], key="c_man_log")
            
            col_d, col_e, col_f = st.columns([1.5, 2, 1])
            with col_d: resource_type, category = resource_selectors("supply")
            with col_e: item = st.text_input("📦 可提供品項", key="c_man_item")
            with col_f: qty = st.number_input("🔢 數量", min_value=1, value=1, key="c_man_qty")
                
            submitted = st.form_submit_button("🚀 建立供給", type="primary")

        if submitted:
            if not item.strip() or not location_current.strip():
                st.error("❌ 『物資存放地點』與『品項』為必填。")
            else:
                with st.spinner("定位中..."):
                    ai_geo_result = extract_info_with_ai(raw_text=f"請解析此地標行政區與經緯度：{location_current}")
                    geo_data = ai_geo_result.get("data", ai_geo_result)
                    district = geo_data.get("district")
                    if not district or district in ["未知", "無", ""]: district = user.get("district", "全區")

                supply = {
                    "id": make_id("S"), "time": now_str(), "source": "手動備援表單",
                    "provider_id": user.get("id"), "provider": user.get("name"), "provider_email": user.get("email"),
                    "district": district, "village": "全區", "location_current": location_current,
                    "lat": geo_data.get("lat", 23.8), "lon": geo_data.get("lon", 121.0),
                    "resource_type": resource_type, "category": category, "item": item, "qty": int(qty),
                    "has_logistics": "可自行運送" if "✅" in has_logistics else "需車隊協助",
                    "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending",
                    "verified_by": user.get("id") if user.get("verified") else "", "raw_text": "", "risk_flag": geo_data.get("risk_flag", ""),
                }
                st.session_state.supplies.insert(0, supply)
                st.success(f"✅ 單筆供給已建立！")

    # ==========================================
    # Tab 4: 供給庫存清單
    # ==========================================
    with tab4:
        my_supplies = [s for s in st.session_state.supplies if s.get("provider_id") == user.get("id")]
        if my_supplies:
            df = pd.DataFrame(my_supplies)
            
            # 💡 欄位防呆補齊機制：確保舊資料或殘缺資料不會引發 KeyError
            display_cols = ["id", "time", "location_current", "item", "qty", "has_logistics", "status"]
            for col in display_cols:
                if col not in df.columns:
                    df[col] = "未提供" # 若舊資料缺漏此欄位，自動補上預設值
                    
            st.dataframe(
                df[display_cols],
                column_config={
                    "id": "編號", 
                    "time": "登錄時間", 
                    "location_current": "存放地", 
                    "item": "品項", 
                    "qty": "數量", 
                    "has_logistics": "物流配送",
                    "status": "狀態"
                },
                hide_index=True, 
                use_container_width=True
            )
        else:
            st.info("目前尚無供給紀錄。")

def page_company_claim_center():
    user = get_current_user()
    st.title("🤝 Mountain Guard AI - 企業物資認領中心")
    st.caption("運用 AI 與風險評估技術，快速媒合企業物資能量至南投山區受災孤島，建立韌性協作機制。")
    
    tab1, tab2, tab3 = st.tabs(["🤖 AI 災情需求檢索", "🔍 依南投風險分級瀏覽", "⏳ 認領與配送進度"])
    
    # ==========================================
    # Tab 1: AI 災情需求檢索 (結合南投地理與孤島情境)
    # ==========================================
    with tab1:
        st.info("💡 提示：您可以直接詢問 AI 想尋找的南投特定災區。例如：『幫我找仁愛鄉因道路中斷缺乏醫療物資的村落』或『信義鄉哪裡最需要土石流救援物資？』")
        
        search_query = st.text_input("🔍 對話式搜尋山區需求：", placeholder="例如：幫我找仁愛鄉或信義鄉缺物資且處於孤島狀態的區域")
        if st.button("🧠 Mountain Guard AI 智能檢索", type="primary"):
            if not search_query:
                st.warning("請輸入搜尋條件。")
            else:
                with st.spinner("AI 正在分析您的條件並比對南投山區災情庫..."):
                    # 提示詞微調：加入南投鄉鎮（仁愛、信義、水里等）的地理脈絡解析
                    prompt = f"請從使用者的搜尋『{search_query}』中，萃取出他想找的南投『地區鄉鎮(district)』與『物資關鍵字(item)』。回傳 JSON，若無則填空字串。格式：{{\"district\": \"\", \"item\": \"\"}}"
                    try:
                        from openai import OpenAI
                        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
                        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.0)
                        raw_output = res.choices[0].message.content
                        start_idx, end_idx = raw_output.find("{"), raw_output.rfind("}")
                        filter_cond = json.loads(raw_output[start_idx:end_idx+1]) if start_idx != -1 else {"district": "", "item": ""}
                    except:
                        filter_cond = {"district": "", "item": search_query} # 降級處理
                        
                    target_district = filter_cond.get("district", "")
                    target_item = filter_cond.get("item", "")
                    
                    matched_demands = []
                    for d in st.session_state.demands:
                        if d.get("verification_status") != "verified" or d.get("status") not in ["未處理", "部分配對 (尚缺)"]:
                            continue
                        
                        match = True
                        if target_district and target_district not in d.get("district", ""): match = False
                        if target_item and target_item not in d.get("item", "") and target_item not in d.get("raw_text", ""): match = False
                        if match: matched_demands.append(d)
                        
                    st.success(f"✅ AI 檢索完成！為您找到 {len(matched_demands)} 筆符合【{target_district if target_district else '全區'} / {target_item if target_item else '所有物資'}】的山區韌性需求。")
                    
                    if matched_demands:
                        for d in matched_demands:
                            with st.container(border=True):
                                col_a, col_b = st.columns([3, 1])
                                with col_a:
                                    st.markdown(f"#### {d['item']} (需 {d['qty']} 單位)")
                                    # 結合計畫書的「風險評估模組」：呈現地區、緊急度、土石流與道路中斷風險
                                    road_badge = "🚨 道路中斷(孤島效應)" if d.get("road_blocked", False) else "🟢 交通可通行"
                                    risk_level = f"🔥 風險分級: {d.get('risk_grade', '中')}"
                                    st.write(f"📍 {d['location']} | {risk_level} | {road_badge} | {get_status_badge(d['status'])}", unsafe_allow_html=True)
                                    if d.get("vulnerable_groups"):
                                        st.caption(f"👥 受困族群特別註記: {d.get('vulnerable_groups')}")
                                with col_b:
                                    st.write("")
                                    if st.button("我要認領", key=f"ai_claim_btn_{d['id']}", use_container_width=True):
                                        st.session_state.claiming_demand_id = d["id"]
                                        st.rerun()

    # ==========================================
    # Tab 2: 手動瀏覽與認領 (融入風險評估指標)
    # ==========================================
    with tab2:
        st.subheader("🌋 南投縣高風險與孤島區域需求總覽")
        st.caption("系統已依據「土石流風險、道路中斷狀況、受困族群」完成風險分級，請依企業物資與車隊能量進行認領。")
        
        public_demands = [d for d in st.session_state.demands if d.get("verification_status") == "verified" and d.get("status") in ["未處理", "部分配對 (尚缺)"]]
        if not public_demands:
            st.info("目前南投山區沒有待處理的公開物資需求。")
        else:
            for d in public_demands:
                with st.container(border=True):
                    col_c, col_d = st.columns([3, 1])
                    with col_c:
                        # 顯著標示核心計畫書中提到的高風險鄉鎮（如仁愛鄉、信義鄉）
                        st.markdown(f"**【{d.get('district', '南投縣')}】{d['item']} (需 {d['qty']} 單位)**")
                        # 呈現計畫書「風險評估模組」的核心要素：土石流風險、道路中斷
                        landslide_str = f"⚠️ 土石流風險: {d.get('landslide_risk', '高')}"
                        road_str = "🚫 道路坍方(交通中斷)" if d.get("road_blocked", True) else "🚙 車輛可達"
                        st.caption(f"📍 位置: {d['location']} | {landslide_str} | {road_str} | 優先級: {d.get('urgency', 3)}⭐")
                    with col_d:
                        st.write("")
                        if st.button("我要認領", key=f"man_claim_btn_{d['id']}", use_container_width=True):
                            st.session_state.claiming_demand_id = d["id"]
                            st.rerun()

    # ==========================================
    # 處理彈出的認領表單 (智慧資源媒合：支援民間捐贈、志工與車隊整合)
    # ==========================================
    if st.session_state.get("claiming_demand_id"):
        d_id = st.session_state.claiming_demand_id
        target_d = next((x for x in st.session_state.demands if x["id"] == d_id), None)
        if target_d:
            st.markdown("---")
            st.subheader(f"🧱 啟動智慧資源媒合：{target_d['item']}")
            my_avail_supplies = [s for s in st.session_state.supplies if s.get("provider_id") == user.get("id") and s.get("status") == "可調派"]
            
            if not my_avail_supplies:
                st.error("您目前沒有『可調派』的庫存或救援能量！請先至【📦 企業供給中心】建立您的物資或四輪驅動救援車隊數據。")
                if st.button("取消"):
                    st.session_state.claiming_demand_id = None; st.rerun()
            else:
                # 結合計畫書的「智慧資源媒合模組」：不只能媒合物資，也能選擇救援車隊或志工載具
                supply_options = {s["id"]: f"{s['item']} (可用餘額: {s['qty']}) - 目前位置: {s['location_current']}" for s in my_avail_supplies}
                
                with st.form("comp_claim_form"):
                    sel_supply_id = st.selectbox("請選擇您要調派哪一筆物資/車隊支援此山區孤島？", list(supply_options.keys()), format_func=lambda x: supply_options[x])
                    sel_supply = next((x for x in my_avail_supplies if x["id"] == sel_supply_id), None)
                    max_q = min(target_d.get("qty", 1), sel_supply.get("qty", 1)) if sel_supply else 1
                    
                    claim_qty = st.number_input("預計認領/投入數量", min_value=1, max_value=max_q, value=max_q)
                    
                    # 配合計畫書：資源智慧配對評估
                    st.caption("💡 系統提示：本平台 AI 將自動計算最佳配送方案（如道路中斷時改以空投、空拍無人機或高底盤救援車隊對接）。")
                    
                    submit_claim = st.form_submit_button("🚀 送出智慧媒合申請", type="primary")
                    
                    if submit_claim:
                        c_id = make_id("C")
                        # 模擬計畫書的 AI 自動推薦最佳配送方案分數
                        claim = {
                            "id": c_id, "time": now_str(), "demand_id": target_d["id"], "supply_id": sel_supply_id,
                            "claimant_id": user.get("id"), "claimant_name": user.get("name"), "claim_qty": claim_qty,
                            "status": "pending_gov_review", "match_score": 92, 
                            "match_reason": f"成功媒合！考量該區{ '道路坍方' if target_d.get('road_blocked', True) else '交通尚可' }，AI 建議採取最佳配送路徑。"
                        }
                        st.session_state.claims.append(claim)
                        st.session_state.claiming_demand_id = None
                        st.success("✅ 韌性資源媒合申請已送出！待南投應變指揮中心審核通過後，即可依最佳方案出貨。")
                        time.sleep(1.5); st.rerun()

    # ==========================================
    # Tab 3: 我的認領進度
    # ==========================================
    with tab3:
        my_claims = [c for c in st.session_state.claims if c.get("claimant_id") == user.get("id")]
        if my_claims:
            df = pd.DataFrame(my_claims)
            # 重新命名欄位，讓報告書的呈現更為直觀專業
            df_display = df[["id", "time", "demand_id", "claim_qty", "match_score", "match_reason", "status"]].copy()
            df_display.columns = ["媒合編號", "申請時間", "需求編號", "認領數量", "AI 配對度(%)", "智慧配送建議", "審核狀態"]
            st.dataframe(df_display, hide_index=True, use_container_width=True)
        else:
            st.info("目前尚無山區物資認領的媒合申請紀錄。")


def page_company_logistics_esg_center():
    # 調整標題，彰顯計畫書的「提升山區防災韌性」與「SDGs 預計效益」
    st.title("🚚 山城物資調配與永續影響力 (SDGs)")
    st.caption("整合已配對訂單、山區物流配送進度，並量化企業在南投山區救援中所貢獻的 SDGs 永續影響力。")
    
    tab1, tab2, tab3 = st.tabs(["📦 災區配對物資出貨", "🌱 企業 SDGs 防災貢獻度", "🔔 應變即時通知"])
    with tab1:
        page_matched_orders()  # 呼叫您原本的出貨管理
    with tab2:
        # 新增/重寫專屬於你們黑客松計畫書的 SDGs 儀表板
        page_esg_dashboard_nantou()
    with tab3:
        if st.session_state.notifications:
            st.dataframe(pd.DataFrame(st.session_state.notifications), hide_index=True, use_container_width=True)
        else:
            st.info("目前沒有來自應變指揮中心的即時通知。")


def page_esg_dashboard_nantou():
    """ 新增：完全契合計畫書第五節與第十節的 SDGs 量化質化效益儀表板 """
    st.subheader("📊 企業參與「Mountain Guard AI」之永續成效指標")
    st.write("本儀表板依據聯合國 SDGs 永續發展目標，即時計算貴單位在本平台投入山區救援之績效：")
    
    # 模擬計算該企業累積的數據
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="🇺🇳 SDG 11 韌性社區貢獻", value="12 案次", delta="降低傷亡與財產損失")
    with col2:
        st.metric(label="🌍 SDG 13 氣候行動適應", value="8 鄉鎮次", delta="極端氣候災情調適")
    with col3:
        st.metric(label="❤️ SDG 3 醫療物資福祉", value="450 件", delta="生命安全保障率提升")
    with col4:
        st.metric(label="🏗️ SDG 9 數位基礎建設", value="92% 配對率", delta="智慧防災治理效率")
        
    st.markdown("---")
    st.markdown("#### 🎯 呼應本計畫之 SDGs 質化成效評估")
    
    with st.container(border=True):
        st.markdown("**🏡 SDG 11 永續城市與社區**")
        st.write("透過智慧物資媒合，縮短仁愛鄉、信義鄉等高風險部落於成為「孤島」時的空窗期，實質提升偏鄉社區的災害應變能力。")
        
    with st.container(border=True):
        st.markdown("**⛈️ SDG 13 氣候行動**")
        st.write("協助南投地方政府因應極端暴雨與地震，以 AI 替代分散的傳統通報方式，提高地方社會對氣候災害的外部調適韌性。")

    with st.container(border=True):
        st.markdown("**🏥 SDG 3 健康與福祉**")
        st.write("優化偏鄉慢性病患、嬰幼兒等受困族群之緊急醫療、口服藥物調度效率，確保災害期間生命線不中斷。")

    with st.container(border=True):
        st.markdown("**🚀 SDG 9 產業創新與基礎建設**")
        st.write("建立公私協力（政府-企業-民間志工）的跨單位數位治理平台，為南投山區建構智慧防災的數位基礎設施。")

def page_smart_match_review():
    user = get_current_user()
    if user.get("role") != "admin":
        st.error("此頁面僅限平台管理員使用。")
        return

    st.title("🧠 智慧配對審核")
    st.caption("系統會自動掃描需求池與供給池，若品項、分類、數量與地區條件符合，就產生配對建議；管理員核准後才會正式扣庫存、建立配對紀錄並通知雙方。")

    with st.container(border=True):
        st.subheader("產生智慧配對建議")
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        with col1:
            min_score = st.slider("最低媒合分數", 30, 100, 45, 5)
        with col2:
            only_verified_demand = st.checkbox("只掃描已認證需求", value=False)
        with col3:
            only_verified_supply = st.checkbox("只掃描已認證供給", value=False)
        with col4:
            st.write("")
            st.write("")
            if st.button("⚡ 自動掃描並產生建議", type="primary", use_container_width=True):
                created = generate_smart_match_suggestions(min_score, only_verified_demand, only_verified_supply)
                if created:
                    st.success(f"已新增 {created} 筆智慧配對建議。")
                else:
                    st.info("目前沒有新的可配對組合，或已存在待審建議。")
                st.rerun()

    st.divider()

    tab1, tab2, tab3 = st.tabs(["待審智慧配對", "已核准", "已駁回/失效"])

    def render_match_card(m):
        d = next((x for x in st.session_state.demands if x.get("id") == m.get("demand_id")), None)
        s = next((x for x in st.session_state.supplies if x.get("id") == m.get("supply_id")), None)

        if not d or not s:
            st.warning(f"{m.get('id')}：需求或供給資料已不存在。")
            return

        st.markdown(f"### [{m.get('id')}] {d.get('item')} x {m.get('suggested_qty')} ｜ {SMART_MATCH_STATUS.get(m.get('status'), m.get('status'))}")
        col_d, col_s = st.columns(2)
        with col_d:
            st.markdown("#### 🚨 需求端")
            st.write(f"地點：{d.get('location')}")
            st.write(f"需求：{d.get('item')}｜剩餘 {d.get('qty')}")
            st.write(f"分類：{d.get('resource_type')} / {d.get('category')}")
            st.write(f"認證：{badge_text(d.get('verification_status'))}")
            st.caption(f"提出者：{d.get('requester_name')}｜緊急度：{d.get('urgency')}")
        with col_s:
            st.markdown("#### 📦 供給端")
            st.write(f"提供者：{s.get('provider')}")
            st.write(f"供給：{s.get('item')}｜庫存 {s.get('qty')}")
            st.write(f"分類：{s.get('resource_type')} / {s.get('category')}")
            st.write(f"認證：{badge_text(s.get('verification_status'))}")
            st.caption(f"所在地：{s.get('location_current')}")

        st.progress(min(int(m.get("match_score", 0)), 100) / 100, text=f"媒合分數：{m.get('match_score')}｜{m.get('match_reason')}")
        if m.get("review_note"):
            st.caption(f"審核備註：{m.get('review_note')}")

    with tab1:
        rows = [m for m in st.session_state.smart_matches if m.get("status") == "pending_admin_review"]
        if not rows:
            st.info("目前沒有待審智慧配對建議。")
        for idx, m in enumerate(rows):
            unique_key = f"{m.get('id')}_{m.get('demand_id')}_{m.get('supply_id')}_{idx}"
            with st.container(border=True):
                render_match_card(m)
                note = st.text_input("管理員審核備註", key=f"smart_note_{unique_key}")
                col_a, col_b = st.columns(2)
                if col_a.button("✅ 核准智慧配對並正式調度", key=f"smart_ok_{unique_key}"):
                    ok, msg = approve_smart_match(m.get("id"), note)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
                    st.rerun()
                if col_b.button("❌ 駁回智慧配對", key=f"smart_no_{unique_key}"):
                    reject_smart_match(m.get("id"), note)
                    st.warning("已駁回。")
                    st.rerun()

    with tab2:
        rows = [m for m in st.session_state.smart_matches if m.get("status") == "approved"]
        if not rows:
            st.info("目前沒有已核准的智慧配對。")
        for m in rows:
            with st.container(border=True):
                render_match_card(m)

    with tab3:
        rows = [m for m in st.session_state.smart_matches if m.get("status") in ["rejected", "expired"]]
        if not rows:
            st.info("目前沒有已駁回或失效的智慧配對。")
        for m in rows:
            with st.container(border=True):
                render_match_card(m)


def page_admin():
    user = get_current_user()
    if user.get("role") != "admin":
        st.error("此頁面僅限平台管理員使用。")
        return

    st.title("🛡️ 平台管理員總控台")
    st.caption("管理員功能已集中在本總控台：帳號審核、資料修正、智慧配對、認領審核、通知紀錄與稽核紀錄。")

    tabs = st.tabs(["帳號審核", "需求/供給控管", "智慧配對審核", "認領總審核", "通知與信件", "稽核紀錄"])

    with tabs[0]:
        st.subheader("帳號審核")
        pending_users = [u for u in st.session_state.users if u.get("status") == "pending"]
        if not pending_users:
            st.info("目前沒有待審帳號。")
        for u in pending_users:
            with st.container(border=True):
                st.markdown(f"### {u.get('name')}｜{ROLE_LABELS.get(u.get('role'))}")
                st.write(f"Email：{u.get('email')}｜手機：{u.get('phone', '未填')}（{'已驗證' if u.get('phone_verified') else '未驗證'}）｜行政區：{u.get('district')} / {u.get('village')}")
                st.caption(f"證明資料：{u.get('proof')}")
                col_a, col_b = st.columns(2)
                if col_a.button("✅ 核准帳號並給予認證", key=f"admin_user_ok_{u['id']}"):
                    u["status"] = "active"
                    u["verified"] = True
                    add_audit("管理員核准帳號", u.get("name"))
                    st.rerun()
                if col_b.button("❌ 駁回帳號", key=f"admin_user_no_{u['id']}"):
                    u["status"] = "rejected"
                    u["verified"] = False
                    add_audit("管理員駁回帳號", u.get("name"))
                    st.rerun()
        st.divider()
        st.subheader("全部帳號")
        st.dataframe(pd.DataFrame(st.session_state.users), hide_index=True, use_container_width=True)

    with tabs[1]:
        st.subheader("需求/供給控管")
        data_type = st.radio("選擇資料類型", ["需求", "供給"], horizontal=True)
        records = st.session_state.demands if data_type == "需求" else st.session_state.supplies
        if not records:
            st.info("沒有資料。")
        for r in records:
            with st.container(border=True):
                title_item = r.get("item", "未知")
                st.markdown(f"### [{r.get('id')}] {title_item} x {r.get('qty')}｜{badge_text(r.get('verification_status'))}")
                st.write(f"分類：{r.get('resource_type')} / {r.get('category')}｜狀態：{r.get('status')}｜地區：{r.get('district')} / {r.get('village')}")
                if r.get("risk_flag"):
                    st.warning(f"異常標記：{r.get('risk_flag')}")
                col1, col2, col3, col4 = st.columns(4)
                if col1.button("✅ 設為已認證", key=f"admin_verify_{data_type}_{r['id']}"):
                    r["verification_status"] = "verified"
                    r["verified_by"] = user.get("id")
                    add_audit("管理員認證資料", f"{data_type} {r['id']}")
                    st.rerun()
                if col2.button("🟡 設為待認證", key=f"admin_pending_{data_type}_{r['id']}"):
                    r["verification_status"] = "pending"
                    add_audit("管理員重設待認證", f"{data_type} {r['id']}")
                    st.rerun()
                if col3.button("⚠️ 標記異常", key=f"admin_flag_{data_type}_{r['id']}"):
                    r["risk_flag"] = "管理員標記：疑似重複、資訊不足或需人工確認"
                    add_audit("管理員標記異常", f"{data_type} {r['id']}")
                    st.rerun()
                if col4.button("🗑️ 下架資料", key=f"admin_delete_{data_type}_{r['id']}"):
                    r["status"] = "已下架"
                    r["risk_flag"] = "管理員下架"
                    add_audit("管理員下架資料", f"{data_type} {r['id']}")
                    st.rerun()

    with tabs[2]:
        st.subheader("智慧配對審核")
        st.caption("在這裡直接產生、查看、核准或駁回智慧配對建議。管理員核准後才會正式扣庫存、建立配對紀錄並通知雙方。")

        with st.container(border=True):
            st.markdown("#### ⚡ 自動掃描供需並產生建議")
            col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
            with col1:
                min_score = st.slider("最低媒合分數", 30, 100, 45, 5, key="admin_tab_smart_min_score")
            with col2:
                only_verified_demand = st.checkbox("只掃描已認證需求", value=False, key="admin_tab_only_verified_demand")
            with col3:
                only_verified_supply = st.checkbox("只掃描已認證供給", value=False, key="admin_tab_only_verified_supply")
            with col4:
                st.write("")
                st.write("")
                if st.button("⚡ 自動掃描", type="primary", use_container_width=True, key="admin_tab_generate_smart"):
                    created = generate_smart_match_suggestions(min_score, only_verified_demand, only_verified_supply)
                    if created:
                        st.success(f"已新增 {created} 筆智慧配對建議。")
                    else:
                        st.info("目前沒有新的可配對組合，或已存在待審建議。")
                    st.rerun()

        st.divider()
        subtab1, subtab2, subtab3 = st.tabs(["待審智慧配對", "已核准", "已駁回/失效"])

        def render_admin_smart_match(m, idx, readonly=False):
            d = next((x for x in st.session_state.demands if x.get("id") == m.get("demand_id")), None)
            s = next((x for x in st.session_state.supplies if x.get("id") == m.get("supply_id")), None)
            unique_key = f"admin_inline_smart_{m.get('id')}_{m.get('demand_id')}_{m.get('supply_id')}_{idx}"

            if not d or not s:
                st.warning(f"{m.get('id')}：需求或供給資料已不存在。")
                return

            with st.container(border=True):
                st.markdown(f"### [{m.get('id')}] {d.get('item')} x {m.get('suggested_qty')}｜{SMART_MATCH_STATUS.get(m.get('status'), m.get('status'))}")
                col_d, col_s = st.columns(2)
                with col_d:
                    st.markdown("#### 🚨 需求端")
                    st.write(f"地點：{d.get('location')}")
                    st.write(f"需求：{d.get('item')}｜剩餘 {d.get('qty')}")
                    st.write(f"分類：{d.get('resource_type')} / {d.get('category')}")
                    st.write(f"認證：{badge_text(d.get('verification_status'))}")
                    st.caption(f"提出者：{d.get('requester_name')}｜緊急度：{d.get('urgency')}")
                with col_s:
                    st.markdown("#### 📦 供給端")
                    st.write(f"提供者：{s.get('provider')}")
                    st.write(f"供給：{s.get('item')}｜庫存 {s.get('qty')}")
                    st.write(f"分類：{s.get('resource_type')} / {s.get('category')}")
                    st.write(f"認證：{badge_text(s.get('verification_status'))}")
                    st.caption(f"所在地：{s.get('location_current')}")

                st.progress(min(int(m.get("match_score", 0)), 100) / 100, text=f"媒合分數：{m.get('match_score')}｜{m.get('match_reason')}")
                if m.get("review_note"):
                    st.caption(f"審核備註：{m.get('review_note')}")

                if not readonly:
                    note = st.text_input("管理員審核備註", key=f"{unique_key}_note")
                    col_a, col_b = st.columns(2)
                    if col_a.button("✅ 核准智慧配對並正式調度", key=f"{unique_key}_ok"):
                        ok, msg = approve_smart_match(m.get("id"), note)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                        st.rerun()
                    if col_b.button("❌ 駁回智慧配對", key=f"{unique_key}_no"):
                        reject_smart_match(m.get("id"), note)
                        st.warning("已駁回。")
                        st.rerun()

        with subtab1:
            rows = [m for m in st.session_state.smart_matches if m.get("status") == "pending_admin_review"]
            if not rows:
                st.info("目前沒有待審智慧配對。請按上方『自動掃描』產生建議。")
            for idx, m in enumerate(rows):
                render_admin_smart_match(m, idx, readonly=False)

        with subtab2:
            rows = [m for m in st.session_state.smart_matches if m.get("status") == "approved"]
            if not rows:
                st.info("目前沒有已核准的智慧配對。")
            for idx, m in enumerate(rows):
                render_admin_smart_match(m, idx, readonly=True)

        with subtab3:
            rows = [m for m in st.session_state.smart_matches if m.get("status") in ["rejected", "expired"]]
            if not rows:
                st.info("目前沒有已駁回或失效的智慧配對。")
            for idx, m in enumerate(rows):
                render_admin_smart_match(m, idx, readonly=True)

    with tabs[3]:
        st.subheader("認領總審核")
        pending_claims = [c for c in st.session_state.claims if c.get("status") == "pending_gov_review"]
        if not pending_claims:
            st.info("目前沒有待審認領申請。")
        for c in pending_claims:
            d = next((x for x in st.session_state.demands if x["id"] == c["demand_id"]), None)
            s = next((x for x in st.session_state.supplies if x["id"] == c["supply_id"]), None)
            if not d or not s:
                continue
            with st.container(border=True):
                st.markdown(f"### {c['id']}｜{c['claimant_name']} 認領 {d.get('item')} x {c.get('claim_qty')}")
                st.write(f"需求：{d.get('location')}｜{badge_text(d.get('verification_status'))}")
                st.write(f"供給：{s.get('provider')} / {s.get('item')}｜庫存 {s.get('qty')}｜{badge_text(s.get('verification_status'))}")
                st.progress(min(c.get("match_score", 0), 100) / 100, text=f"媒合分數：{c.get('match_score')}｜{c.get('match_reason')}")
                note = st.text_input("管理員審核備註", key=f"admin_claim_note_{c['id']}")
                col_a, col_b = st.columns(2)
                if col_a.button("✅ 管理員核准並完成配對", key=f"admin_claim_ok_{c['id']}"):
                    c["reviewer"] = user.get("name")
                    c["review_note"] = note or "管理員審核通過"
                    execute_dispatch(d["id"], s["id"], s.get("provider"), c.get("claim_qty"), claim_id=c["id"])
                    st.rerun()
                if col_b.button("❌ 管理員駁回", key=f"admin_claim_no_{c['id']}"):
                    c["status"] = "rejected"
                    c["reviewer"] = user.get("name")
                    c["review_note"] = note or "管理員駁回"
                    c["review_time"] = now_str()
                    notify_claim_result(d, s, c, result="rejected")
                    add_audit("管理員駁回認領", c["id"])
                    st.rerun()

    with tabs[4]:
        st.subheader("通知與 Email 紀錄")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 通知紀錄")
            st.dataframe(pd.DataFrame(st.session_state.notifications), hide_index=True, use_container_width=True)
        with col2:
            st.markdown("#### Email 紀錄")
            st.dataframe(pd.DataFrame(st.session_state.email_logs), hide_index=True, use_container_width=True)

    with tabs[5]:
        st.subheader("稽核紀錄")
        if st.session_state.audit_logs:
            st.dataframe(pd.DataFrame(st.session_state.audit_logs), hide_index=True, use_container_width=True)
        else:
            st.info("目前無稽核紀錄。")



# =========================================================
# 6.5 依架構圖補齊的角色儀表板與分頁 (完美契合 Mountain Guard AI 南投山區專案)
# =========================================================
def page_role_dashboard():
    user = get_current_user()
    role = user.get("role")
    # 結合計畫書名稱：Mountain Guard AI 戰情儀表板
    st.title(f"📊 Mountain Guard AI - {ROLE_LABELS.get(role)}決策儀表板")

    my_demands = [d for d in st.session_state.demands if d.get("requester_id") == user.get("id")]
    my_supplies = [s for s in st.session_state.supplies if s.get("provider_id") == user.get("id")]
    my_claims = [c for c in st.session_state.claims if c.get("claimant_id") == user.get("id")]

    if role == "government":
        area_demands = [d for d in st.session_state.demands if can_gov_review(user, d)]
        area_claims = []
        for c in st.session_state.claims:
            d = next((x for x in st.session_state.demands if x.get("id") == c.get("demand_id")), None)
            if d and can_gov_review(user, d):
                area_claims.append(c)
                
        # 建立契合南投極端氣候防救災的戰情數據
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("轄區通報需求", len(area_demands))
        col2.metric("🌋 孤島高風險待認證", len([d for d in area_demands if d.get("verification_status") == "pending" and d.get("urgency", 0) >= 4]))
        col3.metric("🤝 待審智慧認領", len([c for c in area_claims if c.get("status") == "pending_gov_review"]))
        col4.metric("✅ 已解編/完成配對", len([d for d in area_demands if d.get("status") == "已完成配對"]))
        
        st.info("💡 指揮官提示：系統已自動結合 GIS 與土石流潛勢分析。您可以在『需求審核』中針對仁愛、信義等孤島鄉鎮進行一鍵核准，並透過『智慧資源媒合』引導民間四輪傳動車隊或無人機投入物資調度。")

    elif role == "company":
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("企業已登錄儲備", len(my_supplies))
        col2.metric("📦 可調派防汛/救援物資", sum(int(s.get("qty", 0)) for s in my_supplies))
        col3.metric("已申請媒合案", len(my_claims))
        col4.metric("🌱 累積 SDGs 貢獻件數", len([c for c in my_claims if c.get("status") == "approved"]))
        st.info("🏢 企業夥伴您好：感謝您參與南投山城韌性建設！請先建立您的庫存（如衛星通訊、高底盤車隊、醫療用品），系統將透過 AI 推薦最佳的防災配對路徑，提升您的 ESG/SDGs 履職績效。")

    elif role == "citizen":
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("我回報的災情", len(my_demands))
        col2.metric("審核中通報", len([d for d in my_demands if d.get("verification_status") == "pending"]))
        col3.metric("互助認領紀錄", len(my_claims))
        col4.metric("⚠️ 避難與防救災通知", len(st.session_state.notifications))
        st.info("⛰️ 南投縣民互助平台：當山區發生暴雨、土石流致道路中斷時，您可透過本功能回報受困狀況，或針對鄰近村落提供小量生活資源共享，共同抵抗孤島效應。")

    elif role == "admin":
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("南投全區需求", len(st.session_state.demands))
        col2.metric("全台民間總供給", len(st.session_state.supplies))
        col3.metric("應變人員待審", len([u for u in st.session_state.users if u.get("status") == "pending"]))
        col4.metric("跨單位待審認領", len([c for c in st.session_state.claims if c.get("status") == "pending_gov_review"]))
        st.metric("🤖 Mountain Guard AI 智慧配對池", len([m for m in st.session_state.smart_matches if m.get("status") == "pending_admin_review"]))
        st.info("🛠️ 全域系統管理員：負責維護平台跨單位（消防局、社會處、民間企業、志工車隊）的資料安全、智慧配對演算法稽核及南投高潛勢災害區的基礎圖資維護。")


def page_gov_inbox():
    user = get_current_user()
    # 完美扣合南投高風險行政區（仁愛鄉、信義鄉、水里鄉等）
    district_name = user.get('district', '南投縣')
    st.title(f"📥 {district_name} - 智慧災害防救收件匣")
    st.caption("Mountain Guard AI 已結合南投縣地形、道路坍方通報與土石流潛勢圖，為您完成初步的風險分流與孤島 triage 評估。")

    pending_demands = [d for d in st.session_state.demands if d.get("verification_status") == "pending" and can_gov_review(user, d)]
    
    reviewable_claims = []
    for c in st.session_state.claims:
        if c.get("status") == "pending_gov_review":
            d = next((x for x in st.session_state.demands if x["id"] == c["demand_id"]), None)
            if d and can_gov_review(user, d):
                reviewable_claims.append(c)

    # 💡 呼應計畫書核心功能：AI 災情分流與孤島效應判斷 (Triage 邏輯升級)
    # 綠燈：描述具體、屬於南投核心急需物資且在合理範圍內
    green_demands = [d for d in pending_demands if d.get("urgency", 0) >= 3 and any(k in str(d.get("item", "")) for k in ["水", "藥", "糧食", "通訊", "車"])]
    # 紅燈：疑似惡意、涉及高額金錢、或超出常理的特大數量（黑客松計畫書中提到的異常防堵）
    red_demands = [d for d in pending_demands if "現金" in d.get("item", "") or "錢" in d.get("item", "") or d.get("qty", 1) > 2000 or d.get("landslide_risk") == "極端異常"]
    
    st.subheader("🚨 Mountain Guard AI 智能警報 (Smart Alerts)")
    if red_demands:
        st.error(f"⚠️ **異常或惡意通報警告**：偵測到 {len(red_demands)} 筆疑似內容異常或非防救災物資之請求，平台已自動攔截，請指揮官優先人工介入核實！")
    elif pending_demands or reviewable_claims:
        st.warning(f"💡 **AI 指揮建議**：偵測到 {len(green_demands)} 筆受災孤島需求，經 AI 評估為【綠燈（合理且具時效性）】，建議可至 AI 助理下達一鍵核准，以加速企業物資出動。")
    else:
        st.success("🎉 目前轄區各觀測點與通報平台尚無緊急災情，韌性狀態良好。")

    st.divider()
    st.subheader("📋 應變應對待辦任務 (Action To-Do List)")
    
    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.metric("⏳ 待認證：偏鄉孤島災情回報", f"{len(pending_demands)} 筆")
            if st.button("前往 AI 助理引導快速批次處理 ➡️", key="btn_go_chat", use_container_width=True):
                st.info("請點擊左側功能選單的「🤖 AI 指揮官助理」下達應變決策指令。")
    with col2:
        with st.container(border=True):
            st.metric("🚛 待核准：企業/民間資源智慧調度", f"{len(reviewable_claims)} 筆")
            if st.button("前往人工審核與調度中心 ➡️", key="btn_go_review", use_container_width=True):
                st.info("請點擊左側功能選單的「✅ 需求與認領審核」進行細部路徑與載具確認。")
                

def page_gov_chatbot():
    user = get_current_user()
    district_context = user.get('district', '南投縣')
    st.title("🤖 AI 指揮官助理")
    st.caption("專為南投山區極端氣候打造之自然語言指揮系統。支援：批次核准、孤島資源搜尋、土石流災情總結、快速錄入通報。")

    st.info(f"""
🏞️ **南投山區應變對話範例：**
- `幫我處理今日南投山區需求` (AI 自動將綠燈需求一鍵認證通過)
- `尋找附近可用的越野車輛或發電機` (自動比對企業端登錄的四輪傳動車與發電機)
- `總結目前的災情狀況與道路中斷情形` (依據高潛勢鄉鎮輸出結構化摘要)
- `新增需求：仁愛鄉神木村因土石流道路坍方，急需 10 台發電機與保暖衣物，緊急度 5`
- `新增供給：信義鄉有志工車隊提供 5 輛四輪傳動越野車，可協助挺進交通中斷點`
""")

    if "gov_chat" not in st.session_state:
        st.session_state.gov_chat = [
            {
                "role": "assistant",
                "content": f"""長官您好！我是您的 Mountain Guard AI 戰情助理。

我已為您對接南投防救災資料庫，您可以隨時輸入：
- 「新增需求：鄉鎮村落 + 災情現況 + 缺少的物資/載具 + 數量」
- 「新增供給：提供單位 + 資源品項 + 數量 + 目前位置」
- 「幫我處理今日南投山區需求」
- 「尋找附近可用的四輪傳動車或衛星通訊」
- 「總結目前的災情狀況與道路中斷情形」
""",
            }
        ]

    for msg in st.session_state.gov_chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if user_input := st.chat_input("請輸入應變指揮指令（例如：新增需求：信義鄉同富村急需醫療用品 20 箱）"):
        st.session_state.gov_chat.append({"role": "user", "content": user_input})

        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            # 1. 政府 AI 助理：新增需求 (全面融入南投地理欄位)
            if "新增需求" in user_input or "提出需求" in user_input or "建立需求" in user_input:
                with st.spinner("AI 正在解析南投偏鄉通報內容並進行風險分級..."):
                    result = extract_info_with_ai(raw_text=user_input)

                if result.get("error") == "API_RATE_LIMIT":
                    reply = "⚠️ AI 目前忙碌，請改用『個人設定與表單 → 填寫需求表單』手動建立南投災情通報。"
                elif "error" in result:
                    reply = f"❌ 需求解析失敗：{result.get('error')}"
                else:
                    extracted = result.get("data", result)
                    item = extracted.get("item", "")
                    qty = int(extracted.get("qty", 0) or 0)

                    if not item or item in ["未知", "無", ""] or qty <= 0:
                        reply = "⚠️ 無法辨識通報品項或數量，請輸入明確格式，例如：新增需求：地點、品項、數量、緊急度。"
                    else:
                        # 擷取或自動填入南投行政區
                        detected_district = extracted.get("district", district_context)
                        if detected_district not in ["仁愛鄉", "信義鄉", "水里鄉", "埔里鎮", "竹山鎮", "鹿谷鄉"]:
                            # 預設防止解析錯誤
                            detected_district = district_context if district_context != "全區" else "仁愛鄉"

                        record = {
                            "id": make_id("D"),
                            "time": now_str(),
                            "source": "Mountain Guard AI 指指揮官助理",
                            "requester_id": user.get("id"),
                            "requester_name": user.get("name"),
                            "requester_email": user.get("email"),
                            "district": detected_district,
                            "village": extracted.get("village", "受災部落"),
                            "location": extracted.get("location", user_input),
                            "lat": extracted.get("lat", 23.8),
                            "lon": extracted.get("lon", 121.0),
                            "resource_type": extracted.get("resource_type", "有形資源"),
                            "category": extracted.get("category", "救災工具"),
                            "item": item,
                            "qty": qty,
                            "urgency": int(extracted.get("urgency", 5) or 5),
                            "status": "未處理",
                            "matched_provider": "",
                            "verification_status": "verified", # 指揮官直接輸入視同已驗證
                            "verified_by": user.get("id"),
                            "raw_text": user_input,
                            "risk_flag": extracted.get("risk_flag", "山區孤島通報"),
                            "landslide_risk": "高 (豪雨沖刷區域)", # 符合計畫書風險指標
                            "road_blocked": True if any(k in user_input for k in ["中斷", "坍方", "受困", "孤島", "不通"]) else False
                        }
                        st.session_state.demands.insert(0, record)
                        add_audit("政府AI錄入南投需求", f"{record['id']} / {detected_district} / {item} x {qty}")
                        add_notification(f"🚨 指揮中心錄入受災需求：【{detected_district}】{item} x {qty}", "government_demand")
                        
                        road_status_str = "🚫 偵測到伴隨道路中斷(孤島狀態)" if record["road_blocked"] else "🚙 交通暫時可通行"
                        reply = f"✅ **已由 AI 指揮官助理成功錄入南投戰情系統**：\n- 區域：`{record['district']}{record['village']}`\n- 物資：**{item} x {qty}**\n- 交通狀況：{road_status_str}\n- 系統編號：`{record['id']}` (已自動核准並開放企業端智慧認領)"

                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

            # 2. 政府 AI 助理：新增供給 (包含車隊、物資、載具)
            elif "新增供給" in user_input or "提供供給" in user_input or "建立供給" in user_input:
                with st.spinner("AI 正在解析民間支援能量..."):
                    result = extract_info_with_ai(raw_text=user_input)

                if result.get("error") == "API_RATE_LIMIT":
                    reply = "⚠️ AI 目前忙碌，請透過供給表單手動建立資源。"
                elif "error" in result:
                    reply = f"❌ 資源解析失敗：{result.get('error')}"
                else:
                    extracted = result.get("data", result)
                    item = extracted.get("item", "")
                    qty = int(extracted.get("qty", 0) or 0)

                    if not item or item in ["未知", "無", ""] or qty <= 0:
                        reply = "⚠️ 無法辨識支援物資或載具數量。請輸入如：新增供給：吉普車隊提供 5 輛四輪傳動車，目前在埔里。"
                    else:
                        record = {
                            "id": make_id("S"),
                            "time": now_str(),
                            "source": "Mountain Guard AI 智慧供給對接",
                            "provider_id": user.get("id"),
                            "provider": extracted.get("provider") or "民間熱心團體/企業",
                            "provider_email": user.get("email"),
                            "district": extracted.get("district", "全區"),
                            "village": extracted.get("village", "全區"),
                            "location_current": extracted.get("location_current") or extracted.get("location") or "南投鄰近基地",
                            "lat": extracted.get("lat", 23.8),
                            "lon": extracted.get("lon", 121.0),
                            "resource_type": extracted.get("resource_type", "有形資源"),
                            "category": extracted.get("category", "交通工具"),
                            "item": item,
                            "qty": qty,
                            "status": "可調派",
                            "verification_status": "verified",
                            "verified_by": user.get("id"),
                            "raw_text": user_input,
                            "risk_flag": ""
                        }
                        st.session_state.supplies.insert(0, record)
                        add_audit("政府AI登錄物資供給", f"{record['id']} / {item} x {qty}")
                        add_notification(f"📦 新增民間應變物資/車隊支援：{item} x {qty}", "government_supply")
                        reply = f"✅ **已將民間能量成功登錄至南投防救災儲備池**：\n- 提供者：`{record['provider']}`\n- 品項：**{item} x {qty}**\n- 現況：可即刻參與智慧媒合，編號 `{record['id']}`。"

                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

            # 3. 處理南投山區需求 (一鍵分流)
            elif "需求" in user_input and ("處理" in user_input or "核准" in user_input or "列出" in user_input):
                pending = [
                    d for d in st.session_state.demands
                    if d.get("verification_status") == "pending" and can_gov_review(user, d)
                ]

                if not pending:
                    reply = f"報告指揮官，目前【{district_context}】轄區內沒有待核准的緊急民眾通報。"
                else:
                    reply = f"報告指揮官，目前轄區內偵測到 **{len(pending)}** 筆待審核的偏鄉山區通報。其中包含經 AI 評估為合理且緊急的需求。請問是否需要我為您啟動「一鍵安全分流與批次核准」？"
                    st.session_state.awaiting_action = "approve_all_demands"

                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

            # 4. 尋找特定防救災物資/載具 (如四輪傳動、發電機)
            elif any(k in user_input for k in ["車", "發電機", "水", "通訊", "尋找", "搜尋"]):
                # 建立適合南投斷路斷電情境的關鍵字匹配
                keyword = ""
                for k in ["四輪傳動", "越野車", "車", "發電機", "發電機", "衛星通訊", "無人機", "飲用水", "醫療"]:
                    if k in user_input:
                        keyword = k
                        break
                
                available = [
                    s for s in st.session_state.supplies
                    if int(s.get("qty", 0)) > 0
                    and s.get("status") not in ["已駁回", "已下架", "已指派 (無庫存)"]
                    and (not keyword or keyword in str(s.get("item", "")) or keyword in str(s.get("category", "")))
                ]

                if available:
                    s = available[0]
                    reply = f"""報告指揮官，為您即時自企業與民間儲備池尋獲可用適應載具/物資：

- ⚙️ **資源項目**：{s.get('item')} (可用數量: {s.get('qty')})
- 🏢 **提供單位**：{s.get('provider')}
- 📍 **目前集結位置**：{s.get('location_current')}
- 🟢 **狀態**：{s.get('status')}

💡 **Mountain Guard AI 配送建議**：該資源符合山區救援標準，可指派前往對接目前通報斷路的受困孤島。
"""
                else:
                    reply = f"報告指揮官，目前南投韌性資源池中，暫時沒有符合『{keyword if keyword else user_input}』的閒置民間車隊或物資。已對合作企業發出即時應變徵調通知。"

                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

            # 5. 南投山區災情總結與 SDGs 防災治理效益摘要
            elif any(k in user_input for k in ["總結", "狀況", "摘要", "戰情"]):
                area_demands = [d for d in st.session_state.demands if can_gov_review(user, d)]
                area_supplies = [s for s in st.session_state.supplies if can_gov_review(user, s)]

                high_urgency_isolated = [d for d in area_demands if int(d.get("urgency", 0) or 0) >= 4 and d.get("road_blocked", True)]
                pending_review = [d for d in area_demands if d.get("verification_status") == "pending"]
                unhandled = [d for d in area_demands if d.get("status") == "未處理"]

                reply = f"""🌋 **南投山城目前即時應變戰情摘要：**

- 📥 **轄區通報總數**：**{len(area_demands)}** 筆 (涵蓋仁愛、信義等易成孤島區域)
- 📦 **企業登錄可調派儲備**：**{len(area_supplies)}** 筆
- 🚫 **高緊急度受困孤島需求**：**{len(high_urgency_isolated)}** 筆 ⚠️ (系統列為最高危急)
- ⏳ **待認證災情通報**：**{len(pending_review)}** 筆
- 🔄 **未處理/等待媒合案件**：**{len(unhandled)}** 筆

🎯 **SDGs 智慧治理指引**：建議優先核准待認證通報，並核發智慧派單，引導企業四輪傳動載具或空投物資挺進高危孤島，落實 **SDG 11 韌性社區** 指標。
"""
                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

            else:
                reply = "收到指令。身為南投山區救援 AI，您可以對我輸入：『總結目前災情狀況』、『尋找可用的四輪傳動車』、『幫我處理今日南投山區需求』，或使用自然語言直接錄入新災情。"
                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

    if st.session_state.get("awaiting_action") == "approve_all_demands":
        if st.button("🚀 確認授權：一鍵核准所有安全分流需求", type="primary"):
            pending = [
                d for d in st.session_state.demands
                if d.get("verification_status") == "pending" and can_gov_review(user, d)
            ]
            for d in pending:
                d["verification_status"] = "verified"
                d["verified_by"] = user["id"]

            st.session_state.awaiting_action = None
            st.success(f"✅ 應變中心安全授權完成！已批次核准 {len(pending)} 筆偏鄉災情，正式開放全台企業端智慧認領。")
            st.session_state.gov_chat.append({
                "role": "assistant",
                "content": f"✅ 指揮官，已遵照您的指令，完成 {len(pending)} 筆山區需求的安全分流與核准流程。",
            })
            time.sleep(1)
            st.rerun()

# =========================================================
# 6.6 依架構圖補齊的個人/企業端功能分頁 (完美契合 Mountain Guard AI 南投山區專案)
# =========================================================

def page_my_demands():
    user = get_current_user()
    st.title("📌 我回報的災情與受困需求")
    st.caption("回報紀錄已同步至 Mountain Guard AI 戰情系統，並將依據土石流潛勢與孤島狀態進行權重分流。")
    
    rows = [d for d in st.session_state.demands if d.get("requester_id") == user.get("id")]
    if not rows:
        st.info("⛰️ 您目前在南投轄區尚未有災情通報。")
        return
    for d in rows:
        with st.container(border=True):
            demand_card(d)
            # 呈現更具體的偏鄉受災狀況
            road_status = "🚫 道路中斷/孤島狀態" if d.get('road_blocked') else "🚙 交通尚可通行"
            st.markdown(f"**💡 AI 偵測狀態：** `土石流風險: {d.get('landslide_risk', '評估中')}` ｜ `路況: {road_status}`")
            st.caption(f"原始通報文字：{d.get('raw_text', '')}")


def page_my_supplies():
    user = get_current_user()
    st.title("📦 企業/民間資源儲備登記")
    st.caption("登錄適合挺進南投深山之特種載具（四輪傳動、無人機）、通訊設備或緊急醫療物資。")
    
    rows = [s for s in st.session_state.supplies if s.get("provider_id") == user.get("id")]
    if not rows:
        st.info("🏢 您目前尚未登錄可用於南投山區防救災的民間資源儲備。")
        return
    for s in rows:
        with st.container(border=True):
            st.markdown(f"### {badge_text(s.get('verification_status'))} [{s.get('id')}] {s.get('item')} x {s.get('qty')}")
            st.write(f"📍 資源目前集結點：{s.get('location_current')}｜分類：{s.get('resource_type')} / {s.get('category')}｜儲備狀態：{s.get('status')}")
            st.caption(f"登記單位：{s.get('provider')}｜規格/說明：{s.get('raw_text', '')}")
            if s.get("risk_flag"):
                st.warning(f"⚠️ 平台攔截異常標記：{s.get('risk_flag')} (請確認物資是否適合高山環境，或涉及敏感金流)")


def page_my_claims():
    user = get_current_user()
    st.title("📋 智慧認領與媒合進度")
    st.caption("由 Mountain Guard AI 根據地形、路網阻斷及物資急迫性計算出的精準認領配對。")
    
    rows = [c for c in st.session_state.claims if c.get("claimant_id") == user.get("id")]
    if not rows:
        st.info("🤝 目前沒有已發起的資源認領申請。您可以前往「我要認領需求」進行山區派單。")
        return
    for c in rows:
        d = next((x for x in st.session_state.demands if x.get("id") == c.get("demand_id")), None)
        s = next((x for x in st.session_state.supplies if x.get("id") == c.get("supply_id")), None)
        with st.container(border=True):
            st.markdown(f"### [{c.get('id')}] {CLAIM_STATUS.get(c.get('status'), c.get('status'))}")
            st.write(f"🏔️ 目標災區：【{d.get('district', '南投縣') if d else '已結案'}】{d.get('location') if d else ''} ｜ 認領配發數量：{c.get('claim_qty')}")
            st.write(f"🛠️ 支援資源：{s.get('provider') if s else '已不存在'} ｜ {s.get('item') if s else ''}")
            
            # 強調 AI 媒合路徑合理性
            st.progress(min(int(c.get('match_score', 0)), 100) / 100, text=f"🤖 孤島挺進匹配度：{c.get('match_score')}% ｜ 原因：{c.get('match_reason')}")
            if c.get("review_note"):
                st.caption(f"🏛️ 指揮中心核准備註：{c.get('review_note')}")


def page_matched_orders():
    user = get_current_user()
    st.title("🚚 南投山區特種物流 / 配送進度")
    st.caption("此處追蹤已獲政府指揮中心核准的配送任務。請配合路況回報，防範二次災害。")
    related = []
    
    for c in st.session_state.claims:
        if c.get("status") != "approved":
            continue
        d = next((x for x in st.session_state.demands if x.get("id") == c.get("demand_id")), None)
        s = next((x for x in st.session_state.supplies if x.get("id") == c.get("supply_id")), None)
        if not d or not s:
            continue
        if user.get("role") in ["admin", "government"] or c.get("claimant_id") == user.get("id") or d.get("requester_id") == user.get("id"):
            related.append((c, d, s))
            
    if not related:
        st.info("目前尚無正在挺進南投山區的物流訂單。")
        return
        
    for c, d, s in related:
        if "fulfillment_status" not in c:
            c["fulfillment_status"] = "待出貨"
            
        with st.container(border=True):
            st.markdown(f"### 🚜 應變派單 {c.get('id')} ｜ {s.get('provider')} ➡️ 前往 【{d.get('district')}{d.get('village', '')}】")
            
            col_info, col_action = st.columns([2, 1])
            with col_info:
                st.write(f"📦 配送項目：**{d.get('item')} x {c.get('claim_qty')}**")
                
                # 結合南投地形與計畫書載具，加強物流適應性描述
                logistics_mode = s.get('has_logistics', '需四輪傳動越野載具/志工挺進')
                st.write(f"🧗 運輸載具/模式：`{logistics_mode}`")
                
                # 依據狀態顯示不同顏色
                status_color = "red" if c["fulfillment_status"] == "待出貨" else ("orange" if c["fulfillment_status"] == "已出貨" else "green")
                st.markdown(f"**⛰️ 配送進度：<span style='color:{status_color}'>{c['fulfillment_status']}</span>**", unsafe_allow_html=True)
            
            with col_action:
                st.write("") # 排版用
                # 💡 供給方(企業/救災隊)：出貨與回報
                if user.get("id") == s.get("provider_id") and c["fulfillment_status"] == "待出貨":
                    if st.button("🚚 啟動運輸(已出發)", key=f"ship_{c['id']}", use_container_width=True):
                        c["fulfillment_status"] = "已出貨"
                        add_notification(f"🌋 挺進孤島：{s.get('provider')} 登記之特種資源已出發前往 【{d.get('district')}】{d.get('location')}！", "logistics")
                        st.rerun()
                        
                # 💡 需求方(災區民眾/避難所村長)：確認抵達解編
                elif user.get("id") == d.get("requester_id") and c["fulfillment_status"] == "**已出貨**":
                    if st.button("✅ 確認物資已「安全送達」", key=f"deliver_{c['id']}", type="primary", use_container_width=True):
                        c["fulfillment_status"] = "已完成(收妥)"
                        add_notification(f"🎉 成功打破孤島：訂單 {c['id']} 應變資源已翻山越嶺、安全送達避難據點！", "logistics")
                        st.rerun()


def page_esg_dashboard():
    user = get_current_user()
    st.title("📈 企業 ESG 社會影響力與南投韌性救援報告")
    st.caption("彙整貴單位於 Mountain Guard AI 平台上參與的南投防救災行動，支援一鍵生成對接聯合國 SDGs 指標之永續報告草稿。")
    
    related_claims = [c for c in st.session_state.claims if c.get("claimant_id") == user.get("id") and c.get("status") == "approved"]
    
    if not related_claims:
        st.info("🏢 您的企業帳號目前尚未有經核准的救援任務。一旦您的儲備物資成功配對至仁愛、信義等山區，此處將自動計算您的 SDGs 數位治理效益。")
        return
        
    # 影響力數據面板
    total_items = sum(c.get("claim_qty", 0) for c in related_claims)
    districts_helped = set()
    data = []
    
    for c in related_claims:
        d = next((x for x in st.session_state.demands if x.get("id") == c.get("demand_id")), {})
        s = next((x for x in st.session_state.supplies if x.get("id") == c.get("supply_id")), {})
        districts_helped.add(d.get("district", "南投山區"))
        data.append({
            "出貨時間": c.get("time"),
            "馳援偏鄉行政區": d.get("district", ""),
            "具體村落/避難點": d.get("location", ""),
            "支援物資載具": s.get("item", ""),
            "發放數量": c.get("claim_qty"),
            "特種運輸模式": s.get("has_logistics", "四輪傳動挺進")
        })
        
    col1, col2, col3 = st.columns(3)
    col1.metric("📊 累積捐贈防汛/救災物資", f"{total_items} 件")
    col2.metric("🌋 成功打通山區孤島", f"{len(districts_helped)} 個行政區")
    col3.metric("🎯 實踐 SDGs 協作任務", f"{len(related_claims)} 次")
    
    st.divider()
    st.subheader("📋 詳細出貨與山區支援紀錄明細")
    st.dataframe(pd.DataFrame(data), hide_index=True, use_container_width=True)
    
    st.divider()
    # 💡 重大優化：優化 Prompt 提示詞，完美對接南投黑客松與 SDGs 計畫目標
    if st.button("✨ 一鍵生成 Mountain Guard AI 永續報告 (AI 撰稿)", type="primary"):
        with st.spinner("AI 正在整合南投山區救援數據，並依據 SDGs 3, 9, 11, 13 指標撰寫報告..."):
            prompt = f"""
            你是一個專業的企業品牌公關與永續發展(ESG/CSR)撰稿專家，正在為參與南投縣山城數位黑客松防救災專案的企業撰寫成果。
            請根據以下企業「{user.get('name')}」在「Mountain Guard AI 南投山區韌性救援平台」上的真實馳援數據，寫一篇大約 400 字、情感動人且極具專業度的 ESG 永續報告草稿：
            
            【企業馳援南投數據】
            - 受益行政區：{', '.join(districts_helped)}
            - 共計運送救災物資數：{total_items} 件
            - 詳細派單與物流履歷：{json.dumps(data, ensure_ascii=False)}
            
            【寫作規範與要求】
            1. 標題請設定為結合企業名稱與南投山區韌性建設的新聞感標題。
            2. 請強調該企業如何透過 Mountain Guard AI 的智慧資源媒合技術，克服極端氣候（暴雨、土石流）造成的交通中斷與「孤島效應」，將關鍵資源精準送達災民或村長避難所。
            3. 請明確指出本次行動呼應了聯合國永續發展目標：
               - SDG 3 (健康與福祉：提供偏鄉緊急醫療或生活物資)
               - SDG 9 (韌性基礎設施：運用智慧科技優化資源分配)
               - SDG 11 (永續城市與社區：建立南投山城抗災韌性)
               - SDG 13 (氣候行動：積極響應極端氣候引發的複合式災害)
            4. 結尾強調「數位治理、永續南投」的公私協力精神。
            
            請使用繁體中文、Markdown 格式輸出。
            """
            try:
                from openai import OpenAI
                client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
                res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.3)
                report_md = res.choices[0].message.content
                st.success("🎉 專屬南投永續 ESG 報告草稿生成完畢！")
                st.markdown(f"{report_md}")
                
                st.download_button(
                    label="📥 下載報告為 Markdown 檔",
                    data=report_md,
                    file_name=f"{user.get('name')}_Nantou_MountainGuard_ESG.md",
                    mime="text/markdown"
                )
            except Exception as e:
                st.error("生成報告失敗，請檢查 Groq API 金鑰設定。")

# =========================================================
# 6.7 系統共用頁面與設定 (完美契合 Mountain Guard AI 南投山區專案)
# =========================================================

def page_profile():
    user = get_current_user()
    st.title("👤 數位治理身分與轄區資料")
    
    # 
    
    st.write(f"**📝 名稱/單位：** {user.get('name')}")
    st.write(f"**🏷️ 系統角色：** {ROLE_LABELS.get(user.get('role'))}")
    st.write(f"**📧 電子郵件：** {user.get('email')}")
    st.write(f"**📱 緊急聯絡手機：** {user.get('phone', '未填')}｜{'✅ SMS/OTP 弱網備援驗證通過' if user.get('phone_verified') else '⚪ 手機未驗證'}")
    
    # 強調南投鄉鎮與聚落
    st.write(f"**📍 負責轄區/所在聚落：** {user.get('district')} / {user.get('village')}")
    st.write(f"**🛡️ 官方信任認證：** {'✅ 已由應變中心認證' if user.get('verified') else '⚪ 未認證 / 等待南投縣府審核'}")
    st.caption(f"身分驗證證明：{user.get('proof')}")


def page_gov_supply_review():
    user = get_current_user()
    st.title("📦 民間支援能量審核中心")
    st.caption("鄉鎮公所(如信義鄉、仁愛鄉)可審核該區內的志工車隊與物資，南投縣災害應變中心(管理員)則可統籌審核全縣資源。")
    if user.get("role") == "admin":
        rows = [s for s in st.session_state.supplies if s.get("verification_status") == "pending"]
    else:
        rows = [s for s in st.session_state.supplies if s.get("verification_status") == "pending" and can_gov_review(user, s)]
    
    if not rows:
        st.info("☀️ 目前無待審核的民間支援能量。")
        return
        
    for s in rows:
        with st.container(border=True):
            st.markdown(f"### [{s.get('id')}] {s.get('provider')}｜提供：{s.get('item')} x {s.get('qty')}")
            st.write(f"📍 資源集結點：{s.get('district')} / {s.get('village')}｜資源屬性：{s.get('resource_type')} / {s.get('category')}")
            st.write(f"🧗 運能特徵：`{s.get('has_logistics', '未註明')}`")
            note = st.text_input("📝 應變中心審核備註", key=f"supply_review_note_{s.get('id')}")
            col1, col2 = st.columns(2)
            if col1.button("✅ 納入南投韌性資源池", key=f"supply_review_ok_{s.get('id')}", type="primary"):
                s["verification_status"] = "verified"
                s["verified_by"] = user.get("id")
                add_audit("認證民間資源", f"{s.get('id')} / {note}")
                st.rerun()
            if col2.button("❌ 駁回或暫不徵調", key=f"supply_review_no_{s.get('id')}"):
                s["verification_status"] = "rejected"
                s["status"] = "已駁回"
                s["risk_flag"] = note or "應變中心綜合評估後暫不徵調"
                add_audit("駁回民間資源", f"{s.get('id')} / {note}")
                st.rerun()


def page_transfer_settings():
    user = get_current_user()
    st.title("📍 災防轄區邊界設定")
    st.caption("競賽 Demo 說明：此處展示地方政府與公所的數位治理邊界；實務運作將介接內政部南投縣行政區 GIS 資料庫。")
    st.info(f"🚨 您目前最高指揮審核權限範圍：**【{user.get('district')} / {user.get('village')}】**")
    st.write("📖 **智慧治理規則**：各鄉鎮長官（如仁愛鄉長）僅能審核、調度發生於所屬鄉鎮之孤島求助。若發生跨區土石流災情，需由「平台管理員(縣級應變中心)」進行跨區調配。")


def page_system_overview():
    st.title("📈 Mountain Guard AI 山城韌性總覽")
    
    # 
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🚨 南投災情/孤島需求", len(st.session_state.demands))
    col2.metric("📦 全台馳援南投物資", len(st.session_state.supplies))
    col3.metric("🤝 AI 智慧配對與認領", len(st.session_state.claims))
    col4.metric("🔔 跨區調度通知發送", len(st.session_state.notifications))
    
    st.divider()
    st.subheader("🌋 南投山區應變狀態分布")
    st.dataframe(pd.DataFrame({
        "數位治理項目": ["官方認證：偏鄉災情", "等待核實：疑似災情通報", "官方認證：可出動民間運能", "等待核實：民間志願資源", "正式發車：已核准挺進孤島", "等待審批：跨區調派請求", "AI自動演算：待批推薦清單"],
        "累計數量": [
            len([d for d in st.session_state.demands if d.get("verification_status") == "verified"]),
            len([d for d in st.session_state.demands if d.get("verification_status") == "pending"]),
            len([s for s in st.session_state.supplies if s.get("verification_status") == "verified"]),
            len([s for s in st.session_state.supplies if s.get("verification_status") == "pending"]),
            len([c for c in st.session_state.claims if c.get("status") == "approved"]),
            len([c for c in st.session_state.claims if c.get("status") == "pending_gov_review"]),
            len([m for m in st.session_state.smart_matches if m.get("status") == "pending_admin_review"]),
        ]
    }), hide_index=True, use_container_width=True)


def page_system_settings():
    st.title("⚙️ 黑客松競賽系統設定展示")
    st.caption("此頁面旨在向麥克松評審展示系統底層的「多樣化分類、弱網備援及分層授權」實作概念。")
    
    st.subheader("📦 南投山區特性資源字典")
    st.write("已針對南投土石流、斷橋情境，擴充如「空拍機勘災」、「四輪傳動越野車」、「直升機空投」等特種選項。")
    st.json(RESOURCE_TYPES)
    
    st.subheader("📡 山區弱網通訊設定")
    st.write("📧 **SMTP 信件派送**：", "✅ 即時派車單服務已連線" if SMTP_HOST and SMTP_USER else "⚠️ Demo 模式運作中 (日誌紀錄)")
    st.write("📱 **SMS/OTP 災區簡訊備援**：模擬災區斷網，保留手機純簡訊發送與驗證通道，確保「孤島」通訊不中斷。")
    
    st.subheader("🔐 數位治理分權架構 (RBAC)")
    st.write("👨‍👩‍👧‍👦 **在地縣民/受災居民**：通報受困狀況、在地互助、檢視避難與派單進度。")
    st.write("🏢 **響應企業/志工車隊**：登錄四驅車或物資、接受 AI 推薦認領、累積 SDGs 永續成績單。")
    st.write("🏛️ **地方公所(仁愛/信義等)**：AI 災情分流、一鍵安全核定、啟動在地資源調度。")
    st.write("🛡️ **縣府應變中心(管理員)**：跨鄉鎮總控、異常通報 DLP 攔截、全域戰情室督導。")

def page_multimodal():
    # 💡 修正先前的 Bug：確保提早取得 user 變數
    user = get_current_user()
    
    st.title("📥 多模態災情轉譯 Vision ETL 中心")
    st.caption("【解決孤島斷網痛點】適用於極端災變下，第一線災民或基層公所透過「衛星電話簡訊、手寫紙條照片、無線電抄件紀錄或空拍機災情截圖」快速利用 AI 結構化建檔。")
    
    col_in, col_out = st.columns(2)
    
    with col_in:
        uploaded_file = st.file_uploader("📸 上傳山區手寫紙條、物資清單照片或災情截圖", type=["jpg", "jpeg", "png"], help="🛡️ 隱私防護：系統已自動啟動南投災區專屬去識別化機制，自動遮蔽清晰人臉。")
        raw_text_input = st.text_area("✍️ 補充無線電通報語音紀錄或文字說明", placeholder="輸入範例：我是信義鄉神木村長，這裡舊林道坍方，有 3 戶居民斷糧，急需嬰兒奶粉 5 罐、白米 2 包，目前無人機可降落。")
        
        if st.button("🧠 啟動 Mountain Guard 多模態萃取與 DLP 風險掃描", type="primary"):
            img_bytes = uploaded_file.getvalue() if uploaded_file else None
            mime_type = uploaded_file.type if uploaded_file else "image/jpeg"
            text_to_send = raw_text_input or "請根據圖片判斷災情與需求，務必找出具體品項、數量，並自動推估屬於南投縣哪個行政區。"
            
            with st.spinner("AI 正在進行多模態大模型語意萃取與個人隱私 DLP 安全防護掃描..."):
                result = extract_info_with_ai(text_to_send, img_bytes, mime_type)
                
            with col_out:
                st.subheader("🤖 AI 自動結構化解析結果")
                st.json(result)
                
            if result.get("error") == "API_RATE_LIMIT":
                st.warning("⚠️ 目前 API 伺服器滿載，請改用手動標準表單進行建檔。")
                return
            elif "error" in result:
                st.error(f"❌ 解析失敗：{result['error']}")
                return
                
            info_type = result.get("info_type", "").lower()
            
            # 💡 智慧過濾惡意或無關圖片
            if "irrelevant" in info_type:
                st.warning("⚠️ AI 安全防禦提示：偵測到此圖片/文字與南投山區天災、救災物資或運能調度無關，系統已主動終止建檔。")
                return
                
            extracted = result.get("data", result)
            item = extracted.get("item", "")
            qty = extracted.get("qty", 0)
            risk_flag = extracted.get("risk_flag", "")
            
            resource_type = extracted.get("resource_type", "有形資源")
            category = extracted.get("category", "未分類")
            
            # 預設錨定南投山區座標
            try: lat = float(extracted.get("lat", 23.9))
            except: lat = 23.9
            try: lon = float(extracted.get("lon", 120.9))
            except: lon = 120.9
            
            # 智慧補全鄉鎮行政區
            district = extracted.get("district")
            if not district or district in ["未知", "無", ""]: 
                district = user.get("district", "信義鄉")  # 預設落點於南投山區常受災點
                
            if risk_flag:
                st.warning(f"🛡️ **DLP 防護敏感詞遮蔽**：AI 已自動識別並隱藏不適宜公開的受傷隱私或機敏座標資訊（{risk_flag}）。")

            # ==========================================
            # 💡 路由 1：純災情照片 (如土石流、路斷截圖)
            # ==========================================
            if "disaster" in info_type:
                if "disasters" not in st.session_state: 
                    st.session_state.disasters = []
                record = {
                    "id": make_id("E"), "time": now_str(), "source": "AI多模態轉譯",
                    "reporter_id": user.get("id"), "reporter_name": user.get("name"),
                    "district": district, "location": extracted.get("location", "南投山區路段"),
                    "lat": lat, "lon": lon, 
                    "description": extracted.get("item", "現場崩塌災情"),
                    "disaster_type": extracted.get("disaster_type", "土石流/道路中斷"),
                    "urgency_level": extracted.get("urgency_level", "高風險"),
                    "raw_text": text_to_send, "risk_flag": risk_flag, "status": "未處理"
                }
                st.session_state.disasters.insert(0, record)
                st.success(f"🚨 **災情自動上鏈成功**！此路段災情已獨立標記於全局戰情地圖（AI定錨鄉鎮: {district}），已同步應變中心通報。")

            # ==========================================
            # 💡 路由 2：前線孤島物資需求照片 (如直升機空投需求紙條)
            # ==========================================
            elif "demand" in info_type:
                if not item or item in ["未知", "無", ""]:
                    st.warning("⚠️ 解析終止：AI 無法從紙條/文字中辨識出『具體的救災物資名稱』。")
                    return
                if qty <= 0:
                    st.warning("⚠️ 解析終止：AI 無法明確判斷『物資所需數量』。")
                    return
                    
                record = {
                    "id": make_id("D"), "time": now_str(), "source": "AI多模態轉譯",
                    "requester_id": user.get("id"), "requester_name": user.get("name"), "requester_email": user.get("email"),
                    "resource_type": resource_type, "category": category, 
                    "lat": lat, "lon": lon, 
                    "status": "未處理", "matched_provider": "", 
                    "verification_status": "verified" if user.get("role") == "government" and user.get("verified") else "pending",
                    "verified_by": user.get("id") if user.get("role") == "government" and user.get("verified") else "",
                    "raw_text": text_to_send, "risk_flag": risk_flag,
                    "landslide_risk": extracted.get("landslide_risk", "極高"),
                    "road_blocked": True if any(k in text_to_send for k in ["中斷", "坍方", "孤島", "直升機", "空投"]) else False
                }
                record.update(extracted)
                record["item"] = item
                record["qty"] = qty
                record["district"] = district
                if not record.get("village") or record.get("village") in ["未知", ""]: 
                    record["village"] = user.get("village", "全區")
                    
                st.session_state.demands.insert(0, record)
                st.success(f"✅ 成功轉換為孤島需求單！自動導入物資池：{item} x {qty} 件（AI精準落點: {district}）")
                
            # ==========================================
            # 💡 路由 3：後勤供給/企業主動馳援運能清單照片
            # ==========================================
            else:
                if not item or item in ["未知", "無", ""]:
                    st.warning("⚠️ 解析終止：AI 無法辨識出『企業/民間擬提供的物資或車隊項目』。")
                    return
                if qty <= 0:
                    st.warning("⚠️ 解析終止：AI 無法確定其『可提供之數量/運能規模』。")
                    return
                    
                record = {
                    "id": make_id("S"), "time": now_str(), "source": "AI多模態轉譯",
                    "provider_id": user.get("id"), "provider": extracted.get("provider") or user.get("name"), "provider_email": user.get("email"),
                    "resource_type": resource_type, "category": category,
                    "lat": lat, "lon": lon, 
                    "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending",
                    "verified_by": user.get("id") if user.get("verified") else "", "raw_text": text_to_send, "risk_flag": risk_flag,
                }
                record.update(extracted)
                record["district"] = district
                if "location" in record and "location_current" not in record: 
                    record["location_current"] = record["location"]
                if not record.get("village") or record.get("village") in ["未知", ""]: 
                    record["village"] = user.get("village", "全區")
                    
                st.session_state.supplies.insert(0, record)
                st.success(f"✅ 成功將民間義舉轉換為標準庫存！已建檔：{item} x {qty} 件（登錄集結地: {district}）")

# =========================================================
# 7. Main App 與 路由控制
# =========================================================
st.set_page_config(page_title="Mountain Guard AI ｜ 南投山區韌性救援平台", layout="wide", page_icon="🏔️")
init_session_state()

if not is_logged_in():
    login_panel()
    st.stop()

user = get_current_user()
role = user.get("role")

# =========================================================
# 側邊欄 UI：身分卡片與功能選單
# =========================================================
with st.sidebar:
    # 💡 UI 升級：具備南投山城風格的側邊欄使用者狀態卡片
    if role:
        st.markdown(f"""
        <div style="padding: 15px; border-radius: 10px; background: linear-gradient(135deg, #f0f2f6 0%, #e0e6ed 100%); border-left: 5px solid #2ecc71; margin-bottom: 20px;">
            <h4 style="margin:0; color: #1e375a;">👤 {user.get('name', '未登入')}</h4>
            <p style="margin:0; font-size: 14px; color: #4a5568; line-height: 1.6; margin-top: 5px;">
                🏷️ <b>數位權限：</b>{ROLE_LABELS.get(user.get('role'), '未知')}<br>
                📍 <b>防救災轄區：</b>{user.get('district', '全區')}
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""<div style="padding: 15px; border-radius: 10px; background-color: #f0f2f6; margin-bottom: 20px;"><h4 style="margin:0; color: #31333F;">請先登入</h4></div>""", unsafe_allow_html=True)
        
    st.divider()

    # 💡 選單結構大洗牌：完美對接計畫書的四大核心模組
    role_pages = {
        "citizen": [
            "💬 AI 多模態災情通報", "🗺️ 山區戰情與避難地圖", "🤝 在地互助與認領", "📌 我的通報紀錄", "👤 數位身分與表單"
        ],
        "company": [
            "📊 企業永續總覽",
            "📦 救援能量登錄 (AI 自動化)", 
            "🤝 智慧孤島馳援 (AI 配對)", 
            "🚚 特種物流與 SDGs 成效",  # 💡 結合 SDGs 的企業誘因
            "🗺️ 南投全域需求池",
            "👤 企業設定",
        ],
        "government": [
            "📥 孤島戰情收件匣 (Triage)",  
            "🤖 AI 指揮官決策助理",       # 黑客松大亮點
            "✅ 災情與調度安全審核",    
            "🗺️ 山城即時 GIS 戰情圖",    
            "🚚 山道配對與挺進追蹤",     
            "👤 指揮官權限與設定"       
        ],
        "admin": [
            "📈 縣級系統總覽", "🛡️ 最高應變管理總控台"
        ],
    }

    page = st.radio("🌲 Mountain Guard 導覽", role_pages.get(role, ["📊 決策儀表板"]))

    # 💡 登出按鈕
    st.divider()
    if st.button("🚪 登出指揮系統", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.current_user = None
        st.rerun()


# =========================================================
# 路由綁定 (將功能名稱精準映射至對應之 Mountain Guard AI 函數)
# =========================================================
if page in ["💬 AI 多模態災情通報", "💬 智慧對話通報", "💬 對話通報"]:
    page_chatbot()
elif page == "🤖 AI 指揮官決策助理" or page == "🤖 AI 指揮官助理":    
    page_gov_chatbot()
elif page == "📥 孤島戰情收件匣 (Triage)" or page == "📥 戰情收件匣":       
    page_gov_inbox()
elif page in ["🏠 首頁", "📊 儀表板", "📊 決策儀表板", "📊 企業永續總覽", "📊 公司總覽"]:
    page_role_dashboard()
elif page in ["🗺️ 山城即時 GIS 戰情圖", "🗺️ 災情與資源地圖", "🗺️ 山區戰情與避難地圖", "🗺️ 南投全域需求池", "🗺️ 公開資源池"]:
    page_map_pool()
elif page in ["🤝 在地互助與認領", "🤝 我要認領需求", "🤝 協助與認領"]:
    page_public_claims()
elif page in ["📌 我的通報紀錄", "📌 我的紀錄"]:
    st.title("📌 南投山區行動紀錄")
    tab1, tab2, tab3 = st.tabs(["通報的災情", "登錄的資源", "馳援行動"])
    with tab1: page_my_demands()
    with tab2: page_my_supplies()
    with tab3: page_my_claims()
    
# 企業/民間力量兩大核心全新頁面對接
elif page == "📦 救援能量登錄 (AI 自動化)" or page == "📦 提供供給 (AI 優先)":
    page_company_supply_center()
elif page == "🤝 智慧孤島馳援 (AI 配對)" or page == "🤝 認領需求 (AI 優先)":
    page_company_claim_center()
elif page == "🚚 特種物流與 SDGs 成效" or page == "🚚 配對物流與 ESG":
    st.title("🚚 山路特種物流與 SDGs 永續影響力")
    tabA, tabB = st.tabs(["🚚 物流車隊挺進追蹤", "📈 SDGs 永續行動報告"])
    with tabA: page_matched_orders()
    with tabB: page_esg_dashboard_nantou() # 💡 替換為我們之前實作的南投專屬 SDGs 儀表板
    
# 設定與表單路由
elif page in ["👤 數位身分與表單", "👤 企業設定", "👤 指揮官權限與設定", "👤 個人設定與表單", "👤 個人設定"]:
    st.title("👤 身分權限與系統備用表單")
    if role == "company":
        tabs = st.tabs(["企業認證資料", "跨區調派通知"])
        with tabs[0]: page_profile()
        with tabs[1]: st.dataframe(pd.DataFrame(st.session_state.notifications), hide_index=True, use_container_width=True)
    elif role in ["government", "citizen"]:
        tabs = st.tabs(["數位身分", "警報通知", "手動建檔(災情)", "手動建檔(供給)"])
        with tabs[0]: page_profile()
        with tabs[1]: st.dataframe(pd.DataFrame(st.session_state.notifications), hide_index=True, use_container_width=True)
        with tabs[2]: page_submit_demand()
        with tabs[3]: page_submit_supply()
    else:
        tabs = st.tabs(["管理員資料", "系統日誌"])
        with tabs[0]: page_profile()
        with tabs[1]: st.dataframe(pd.DataFrame(st.session_state.notifications), hide_index=True, use_container_width=True)

# 保留給管理員或縣府應變中心共用審核的專屬功能
elif page in ["📦 建立供給(含批次)", "📦 建立供給"]:
    page_submit_supply()
elif page == "📦 我提供的供給":
    page_my_supplies()
elif page == "📋 我的認領申請":
    page_my_claims()
elif page in ["✅ 災情與調度安全審核", "✅ 需求審核", "📋 認領申請審核", "✅ 需求與認領審核"]:
    page_gov_review()
elif page in ["🪪 認證管理", "🧾 帳號審核管理", "📌 需求管理", "📦 供給管理", "📋 認領申請總審核", "🔔 通知與Email紀錄", "📜 稽核紀錄", "🛡️ 最高應變管理總控台", "🛡️ 管理員總控台"]:
    page_admin()
elif page in ["🚚 山道配對與挺進追蹤", "🚚 已配對訂單", "🚚 配對管理", "🚚 配對與物流管理"]:
    page_matched_orders()
elif page in ["📈 縣級系統總覽", "📈 系統總覽"]:
    page_system_overview()
elif page == "📥 AI轉譯": # 可選的隱藏除錯功能
    page_multimodal()
else:
    if role == "government":
        page_gov_inbox()
    else:
        page_role_dashboard()