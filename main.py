import os
import re
import logging
import time
from datetime import datetime, timedelta, time, timezone
from threading import Thread

import discord
from discord.ext import tasks
from flask import Flask

# --- 定数 ---
NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
REACTION_EMOJIS = ["⭕", "❌", "🔺"]
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]
TOKEN = os.getenv('DISCORD_TOKEN')
PORT = int(os.getenv('PORT', 8080))  # KoyebはPORT環境変数を設定してくれる

# --- ▼▼▼ sesh連携機能のための定数を追加 ▼▼▼ ---
SESH_BOT_ID = 616754792965865495
TARGET_SESH_CHANNEL_NAME = "sesh⚙️"
MENTION_ROLES_FOR_SESH = ["sesh"]
# --- ▲▲▲ sesh連携機能のための定数を追加 ▲▲▲ ---

# --- ▼▼▼ /baseコマンド連携機能のための定数を追加 ▼▼▼ ---
TARGET_BOT_ID_FOR_BASE = 824653933347209227
TARGET_CHANNEL_NAME_FOR_BASE = "未耐久"
TARGET_COMMAND_NAME_FOR_BASE = "base"
# --- ▲▲▲ /baseコマンド連携機能のための定数を追加 ▲▲▲ ---

# --- ロギング設定 ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s: %(message)s")

# --- Webサーバー定義 ---
app = Flask(__name__)

@app.route("/")
def home():
    logging.info("Web server received a request.")
    return "I am alive!"

def run_web_server():
    app.run(host="0.0.0.0", port=PORT)

# --- Discordボット定義 ---
def run_bot():
    if not TOKEN:
        logging.error("エラー: 環境変数 'DISCORD_TOKEN' が設定されていません。")
        return

    while True:
        try:
            intents = discord.Intents.none()
            intents.guilds = True
            intents.guild_messages = True
            intents.message_content = True
            client = discord.Client(intents=intents, max_messages=None)

            JST = timezone(timedelta(hours=9), "JST")
            scheduled_time = time(hour=20, minute=0, tzinfo=JST)

            @tasks.loop(time=scheduled_time)
            async def send_weekly_schedule():
                await client.wait_until_ready()
                if datetime.now(JST).weekday() != 2:
                    return

                logging.info("定期実行タスク: 週間予定の投稿を開始します。")
                CHANNEL_NAME = "attendance"
                ROLE_NAMES = ["player", "guest"]

                for guild in client.guilds:
                    channel = discord.utils.get(guild.text_channels, name=CHANNEL_NAME)
                    roles_to_mention = [discord.utils.get(guild.roles, name=name) for name in ROLE_NAMES]
                    found_roles = [r for r in roles_to_mention if r is not None]

                    if channel and found_roles:
                        try:
                            mentions = " ".join(r.mention for r in found_roles)
                            message_text = f"【出欠投票】 {mentions}\n21:00~25:00辺りに可能なら投票\n（細かい時間の可否は各自連絡）"
                            await channel.send(message_text)

                            start_date = datetime.now(JST).date() + timedelta(days=5)
                            for i in range(7):
                                d = start_date + timedelta(days=i)
                                date_text = f"{d.month}/{d.day}({WEEKDAYS_JP[d.weekday()]})"
                                sent = await channel.send(date_text)
                                for e in REACTION_EMOJIS:
                                    await sent.add_reaction(e)
                            logging.info(f"サーバー'{guild.name}'への週間予定の投稿が完了しました。")
                        except Exception as e:
                            logging.error(f"定期タスク実行中にエラー: {e}", exc_info=True)

            @client.event
            async def on_ready():
                logging.info(f"{client.user.name} が起動しました！")
                if not send_weekly_schedule.is_running():
                    send_weekly_schedule.start()

            @client.event
            async def on_message(message):
                if message.author == client.user:
                    return

                # sesh連携
                if (
                    message.channel.name == TARGET_SESH_CHANNEL_NAME
                    and message.author.id == SESH_BOT_ID
                    and message.interaction is not None
                    and message.interaction.name == "create"
                    and not message.interaction.user.bot
                ):
                    guild = message.guild
                    roles_to_mention = [discord.utils.get(guild.roles, name=name) for name in MENTION_ROLES_FOR_SESH]
                    found_roles = [r for r in roles_to_mention if r is not None]
                    if found_roles:
                        mentions = " ".join(r.mention for r in found_roles)
                        await message.channel.send(mentions)
                    return

                # /base連携
                if (
                    message.channel.name == TARGET_CHANNEL_NAME_FOR_BASE
                    and message.author.id == TARGET_BOT_ID_FOR_BASE
                    and message.interaction is not None
                    and message.interaction.name == TARGET_COMMAND_NAME_FOR_BASE
                    and not message.interaction.user.bot
                ):
                    logging.info(f"'/base'コマンド応答を'{message.channel.name}'チャンネルで検知しました。")
                    try:
                        guild = message.guild
                        command_time = message.created_at.astimezone(JST)

                        # カテゴリ作成/取得
                        category_name = command_time.strftime("%B").lower()
                        category = discord.utils.get(guild.categories, name=category_name)
                        if category is None:
                            category = await guild.create_category(category_name)
                            logging.info(f"カテゴリー '{category_name}' を作成しました。")

                        # チャンネル連番
                        prefix = command_time.strftime("%b").lower()
                        max_num = 0
                        for ch in category.text_channels:
                            match = re.match(rf"^{re.escape(prefix)}(\d+)", ch.name, re.IGNORECASE)
                            if match:
                                n = int(match.group(1))
                                max_num = max(max_num, n)
                        new_name = f"{prefix}{max_num + 1}"

                        # チャンネル作成
                        new_channel = await guild.create_text_channel(new_name, category=category)
                        logging.info(f"チャンネル '{new_name}' を作成しました。")

                        # 元メッセージリンクを貼る
                        message_link = message.jump_url
                        await new_channel.send(f"元メッセージリンク: {message_link}")
                        logging.info(f"'{new_name}' にメッセージリンクを貼り付けました。")

                    except Exception as e:
                        logging.error(f"/base処理中にエラー: {e}", exc_info=True)
                    return

                # メンションされたときの処理
                if not client.user.mentioned_in(message):
                    return

                pattern = rf"<@!?{client.user.id}>\s*(.*)"
                match = re.search(pattern, message.content, re.DOTALL)
                if not match:
                    return
                command_text = match.group(1).strip()

                date_pattern = r"(\d{1,2})/(\d{1,2})(?:\s+day:(\d+))?"
                date_match = re.fullmatch(date_pattern, command_text, re.IGNORECASE)
                if date_match:
                    try:
                        month, day = date_match.group(1), date_match.group(2)
                        days = int(date_match.group(3)) if date_match.group(3) else 7
                        if not (1 <= days <= 10):
                            await message.channel.send("日数は1〜10の間で指定してください。")
                            return

                        now = datetime.now()
                        start_date = datetime.strptime(f"{month}/{day}", "%m/%d").replace(year=now.year)
                        if start_date.date() < now.date():
                            start_date = start_date.replace(year=now.year + 1)

                        for i in range(days):
                            d = start_date + timedelta(days=i)
                            date_text = f"{d.month}/{d.day}({WEEKDAYS_JP[d.weekday()]})"
                            sent = await message.channel.send(date_text)
                            for e in REACTION_EMOJIS:
                                await sent.add_reaction(e)
                        return
                    except Exception:
                        await message.channel.send(f"コマンドの形式が正しくありません: `{command_text}`")
                        return

                num_match = re.fullmatch(r"num:(\d+)", command_text, re.IGNORECASE)
                if num_match:
                    try:
                        n = int(num_match.group(1))
                        if 1 <= n <= 10:
                            for i in range(n):
                                await message.add_reaction(NUMBER_EMOJIS[i])
                        else:
                            await message.channel.send("数字は1〜10の間で指定してください。")
                        return
                    except Exception:
                        pass

                if command_text == "":
                    for e in REACTION_EMOJIS:
                        await message.add_reaction(e)
                    return

            client.run(TOKEN)

        except Exception as e:
            logging.error(f"ボット実行中にエラー: {e}", exc_info=True)
            logging.info("10秒後に再起動します。")
            time.sleep(10)

if __name__ == "__main__":
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    run_bot()
