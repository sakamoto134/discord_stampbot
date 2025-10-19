import os
import re
import logging
import time
from datetime import datetime, timedelta, time as dt_time, timezone
from threading import Thread

import discord
from discord.ext import tasks
from flask import Flask

# --- 定数 ---
NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
REACTION_EMOJIS = ["⭕", "❌", "🔺"]
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]
TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", 8080))

# --- sesh連携設定 ---
SESH_BOT_ID = 616754792965865495
TARGET_SESH_CHANNEL_NAME = "sesh⚙️"
MENTION_ROLES_FOR_SESH = ["sesh"]

# --- /base連携設定 ---
TARGET_BOT_ID_FOR_BASE = 824653933347209227
TARGET_CHANNEL_NAME_FOR_BASE = "未耐久"
TARGET_COMMAND_NAME_FOR_BASE = "base"

# --- ロギング設定 ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s: %(message)s")

# --- Flaskサーバー (UptimeRobot対応) ---
app = Flask(__name__)

@app.route("/")
def home():
    return "I am alive!"

def run_web_server():
    app.run(host="0.0.0.0", port=PORT)

# --- Discord Bot本体 ---
def run_bot():
    if not TOKEN:
        logging.error("環境変数 'DISCORD_TOKEN' が設定されていません。")
        return

    while True:
        try:
            intents = discord.Intents.default()
            intents.message_content = True
            client = discord.Client(intents=intents)

            JST = timezone(timedelta(hours=9), "JST")
            scheduled_time = dt_time(hour=20, minute=0, tzinfo=JST)

            @tasks.loop(time=scheduled_time)
            async def send_weekly_schedule():
                await client.wait_until_ready()
                if datetime.now(JST).weekday() != 2:
                    return

                CHANNEL_NAME = "attendance"
                ROLE_NAMES = ["player", "guest"]

                for guild in client.guilds:
                    channel = discord.utils.get(guild.text_channels, name=CHANNEL_NAME)
                    roles_to_mention = [discord.utils.get(guild.roles, name=r) for r in ROLE_NAMES]
                    found_roles = [r for r in roles_to_mention if r]

                    if channel and found_roles:
                        mentions = " ".join(r.mention for r in found_roles)
                        await channel.send(
                            f"【出欠投票】 {mentions}\n21:00~25:00辺りに可能なら投票\n（細かい時間の可否は各自連絡）"
                        )
                        start_date = datetime.now(JST).date() + timedelta(days=5)
                        for i in range(7):
                            d = start_date + timedelta(days=i)
                            msg = await channel.send(f"{d.month}/{d.day}({WEEKDAYS_JP[d.weekday()]})")
                            for emoji in REACTION_EMOJIS:
                                await msg.add_reaction(emoji)

            @client.event
            async def on_ready():
                logging.info(f"{client.user} が起動しました")
                if not send_weekly_schedule.is_running():
                    send_weekly_schedule.start()

            @client.event
            async def on_message(message: discord.Message):
                if message.author == client.user:
                    return

                # seshのcreate検出
                if (
                    message.channel.name == TARGET_SESH_CHANNEL_NAME
                    and message.author.id == SESH_BOT_ID
                    and message.interaction
                    and message.interaction.name == "create"
                    and not message.interaction.user.bot
                ):
                    guild = message.guild
                    roles = [discord.utils.get(guild.roles, name=r) for r in MENTION_ROLES_FOR_SESH]
                    found = [r for r in roles if r]
                    if found:
                        mentions = " ".join(r.mention for r in found)
                        await message.channel.send(mentions)
                    return

                # /base コマンド応答
                if (
                    message.channel.name == TARGET_CHANNEL_NAME_FOR_BASE
                    and message.author.id == TARGET_BOT_ID_FOR_BASE
                    and message.interaction
                    and message.interaction.name == TARGET_COMMAND_NAME_FOR_BASE
                    and not message.interaction.user.bot
                ):
                    guild = message.guild
                    command_time = message.created_at.astimezone(JST)

                    # --- カテゴリー作成 or 取得 ---
                    category_name = command_time.strftime("%B").lower()
                    category = discord.utils.get(guild.categories, name=category_name)

                    # 対象ロール取得
                    player_role = discord.utils.get(guild.roles, name="player")
                    guest_role = discord.utils.get(guild.roles, name="guest")

                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    }
                    if player_role:
                        overwrites[player_role] = discord.PermissionOverwrite(
                            view_channel=True, send_messages=True, read_message_history=True
                        )
                    if guest_role:
                        overwrites[guest_role] = discord.PermissionOverwrite(
                            view_channel=True, send_messages=True, read_message_history=True
                        )

                    if category is None:
                        logging.info(f"新しいプライベートカテゴリー '{category_name}' を作成します。")
                        category = await guild.create_category(category_name, overwrites=overwrites)
                    else:
                        # 既存カテゴリーの権限を更新
                        await category.edit(overwrites=overwrites)

                    # --- チャンネル名連番決定 ---
                    prefix = command_time.strftime("%b").lower()
                    max_n = 0
                    for ch in category.text_channels:
                        m = re.match(rf"^{prefix}(\d+)", ch.name, re.IGNORECASE)
                        if m:
                            n = int(m.group(1))
                            if n > max_n:
                                max_n = n
                    new_name = f"{prefix}{max_n + 1}"

                    # --- チャンネル作成 ---
                    new_channel = await guild.create_text_channel(new_name, category=category)
                    logging.info(f"チャンネル '{new_channel.name}' を作成しました。")

                    # --- メッセージ転送 (content + embeds) ---
                    if message.content or message.embeds:
                        await new_channel.send(content=message.content, embeds=message.embeds)
                    else:
                        await new_channel.send("（/baseコマンド応答を転送しました）")

                    logging.info(f"/base メッセージを '{new_channel.name}' に転送しました。")
                    return

            client.run(TOKEN)

        except Exception as e:
            logging.error(f"Bot実行中エラー: {e}", exc_info=True)
            logging.info("10秒後に再起動します。")
            time.sleep(10)

# --- メイン実行 ---
if __name__ == "__main__":
    Thread(target=run_web_server).start()
    run_bot()
