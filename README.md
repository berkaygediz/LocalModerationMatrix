# LocalModeration for Matrix

A CLI tool for bulk message deletion, media cleanup, and sticker purge in Matrix rooms.

> **Note:** This tool targets **public (unencrypted) rooms**. Encrypted messages are skipped automatically.

## Installation

**View on PyPI:** [pypi.org/project/localmoderationmatrix](https://pypi.org/project/localmoderationmatrix/)

**Using pip:**

```bash
pip install localmoderationmatrix
```

**Using uv:**

```bash
uv tool install localmoderationmatrix
```

**Standalone Executable:** [GitHub Releases](https://github.com/berkaygediz/LocalModerationMatrix/releases)

## Session

Once logged in, your session is saved in your home directory. Just enter your **User ID** on the next run to auto-login.

## Usage

```bash
localmoderationmatrix <room_id> [options]
```

### Parameters

| Parameter | Description |
| --- | --- |
| `room_id` | (Required) The Matrix room ID. |
| `--search` | Search for a single keyword. |
| `--file` | Search using a wordlist file (one word per line). |
| `--purge-media` | Delete media older than X days (`0` for all). |
| `--purge-sticker` | Delete stickers older than X days (`0` for all). |
| `--log-room` | Room ID to send moderation logs. |
| `--days` | Time filter: Days (Default: 0). |
| `--hours` | Time filter: Hours (Default: 1). |
| `--minutes` | Time filter: Minutes (Default: 0). |
| `--homeserver` | Custom homeserver URL. |

### Interactive Keys

* `y` : Delete.
* `n` : Skip.
* `a` : **Delete All** remaining items automatically.
* `q` : Quit.

## Examples

**Search for a keyword:**

```bash
localmoderationmatrix "!roomID:matrix.org" --search "spam"
```

**Scan with a wordlist and log actions:**

```bash
localmoderationmatrix "!roomID:matrix.org" --file words.txt --days 7 --log-room "!LogRoomID:matrix.org"
```

**Delete media older than 90 days:**

```bash
localmoderationmatrix "!roomID:matrix.org" --purge-media 90
```

**Delete ALL stickers:**

```bash
localmoderationmatrix "!roomID:matrix.org" --purge-sticker 0
```

**Custom time filter:**

```bash
localmoderationmatrix "!roomID:matrix.org" --search "test" --days 3 --hours 12
```

## Building from Source

**PyPI Package:**

```bash
uv build
```

**Standalone Executable:**

```bash
pyinstaller --onefile --name LocalModerationMatrix --clean --noconfirm --optimize 2 src/localmoderationmatrix/cli.py
```

## License

Apache-2.0
