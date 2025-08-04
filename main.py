# main.py (Koyeb対応版)

import os
import re
import logging
import time
from datetime import datetime, timedelta

import discord
from flask import Flask

# --- 定数 ---
NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
REACTION_EMOJIS = ["⭕", "❌", "🔺"]
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]
TOKEN = os.getenv('DISCORD_TOKEN')
PROCESS_TYPE = os.getenv('PROCESS_TYPE', 'all') # 環境変数でプロセスの種類を判別

# --- ロギング設定 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')

# --- Webサーバーの定義 (UptimeRobot用) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Web server is alive!"

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

            @client.event
            async def on_ready():
                logging.info(f'{client.user.name} が起動しました！')

            @client.event
            async def on_message(message):
                if message.author == client.user or not client.user.mentioned_in(message):
                    return

                pattern = f'<@!?{client.user.id}>\s*(.*)'
                match = re.search(pattern, message.content, re.DOTALL)
                if not match:
                    return

                command_text = match.group(1).strip()

                # (ここに各コマンドのロジックが来る... コピペでOK)
                date_match = re.fullmatch(r'(\d{1,2})/(\d{1,2})', command_text)
                if date_match:
                    try:
                        date_str = date_match.group(0)
                        now = datetime.now()
                        start_date = datetime.strptime(date_str, '%m/%d').replace(year=now.year)
                        if start_date.date() < now.date():
                            start_date = start_date.replace(year=now.year + 1)
                        await message.add_reaction('✅')
                        for i in range(7):
                            current_date = start_date + timedelta(days=i)
                            date_text = f"{current_date.month}/{current_date.day}({WEEKDAYS_JP[current_date.weekday()]})"
                            sent_message = await message.channel.send(date_text)
                            for emoji in REACTION_EMOJIS:
                                await sent_message.add_reaction(emoji)
                        return
                    except ValueError:
                        await message.channel.send(f"日付の形式が正しくありません: `{command_text}`")
                        return

                num_match = re.fullmatch(r'num:(\d+)', command_text, re.IGNORECASE)
                if num_match:
                    try:
                        count = int(num_match.group(1))
                        if 1 <= count <= 10:
                            for i in range(count):
                                await message.add_reaction(NUMBER_EMOJIS[i])
                        else:
                            await message.channel.send("数字は1から10の間で指定してください。")
                        return
                    except (ValueError, IndexError):
                        pass

                if command_text == "":
                    for emoji in REACTION_EMOJIS:
                        await message.add_reaction(emoji)
                    return

            client.run(TOKEN)

        except Exception as e:
            logging.error(f"ボットの実行中にエラーが発生: {e}", exc_info=True)
            logging.info("10秒後に再起動します。")
            time.sleep(10)

# --- 起動プロセスの分岐 ---
if __name__ == '__main__':
    if PROCESS_TYPE == 'worker':
        logging.info("起動モード: Worker (Discordボットのみ)")
        run_bot()
    elif PROCESS_TYPE == 'web':
        # この部分は 'gunicorn' が直接実行するため、実際には使われない
        logging.info("起動モード: Web (このメッセージはローカル実行時のみ表示)")
    else: # ローカルでのテスト用
        logging.info("起動モード: all (WebとBotの両方)")
        # threading は使わず、ここではボットのみを起動
        run_bot()