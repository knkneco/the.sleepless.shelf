import calendar
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
    """reminders.jsonを読み込む。"""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"設定ファイルが見つかりません: {CONFIG_PATH}"
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def add_months(year: int, month: int, amount: int) -> tuple[int, int]:
    """指定した年月に月数を加算する。年またぎにも対応。"""
    month_index = year * 12 + (month - 1) + amount

    new_year = month_index // 12
    new_month = month_index % 12 + 1

    return new_year, new_month


def format_message(template: str, now: datetime) -> str:
    """メッセージ内の月・日付用プレースホルダーを置換する。"""
    next_year, next_month = add_months(
        now.year,
        now.month,
        1,
    )

    month_after_next_year, month_after_next = add_months(
        now.year,
        now.month,
        2,
    )

    last_day = calendar.monthrange(
        now.year,
        now.month,
    )[1]

    return template.format(
        current_year=now.year,
        current_month=now.month,
        next_year=next_year,
        next_month=next_month,
        month_after_next_year=month_after_next_year,
        month_after_next=month_after_next,
        last_day=last_day,
    )


def send_to_discord(
    webhook_url: str,
    mention: str,
    message: str,
) -> None:
    """Discord Webhookへメッセージを送信する。"""
    content = f"{mention}\n{message}".strip()

    payload = {
        "content": content,
        "allowed_mentions": {
            "parse": [
                "users",
                "roles",
            ]
        },
    }

    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": (
                "The-Sleepless-Shelf-Scheduler/1.0"
            ),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            if response.status not in (200, 204):
                raise RuntimeError(
                    "Discordへの送信に失敗しました。"
                    f"HTTP {response.status}"
                )

    except urllib.error.HTTPError as error:
        body = error.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            "Discordへの送信に失敗しました。"
            f"HTTP {error.code}: {body}"
        ) from error

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Discordへの接続に失敗しました: {error.reason}"
        ) from error


def should_send(
    reminder: dict,
    now: datetime,
) -> bool:
    """現在時刻がリマインダーの送信日時か判定する。"""
    if not reminder.get("enabled", False):
        return False

    schedule = reminder.get("schedule", {})

    if schedule.get("type") != "monthly":
        return False

    try:
        expected_day = int(schedule["day"])
        expected_time = str(schedule["time"])

    except (KeyError, TypeError, ValueError):
        print(
            "スケジュール設定が不正です:",
            reminder.get("id", "unknown"),
        )
        return False

    current_time = now.strftime("%H:%M")

    return (
        now.day == expected_day
        and current_time == expected_time
    )


def send_reminder(
    webhook_url: str,
    reminder: dict,
    now: datetime,
) -> None:
    """リマインダー1件をDiscordへ送信する。"""
    message_template = reminder.get("message", "")
    formatted_message = format_message(
        message_template,
        now,
    )

    send_to_discord(
        webhook_url=webhook_url,
        mention=reminder.get("mention", ""),
        message=formatted_message,
    )


def main() -> None:
    config = load_config()

    webhook_url = os.environ.get("DISCORD_WEBHOOK")

    if not webhook_url:
        raise RuntimeError(
            "GitHub SecretのDISCORD_WEBHOOKが"
            "設定されていません。"
        )

    timezone_name = config.get(
        "timezone",
        "Asia/Tokyo",
    )

    try:
        timezone = ZoneInfo(timezone_name)

    except Exception as error:
        raise RuntimeError(
            f"タイムゾーン設定が不正です: {timezone_name}"
        ) from error

    now = datetime.now(timezone)

    reminders = config.get("reminders", [])

    if not isinstance(reminders, list):
        raise RuntimeError(
            "remindersは配列で指定してください。"
        )

    test_mode = "--test" in sys.argv

    if test_mode:
        if not reminders:
            raise RuntimeError(
                "テスト送信できるリマインダーがありません。"
            )

        reminder = reminders[0]

        send_reminder(
            webhook_url=webhook_url,
            reminder=reminder,
            now=now,
        )

        print(
            "テスト送信しました:",
            reminder.get("id", "unknown"),
        )
        return

    sent_count = 0

    for reminder in reminders:
        if not should_send(reminder, now):
            continue

        send_reminder(
            webhook_url=webhook_url,
            reminder=reminder,
            now=now,
        )

        print(
            "送信しました:",
            reminder.get("id", "unknown"),
        )

        sent_count += 1

    print(
        f"処理完了。現在時刻: "
        f"{now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    )
    print(f"送信件数: {sent_count}")


if __name__ == "__main__":
    main()
