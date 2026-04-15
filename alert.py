"""
alert.py - Alert Management with Telegram (image + text in one message)
"""

import os
import time
import threading
import requests
from datetime import datetime
import cv2


class AlertManager:
    def __init__(self, cooldown_seconds=20, snapshots_dir="snapshots"):
        self.cooldown_seconds = cooldown_seconds
        self.snapshots_dir = snapshots_dir
        self.last_alert_time = 0
        self.alert_count = 0
        self.last_alert_message = ""

        # --- Telegram Bot config (FREE, sends image + text) ---
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        # Fallback: CallMeBot text-only WhatsApp
        self.whatsapp_phone = os.getenv("WHATSAPP_PHONE", "")
        self.whatsapp_api_key = os.getenv("WHATSAPP_API_KEY", "")

        os.makedirs(self.snapshots_dir, exist_ok=True)
        self.alarm_sound_path = os.path.join("static", "alarm.wav")

        print(f"[AlertManager] Cooldown: {cooldown_seconds}s | Dir: {self.snapshots_dir}")
        if self.telegram_bot_token:
            print("[AlertManager] Telegram alerts ENABLED (text + image)")
        elif self.whatsapp_phone:
            print("[AlertManager] WhatsApp (CallMeBot) text alerts ENABLED")
        else:
            print("[AlertManager] WARNING: No messaging configured — alerts will be LOCAL ONLY")

    def can_trigger(self):
        return (time.time() - self.last_alert_time) >= self.cooldown_seconds

    def trigger_alert(self, frame, message="Person detected near shutter!"):
        if not self.can_trigger():
            return False

        self.last_alert_time = time.time()
        self.alert_count += 1
        self.last_alert_message = message

        # 1. Screenshot
        screenshot_path = self.capture_screenshot(frame)

        # 2. Alarm sound (non-blocking)
        self.play_alarm_sound()

        # 3. Send alert with image (non-blocking)
        threading.Thread(target=self._send_alert_with_image,
                        args=(message, screenshot_path), daemon=True).start()

        print(f"[ALERT #{self.alert_count}] {message} | {screenshot_path}")
        return True

    def capture_screenshot(self, frame):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self.snapshots_dir, f"alert_{ts}.jpg")
        cv2.imwrite(filepath, frame)
        print(f"[AlertManager] Screenshot: {filepath}")
        return filepath

    def play_alarm_sound(self):
        if os.path.exists(self.alarm_sound_path):
            threading.Thread(target=self._play_sound_thread, daemon=True).start()

    def _play_sound_thread(self):
        try:
            import platform, subprocess
            system = platform.system()
            if system == "Linux":
                # Try mpv (best), then ffplay, then cvlc
                for player in [["mpv", "--no-video"], ["ffplay", "-nodisp", "-autoexit"], ["cvlc", "--play-and-exit"]]:
                    try:
                        subprocess.run(player + [self.alarm_sound_path],
                                     capture_output=True, timeout=5)
                        break
                    except FileNotFoundError:
                        continue
            elif system == "Darwin":
                subprocess.run(["afplay", self.alarm_sound_path], capture_output=True, timeout=5)
            elif system == "Windows":
                import winsound
                winsound.PlaySound(self.alarm_sound_path, winsound.SND_FILENAME)
        except Exception as e:
            print(f"[AlertManager] Sound error: {e}")

    def _send_alert_with_image(self, message, screenshot_path):
        """Send alert via Telegram (image + caption) or fallback to WhatsApp text."""

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        caption = (
            f"🚨 CCTV ALERT 🚨\n"
            f"{message}\n"
            f"⏰ {ts}\n"
            f"📊 Alert #{self.alert_count}"
        )

        # ---- Priority 1: Telegram (supports image) ----
        if self.telegram_bot_token and self.telegram_chat_id:
            try:
                url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendPhoto"
                with open(screenshot_path, "rb") as photo:
                    resp = requests.post(url, data={
                        "chat_id": self.telegram_chat_id,
                        "caption": caption,
                        "parse_mode": "HTML"
                    }, files={"photo": photo}, timeout=15)

                if resp.status_code == 200:
                    print(f"[AlertManager] Telegram alert sent with image ✅")
                else:
                    print(f"[AlertManager] Telegram error: {resp.status_code} — {resp.text}")
            except Exception as e:
                print(f"[AlertManager] Telegram failed: {e}")
            return

        # ---- Fallback: CallMeBot WhatsApp (text only) ----
        if self.whatsapp_phone and self.whatsapp_api_key:
            try:
                url = "https://api.callmebot.com/send.php"
                resp = requests.get(url, params={
                    "phone": self.whatsapp_phone,
                    "apikey": self.whatsapp_api_key,
                    "text": caption
                }, timeout=10)
                if resp.status_code == 200:
                    print(f"[AlertManager] WhatsApp alert sent (text only)")
                else:
                    print(f"[AlertManager] WhatsApp error: {resp.status_code}")
            except Exception as e:
                print(f"[AlertManager] WhatsApp failed: {e}")

    def get_alert_status(self):
        cooldown_remaining = max(0, self.cooldown_seconds - (time.time() - self.last_alert_time))
        return {
            "total_alerts": self.alert_count,
            "last_alert_message": self.last_alert_message,
            "last_alert_time": datetime.fromtimestamp(self.last_alert_time).strftime("%H:%M:%S") if self.last_alert_time > 0 else "None",
            "cooldown_active": cooldown_remaining > 0,
            "cooldown_remaining": f"{cooldown_remaining:.0f}s"
        }

    def get_latest_snapshot(self):
        if not os.path.exists(self.snapshots_dir):
            return None
        snapshots = [
            os.path.join(self.snapshots_dir, f)
            for f in os.listdir(self.snapshots_dir)
            if f.endswith(('.jpg', '.jpeg', '.png'))
        ]
        return max(snapshots, key=os.path.getmtime) if snapshots else None
