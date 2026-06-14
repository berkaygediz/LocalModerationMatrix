import argparse
import asyncio
import base64
import html
import json
import logging
import os
import re
import shutil
import sys
import textwrap
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set

from nio import (
    AsyncClient,
    AsyncClientConfig,
    LoginError,
    MegolmEvent,
    RoomMessageAudio,
    RoomMessageFile,
    RoomMessageImage,
    RoomMessagesError,
    RoomMessageVideo,
    RoomRedactError,
    StickerEvent,
)

logging.getLogger("nio").setLevel(logging.ERROR)

TERM_WIDTH = shutil.get_terminal_size((80, 20)).columns
MSG_WIDTH = min(TERM_WIDTH, 100)

PROJECT_NAME = "LocalModeration for Matrix"
PROJECT_ID = "LocalModerationMatrix"

HOME_DIR = os.path.expanduser("~")
SESSION_FILE = os.path.join(HOME_DIR, f".{PROJECT_ID}_session.json")


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
        "login": "[*] Giriş yapılıyor...",
        "login_fail": "[!] Giriş başarısız: ",
        "sync": "[*] Senkronizasyon...",
        "scan_start": "[*] Tarama Başlıyor",
        "scan_mode": "Mod: Public (Şifresiz)",
        "date_filter": "Tarih Filtresi: ",
        "scan_progress": "   > Tarandı: {} mesaj | Bulunan: {}",
        "scan_done": "   > Tarama Tamamlandı. Toplam: {} mesaj.",
        "no_match": "[~] Belirtilen kriterlere uyan mesaj bulunamadı.",
        "found_count": "[!] {} adet şüpheli mesaj bulundu.",
        "review": "[ {} / {} ] İnceleme",
        "context_prev": "--- Önceki Mesajlar ---",
        "context_next": "--- Sonraki Mesajlar ---",
        "target_header": ">>> İNCELENECEK MESAJ <<<",
        "action_prompt": ">> Silinsin mi? (y/N/a/q): ",
        "action_delete": "   -> Silme işlemi gönderiliyor...",
        "action_success": "   -> Başarıyla silindi.",
        "action_fail": "   -> Hata: ",
        "action_skip": "   -> Atlandı.",
        "action_all": "   -> Toplu Silme Modu Aktif! Geri kalanlar otomatik silinecek...",
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
        "sticker_mode": "[*] Sticker Temizleme Modu Aktif.",
        "sticker_found": "[!] {} adet eski sticker bulundu.",
        "log_action": "İşlem",
        "log_room": "Oda",
        "log_user": "Kullanıcı",
        "log_date": "Tarih",
        "log_reason": "Sebep",
        "log_content": "Mesaj İçeriği",
        "log_deleted": "Silindi",
        "warn_encrypted": "[!] Uyarı: {} adet şifreli mesaj atlandı. Bu araç sadece herkese açık (public) odalarda çalışır.",
        "bulk_deleting": "Siliniyor: {} / {}",
        "bulk_failed": "Hata: {}",
        "bulk_eta": "Kalan Süre: {}",
    }
    en = {
        "welcome": f"=== {PROJECT_NAME} ===",
        "login": "[*] Logging in...",
        "login_fail": "[!] Login failed: ",
        "sync": "[*] Synchronizing...",
        "scan_start": "[*] Scanning Started",
        "scan_mode": "Mode: Public (Unencrypted)",
        "date_filter": "Date Filter: ",
        "scan_progress": "   > Scanned: {} msgs | Found: {}",
        "scan_done": "   -> Scan Complete. Total: {} msgs.",
        "no_match": "[~] No messages found matching criteria.",
        "found_count": "[!] {} suspicious messages found.",
        "review": "[ {} / {} ] Review",
        "context_prev": "--- Previous Messages ---",
        "context_next": "--- Next Messages ---",
        "target_header": ">>> TARGET MESSAGE <<<",
        "action_prompt": ">> Delete? (y/N/a/q): ",
        "action_delete": "   -> Sending delete request...",
        "action_success": "   -> Successfully deleted.",
        "action_fail": "   -> Error: ",
        "action_skip": "   -> Skipped.",
        "action_all": "   -> Delete All mode active! Remaining will be auto-deleted...",
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
        "sticker_mode": "[*] Sticker Purge Mode Active.",
        "sticker_found": "[!] {} old stickers found.",
        "log_action": "Action",
        "log_room": "Room",
        "log_user": "User",
        "log_date": "Date",
        "log_reason": "Reason",
        "log_content": "Message Content",
        "log_deleted": "Deleted",
        "warn_encrypted": "[!] Warning: {} encrypted messages were skipped. This tool only works in public (unencrypted) rooms.",
        "bulk_deleting": "Deleting: {} / {}",
        "bulk_failed": "Failed: {}",
        "bulk_eta": "ETA: {}",
    }
    de = {
        "welcome": f"=== {PROJECT_NAME} ===",
        "login": "[*] Anmelden...",
        "login_fail": "[!] Anmeldung fehlgeschlagen: ",
        "sync": "[*] Synchronisierung...",
        "scan_start": "[*] Scan gestartet",
        "scan_mode": "Modus: Öffentlich (Unverschlüsselt)",
        "date_filter": "Datumsfilter: ",
        "scan_progress": "   > Gescannt: {} Nachr. | Gefunden: {}",
        "scan_done": "   -> Scan abgeschlossen. Gesamt: {} Nachr.",
        "no_match": "[~] Keine Nachrichten entsprechen den Kriterien.",
        "found_count": "[!] {} verdächtige Nachrichten gefunden.",
        "review": "[ {} / {} ] Überprüfung",
        "context_prev": "--- Vorherige Nachrichten ---",
        "context_next": "--- Nächste Nachrichten ---",
        "target_header": ">>> ZIELNACHRICHT <<<",
        "action_prompt": ">> Löschen? (y/N/a/q): ",
        "action_delete": "   -> Löschanfrage wird gesendet...",
        "action_success": "   -> Erfolgreich gelöscht.",
        "action_fail": "   -> Fehler: ",
        "action_skip": "   -> Übersprungen.",
        "action_all": "   -> Alle-Löschen-Modus aktiv! Rest wird automatisch gelöscht...",
        "action_exit": "Beenden...",
        "prompt_user": "Benutzer-ID: ",
        "prompt_pass": "Passwort: ",
        "quote_label": "[ZITAT]",
        "encrypted": "[Verschlüsselte Nachricht]",
        "session_found": "[*] Gespeicherte Sitzung gefunden, wird verwendet...",
        "session_saved": "[*] Sitzung gespeichert.",
        "log_push": "[*] Aktion im Raum protokolliert.",
        "media_mode": "[*] Medien-Bereinigungsmodus aktiv.",
        "media_found": "[!] {} alte Medien gefunden.",
        "media_type": "Typ: {}",
        "sticker_mode": "[*] Sticker-Bereinigungsmodus aktiv.",
        "sticker_found": "[!] {} alte Sticker gefunden.",
        "log_action": "Aktion",
        "log_room": "Raum",
        "log_user": "Benutzer",
        "log_date": "Datum",
        "log_reason": "Grund",
        "log_content": "Nachrichteninhalt",
        "log_deleted": "Gelöscht",
        "warn_encrypted": "[!] Warnung: {} verschlüsselte Nachrichten wurden übersprungen. Dieses Tool funktioniert nur in öffentlichen (unverschlüsselten) Räumen.",
        "bulk_deleting": "Lösche: {} / {}",
        "bulk_failed": "Fehler: {}",
        "bulk_eta": "Restzeit: {}",
    }

    @staticmethod
    def get(lang_code: str) -> Dict:
        if lang_code == "3" or lang_code == "tr":
            return Lang.tr
        elif lang_code == "2" or lang_code == "de":
            return Lang.de
        return Lang.en


def obfuscate_token(data: str) -> str:
    return base64.b64encode(data.encode()[::-1]).decode()


def deobfuscate_token(data: str) -> str:
    try:
        return base64.b64decode(data).decode()[::-1]
    except Exception:
        return ""


def get_single_keypress() -> str:
    try:
        import msvcrt

        pressed_key = msvcrt.getch()
        if pressed_key == b"\r":
            return "n"
        try:
            return pressed_key.decode("utf-8").lower()
        except KeyError:
            msvcrt.getch()
            return ""
    except ImportError:
        import termios
        import tty

        file_descriptor = sys.stdin.fileno()
        old_settings = termios.tcgetattr(file_descriptor)
        try:
            tty.setraw(sys.stdin.fileno())
            pressed_key = sys.stdin.read(1)
            if pressed_key in ("\r", "\n"):
                return "n"
            return pressed_key.lower()
        finally:
            termios.tcsetattr(file_descriptor, termios.TCSADRAIN, old_settings)


def wrap_text(text: str, indent: int = 0) -> List[str]:
    wrapper = textwrap.TextWrapper(
        width=MSG_WIDTH - indent, subsequent_indent=" " * indent
    )
    return wrapper.wrap(text)


def print_message_body(body: str, is_target: bool, language_dict: Dict):
    lines = body.split("\n")
    target_color = Colors.RED + Colors.BOLD if is_target else Colors.WHITE

    for line in lines:
        is_quote = line.strip().startswith(">")
        wrapped_lines = wrap_text(line, indent=6)

        for line_index, wrapped_line in enumerate(wrapped_lines):
            if is_quote:
                label = f"{language_dict['quote_label']} " if line_index == 0 else ""
                print(f"     {Colors.DIM}| {label}{wrapped_line}{Colors.ENDC}")
            else:
                print(f"     {target_color}{wrapped_line}{Colors.ENDC}")


def load_targets_from_source(source: str) -> Set[str]:
    if os.path.exists(source):
        with open(source, "r", encoding="utf-8") as file:
            return set(line.strip().lower() for line in file if line.strip())
    return {source.lower()}


def truncate_text(text: str, max_length: int = 30) -> str:
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def calculate_remaining_time(
    start_time: float, processed_count: int, total_count: int
) -> str:
    if start_time == 0 or processed_count == 0:
        return "--:--:--"

    elapsed_seconds = time.time() - start_time
    processing_rate = processed_count / elapsed_seconds
    remaining_items = total_count - processed_count

    if processing_rate > 0:
        eta_seconds = remaining_items / processing_rate
        return str(timedelta(seconds=int(eta_seconds)))
    return "--:--:--"


class MatrixModerator:
    def __init__(
        self,
        homeserver: str,
        user_id: str,
        password: str,
        room_id: str,
        targets: Set[str],
        cutoff_date: datetime,
        language_dict: Dict,
        log_room_id: str,
        purge_media_days: int,
        purge_sticker_days: int,
    ):
        self.ui_text = language_dict
        self.homeserver = homeserver
        self.user_id = user_id
        self.password = password
        self.room_id = room_id
        self.targets = targets
        self.cutoff_date = cutoff_date
        self.log_room_id = log_room_id
        self.purge_media_days = purge_media_days
        self.purge_sticker_days = purge_sticker_days

        self.store_path = os.path.join(HOME_DIR, f".{PROJECT_ID}_store")

        client_config = AsyncClientConfig(
            store_sync_tokens=True, encryption_enabled=False
        )
        self.client = AsyncClient(
            homeserver, user_id, store_path=self.store_path, config=client_config
        )

        self.recent_buffer = deque(maxlen=10)
        self.encrypted_count = 0

        if targets:
            escaped_targets = [re.escape(t) for t in targets]
            self.search_pattern = re.compile(
                r"\b(" + "|".join(escaped_targets) + r")\b", re.IGNORECASE | re.UNICODE
            )
        else:
            self.search_pattern = None

    async def run(self):
        try:
            await self._handle_login()

            print(f"{Colors.CYAN}{self.ui_text['sync']}{Colors.ENDC}")
            await self.client.sync(timeout=10000)

            if self.purge_media_days is not None:
                await self.run_purge_operation(
                    purge_type="media", purge_days=self.purge_media_days
                )

            if self.purge_sticker_days is not None:
                await self.run_purge_operation(
                    purge_type="sticker", purge_days=self.purge_sticker_days
                )

            if self.purge_media_days is None and self.purge_sticker_days is None:
                candidates = await self.run_text_scan()
                await self.process_candidates(
                    candidates, reason="Text Moderation", is_text_mode=True
                )

        except Exception as e:
            print(f"\n{Colors.RED}Error: {e}{Colors.ENDC}")
        finally:
            await self.client.close()

    async def _handle_login(self):
        session_data = None
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, "r") as file:
                session_data = json.load(file)

        if session_data and session_data.get("user_id") == self.user_id:
            print(f"{Colors.CYAN}{self.ui_text['session_found']}{Colors.ENDC}")
            self.client.restore_login(
                user_id=self.user_id,
                device_id=session_data["device_id"],
                access_token=deobfuscate_token(session_data["token"]),
            )
        else:
            print(f"{Colors.CYAN}{self.ui_text['login']}{Colors.ENDC}")
            login_response = await self.client.login(self.password)

            if isinstance(login_response, LoginError):
                print(
                    f"{Colors.RED}{self.ui_text['login_fail']}{login_response.message}{Colors.ENDC}"
                )
                sys.exit(1)

            with open(SESSION_FILE, "w") as file:
                json.dump(
                    {
                        "user_id": self.user_id,
                        "device_id": self.client.device_id,
                        "token": obfuscate_token(self.client.access_token),
                    },
                    file,
                )
            print(f"{Colors.GREEN}{self.ui_text['session_saved']}{Colors.ENDC}")

    async def run_purge_operation(self, purge_type: str, purge_days: int):
        if purge_type == "media":
            print(f"{Colors.GREEN}{self.ui_text['media_mode']}{Colors.ENDC}")
        else:
            print(f"{Colors.GREEN}{self.ui_text['sticker_mode']}{Colors.ENDC}")

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=purge_days)
        print(f"[*] {self.ui_text['date_filter']}{cutoff_date.strftime('%Y-%m-%d')}")

        current_token = self.client.next_batch
        total_scanned = 0
        candidates = []
        self.encrypted_count = 0

        while True:
            response = await self.client.room_messages(
                self.room_id, start=current_token, limit=100, direction="b"
            )
            if isinstance(response, RoomMessagesError) or not response.chunk:
                break

            for event in response.chunk:
                event_datetime = datetime.fromtimestamp(
                    event.server_timestamp / 1000, tz=timezone.utc
                )

                if event_datetime < cutoff_date:
                    if isinstance(event, MegolmEvent):
                        self.encrypted_count += 1
                        continue

                    is_media = purge_type == "media" and isinstance(
                        event,
                        (
                            RoomMessageImage,
                            RoomMessageVideo,
                            RoomMessageAudio,
                            RoomMessageFile,
                        ),
                    )
                    is_sticker = purge_type == "sticker" and isinstance(
                        event, StickerEvent
                    )

                    if is_media or is_sticker:
                        content = event.source.get("content", {})
                        candidates.append(
                            {
                                "event": event,
                                "body": getattr(
                                    event, "body", content.get("body", "Unknown")
                                ),
                                "msgtype": getattr(
                                    event,
                                    "msgtype",
                                    content.get("msgtype", "m.sticker"),
                                ),
                                "ts": event.server_timestamp,
                            }
                        )
                total_scanned += 1

            current_token = response.end
            if not current_token:
                break
            print(
                f"\r{Colors.CYAN}{self.ui_text['scan_progress'].format(total_scanned, len(candidates))}{Colors.ENDC}",
                end="",
            )

        print(
            f"\n{Colors.GREEN}{self.ui_text['scan_done'].format(total_scanned)}{Colors.ENDC}"
        )

        if self.encrypted_count > 0:
            print(
                f"{Colors.YELLOW}{self.ui_text['warn_encrypted'].format(self.encrypted_count)}{Colors.ENDC}"
            )

        if not candidates:
            print(f"{Colors.YELLOW}{self.ui_text['no_match']}{Colors.ENDC}")
            return

        candidates.sort(key=lambda x: x["ts"])

        if purge_type == "media":
            print(
                f"{Colors.RED}{self.ui_text['media_found'].format(len(candidates))}{Colors.ENDC}"
            )
        else:
            print(
                f"{Colors.RED}{self.ui_text['sticker_found'].format(len(candidates))}{Colors.ENDC}"
            )

        await self.process_candidates(
            candidates, reason=f"{purge_type.capitalize()} Purge", is_text_mode=False
        )

    async def run_text_scan(self) -> List[Dict]:
        print(
            f"{Colors.GREEN}{self.ui_text['scan_start']} ({self.ui_text['scan_mode']}){Colors.ENDC}"
        )
        print(
            f"[*] {self.ui_text['date_filter']}{self.cutoff_date.strftime('%Y-%m-%d %H:%M')}"
        )

        current_token = self.client.next_batch
        total_scanned = 0
        candidates = []

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

            for index, event in enumerate(chunk):
                event_datetime = datetime.fromtimestamp(
                    event.server_timestamp / 1000, tz=timezone.utc
                )
                if event_datetime < self.cutoff_date:
                    print(
                        f"\n{Colors.GREEN}{self.ui_text['scan_done'].format(total_scanned)}{Colors.ENDC}   "
                    )
                    return candidates

                total_scanned += 1

                if isinstance(event, MegolmEvent):
                    self.encrypted_count += 1
                    self._update_recent_buffer(event)
                    continue

                body = getattr(event, "body", None) or event.source.get(
                    "content", {}
                ).get("body", "")

                if not body:
                    self._update_recent_buffer(event)
                    continue

                if self.search_pattern and self.search_pattern.search(body):
                    older_context = chunk[index + 1 : index + 3]
                    newer_context = list(self.recent_buffer)[-2:]
                    candidates.append(
                        {
                            "event": event,
                            "older": older_context,
                            "newer": newer_context,
                            "body": body,
                            "ts": event.server_timestamp,
                        }
                    )

                self._update_recent_buffer(event)

            current_token = response.end
            if not current_token:
                break
            print(
                f"\r{Colors.CYAN}{self.ui_text['scan_progress'].format(total_scanned, len(candidates))}{Colors.ENDC}",
                end="",
            )
            await asyncio.sleep(0.1)

        print(
            f"\n{Colors.GREEN}{self.ui_text['scan_done'].format(total_scanned)}{Colors.ENDC}   "
        )
        return candidates

    def _update_recent_buffer(self, event):
        if hasattr(event, "sender") and hasattr(event, "server_timestamp"):
            self.recent_buffer.append(event)

    async def process_candidates(
        self, candidates: List[Dict], reason: str, is_text_mode: bool
    ):
        if is_text_mode:
            if self.encrypted_count > 0:
                print(
                    f"{Colors.YELLOW}{self.ui_text['warn_encrypted'].format(self.encrypted_count)}{Colors.ENDC}"
                )
            if not candidates:
                print(f"\n{Colors.YELLOW}{self.ui_text['no_match']}{Colors.ENDC}")
                return

            print(
                f"\n{Colors.RED}{Colors.BOLD}{self.ui_text['found_count'].format(len(candidates))}{Colors.ENDC}"
            )

        auto_delete_mode = False
        deleted_count = 0
        failed_count = 0
        start_time = 0.0

        for current_index, candidate in enumerate(candidates, 1):
            user_action = (
                "y"
                if auto_delete_mode
                else await self.display_candidate_for_review(
                    candidate, current_index, len(candidates), is_text_mode
                )
            )

            if user_action == "a":
                auto_delete_mode = True
                user_action = "y"
                deleted_count = 0
                failed_count = 0
                start_time = time.time()
                print(f"{Colors.YELLOW}{self.ui_text['action_all']}{Colors.ENDC}")

            if user_action == "y":
                if is_text_mode:
                    content_preview = candidate.get("body", "")
                else:
                    type_str = (
                        "STICKER"
                        if candidate["msgtype"] == "m.sticker"
                        else candidate["msgtype"].split(".")[-1].upper()
                    )
                    content_preview = f"[{type_str}] {candidate['body']}"

                success = await self.perform_redaction(
                    candidate["event"],
                    reason=reason,
                    content_preview=content_preview,
                    silent=auto_delete_mode,
                )

                if auto_delete_mode:
                    if success:
                        deleted_count += 1
                    else:
                        failed_count += 1

                    processed_count = deleted_count + failed_count
                    total_count = len(candidates)

                    eta_string = calculate_remaining_time(
                        start_time, processed_count, total_count
                    )
                    detail_text = truncate_text(content_preview, 20)
                    progress_message = (
                        f"   > {self.ui_text['bulk_deleting'].format(processed_count, total_count)} | "
                        f"{self.ui_text['bulk_failed'].format(failed_count)} | "
                        f"{self.ui_text['bulk_eta'].format(eta_string)} - {detail_text}"
                    )

                    print(
                        f"\r{Colors.CYAN}{progress_message.ljust(TERM_WIDTH - 10)}{Colors.ENDC}",
                        end="",
                        flush=True,
                    )
                    await asyncio.sleep(0.5)

            elif user_action == "q":
                print("\n" + self.ui_text["action_exit"])
                return

        if auto_delete_mode:
            print()

    async def display_candidate_for_review(
        self, candidate: Dict, current_index: int, total_count: int, is_text_mode: bool
    ) -> str:
        event = candidate["event"]
        event_datetime = datetime.fromtimestamp(event.server_timestamp / 1000)
        formatted_timestamp = event_datetime.strftime("%d.%m.%Y %H:%M")
        sender_name = event.sender.split(":")[0]

        print("\n" + "═" * 50)
        print(
            f"{Colors.BOLD}{Colors.BG_RED} {self.ui_text['review'].format(current_index, total_count)} {Colors.ENDC}"
        )
        print("═" * 50)

        if is_text_mode:
            if candidate.get("older"):
                print(f"{Colors.DIM}{self.ui_text['context_prev']}{Colors.ENDC}")
                for older_event in reversed(candidate["older"]):
                    self._print_context_line(older_event)

            print(
                f"{Colors.RED}{Colors.BOLD}{self.ui_text['target_header']}{Colors.ENDC}"
            )
            print(f"{Colors.BOLD}[{formatted_timestamp}] {sender_name}:{Colors.ENDC}")
            print_message_body(
                candidate["body"], is_target=True, language_dict=self.ui_text
            )

            if candidate.get("newer"):
                print(f"{Colors.CYAN}{self.ui_text['context_next']}{Colors.ENDC}")
                for newer_event in candidate["newer"]:
                    self._print_context_line(newer_event)
        else:
            message_type = (
                "STICKER"
                if candidate["msgtype"] == "m.sticker"
                else candidate["msgtype"].split(".")[-1].upper()
            )
            print(
                f"{Colors.YELLOW}{self.ui_text['media_type'].format(message_type)}{Colors.ENDC}"
            )
            print(f"{Colors.BOLD}[{formatted_timestamp}] {sender_name}:{Colors.ENDC}")
            print(f"     {Colors.WHITE}File: {candidate['body']}{Colors.ENDC}")

        print("─" * 50)
        print(
            f"{Colors.BOLD}{self.ui_text['action_prompt']}{Colors.ENDC}",
            end="",
            flush=True,
        )

        pressed_key = ""
        while pressed_key not in ["y", "n", "a", "q"]:
            pressed_key = get_single_keypress()
            await asyncio.sleep(0.05)

        print()
        return pressed_key

    async def perform_redaction(
        self, event, reason: str, content_preview: str, silent: bool = False
    ) -> bool:
        if not silent:
            print(f"{Colors.YELLOW}{self.ui_text['action_delete']}{Colors.ENDC}")

        response = await self.client.room_redact(
            self.room_id, event.event_id, reason=reason
        )

        if isinstance(response, RoomRedactError):
            if not silent:
                print(
                    f"{Colors.RED}{self.ui_text['action_fail']}{response.message}{Colors.ENDC}"
                )
            return False

        if not silent:
            print(f"{Colors.GREEN}{self.ui_text['action_success']}{Colors.ENDC}")

        if self.log_room_id:
            await self.send_log_to_room(event, reason, content_preview, silent)
        return True

    async def send_log_to_room(
        self, event, reason: str, content_preview: str, silent: bool = False
    ):
        timestamp = datetime.fromtimestamp(event.server_timestamp / 1000).strftime(
            "%d.%m.%Y %H:%M"
        )

        log_message = (
            f"{self.ui_text['log_action']}: {self.ui_text['log_deleted']}\n"
            f"{self.ui_text['log_room']}: {self.room_id}\n"
            f"{self.ui_text['log_user']}: {event.sender}\n"
            f"{self.ui_text['log_date']}: {timestamp}\n"
            f"{self.ui_text['log_reason']}: {reason}\n"
            f"----------------------------------------\n"
            f"{self.ui_text['log_content']}:\n{content_preview}"
        )

        try:
            await self.client.room_send(
                self.log_room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": log_message,
                    "format": "org.matrix.custom.html",
                    "formatted_body": f"<pre><code>{html.escape(log_message)}</code></pre>",
                },
            )
            if not silent:
                print(f"{Colors.DIM}{self.ui_text['log_push']}{Colors.ENDC}")
        except Exception as e:
            if not silent:
                print(f"{Colors.RED}Log error: {e}{Colors.ENDC}")

    def _print_context_line(self, event):
        content = event.source.get("content", {})
        body = getattr(event, "body", None) or content.get("body", "")

        if isinstance(event, MegolmEvent):
            body = self.ui_text["encrypted"]

        formatted_time = datetime.fromtimestamp(event.server_timestamp / 1000).strftime(
            "%H:%M"
        )
        sender_name = event.sender.split(":")[0]

        print(f"{Colors.CYAN}[{formatted_time}] {sender_name}:{Colors.ENDC}")
        print_message_body(body, is_target=False, language_dict=self.ui_text)


def main():
    parser = argparse.ArgumentParser(
        description=f"{PROJECT_NAME} CLI (Public Rooms Only)"
    )
    parser.add_argument("room_id", help="Room ID")

    search_source = parser.add_mutually_exclusive_group(required=False)
    search_source.add_argument("--file", help="Wordlist file")
    search_source.add_argument("--search", help="Single search term")

    parser.add_argument("--days", type=int, default=0)
    parser.add_argument("--hours", type=int, default=1)
    parser.add_argument("--minutes", type=int, default=0)
    parser.add_argument("--homeserver", default="https://matrix-client.matrix.org")
    parser.add_argument("--log-room", help="Room ID to send moderation logs")

    def check_positive(value):
        int_value = int(value)
        if int_value < 0:
            raise argparse.ArgumentTypeError("Negative values are not allowed.")
        return int_value

    parser.add_argument(
        "--purge-media",
        type=check_positive,
        default=None,
        help="Delete media older than X days (0 for all)",
    )

    parser.add_argument(
        "--purge-sticker",
        type=check_positive,
        default=None,
        help="Delete stickers older than X days (0 for all)",
    )

    args = parser.parse_args()

    print(f"{Colors.BOLD}{Lang.en['welcome']}{Colors.ENDC}")
    language_choice = input(
        "Select Language (1: English, 2: Deutsch, 3: Türkçe): "
    ).strip()
    selected_language = Lang.get(language_choice)

    if (
        args.purge_media is None
        and args.purge_sticker is None
        and not (args.file or args.search)
    ):
        parser.error(
            "Text scan requires --file or --search unless --purge-media or --purge-sticker is specified."
        )

    username = input(selected_language["prompt_user"]).strip()

    is_session_valid = False
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as file:
            try:
                data = json.load(file)
                if data.get("user_id") == username:
                    is_session_valid = True
            except json.JSONDecodeError:
                pass

    password = ""
    if not is_session_valid:
        password = input(selected_language["prompt_pass"])

    cutoff_date = datetime.now(timezone.utc) - timedelta(
        days=args.days, hours=args.hours, minutes=args.minutes
    )

    targets = set()
    if args.file or args.search:
        targets = load_targets_from_source(args.file if args.file else args.search)

    moderator = MatrixModerator(
        homeserver=args.homeserver,
        user_id=username,
        password=password,
        room_id=args.room_id,
        targets=targets,
        cutoff_date=cutoff_date,
        language_dict=selected_language,
        log_room_id=args.log_room,
        purge_media_days=args.purge_media,
        purge_sticker_days=args.purge_sticker,
    )

    try:
        asyncio.run(moderator.run())
    except KeyboardInterrupt:
        print("\nExit.")


if __name__ == "__main__":
    main()
