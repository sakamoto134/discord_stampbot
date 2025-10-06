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
PORT = int(os.getenv('PORT', 8080)) # KoyebはPORT環境変数を設定してくれる
JST = timezone(timedelta(hours=9), 'JST') # 日本時間を定義

# 月の英語名辞書 (カテゴリー名として使用)
MONTH_NAMES = {
    1: "january", 2: "february", 3: "march", 4: "april", 5: "may", 6: "june",
    7: "july", 8: "august", 9: "september", 10: "october", 11: "november", 12: "december"
}
# コマンドを監視するチャンネル名
SOURCE_CHANNEL_NAME = "未耐久"

# --- ▼▼▼【重要】設定してください ▼▼▼ ---
# コピーしたいメッセージを投稿する「もう一方のBot」のユーザーID
# このIDのBotが「未耐久」チャンネルに投稿したメッセージのみをコピーします。
# IDの取得方法: Discordで開発者モードを有効にし、Botの名前を右クリックして「ユーザーIDをコピー」
OTHER_BOT_ID = 824653933347209227 # ここにBotのID(数字)を記入してください
# --- ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲ ---


# --- ロギング設定 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')

# --- Webサーバーの定義 (UptimeRobot用) ---
app = Flask(__name__)
@app.route('/')
def home():
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
            # --- 変更点: on_messageでBotのメッセージも読み取るためIntentsを調整 ---
            intents = discord.Intents.default()
            intents.messages = True
            intents.message_content = True 
            intents.guilds = True
            client = discord.Client(intents=intents)

            # --- 定期実行タスク (変更なし) ---
            scheduled_time = time(hour=20, minute=0, tzinfo=JST)
            @tasks.loop(time=scheduled_time)
            async def send_weekly_schedule():
                # ... (週間予定のロジックは変更なし)
                pass

            @client.event
            async def on_ready():
                logging.info(f'{client.user.name} が起動しました！')
                if not send_weekly_schedule.is_running():
                    send_weekly_schedule.start()

            # --- ▼▼▼ 変更点: アーカイブ処理を on_message 内で完結させる ▼▼▼ ---
            @client.event
            async def on_message(message: discord.Message):
                # 自分のBotのメッセージは無視 (無限ループ防止)
                if message.author == client.user:
                    return

                # --- アーカイブ処理のトリガー判定 ---
                # 1. 「未耐久」チャンネルであること
                # 2. メッセージの投稿者が指定したIDのBotであること
                if (message.channel.name == SOURCE_CHANNEL_NAME and 
                    message.author.bot and 
                    message.author.id == OTHER_BOT_ID):
                    
                    logging.info(f"Bot (ID: {OTHER_BOT_ID}) によるメッセージを検知しました。アーカイブ処理を開始します。")
                    
                    try:
                        guild = message.guild
                        
                        # 元のコマンド実行者を探す (Botの投稿が返信形式の場合)
                        original_author = None
                        if message.reference and message.reference.message_id:
                            try:
                                original_message = await message.channel.fetch_message(message.reference.message_id)
                                original_author = original_message.author
                            except discord.NotFound:
                                logging.warning("返信元のメッセージが見つかりませんでした。")
                        
                        # 1. 月のカテゴリー名を決定
                        posted_at_jst = message.created_at.astimezone(JST)
                        category_name = MONTH_NAMES[posted_at_jst.month]
                        category = discord.utils.get(guild.categories, name=category_name)
                        if category is None:
                            logging.info(f"カテゴリー '{category_name}' を作成します。")
                            category = await guild.create_category(category_name)

                        # 2. 連番チャンネル名を決定
                        channel_prefix = posted_at_jst.strftime('%b').lower()
                        max_num = 0
                        for ch in category.text_channels:
                            match = re.fullmatch(rf'{channel_prefix}(\d+)', ch.name)
                            if match and int(match.group(1)) > max_num:
                                max_num = int(match.group(1))
                        new_channel_name = f"{channel_prefix}{max_num + 1}"

                        # 3. 新しいチャンネルを作成
                        logging.info(f"新しいチャンネル '{new_channel_name}' を作成します。")
                        new_channel = await category.create_text_channel(new_channel_name)

                        # 4. メッセージを新しいチャンネルにコピー
                        logging.info(f"メッセージを '{new_channel.name}' にコピーします。")
                        
                        # 添付ファイルを準備
                        files = [await attachment.to_file() for attachment in message.attachments]
                        
                        # コピーするメッセージを作成
                        header_text = (
                            f"**Copied from:** {message.channel.mention} (Original Message: {message.jump_url})\n"
                            f"**Triggered by:** {original_author.mention if original_author else '不明なユーザー'}\n"
                            f"--------------------------------"
                        )
                        
                        # ヘッダーと、元のメッセージ(コンテンツ、埋め込み、ファイル)を送信
                        await new_channel.send(content=header_text)
                        if message.content or message.embeds or files:
                            await new_channel.send(
                                content=message.content or None, 
                                embeds=message.embeds, 
                                files=files
                            )
                        
                        # 元のチャンネルに通知 (任意)
                        await message.channel.send(f"記録を <#{new_channel.id}> にコピーしました。", reference=message)

                    except discord.errors.Forbidden:
                        logging.error(f"エラー: カテゴリー/チャンネルの作成またはメッセージ送信の権限がありません。")
                        await message.channel.send("エラー: 権限不足で処理を実行できませんでした。サーバー管理者にご確認ください。")
                    except Exception as e:
                        logging.error(f"アーカイブ処理中に予期せぬエラーが発生: {e}", exc_info=True)
                        await message.channel.send(f"予期せぬエラーが発生しました: {e}")
                    
                    return # アーカイブ処理が完了したら以降の処理は不要
                
                # --- 既存のメンションコマンド処理 (変更なし) ---
                if client.user.mentioned_in(message):
                    # ... (メンションに対する返信ロジックは変更なし)
                    pass
            # --- ▲▲▲ 変更ここまで ▲▲▲ ---

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