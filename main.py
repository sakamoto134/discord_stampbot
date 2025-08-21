import os
import re
import logging
import time
from datetime import datetime, timedelta, time, timezone # --- 変更 ---
from threading import Thread

import discord
from discord.ext import tasks # --- ▼▼▼ ここから追加 ▼▼▼ ---
from flask import Flask

# --- 定数 ---
NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
REACTION_EMOJIS = ["⭕", "❌", "🔺"]
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]
TOKEN = os.getenv('DISCORD_TOKEN')
PORT = int(os.getenv('PORT', 8080)) # KoyebはPORT環境変数を設定してくれる

# --- ロギング設定 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')

# --- Webサーバーの定義 (UptimeRobot用) ---
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

            # --- ▼▼▼ ここから追加 ▼▼▼ ---

            # --- 定期実行タスクの定義 ---
            # 日本時間 (JST, UTC+9) の15:15を指定
            JST = timezone(timedelta(hours=9), 'JST')
            scheduled_time = time(hour=15, minute=15, tzinfo=JST)

            @tasks.loop(time=scheduled_time)
            async def send_weekly_schedule():
                """毎週木曜日の15:15に週間予定を投稿するタスク"""
                # ボットが完全に起動するまで待機
                await client.wait_until_ready()

                # 実行日が木曜日(weekday()==3)でなければ処理を中断
                if datetime.now(JST).weekday() != 3:
                    return

                logging.info("定期実行タスク: 週間予定の投稿を開始します。")

                # 送信先のチャンネル名とメンションするロール名
                CHANNEL_NAME = "test"
                ROLE_NAME = "meteor"

                # ボットが参加している全てのサーバーをループ
                for guild in client.guilds:
                    # チャンネルとロールを名前で検索
                    channel = discord.utils.get(guild.text_channels, name=CHANNEL_NAME)
                    role = discord.utils.get(guild.roles, name=ROLE_NAME)

                    # チャンネルとロールの両方が見つかった場合のみ処理を実行
                    if channel and role:
                        try:
                            logging.info(f"サーバー'{guild.name}'のチャンネル'{channel.name}'にメッセージを送信します。")

                            # 投稿するメッセージを作成
                            message_text = (
                                f"【出欠投票】 {role.mention}\n"
                                "21:00~25:00辺りに可能なら投票\n"
                                "（細かい時間の可否は各自連絡）"
                            )
                            await channel.send(message_text)

                            # 翌日(金曜日)から1週間分の日付を投稿
                            start_date = datetime.now(JST).date() + timedelta(days=1)
                            for i in range(7):
                                current_date = start_date + timedelta(days=i)
                                date_text = f"{current_date.month}/{current_date.day}({WEEKDAYS_JP[current_date.weekday()]})"
                                sent_message = await channel.send(date_text)
                                for emoji in REACTION_EMOJIS:
                                    await sent_message.add_reaction(emoji)
                            logging.info(f"サーバー'{guild.name}'への週間予定の投稿が完了しました。")

                        except discord.errors.Forbidden:
                            logging.error(f"エラー: チャンネル'{channel.name}'への投稿権限がありません。")
                        except Exception as e:
                            logging.error(f"定期タスク実行中に予期せぬエラーが発生: {e}", exc_info=True)
                    
                    # デバッグ用のログ（ロールが見つからなかった場合など）
                    elif channel and not role:
                        logging.warning(f"サーバー'{guild.name}'でチャンネル'{CHANNEL_NAME}'は見つかりましたが、ロール'{ROLE_NAME}'が見つかりませんでした。")

            # --- ▲▲▲ ここまで追加 ▲▲▲ ---

            @client.event
            async def on_ready():
                logging.info(f'{client.user.name} が起動しました！')
                # --- ▼▼▼ ここから追加 ▼▼▼ ---
                # 定期実行タスクを開始
                if not send_weekly_schedule.is_running():
                    send_weekly_schedule.start()
                # --- ▲▲▲ ここまで追加 ▲▲▲ ---

            @client.event
            async def on_message(message):
                if message.author == client.user or not client.user.mentioned_in(message):
                    return

                pattern = rf'<@!?{client.user.id}>\s*(.*)'
                match = re.search(pattern, message.content, re.DOTALL)
                if not match:
                    return

                command_text = match.group(1).strip()

                # 日付コマンドの処理 ("M/D" または "M/D day:N")
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
                    except (ValueError, IndexError):
                        await message.channel.send(f"コマンドの形式が正しくありません: `{command_text}`")
                        return

                # 数字リアクションコマンド
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

                # デフォルトのリアクション
                if command_text == "":
                    for emoji in REACTION_EMOJIS:
                        await message.add_reaction(emoji)
                    return

            client.run(TOKEN)

        except Exception as e:
            logging.error(f"ボットの実行中にエラーが発生: {e}", exc_info=True)
            logging.info("10秒後に再起動します。")
            time.sleep(10)

# --- メインの実行ブロック ---
if __name__ == '__main__':
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    
    run_bot()