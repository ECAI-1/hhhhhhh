# Full Hosting Manager Bot
# By EC-NISHITH (extended with owner upload + coupons)

import os, sys, time, json, shutil, subprocess, traceback, random, string
from pathlib import Path
import requests

# -------- CONFIG --------
BOT_TOKEN = "8460725856:AAFOz3lBzx6tYeH36kKo4i0lME-nw1CzO6o"
OWNER_ID = 6123174299  # replace with your telegram id
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}/"
FILE_BASE = f"https://api.telegram.org/file/bot{BOT_TOKEN}/"
BASE_DIR = Path(__file__).parent
USER_BOTS_DIR = BASE_DIR / "user_bots"
LOGS_DIR = BASE_DIR / "logs"
PLANS_FILE = BASE_DIR / "plans.json"
COUPONS_FILE = BASE_DIR / "coupons.json"
OFFSET_FILE = BASE_DIR / "offset.txt"

USER_BOTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# runtime state
offset = 0
user_states = {}   # user_id -> dict (awaiting_zip, awaiting_action)
running_bots = {}  # bot_id -> {"proc": Popen, "log": str}
plans = {}
coupons = {}

# -------- Utilities for Telegram API --------
def api_post(method, payload=None, files=None, params=None):
    url = API_BASE + method
    try:
        if files:
            r = requests.post(url, data=payload or {}, files=files, timeout=120)
        else:
            r = requests.post(url, json=payload or {}, timeout=120, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("API error", method, e)
        return None

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return api_post("sendMessage", payload)

def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return api_post("editMessageText", payload)

def answer_callback(callback_query_id, text=""):
    return api_post("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})

def send_document(chat_id, file_path, filename=None):
    try:
        with open(file_path, "rb") as f:
            files = {"document": (filename or os.path.basename(file_path), f)}
            return api_post("sendDocument", None, files=files, params={"chat_id": chat_id})
    except Exception as e:
        print("send_document error", e)
        return None

def get_file_path(file_id):
    res = api_post("getFile", {"file_id": file_id})
    if not res or not res.get("ok"):
        return None
    return res["result"]["file_path"]

def download_file(file_path, dest):
    url = FILE_BASE + file_path
    try:
        r = requests.get(url, stream=True, timeout=120)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(64*1024):
                if not chunk:
                    break
                f.write(chunk)
        return True
    except Exception as e:
        print("download_file error", e)
        return False

# -------- Plans & Coupons --------
def load_plans():
    global plans
    if PLANS_FILE.exists():
        try:
            plans = json.loads(PLANS_FILE.read_text(encoding="utf-8"))
        except Exception:
            plans = {}
    else:
        plans = {}

def save_plans():
    PLANS_FILE.write_text(json.dumps(plans, indent=2), encoding="utf-8")

def get_plan(user_id):
    return plans.get(str(user_id), "free")

def max_bots_for_plan(plan):
    if plan == "free":
        return 1
    if plan == "premium":
        return 3
    if plan == "vip":
        return 999
    return 1

def load_coupons():
    global coupons
    if COUPONS_FILE.exists():
        try:
            coupons = json.loads(COUPONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            coupons = {}
    else:
        coupons = {}

def save_coupons():
    COUPONS_FILE.write_text(json.dumps(coupons, indent=2), encoding="utf-8")

def create_coupon(plan, uses=1):
    code = ''.join(random.choices(string.ascii_uppercase+string.digits, k=8))
    coupons[code] = {"plan": plan, "uses": uses}
    save_coupons()
    return code

def redeem_coupon(user_id, code):
    c = coupons.get(code)
    if not c:
        return False, "❌ Invalid coupon"
    if c["uses"] <= 0:
        return False, "❌ Coupon already used"
    plans[str(user_id)] = c["plan"]
    save_plans()
    c["uses"] -= 1
    if c["uses"] <= 0:
        coupons.pop(code, None)
    save_coupons()
    return True, f"✅ Coupon redeemed! You got {c['plan']}"

# -------- Bot process management --------
def find_main_file(bot_dir: Path):
    for name in ("bot.py", "main.py", "run.py"):
        p = bot_dir / name
        if p.exists():
            return p
    for p in bot_dir.glob("*.py"):
        return p
    return None

def start_user_bot(user_id, bot_id, bot_dir: Path):
    main_file = find_main_file(bot_dir)
    if not main_file:
        return False
    log_file = LOGS_DIR / f"{bot_id}.log"
    lf = open(log_file, "ab")
    try:
        proc = subprocess.Popen([sys.executable, str(main_file)], stdout=lf, stderr=lf, cwd=str(bot_dir))
    except Exception as e:
        lf.close()
        return False
    running_bots[bot_id] = {"proc": proc, "log": str(log_file)}
    return True

def stop_user_bot(bot_id):
    info = running_bots.get(bot_id)
    if not info:
        return False
    proc = info["proc"]
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
    except Exception:
        try: proc.kill()
        except Exception: pass
    running_bots.pop(bot_id, None)
    return True

def restart_user_bot(bot_id):
    info = running_bots.get(bot_id)
    if info:
        stop_user_bot(bot_id)
    bot_dir = USER_BOTS_DIR / bot_id
    if bot_dir.exists():
        return start_user_bot(None, bot_id, bot_dir)
    return False

# -------- Message Handling --------
def handle_message(msg):
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text = msg.get("text", "") or ""
    state = user_states.setdefault(user_id, {})

    # Coupon redeem
    if text.startswith("/redeem "):
        code = text.split(" ",1)[1].strip()
        ok, msgtext = redeem_coupon(user_id, code)
        send_message(chat_id, msgtext)
        return

    # Owner create coupon
    if text.startswith("/makecoupon") and user_id == OWNER_ID:
        parts = text.split()
        if len(parts) < 3:
            send_message(chat_id, "Usage: /makecoupon <plan> <uses>")
            return
        plan = parts[1]
        uses = int(parts[2])
        code = create_coupon(plan, uses)
        send_message(chat_id, f"✅ Coupon Created!\nCode: <code>{code}</code>\nPlan: {plan}\nUses: {uses}")
        return

    # handle zip
    if state.get("awaiting_zip") and "document" in msg:
        doc = msg["document"]
        fname = doc.get("file_name", "")
        if not fname.lower().endswith(".zip"):
            send_message(chat_id, "❌ Please upload a ZIP file.")
            state.pop("awaiting_zip", None)
            return
        file_id = doc["file_id"]
        file_path = get_file_path(file_id)
        if not file_path:
            send_message(chat_id, "❌ Could not get file info.")
            state.pop("awaiting_zip", None)
            return
        bot_id = f"{user_id}_{doc.get('file_unique_id')}"
        bot_dir = USER_BOTS_DIR / bot_id
        bot_dir.mkdir(parents=True, exist_ok=True)
        local_zip = bot_dir / fname
        ok = download_file(file_path, str(local_zip))
        if not ok:
            send_message(chat_id, "❌ Failed to download file.")
            state.pop("awaiting_zip", None)
            return
        try:
            shutil.unpack_archive(str(local_zip), str(bot_dir))
        except Exception as e:
            send_message(chat_id, f"❌ Failed to extract ZIP: {e}")
            state.pop("awaiting_zip", None)
            return
        plan = get_plan(user_id)
        bots = [d.name for d in USER_BOTS_DIR.iterdir() if d.is_dir() and d.name.startswith(str(user_id))]
        if len(bots) > max_bots_for_plan(plan):
            send_message(chat_id, f"❌ Your plan ({plan}) allows max {max_bots_for_plan(plan)} bots.")
            state.pop("awaiting_zip", None)
            return
        send_message(chat_id, f"✅ Uploaded as <code>{bot_id}</code>, starting...")
        start_user_bot(user_id, bot_id, bot_dir)
        state.pop("awaiting_zip", None)
        plans.setdefault(str(user_id), "free")
        save_plans()
        return

    # Panel
    if text.strip() in ("/start", "/panel"):
        if user_id == OWNER_ID:
            keyboard = [
                [{"text":"📂 Upload Bot","callback_data":"upload_bot"}],
                [{"text":"📋 All Users","callback_data":"all_users"}],
                [{"text":"🛠 All Bots","callback_data":"all_bots"}],
                [{"text":"💀 Kill All","callback_data":"kill_all"}],
                [{"text":"📢 Broadcast","callback_data":"broadcast"}],
                [{"text":"👑 Manage Plans","callback_data":"plans"}],
            ]
            send_message(chat_id, "👑 Owner Panel\n\nYou are admin.", reply_markup={"inline_keyboard": keyboard})
        else:
            plan = get_plan(user_id)
            keyboard = [
                [{"text":"📂 Upload Bot","callback_data":"upload_bot"}],
                [{"text":"📋 My Bots","callback_data":"my_bots"}],
                [{"text":f"⭐ Plan: {plan.upper()}","callback_data":"noop"}],
                [{"text":"🎟 Redeem Coupon","callback_data":"redeem_coupon"}],
            ]
            send_message(chat_id, "🛠 User Panel\n\nUpload and manage your bots.", reply_markup={"inline_keyboard": keyboard})
        return

# -------- Callback Handling --------
def handle_callback(cb):
    query_id = cb.get("id")
    data = cb.get("data","")
    msg = cb.get("message",{}) or {}
    chat_id = msg.get("chat",{}).get("id")
    user_id = cb.get("from",{}).get("id")
    message_id = msg.get("message_id")
    answer_callback(query_id)

    if data == "upload_bot":
        user_states.setdefault(user_id, {})["awaiting_zip"] = True
        edit_message(chat_id, message_id, "📂 Please send me a ZIP file now.")
        return

    if data == "redeem_coupon":
        edit_message(chat_id, message_id, "🎟 Send: /redeem COUPONCODE")
        return

# -------- Offset Save --------
def save_offset():
    try:
        OFFSET_FILE.write_text(str(offset), encoding="utf-8")
    except Exception: pass

def load_offset():
    global offset
    try:
        if OFFSET_FILE.exists():
            offset = int(OFFSET_FILE.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        offset = 0

# -------- Main Loop --------
def main_loop():
    global offset
    print("Hosting bot starting (long-polling)...")
    load_plans()
    load_coupons()
    load_offset()
    while True:
        try:
            res = requests.post(API_BASE + "getUpdates", json={"timeout":30, "offset": offset}, timeout=35)
            res.raise_for_status()
            data = res.json()
            if not data.get("ok"):
                time.sleep(1)
                continue
            updates = data.get("result", [])
            for upd in updates:
                offset = upd["update_id"] + 1
                save_offset()
                if "message" in upd:
                    try:
                        handle_message(upd["message"])
                    except Exception:
                        print("handle_message error", traceback.format_exc())
                elif "callback_query" in upd:
                    try:
                        handle_callback(upd["callback_query"])
                    except Exception:
                        print("handle_callback error", traceback.format_exc())
        except Exception as e:
            print("Main loop error:", e)
            time.sleep(2)

if __name__ == "__main__":
    main_loop()
