import os
import re
import logging
import time
from datetime import datetime, timedelta, time as dtime, timezone
from threading import Thread

import discord
from discord.ext import tasks
from flask import Flask

# --- 定数 ---
TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", 8080))

TARGET_BOT_ID_FOR_BASE = 824653933347209227
TARGET_CHANNEL_NAME_FOR_BASE = "未耐久"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# --- Webサーバー ---
app = Flask(__name__)

@app.route("/")
def home():
    return "I am alive!"

def run_web_server():
    app.run(host="0.0.0.0", port=PORT)

# --- Discord Bot ---
def run_bot():
    if not TOKEN:
        logging.error("DISCORD_TOKENが設定されていません")
        return

    processed_messages = set()  # 二重実行防止キャッシュ

    while True:
        try:
            intents = discord.Intents.default()
            intents.message_content = True
            intents.guild_messages = True
            intents.guilds = True

            client = discord.Client(intents=intents, max_messages=None)

            JST = timezone(timedelta(hours=9), "JST")

            @client.event
            async def on_ready():
                logging.info(f"{client.user} 起動完了")

            @client.event
            async def on_message(message: discord.Message):
                if message.author == client.user:
                    return
                if message.id in processed_messages:
                    return

                # --- /base コマンド検知 ---
                if (
                    message.channel.name == TARGET_CHANNEL_NAME_FOR_BASE
                    and message.author.id == TARGET_BOT_ID_FOR_BASE
                    and message.interaction_metadata is not None
                ):
                    processed_messages.add(message.id)
                    logging.info(f"'/base'検知 in {message.channel.name}")

                    try:
                        guild = message.guild
                        command_time = message.created_at.astimezone(JST)

                        # --- カテゴリ名決定 ---
                        category_name = command_time.strftime("%B").lower()
                        category = discord.utils.get(guild.categories, name=category_name)

                        # --- カテゴリが存在しない場合、プライベート作成 ---
                        if category is None:
                            overwrites = {
                                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                            }
                            player_role = discord.utils.get(guild.roles, name="player")
                            guest_role = discord.utils.get(guild.roles, name="guest")
                            if player_role:
                                overwrites[player_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                            if guest_role:
                                overwrites[guest_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                            category = await guild.create_category(category_name, overwrites=overwrites)
                            logging.info(f"プライベートカテゴリ作成: {category_name}")
                        else:
                            logging.info(f"既存カテゴリ使用: {category_name}")

                        # --- チャンネル名決定 ---
                        prefix = command_time.strftime("%b").lower()
                        max_num = 0
                        for ch in category.text_channels:
                            m = re.match(rf"^{re.escape(prefix)}(\d+)", ch.name, re.IGNORECASE)
                            if m:
                                num = int(m.group(1))
                                max_num = max(max_num, num)
                        new_name = f"{prefix}{max_num+1}"

                        # --- 同名チャンネルが既に存在する場合はスキップ ---
                        existing = discord.utils.get(category.text_channels, name=new_name)
                        if existing:
                            logging.warning(f"同名チャンネル {new_name} が既に存在、作成スキップ")
                            return

                        # --- チャンネル作成 ---
                        new_channel = await guild.create_text_channel(new_name, category=category)
                        logging.info(f"チャンネル作成: {new_channel.name}")

                        # --- 元メッセージのリンクを新チャンネルに送信 ---
                        original_link = message.jump_url
                        sent_msg = await new_channel.send(original_link)
                        logging.info("メッセージリンク送信完了✅")

                        # --- 新チャンネルのメッセージリンクを未耐久チャンネルへ送信 ---
                        return_link = sent_msg.jump_url
                        origin_channel = discord.utils.get(guild.text_channels, name=TARGET_CHANNEL_NAME_FOR_BASE)
                        if origin_channel:
                            await origin_channel.send(return_link)
                            logging.info("未耐久チャンネルへリンク送信完了✅")
                        else:
                            logging.warning("未耐久チャンネルが見つかりません")

                    except Exception as e:
                        logging.error(f"/base処理中エラー: {e}", exc_info=True)
                    return

            client.run(TOKEN)

        except Exception as e:
            logging.error(f"ボット実行エラー: {e}", exc_info=True)
            time.sleep(10)

if __name__ == "__main__":
    Thread(target=run_web_server).start()
    run_bot()
