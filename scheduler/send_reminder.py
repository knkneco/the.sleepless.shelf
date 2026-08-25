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
    """
    reminders.json を読み込む。
    """

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"設定ファイルが見つかりません: {CONFIG_PATH}"
        )

    with CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def add_months(
    year: int,
    month: int,
    amount: int,
) -> tuple[int, int]:
    """
    指定した年月に amount ヶ月を加算する。
    """

    month_index = (
        year * 12
        + (month - 1)
        + amount
    )

    new_year = month_index // 12
    new_month = month_index % 12 + 1

    return new_year, new_month


def format_message(
    template: str,
    now: datetime,
) -> str:
    """
    メッセージ内の変数を
    実際の年月などに置き換える。
    """

    next_year, next_month = add_months(
        now.year,
        now.month,
        1,
    )

    (
        month_after_next_year,
        month_after_next,
    ) = add_months(
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

        month_after_next_year=(
            month_after_next_year
        ),
        month_after_next=(
            month_after_next
        ),

        last_day=last_day,
    )


def load_webhooks() -> dict[str, str]:
    """
    Discord Webhook URLを
    GitHub Secretsから取得する。

    未使用のWebhookが未設定でも
    この段階ではエラーにしない。
    """

    return {
        "staff": os.environ.get(
            "DISCORD_WEBHOOK_STAFF",
            "",
        ),
        "public": os.environ.get(
            "DISCORD_WEBHOOK_PUBLIC",
            "",
        ),
    }


def send_to_discord(
    webhook_url: str,
    mention: str,
    message: str,
) -> None:
    """
    Discord Webhookへ送信する。
    """

    if mention:
        content = (
            f"{mention}\n"
            f"{message}"
        )
    else:
        content = message

    payload = {
        "content": content,
        "allowed_mentions": {
            "parse": [
                "users",
                "roles",
            ],
        },
    }

    data = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        webhook_url,
        data=data,
        headers={
            "Content-Type": (
                "application/json"
            ),
            "User-Agent": (
                "The-Sleepless-Shelf-"
                "Scheduler/1.0"
            ),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:

            if response.status not in (
                200,
                204,
            ):
                raise RuntimeError(
                    "Discordへの送信に"
                    "失敗しました。"
                    f" HTTP "
                    f"{response.status}"
                )

    except urllib.error.HTTPError as error:
        body = error.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            "Discordへの送信に"
            "失敗しました。"
            f" HTTP {error.code}: "
            f"{body}"
        ) from error

    except urllib.error.URLError as error:
        raise RuntimeError(
            "Discordへの接続に"
            "失敗しました: "
            f"{error.reason}"
        ) from error


def should_send(
    reminder: dict,
    now: datetime,
) -> bool:
    """
    現在の日付が
    リマインダー対象日か確認する。

    GitHub Actionsは実行開始が
    数分ずれる可能性があるため、
    時刻の完全一致判定はしない。

    時刻はscheduler.yml側で管理し、
    Python側では日付のみ確認する。
    """

    if not reminder.get(
        "enabled",
        False,
    ):
        return False

    schedule = reminder.get(
        "schedule",
        {},
    )

    if schedule.get(
        "type"
    ) != "monthly":
        print(
            "未対応のschedule type:",
            reminder.get(
                "id",
                "unknown",
            ),
        )
        return False

    try:
        expected_day = int(
            schedule["day"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        print(
            "日付設定が不正です:",
            reminder.get(
                "id",
                "unknown",
            ),
        )
        return False

    if not 1 <= expected_day <= 31:
        print(
            "日付が範囲外です:",
            reminder.get(
                "id",
                "unknown",
            ),
        )
        return False

    return now.day == expected_day


def send_reminder(
    webhooks: dict[str, str],
    reminder: dict,
    now: datetime,
) -> None:
    """
    リマインダー1件を送信する。
    """

    reminder_id = reminder.get(
        "id",
        "unknown",
    )

    destination = reminder.get(
        "destination",
        "staff",
    )

    webhook_url = webhooks.get(
        destination,
        "",
    )

    if not webhook_url:
        raise RuntimeError(
            "Discord Webhookが"
            "設定されていません: "
            f"{destination}"
        )

    message_template = reminder.get(
        "message",
        "",
    )

    if not message_template:
        raise RuntimeError(
            "メッセージが"
            "設定されていません: "
            f"{reminder_id}"
        )

    try:
        formatted_message = (
            format_message(
                message_template,
                now,
            )
        )

    except KeyError as error:
        raise RuntimeError(
            "メッセージ内に"
            "未対応の変数があります: "
            f"{error}"
        ) from error

    send_to_discord(
        webhook_url=webhook_url,
        mention=reminder.get(
            "mention",
            "",
        ),
        message=formatted_message,
    )


def run_test(
    reminders: list,
    webhooks: dict[str, str],
    now: datetime,
) -> None:
    """
    手動テスト送信。

    enabled=true の
    最初のリマインダーを
    日付に関係なく送信する。
    """

    enabled_reminders = [
        reminder
        for reminder in reminders
        if reminder.get(
            "enabled",
            False,
        )
    ]

    if not enabled_reminders:
        raise RuntimeError(
            "テスト送信できる"
            "有効なリマインダーが"
            "ありません。"
        )

    reminder = (
        enabled_reminders[0]
    )

    reminder_id = reminder.get(
        "id",
        "unknown",
    )

    print(
        "【テスト送信】",
        reminder_id,
    )

    send_reminder(
        webhooks=webhooks,
        reminder=reminder,
        now=now,
    )

    print(
        "テスト送信成功:",
        reminder_id,
    )


def run_scheduled(
    reminders: list,
    webhooks: dict[str, str],
    now: datetime,
) -> None:
    """
    通常の自動送信。
    """

    sent_count = 0

    for reminder in reminders:
        reminder_id = reminder.get(
            "id",
            "unknown",
        )

        if not reminder.get(
            "enabled",
            False,
        ):
            print(
                "無効のためスキップ:",
                reminder_id,
            )
            continue

        if not should_send(
            reminder,
            now,
        ):
            print(
                "本日は送信対象外:",
                reminder_id,
            )
            continue

        print(
            "送信開始:",
            reminder_id,
        )

        send_reminder(
            webhooks=webhooks,
            reminder=reminder,
            now=now,
        )

        print(
            "送信成功:",
            reminder_id,
        )

        sent_count += 1

    print(
        "送信件数:",
        sent_count,
    )


def main() -> None:
    """
    メイン処理。
    """

    config = load_config()

    timezone_name = config.get(
        "timezone",
        "Asia/Tokyo",
    )

    try:
        timezone = ZoneInfo(
            timezone_name
        )

    except Exception as error:
        raise RuntimeError(
            "タイムゾーン設定が"
            "不正です: "
            f"{timezone_name}"
        ) from error

    now = datetime.now(
        timezone
    )

    print(
        "現在時刻:",
        now.strftime(
            "%Y-%m-%d "
            "%H:%M:%S %Z"
        ),
    )

    reminders = config.get(
        "reminders",
        [],
    )

    if not isinstance(
        reminders,
        list,
    ):
        raise RuntimeError(
            "remindersは"
            "配列で指定してください。"
        )

    webhooks = load_webhooks()

    if "--test" in sys.argv:
        run_test(
            reminders=reminders,
            webhooks=webhooks,
            now=now,
        )
        return

    run_scheduled(
        reminders=reminders,
        webhooks=webhooks,
        now=now,
    )


if __name__ == "__main__":
    main()
