import argparse
import asyncio
import base64
import getpass
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
from datetime import UTC, datetime, timedelta
from typing import Any

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

from .globals import Colors, Lang

logging.getLogger("nio").setLevel(logging.ERROR)

TERM_WIDTH = shutil.get_terminal_size((80, 20)).columns
MSG_WIDTH = min(TERM_WIDTH, 100)

PROJECT_NAME = "LocalModeration for Matrix"
PROJECT_ID = "LocalModerationMatrix"

HOME_DIR = os.path.expanduser("~")
SESSION_FILE = os.path.join(HOME_DIR, f".{PROJECT_ID}_session.json")


def obfuscate_token(data: str) -> str:
    return base64.b64encode(data.encode()[::-1]).decode()


def deobfuscate_token(data: str) -> str:
    try:
        return base64.b64decode(data).decode()[::-1]
    except Exception:  # noqa: BLE001
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


def wrap_text(text: str, indent: int = 0) -> list[str]:
    wrapper = textwrap.TextWrapper(
        width=MSG_WIDTH - indent, subsequent_indent=" " * indent
    )
    return wrapper.wrap(text)


def print_message_body(body: str, is_target: bool, language_dict: dict):
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


def load_targets_from_source(source: str) -> set[str]:
    if os.path.exists(source):
        with open(source, "r", encoding="utf-8") as file:
            return {line.strip().lower() for line in file if line.strip()}
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


class LocalModerationMatrix:
    def __init__(
        self,
        homeserver: str,
        user_id: str,
        password: str,
        room_id: str,
        targets: set[str],
        cutoff_date: datetime,
        language_dict: dict,
        log_room_id: str,
        purge_media_days: int,
        purge_sticker_days: int,
        interactive_mode: bool = False,
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
        self.interactive_mode = interactive_mode

        self.store_path = os.path.join(HOME_DIR, f".{PROJECT_ID}_store")
        client_config = AsyncClientConfig(
            store_sync_tokens=True, encryption_enabled=False
        )
        self.client = AsyncClient(
            homeserver, user_id, store_path=self.store_path, config=client_config
        )

        self.recent_buffer = deque(maxlen=10)
        self.encrypted_count = 0
        self.scanned_messages = []

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
                await self.run_purge_operation("media", self.purge_media_days)

            if self.purge_sticker_days is not None:
                await self.run_purge_operation("sticker", self.purge_sticker_days)

            if self.purge_media_days is None and self.purge_sticker_days is None:
                if self.interactive_mode:
                    await self.run_text_scan(store_in_memory=True)
                    await self.run_interactive_hub()
                else:
                    candidates = await self.run_text_scan()
                    await self.process_candidates(candidates, reason="Text Moderation")

        except Exception as e:  # noqa: BLE001
            print(f"\n{Colors.RED}Error: {e}{Colors.ENDC}")
        finally:
            await self.client.close()

    async def _handle_login(self):
        session_data = None
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, "r") as file:  # noqa: ASYNC230
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

            with open(SESSION_FILE, "w") as file:  # noqa: ASYNC230
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
        print(
            f"{Colors.GREEN}{self.ui_text['media_mode'] if purge_type == 'media' else self.ui_text['sticker_mode']}{Colors.ENDC}"
        )
        cutoff_date = datetime.now(UTC) - timedelta(days=purge_days)
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
                    event.server_timestamp / 1000, tz=UTC
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
                                "msgtype": content.get("msgtype", "m.sticker"),
                                "ts": event.server_timestamp,
                                "is_media": is_media,
                                "is_sticker": is_sticker,
                                "is_text": False,
                            }
                        )
                total_scanned += 1

            current_token = response.end
            if not current_token:
                break
            print(
                f"\r{Colors.CYAN}{self.ui_text['scan_progress'].format(total_scanned)}{Colors.ENDC}",
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
        await self.process_candidates(
            candidates, reason=f"{purge_type.capitalize()} Purge"
        )

    async def run_text_scan(self, store_in_memory: bool = False) -> list[dict]:
        print(
            f"{Colors.GREEN}{self.ui_text['scan_start']} ({self.ui_text['scan_mode']}){Colors.ENDC}"
        )
        print(
            f"[*] {self.ui_text['date_filter']}{self.cutoff_date.strftime('%Y-%m-%d %H:%M')}"
        )

        current_token = self.client.next_batch
        total_scanned = 0
        candidates = []
        retry_count = 0
        max_retries = 3

        while True:
            print(
                f"\r{Colors.CYAN}{self.ui_text['scan_progress'].format(total_scanned, len(candidates))}{Colors.ENDC}",
                end="",
            )

            response = await self.client.room_messages(
                self.room_id, start=current_token, limit=100, direction="b"
            )

            if isinstance(response, RoomMessagesError):
                retry_count += 1
                if retry_count >= max_retries:
                    print(
                        f"\n{Colors.RED}{self.ui_text['scan_error'].format(response.message)}{Colors.ENDC}"
                    )
                    break
                print(
                    f"\n{Colors.YELLOW}{self.ui_text['scan_retry'].format(retry_count, max_retries)}{Colors.ENDC}"
                )
                await asyncio.sleep(5)
                continue

            retry_count = 0

            if not response.chunk:
                break

            chunk = list(response.chunk)

            for index, event in enumerate(chunk):
                event_datetime = datetime.fromtimestamp(
                    event.server_timestamp / 1000, tz=UTC
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
                older_context = chunk[index + 1 : index + 3]
                newer_context = list(self.recent_buffer)[-2:]

                is_media = isinstance(
                    event,
                    (
                        RoomMessageImage,
                        RoomMessageVideo,
                        RoomMessageAudio,
                        RoomMessageFile,
                    ),
                )
                is_sticker = isinstance(event, StickerEvent)

                event_content = event.source.get("content", {})
                msg_type = event_content.get("msgtype", "m.text")

                if store_in_memory and body:
                    self.scanned_messages.append(
                        {
                            "event": event,
                            "older": older_context,
                            "newer": newer_context,
                            "body": body,
                            "ts": event.server_timestamp,
                            "msgtype": msg_type,
                            "is_media": is_media,
                            "is_sticker": is_sticker,
                            "is_text": not is_media and not is_sticker,
                        }
                    )

                if not body:
                    self._update_recent_buffer(event)
                    continue

                if self.search_pattern and self.search_pattern.search(body):
                    candidates.append(
                        {
                            "event": event,
                            "older": older_context,
                            "newer": newer_context,
                            "body": body,
                            "ts": event.server_timestamp,
                            "msgtype": msg_type,
                            "is_media": is_media,
                            "is_sticker": is_sticker,
                            "is_text": not is_media and not is_sticker,
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

    async def run_interactive_hub(self):
        print(
            f"\n{Colors.GREEN}{self.ui_text['cache_loaded'].format(len(self.scanned_messages))}{Colors.ENDC}"
        )
        while True:
            print(f"\n{Colors.BOLD}{self.ui_text['interactive_title']}{Colors.ENDC}")
            print(f"{Colors.CYAN}{self.ui_text['interactive_user']}{Colors.ENDC}")
            print(f"{Colors.CYAN}{self.ui_text['interactive_word']}{Colors.ENDC}")
            print(f"{Colors.CYAN}{self.ui_text['interactive_file']}{Colors.ENDC}")
            print(f"{Colors.CYAN}{self.ui_text['interactive_media']}{Colors.ENDC}")
            print(f"{Colors.CYAN}{self.ui_text['interactive_sticker']}{Colors.ENDC}")
            print(f"{Colors.YELLOW}{self.ui_text['interactive_exit']}{Colors.ENDC}")

            choice = (
                input(f"{Colors.BOLD}{self.ui_text['interactive_prompt']}{Colors.ENDC}")
                .strip()
                .lower()
            )

            if choice == "1":
                user_id = input(f"{self.ui_text['interactive_user_prompt']}").strip()
                if not user_id:
                    continue

                if not user_id.startswith("@"):
                    user_id = "@" + user_id

                filtered = [
                    m for m in self.scanned_messages if m["event"].sender == user_id
                ]
                await self.process_candidates(filtered, reason="User Moderation")

            elif choice == "2":
                keyword = input(f"{self.ui_text['interactive_word_prompt']}").strip()
                if not keyword:
                    continue
                targets = {keyword.lower()}
                escaped_targets = [re.escape(t) for t in targets]
                temp_pattern = re.compile(
                    r"\b(" + "|".join(escaped_targets) + r")\b",
                    re.IGNORECASE | re.UNICODE,
                )
                filtered = [
                    m for m in self.scanned_messages if temp_pattern.search(m["body"])
                ]
                await self.process_candidates(filtered, reason="Keyword Moderation")

            elif choice == "3":
                file_path = input(f"{self.ui_text['interactive_file_prompt']}").strip()
                if not file_path:
                    continue
                if not os.path.exists(file_path):
                    print(f"{Colors.RED}{self.ui_text['file_not_found']}{Colors.ENDC}")
                    continue
                targets = load_targets_from_source(file_path)
                if not targets:
                    print(f"{Colors.YELLOW}{self.ui_text['file_empty']}{Colors.ENDC}")
                    continue
                escaped_targets = [re.escape(t) for t in targets]
                temp_pattern = re.compile(
                    r"\b(" + "|".join(escaped_targets) + r")\b",
                    re.IGNORECASE | re.UNICODE,
                )
                filtered = [
                    m for m in self.scanned_messages if temp_pattern.search(m["body"])
                ]
                await self.process_candidates(filtered, reason="File Moderation")

            elif choice == "4":
                filtered = [m for m in self.scanned_messages if m.get("is_media")]
                await self.process_candidates(filtered, reason="Media Purge")

            elif choice == "5":
                filtered = [m for m in self.scanned_messages if m.get("is_sticker")]
                await self.process_candidates(filtered, reason="Sticker Purge")

            elif choice == "q":
                break

    async def process_candidates(self, candidates: list[dict], reason: str):
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
                    candidate, current_index, len(candidates)
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
                content_preview = candidate.get("body", "")
                if not candidate.get("is_text", True):
                    type_str = (
                        "STICKER"
                        if candidate.get("is_sticker")
                        else candidate["msgtype"].split(".")[-1].upper()
                    )
                    content_preview = f"[{type_str}] {content_preview}"

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
                print(f"\n{Colors.YELLOW}{self.ui_text['action_exit']}{Colors.ENDC}")
                return

        if auto_delete_mode:
            print()

    async def display_candidate_for_review(
        self, candidate: dict, current_index: int, total_count: int
    ) -> str:
        event = candidate["event"]
        event_datetime = datetime.fromtimestamp(event.server_timestamp / 1000, tz=UTC)
        formatted_timestamp = event_datetime.strftime("%d.%m.%Y %H:%M")
        sender_name = event.sender.split(":")[0]

        print("\n" + "─" * 50)
        print(
            f"{Colors.BOLD}{self.ui_text['review'].format(current_index, total_count)}{Colors.ENDC}"
        )

        if candidate.get("older"):
            for older_event in reversed(candidate["older"]):
                self._print_context_line(older_event)

        if candidate.get("is_text", True):
            print(
                f"{Colors.RED}{Colors.BOLD}>>> [{formatted_timestamp}] {sender_name}:{Colors.ENDC}"
            )
            print_message_body(
                candidate["body"], is_target=True, language_dict=self.ui_text
            )
        else:
            msg_type = (
                "STICKER"
                if candidate.get("is_sticker")
                else candidate["msgtype"].split(".")[-1].upper()
            )
            print(
                f"{Colors.RED}{Colors.BOLD}>>> [{formatted_timestamp}] {sender_name} ({msg_type}):{Colors.ENDC}"
            )
            print(f"     {Colors.WHITE}File: {candidate['body']}{Colors.ENDC}")

        if candidate.get("newer"):
            for newer_event in candidate["newer"]:
                self._print_context_line(newer_event)

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
        self, event: Any, reason: str, content_preview: str, silent: bool = False
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
        self, event: Any, reason: str, content_preview: str, silent: bool = False
    ):
        timestamp = datetime.fromtimestamp(
            event.server_timestamp / 1000, tz=UTC
        ).strftime("%d.%m.%Y %H:%M")
        log_message = (
            f"Action: Deleted\nRoom: {self.room_id}\nUser: {event.sender}\n"
            f"Date: {timestamp}\nReason: {reason}\n----------------------------------------\nContent:\n{content_preview}"
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
        except Exception as e:  # noqa: BLE001
            if not silent:
                print(f"{Colors.RED}Log error: {e}{Colors.ENDC}")

    def _print_context_line(self, event: Any):
        content = event.source.get("content", {})
        body = getattr(event, "body", None) or content.get("body", "")

        if isinstance(event, MegolmEvent):
            body = self.ui_text["encrypted"]

        formatted_time = datetime.fromtimestamp(
            event.server_timestamp / 1000, tz=UTC
        ).strftime("%H:%M")
        sender_name = event.sender.split(":")[0]

        print(f"{Colors.DIM}[{formatted_time}] {sender_name}:{Colors.ENDC}")
        print_message_body(body, is_target=False, language_dict=self.ui_text)


def main():
    parser = argparse.ArgumentParser(
        description=f"{PROJECT_NAME} CLI (Public Rooms Only)"
    )
    parser.add_argument("room_id", help="Room ID")

    search_source = parser.add_mutually_exclusive_group(required=False)
    search_source.add_argument("--file", help="Wordlist file")
    search_source.add_argument("--search", help="Single search term")

    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Scan once and enter interactive mode.",
    )

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

    username = input(selected_language["prompt_user"]).strip()

    if username.lower() == "reset":
        confirm = (
            input(f"{Colors.RED}{selected_language['reset_confirm']}{Colors.ENDC}")
            .strip()
            .lower()
        )
        if confirm == "y":
            if os.path.exists(SESSION_FILE):
                os.remove(SESSION_FILE)
            store_path = os.path.join(HOME_DIR, f".{PROJECT_ID}_store")
            if os.path.exists(store_path):
                shutil.rmtree(store_path)
            print(f"{Colors.GREEN}{selected_language['reset_done']}{Colors.ENDC}")
            sys.exit(0)
        else:
            print(f"{Colors.YELLOW}{selected_language['reset_cancel']}{Colors.ENDC}")
            sys.exit(0)

    if (
        args.purge_media is None
        and args.purge_sticker is None
        and not (args.file or args.search)
        and not args.interactive
    ):
        parser.error(
            "Text scan requires --file or --search unless --interactive or --purge-media is specified."
        )

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
        password = getpass.getpass(selected_language["prompt_pass"])

    cutoff_date = datetime.now(UTC) - timedelta(
        days=args.days, hours=args.hours, minutes=args.minutes
    )

    targets = set()
    if args.file or args.search:
        targets = load_targets_from_source(args.file if args.file else args.search)

    moderator = LocalModerationMatrix(
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
        interactive_mode=args.interactive,
    )

    try:
        asyncio.run(moderator.run())
    except KeyboardInterrupt:
        print("\nExit.")


if __name__ == "__main__":
    main()
