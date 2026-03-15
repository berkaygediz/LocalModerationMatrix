# Local Moderation for Matrix

CLI tool for bulk message deletion and media cleanup in Matrix rooms. Supports E2EE.

## Installation

- Python 3.11

**Base Library:**

```bash
pip install matrix-nio
```

**Encrypted Room Support (Required for --e2ee):**
If you need to scan encrypted rooms, install the extra encryption dependencies:

```bash
pip install "matrix-nio[e2e]"
```

## Session

Once logged in, your session is saved. Just enter your **User ID** on the next run to auto-login without a password.

## Usage

```bash
python localmoderation.py <room_id> [options]
```

## Parameters

| Parameter | Description |
| --------- | ----------- |
| `--search` | Search for a single keyword. |
| `--file` | Search using a wordlist file (one word per line). |
| `--purge-media` | Delete media (images/videos) older than X days. Use `0` for all past media. |
| `--e2ee` | **Required for encrypted rooms.** |
| `--log-room` | Room ID to send deletion logs. |
| `--days`, `--hours` | Time filter (Default: 1 hour). |

## Examples

**1. Search in an encrypted room:**

```bash
python localmoderation.py "!roomID:matrix.org" --search "test" --days 1 --e2ee
```

**2. Scan with wordlist and log actions:**

```bash
python localmoderation.py "!roomID:matrix.org" --file forbidden.txt --days 7 --log-room "!LogRoomID:matrix.org"
```

**3. Delete media older than 90 days:**

```bash
python localmoderation.py "!roomID:matrix.org" --purge-media 90
```

**4. Delete ALL past media in an encrypted room:**

```bash
python localmoderation.py "!roomID:matrix.org" --purge-media 0 --e2ee
```

## Note

If messages aren't found, the room is likely encrypted. Add `--e2ee` to your command.
