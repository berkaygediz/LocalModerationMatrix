import argparse
import asyncio
import base64
import html
import json
import os
import re
import shutil
import sys
import textwrap
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Dict, Set

from nio import (AsyncClient, AsyncClientConfig, LoginError, RoomMessagesError,
                 RoomRedactError)

TERM_WIDTH = shutil.get_terminal_size((80, 20)).columns
MSG_WIDTH = min(TERM_WIDTH, 100)

PROJECT_NAME = "LocalModeration for Matrix"
PROJECT_ID = "LocalModerationMatrix"
SESSION_FILE = f"{PROJECT_ID}_session.json"


class Colors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    ENDC = "\033[0m"
    DIM = "\033[90m"
    WHITE = "\033[37m"
    BG_RED = "\033[41m"


class Lang:
    tr = {
        "welcome": f"=== {PROJECT_NAME} ===",
        "select_lang": "Dil seçiniz / Select Language (1: TR, 2: EN): ",
        "login": "[*] Giriş yapılıyor...",
        "login_fail": "[!] Giriş başarısız: ",
        "sync": "[*] Senkronizasyon...",
        "scan_start": "[*] Tarama Başlıyor",
        "scan_mode": "Mod: ",
        "date_filter": "Tarih Filtresi: ",
        "scan_progress": "   > Tarandı: {} mesaj | Bulunan: {}",
        "scan_done": "   > Tarama Tamamlandı. Toplam: {} mesaj.",
        "no_match": "[~] Belirtilen kriterlere uyan mesaj bulunamadı.",
        "found_count": "[!] {} adet şüpheli mesaj bulundu.",
        "review": "[ {} / {} ] İnceleme",
        "context_prev": "--- Önceki Mesajlar (Geçmiş) ---",
        "context_next": "--- Sonraki Mesajlar (Gelecek) ---",
        "target_header": ">>> İNCELENECEK MESAJ <<<",
        "action_prompt": ">> Silinsin mi? (y/N/a): ",
        "action_delete": "   -> Silme işlemi gönderiliyor...",
        "action_success": "   -> Başarıyla silindi.",
        "action_fail": "   -> Hata: ",
        "action_skip": "   -> Atlandı.",
        "action_exit": "Çıkış yapılıyor...",
        "prompt_user": "User ID: ",
        "prompt_pass": "Password: ",
        "quote_label": "[ALINTI]",
        "encrypted": "[Şifreli Mesaj]",
        "session_found": "[*] Kayıtlı oturum bulundu, kullanılıyor...",
        "session_saved": "[*] Oturum kaydedildi.",
        "log_push": "[*] İşlem log odasına iletildi.",
        "media_mode": "[*] Medya Temizleme Modu Aktif.",
        "media_found": "[!] {} adet eski medya bulundu.",
        "media_type": "Tür: {}",
        "log_action": "İşlem",
        "log_room": "Oda",
        "log_user": "Kullanıcı",
        "log_date": "Tarih",
        "log_reason": "Sebep",
        "log_content": "Mesaj İçeriği",
        "log_deleted": "Silindi",
        "warn_encrypted": "[!] Uyarı: {} adet şifreli mesaj atlandı. Okumak için --e2ee parametresini kullanın.",
    }
    en = {
        "welcome": f"=== {PROJECT_NAME} ===",
        "select_lang": "Select Language (1: TR, 2: EN): ",
        "login": "[*] Logging in...",
        "login_fail": "[!] Login failed: ",
        "sync": "[*] Synchronizing...",
        "scan_start": "[*] Scanning Started",
        "scan_mode": "Mode: ",
        "date_filter": "Date Filter: ",
        "scan_progress": "   > Scanned: {} msgs | Found: {}",
        "scan_done": "   > Scan Complete. Total: {} msgs.",
        "no_match": "[~] No messages found matching criteria.",
        "found_count": "[!] {} suspicious messages found.",
        "review": "[ {} / {} ] Review",
        "context_prev": "--- Previous Messages (Context) ---",
        "context_next": "--- Next Messages (Context) ---",
        "target_header": ">>> TARGET MESSAGE <<<",
        "action_prompt": ">> Delete? (y/N/a): ",
        "action_delete": "   -> Sending delete request...",
        "action_success": "   -> Successfully deleted.",
        "action_fail": "   -> Error: ",
        "action_skip": "   -> Skipped.",
        "action_exit": "Exiting...",
        "prompt_user": "User ID: ",
        "prompt_pass": "Password: ",
        "quote_label": "[QUOTE]",
        "encrypted": "[Encrypted Message]",
        "session_found": "[*] Saved session found, using it...",
        "session_saved": "[*] Session saved.",
        "log_push": "[*] Action logged to room.",
        "media_mode": "[*] Media Purge Mode Active.",
        "media_found": "[!] {} old media items found.",
        "media_type": "Type: {}",
        "log_action": "Action",
        "log_room": "Room",
        "log_user": "User",
        "log_date": "Date",
        "log_reason": "Reason",
        "log_content": "Message Content",
        "log_deleted": "Deleted",
        "warn_encrypted": "[!] Warning: {} encrypted messages were skipped. Use --e2ee to read them.",
    }

    @staticmethod
    def get(lang_code):
        return Lang.tr if lang_code == "tr" else Lang.en


def simple_encrypt(data: str) -> str:
    return base64.b64encode(data.encode()[::-1]).decode()


def simple_decrypt(data: str) -> str:
    try:
        return base64.b64decode(data).decode()[::-1]
    except:
        return ""


def get_key() -> str:
    try:
        import msvcrt

        ch = msvcrt.getch()
        try:
            return ch.decode("utf-8").lower()
        except:
            msvcrt.getch()
            return ""
    except ImportError:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
            return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def wrap_text(text, indent=0):
    wrapper = textwrap.TextWrapper(
        width=MSG_WIDTH - indent, subsequent_indent=" " * indent
    )
    return wrapper.wrap(text)


def print_smart_message(body: str, is_target: bool, lang_obj: Dict):
    lines = body.split("\n")
    target_color = Colors.RED + Colors.BOLD if is_target else Colors.WHITE

    for line in lines:
        is_quote = line.strip().startswith(">")
        wrapped_lines = wrap_text(line, indent=6)

        for i, w_line in enumerate(wrapped_lines):
            if is_quote:
                label = f"{lang_obj['quote_label']} " if i == 0 else ""
                print(f"     {Colors.DIM}| {label}{w_line}{Colors.ENDC}")
            else:
                print(f"     {target_color}{w_line}{Colors.ENDC}")


def load_targets(source: str) -> Set[str]:
    if os.path.exists(source):
        with open(source, "r", encoding="utf-8") as f:
            return set(line.strip().lower() for line in f if line.strip())
    return {source.lower()}


class MatrixModerator:
    def __init__(
        self,
        homeserver,
        user_id,
        password,
        room_id,
        targets,
        cutoff_date,
        use_e2ee,
        lang,
        log_room_id,
        purge_media_days,
    ):
        self.lang_dict = lang
        self.t = self.lang_dict
        self.homeserver = homeserver
        self.user_id = user_id
        self.password = password
        self.room_id = room_id
        self.targets = targets
        self.cutoff_date = cutoff_date
        self.log_room_id = log_room_id
        self.purge_media_days = purge_media_days
        self.use_e2ee = use_e2ee

        self.store_path = (
            os.path.join(os.getcwd(), f"{PROJECT_ID}_store") if use_e2ee else None
        )
        config = AsyncClientConfig(store_sync_tokens=True, encryption_enabled=use_e2ee)
        self.client = AsyncClient(
            homeserver, user_id, store_path=self.store_path, config=config
        )

        self.candidates = []
        self.recent_buffer = deque(maxlen=10)
        self.encrypted_count = 0

        if targets:
            escaped = [re.escape(t) for t in targets]
            self.pattern = re.compile(
                r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE | re.UNICODE
            )
        else:
            self.pattern = None

    async def run(self):
        try:
            session_data = None
            if os.path.exists(SESSION_FILE):
                with open(SESSION_FILE, "r") as f:
                    session_data = json.load(f)

            if session_data and session_data.get("user_id") == self.user_id:
                print(f"{Colors.CYAN}{self.t['session_found']}{Colors.ENDC}")
                self.client.restore_login(
                    user_id=self.user_id,
                    device_id=session_data["device_id"],
                    access_token=simple_decrypt(session_data["token"]),
                )
            else:
                print(f"{Colors.CYAN}{self.t['login']}{Colors.ENDC}")
                login_response = await self.client.login(self.password)

                if isinstance(login_response, LoginError):
                    print(
                        f"{Colors.RED}{self.t['login_fail']}{login_response.message}{Colors.ENDC}"
                    )
                    return

                with open(SESSION_FILE, "w") as f:
                    json.dump(
                        {
                            "user_id": self.user_id,
                            "device_id": self.client.device_id,
                            "token": simple_encrypt(self.client.access_token),
                        },
                        f,
                    )
                print(f"{Colors.GREEN}{self.t['session_saved']}{Colors.ENDC}")

            print(f"{Colors.CYAN}{self.t['sync']}{Colors.ENDC}")
            await self.client.sync(timeout=10000)

            if self.purge_media_days is not None:
                await self.run_media_purge()
            else:
                await self.run_text_scan()

        except Exception as e:
            print(f"\n{Colors.RED}Error: {e}{Colors.ENDC}")
        finally:
            await self.client.close()
            if self.store_path and os.path.exists(self.store_path):
                try:
                    shutil.rmtree(self.store_path)
                except:
                    pass

    async def run_media_purge(self):
        print(f"{Colors.GREEN}{self.t['media_mode']}{Colors.ENDC}")
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.purge_media_days)
        print(f"[*] {self.t['date_filter']}{cutoff.strftime('%Y-%m-%d')}")

        current_token = self.client.next_batch
        total_scanned = 0

        while True:
            response = await self.client.room_messages(
                self.room_id, start=current_token, limit=100, direction="b"
            )
            if isinstance(response, RoomMessagesError):
                break
            if not response.chunk:
                break

            for event in response.chunk:
                event_dt = datetime.fromtimestamp(
                    event.server_timestamp / 1000, tz=timezone.utc
                )

                if event_dt < cutoff:
                    content = event.source.get("content", {})
                    msgtype = content.get("msgtype")

                    if msgtype in ["m.image", "m.video", "m.audio", "m.file"]:
                        self.candidates.append(
                            {
                                "event": event,
                                "body": content.get("body", "Unknown"),
                                "msgtype": msgtype,
                                "ts": event.server_timestamp,
                            }
                        )
                total_scanned += 1

            current_token = response.end
            if not current_token:
                break
            print(
                f"\r{Colors.CYAN}{self.t['scan_progress'].format(total_scanned, len(self.candidates))}{Colors.ENDC}",
                end="",
            )

        print(
            f"\n{Colors.GREEN}{self.t['scan_done'].format(total_scanned)}{Colors.ENDC}"
        )

        if not self.candidates:
            print(f"{Colors.YELLOW}{self.t['no_match']}{Colors.ENDC}")
            return

        self.candidates.sort(key=lambda x: x["ts"])
        print(
            f"{Colors.RED}{self.t['media_found'].format(len(self.candidates))}{Colors.ENDC}"
        )

        for idx, item in enumerate(self.candidates, 1):
            await self.review_media_item(item, idx, len(self.candidates))

    async def run_text_scan(self):
        print(
            f"{Colors.GREEN}{self.t['scan_start']} ({self.t['scan_mode']}{'E2EE' if self.store_path else 'Public'}){Colors.ENDC}"
        )
        print(
            f"[*] {self.t['date_filter']}{self.cutoff_date.strftime('%Y-%m-%d %H:%M')}"
        )

        current_token = self.client.next_batch
        total_scanned = 0

        while True:
            response = await self.client.room_messages(
                self.room_id, start=current_token, limit=100, direction="b"
            )
            if isinstance(response, RoomMessagesError):
                await asyncio.sleep(5)
                continue
            if not response.chunk:
                break

            chunk = list(response.chunk)

            for i, event in enumerate(chunk):
                event_dt = datetime.fromtimestamp(
                    event.server_timestamp / 1000, tz=timezone.utc
                )
                if event_dt < self.cutoff_date:
                    await self.finalize_scan(total_scanned)
                    return

                total_scanned += 1
                event_type = event.source.get("type")

                if event_type == "m.room.encrypted" and not self.use_e2ee:
                    self.encrypted_count += 1
                    self.update_buffer(event)
                    continue

                if event_type not in ["m.room.message", "m.room.encrypted"]:
                    self.update_buffer(event)
                    continue

                body = event.source.get("content", {}).get("body", "")
                if not body:
                    self.update_buffer(event)
                    continue

                if self.pattern and self.pattern.search(body):
                    older_ctx = chunk[i + 1 : i + 3]
                    newer_ctx = list(self.recent_buffer)[-2:]
                    self.candidates.append(
                        {
                            "event": event,
                            "older": older_ctx,
                            "newer": newer_ctx,
                            "body": body,
                            "ts": event.server_timestamp,
                        }
                    )

                self.update_buffer(event)

            current_token = response.end
            if not current_token:
                break
            print(
                f"\r{Colors.CYAN}{self.t['scan_progress'].format(total_scanned, len(self.candidates))}{Colors.ENDC}",
                end="",
            )
            await asyncio.sleep(0.1)

        await self.finalize_scan(total_scanned)

    def update_buffer(self, event):
        if event.source.get("type") in ["m.room.message", "m.room.encrypted"]:
            self.recent_buffer.append(event)

    async def finalize_scan(self, total_count):
        print(
            f"\r{Colors.GREEN}{self.t['scan_done'].format(total_count)}{Colors.ENDC}   "
        )

        if self.encrypted_count > 0 and not self.use_e2ee:
            print(
                f"{Colors.YELLOW}{self.t['warn_encrypted'].format(self.encrypted_count)}{Colors.ENDC}"
            )

        if not self.candidates:
            print(f"\n{Colors.YELLOW}{self.t['no_match']}{Colors.ENDC}")
            return

        self.candidates.sort(key=lambda x: x["ts"])
        print(
            f"\n{Colors.RED}{Colors.BOLD}{self.t['found_count'].format(len(self.candidates))}{Colors.ENDC}"
        )

        for idx, item in enumerate(self.candidates, 1):
            await self.review_item(item, idx, len(self.candidates))

    async def review_item(self, item, current_idx, total):
        event = item["event"]
        ts_dt = datetime.fromtimestamp(event.server_timestamp / 1000)
        ts_str = ts_dt.strftime("%d.%m.%Y %H:%M")
        sender = event.sender.split(":")[0]

        print("\n" + "═" * 50)
        print(
            f"{Colors.BOLD}{Colors.BG_RED} {self.t['review'].format(current_idx, total)} {Colors.ENDC}"
        )
        print("═" * 50)

        if item["older"]:
            print(f"{Colors.DIM}{self.t['context_prev']}{Colors.ENDC}")
            for ev in reversed(item["older"]):
                self.print_context_line(ev)

        print(f"{Colors.RED}{Colors.BOLD}{self.t['target_header']}{Colors.ENDC}")
        print(f"{Colors.BOLD}[{ts_str}] {sender}:{Colors.ENDC}")
        print_smart_message(item["body"], is_target=True, lang_obj=self.t)

        if item["newer"]:
            print(f"{Colors.CYAN}{self.t['context_next']}{Colors.ENDC}")
            for ev in item["newer"]:
                self.print_context_line(ev)

        print("─" * 50)
        print(
            f"{Colors.BOLD}{self.t['action_prompt']}{Colors.ENDC}", end="", flush=True
        )

        key = ""
        while key not in ["y", "n", "a"]:
            key = get_key()
            await asyncio.sleep(0.05)

        print()

        if key == "a":
            print(self.t["action_exit"])
            sys.exit(0)
        elif key == "y":
            body_content = event.source.get("content", {}).get("body", "")
            await self.perform_redaction(
                event, reason="Text Moderation", content_preview=body_content
            )

    async def review_media_item(self, item, current_idx, total):
        event = item["event"]
        ts_dt = datetime.fromtimestamp(event.server_timestamp / 1000)
        ts_str = ts_dt.strftime("%d.%m.%Y %H:%M")
        sender = event.sender.split(":")[0]
        msg_type = item["msgtype"].split(".")[-1].upper()

        print("\n" + "═" * 50)
        print(
            f"{Colors.BOLD}{Colors.BG_RED} {self.t['review'].format(current_idx, total)} {Colors.ENDC}"
        )
        print("═" * 50)

        print(f"{Colors.YELLOW}{self.t['media_type'].format(msg_type)}{Colors.ENDC}")
        print(f"{Colors.BOLD}[{ts_str}] {sender}:{Colors.ENDC}")
        print(f"     {Colors.WHITE}Dosya: {item['body']}{Colors.ENDC}")
        print("─" * 50)

        print(
            f"{Colors.BOLD}{self.t['action_prompt']}{Colors.ENDC}", end="", flush=True
        )

        key = ""
        while key not in ["y", "n", "a"]:
            key = get_key()
            await asyncio.sleep(0.05)

        print()
        if key == "a":
            print(self.t["action_exit"])
            sys.exit(0)
        elif key == "y":
            await self.perform_redaction(
                event,
                reason="Media Purge",
                content_preview=f"[{msg_type}] {item['body']}",
            )

    async def perform_redaction(self, event, reason, content_preview):
        print(f"{Colors.YELLOW}{self.t['action_delete']}{Colors.ENDC}")
        res = await self.client.room_redact(self.room_id, event.event_id, reason=reason)

        if isinstance(res, RoomRedactError):
            print(f"{Colors.RED}{self.t['action_fail']}{res.message}{Colors.ENDC}")
        else:
            print(f"{Colors.GREEN}{self.t['action_success']}{Colors.ENDC}")
            if self.log_room_id:
                await self.send_log(event, reason, content_preview)

    async def send_log(self, event, reason, content_preview):
        ts = datetime.fromtimestamp(event.server_timestamp / 1000).strftime(
            "%d.%m.%Y %H:%M"
        )

        log_text = (
            f"{self.t['log_action']}: {self.t['log_deleted']}\n"
            f"{self.t['log_room']}: {self.room_id}\n"
            f"{self.t['log_user']}: {event.sender}\n"
            f"{self.t['log_date']}: {ts}\n"
            f"{self.t['log_reason']}: {reason}\n"
            f"----------------------------------------\n"
            f"{self.t['log_content']}:\n{content_preview}"
        )

        try:
            await self.client.room_send(
                self.log_room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": log_text,
                    "format": "org.matrix.custom.html",
                    "formatted_body": f"<pre><code>{html.escape(log_text)}</code></pre>",
                },
            )
            print(f"{Colors.DIM}{self.t['log_push']}{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.RED}Log error: {e}{Colors.ENDC}")

    def print_context_line(self, ev):
        content = ev.source.get("content", {})
        body = content.get("body", "")
        if ev.source.get("type") == "m.room.encrypted":
            body = self.t["encrypted"]

        ts = datetime.fromtimestamp(ev.server_timestamp / 1000).strftime("%H:%M")
        sender = ev.sender.split(":")[0]

        print(f"{Colors.CYAN}[{ts}] {sender}:{Colors.ENDC}")
        print_smart_message(body, is_target=False, lang_obj=self.t)


def main():
    parser = argparse.ArgumentParser(description=f"{PROJECT_NAME} CLI")
    parser.add_argument("room_id", help="Room ID")
    src = parser.add_mutually_exclusive_group(required=False)
    src.add_argument("--file", help="Wordlist file")
    src.add_argument("--search", help="Single search term")

    parser.add_argument("--days", type=int, default=0)
    parser.add_argument("--hours", type=int, default=1)
    parser.add_argument("--minutes", type=int, default=0)
    parser.add_argument("--homeserver", default="https://matrix-client.matrix.org")
    parser.add_argument("--e2ee", action="store_true", help="Enable E2EE")
    parser.add_argument("--log-room", help="Room ID to send moderation logs")

    def check_positive(value):
        ivalue = int(value)
        if ivalue < 0:
            raise argparse.ArgumentTypeError("Negatif değer kabul edilmez.")
        return ivalue

    parser.add_argument(
        "--purge-media",
        type=check_positive,
        default=None,
        help="Delete media older than X days (0 for all)",
    )

    args = parser.parse_args()

    print(f"{Colors.BOLD}{Lang.tr['welcome']}{Colors.ENDC}")
    lang_choice = input(Lang.tr["select_lang"]).strip()
    selected_lang_dict = Lang.get("tr" if lang_choice != "2" else "en")

    if args.purge_media is None and not (args.file or args.search):
        parser.error(
            "Text scan requires --file or --search unless --purge-media is specified."
        )

    user = input(selected_lang_dict["prompt_user"]).strip()

    session_exists = False
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            try:
                data = json.load(f)
                if data.get("user_id") == user:
                    session_exists = True
            except:
                pass

    pwd = ""
    if not session_exists:
        pwd = input(selected_lang_dict["prompt_pass"])

    cutoff = datetime.now(timezone.utc) - timedelta(
        days=args.days, hours=args.hours, minutes=args.minutes
    )
    targets = set()
    if args.file or args.search:
        targets = load_targets(args.file if args.file else args.search)

    mod = MatrixModerator(
        homeserver=args.homeserver,
        user_id=user,
        password=pwd,
        room_id=args.room_id,
        targets=targets,
        cutoff_date=cutoff,
        use_e2ee=args.e2ee,
        lang=selected_lang_dict,
        log_room_id=args.log_room,
        purge_media_days=args.purge_media,
    )

    try:
        asyncio.run(mod.run())
    except KeyboardInterrupt:
        print("\nExit.")


if __name__ == "__main__":
    main()
