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
PORT = int(os.getenv('PORT', 8080))

# --- sesh連携用 ---
SESH_BOT_ID = 616754792965865495
TARGET_SESH_CHANNEL_NAME = "sesh⚙️"
MENTION_ROLES_FOR_SESH = ["sesh"]
LIST_COMMAND_ID = "950770720303091726"  # /list コマンドID

# --- baseコマンド連携用 ---
TARGET_BOT_ID_FOR_BASE = 824653933347209227
TARGET_CHANNEL_NAME_FOR_BASE = "未耐久"
TARGET_COMMAND_NAME_FOR_BASE = "base"

# --- ロギング設定 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')

# --- Webサーバー定義 ---
app = Flask(__name__)

@app.route('/')
def home():
    logging.info("Web server received a request.")
    return "I am alive!"

def run_web_server():
    app.run(host='0.0.0.0', port=PORT)

# --- Discordボットの定義 ---
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

            JST = timezone(timedelta(hours=9), 'JST')
            scheduled_time = time(hour=20, minute=0, tzinfo=JST)

            @tasks.loop(time=scheduled_time)
            async def send_weekly_schedule():
                await client.wait_until_ready()
                if datetime.now(JST).weekday() != 2:
                    return

                CHANNEL_NAME = "attendance"
                ROLE_NAMES = ["player", "guest"]

                for guild in client.guilds:
                    channel = discord.utils.get(guild.text_channels, name=CHANNEL_NAME)
                    roles_to_mention = [discord.utils.get(guild.roles, name=name) for name in ROLE_NAMES]
                    found_roles = [role for role in roles_to_mention if role is not None]

                    if channel and found_roles:
                        try:
                            mentions = " ".join(role.mention for role in found_roles)
                            message_text = (
                                f"【出欠投票】 {mentions}\n"
                                "21:00~25:00辺りに可能なら投票\n"
                                "（細かい時間の可否は各自連絡）"
                            )
                            await channel.send(message_text)

                            start_date = datetime.now(JST).date() + timedelta(days=5)
                            for i in range(7):
                                current_date = start_date + timedelta(days=i)
                                date_text = f"{current_date.month}/{current_date.day}({WEEKDAYS_JP[current_date.weekday()]})"
                                sent_message = await channel.send(date_text)
                                for emoji in REACTION_EMOJIS:
                                    await sent_message.add_reaction(emoji)

                        except discord.errors.Forbidden:
                            logging.error(f"エラー: チャンネル'{channel.name}'への投稿権限がありません。")
                        except Exception as e:
                            logging.error(f"定期タスク実行中に予期せぬエラー: {e}", exc_info=True)

            @client.event
            async def on_ready():
                logging.info(f'{client.user.name} が起動しました！')
                if not send_weekly_schedule.is_running():
                    send_weekly_schedule.start()

            @client.event
            async def on_message(message):
                if message.author == client.user:
                    return

                # --- sesh /create コマンド応答検知 ---
                if (message.channel.name == TARGET_SESH_CHANNEL_NAME and
                    message.author.id == SESH_BOT_ID and
                    message.interaction is not None and
                    message.interaction.name == 'create' and
                    not message.interaction.user.bot):

                    logging.info(f"seshのcreateコマンド応答を検知: {message.channel.name}")

                    try:
                        # --- /list コマンドをスラッシュコマンドとして実行 ---
                        await client.http.request(
                            discord.http.Route("POST", "/interactions"),
                            json={
                                "type": 2,
                                "application_id": str(SESH_BOT_ID),
                                "guild_id": str(message.guild.id),
                                "channel_id": str(message.channel.id),
                                "session_id": "dummy_session",
                                "data": {
                                    "id": LIST_COMMAND_ID,
                                    "name": "list",
                                    "type": 1
                                }
                            }
                        )
                        logging.info("✅ '/list' スラッシュコマンドを実行しました。")

                        # --- seshロールにメンション送信 ---
                        guild = message.guild
                        roles_to_mention = [discord.utils.get(guild.roles, name=name) for name in MENTION_ROLES_FOR_SESH]
                        found_roles = [role for role in roles_to_mention if role is not None]

                        if found_roles:
                            mentions = " ".join(role.mention for role in found_roles)
                            await message.channel.send(mentions)
                            logging.info(f"メンション送信: {mentions}")
                        else:
                            logging.warning(f"メンション対象のロールが見つかりません: {MENTION_ROLES_FOR_SESH}")

                    except discord.errors.Forbidden:
                        logging.error(f"権限エラー: {message.channel.name} に投稿不可。")
                    except Exception as e:
                        logging.error(f"/list コマンド実行中にエラー: {e}", exc_info=True)
                    return

                # --- base連携機能 ---
                if (message.channel.name == TARGET_CHANNEL_NAME_FOR_BASE and
                    message.author.id == TARGET_BOT_ID_FOR_BASE and
                    message.interaction is not None and
                    message.interaction.name == TARGET_COMMAND_NAME_FOR_BASE and
                    not message.interaction.user.bot):

                    logging.info(f"'/base'コマンド応答を検知: {message.channel.name}")
                    try:
                        guild = message.guild
                        command_time = message.created_at.astimezone(JST)
                        category_name = command_time.strftime('%B').lower()
                        category = discord.utils.get(guild.categories, name=category_name)

                        if category is None:
                            category = await guild.create_category(category_name)
                            logging.info(f"カテゴリー作成: {category_name}")
                        else:
                            logging.info(f"既存カテゴリー使用: {category_name}")

                        channel_prefix = command_time.strftime('%b').lower()
                        max_number = 0
                        for ch in category.text_channels:
                            match = re.match(rf'^{re.escape(channel_prefix)}(\d+)', ch.name, re.IGNORECASE)
                            if match:
                                num = int(match.group(1))
                                if num > max_number:
                                    max_number = num

                        next_number = max_number + 1
                        new_channel_name = f"{channel_prefix}{next_number}"
                        new_channel = await guild.create_text_channel(new_channel_name, category=category)
                        logging.info(f"新チャンネル作成: {new_channel_name}")

                        await new_channel.send(content=message.content, embeds=message.embeds)
                        logging.info(f"メッセージを '{new_channel.name}' にコピーしました。")

                    except discord.errors.Forbidden:
                        logging.error(f"権限エラー: {message.guild.name} でチャンネル作成不可。")
                    except Exception as e:
                        logging.error(f"/base連携中エラー: {e}", exc_info=True)
                    return

                # --- 通常メンション時リアクション処理 ---
                if not client.user.mentioned_in(message):
                    return

                pattern = rf'<@!?{client.user.id}>\s*(.*)'
                match = re.search(pattern, message.content, re.DOTALL)
                if not match:
                    return
                command_text = match.group(1).strip()

                date_pattern = r'(\d{1,2})/(\d{1,2})(?:\s+day:(\d+))?'
                date_match = re.fullmatch(date_pattern, command_text, re.IGNORECASE)

                if date_match:
                    try:
                        month_str = date_match.group(1)
                        day_str = date_match.group(2)
                        date_str = f"{month_str}/{day_str}"

                        days_str = date_match.group(3)
                        days_to_show = int(days_str) if days_str else 7
                        if not (1 <= days_to_show <= 10):
                            await message.channel.send("日数は1から10の間で指定してください。")
                            return

                        now = datetime.now()
                        start_date = datetime.strptime(date_str, '%m/%d').replace(year=now.year)
                        if start_date.date() < now.date():
                            start_date = start_date.replace(year=now.year + 1)

                        for i in range(days_to_show):
                            current_date = start_date + timedelta(days=i)
                            date_text = f"{current_date.month}/{current_date.day}({WEEKDAYS_JP[current_date.weekday()]})"
                            sent_message = await message.channel.send(date_text)
                            for emoji in REACTION_EMOJIS:
                                await sent_message.add_reaction(emoji)
                        return
                    except Exception:
                        await message.channel.send(f"コマンド形式が正しくありません: `{command_text}`")
                        return

                num_match = re.fullmatch(r'num:(\d+)', command_text, re.IGNORECASE)
                if num_match:
                    count = int(num_match.group(1))
                    if 1 <= count <= 10:
                        for i in range(count):
                            await message.add_reaction(NUMBER_EMOJIS[i])
                    else:
                        await message.channel.send("数字は1〜10の範囲で指定してください。")
                    return

                if command_text == "":
                    for emoji in REACTION_EMOJIS:
                        await message.add_reaction(emoji)
                    return

            client.run(TOKEN)

        except Exception as e:
            logging.error(f"ボット実行中にエラー: {e}", exc_info=True)
            logging.info("10秒後に再起動します。")
            time.sleep(10)

if __name__ == '__main__':
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    run_bot()
