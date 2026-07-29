import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


CONFIG_PATH = Path("scheduler/reminders.json")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"設定ファイルがありません: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def send_to_discord(webhook_url: str, mention: str, message: str) -> None:
    content = f"{mention}\n{message}".strip()

    payload = {
        "content": content,
        "allowed_mentions": {
            "parse": ["users", "roles"]
        }
    }

    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "The-Sleepless-Shelf-Scheduler/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in (200, 204):
                raise RuntimeError(
                    f"Discordへの送信に失敗しました。HTTP {response.status}"
                )
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Discordへの送信に失敗しました。HTTP {error.code}: {body}"
        ) from error


def should_send(reminder: dict, now: datetime) -> bool:
    if not reminder.get("enabled", False):
        return False

    schedule = reminder.get("schedule", {})

    if schedule.get("type") != "monthly":
        return False

    expected_day = int(schedule["day"])
    expected_time = schedule["time"]
    current_time = now.strftime("%H:%M")

    return now.day == expected_day and current_time == expected_time


def main() -> None:
    config = load_config()

    webhook_url = os.environ.get("DISCORD_WEBHOOK")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK が設定されていません。")

    timezone_name = config.get("timezone", "Asia/Tokyo")
    now = datetime.now(ZoneInfo(timezone_name))

    test_mode = "--test" in sys.argv

    if test_mode:
        reminders = config.get("reminders", [])

        if not reminders:
            raise RuntimeError("テスト送信できるリマインダーがありません。")

        reminder = reminders[0]
        send_to_discord(
            webhook_url,
            reminder.get("mention", ""),
            reminder.get("message", ""),
        )

        print(f"テスト送信しました: {reminder.get('id', 'unknown')}")
        return

    sent_count = 0

    for reminder in config.get("reminders", []):
        if should_send(reminder, now):
            send_to_discord(
                webhook_url,
                reminder.get("mention", ""),
                reminder.get("message", ""),
            )
            print(f"送信しました: {reminder.get('id', 'unknown')}")
            sent_count += 1

    print(f"処理完了。送信件数: {sent_count}")


if __name__ == "__main__":
    main()
