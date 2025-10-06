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
JST = timezone(timedelta(hours=9), 'JST')

# 月の英語名辞書
MONTH_NAMES = {
    1: "january", 2: "february", 3: "march", 4: "april", 5: "may", 6: "june",
    7: "july", 8: "august", 9: "september", 10: "october", 11: "november", 12: "december"
}
# コマンドを監視するチャンネル名
SOURCE_CHANNEL_NAME = "未耐久"

# --- ▼▼▼【重要】設定してください ▼▼▼ ---
# アーカイブ処理のトリガーとなるロール名 (大文字・小文字を区別します)
TRIGGER_ROLE_NAME = "ClashKing"
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
            intents = discord.Intents.default()
            intents.messages = True
            intents.message_content = True 
            intents.guilds = True
            client = discord.Client(intents=intents)

            # (定期実行タスクは変更なし)
            
            @client.event
            async def on_ready():
                logging.info(f'{client.user.name} が起動しました！')

            # --- ▼▼▼ 変更点: アーカイブ処理のトリガーをロールに変更 ▼▼▼ ---
            @client.event
            async def on_message(message: discord.Message):
                # 自分のBotのメッセージは無視
                if message.author == client.user:
                    return
                
                # DMからのメッセージは無視 (ロール情報が取得できないため)
                if not message.guild:
                    return

                # 「未耐久」チャンネル以外からのメッセージは無視
                if message.channel.name != SOURCE_CHANNEL_NAME:
                    return

                # --- アーカイブ処理のトリガー判定 ---
                # メッセージの投稿者が `TRIGGER_ROLE_NAME` のロールを持っているか確認
                # `isinstance` で Member オブジェクトであることを保証
                if isinstance(message.author, discord.Member):
                    has_trigger_role = any(role.name == TRIGGER_ROLE_NAME for role in message.author.roles)

                    if has_trigger_role:
                        logging.info(f"'{TRIGGER_ROLE_NAME}' ロールを持つ '{message.author.name}' の投稿を検知。アーカイブ処理を開始します。")
                        
                        try:
                            guild = message.guild
                            
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
                            
                            files = [await attachment.to_file() for attachment in message.attachments]
                            
                            # コピーするメッセージのヘッダーを作成
                            header_text = (
                                f"**Copied from:** {message.channel.mention} (Original Message: {message.jump_url})\n"
                                f"**Posted by:** {message.author.mention}\n"
                                f"--------------------------------"
                            )
                            
                            await new_channel.send(content=header_text)
                            if message.content or message.embeds or files:
                                await new_channel.send(
                                    content=message.content or None, 
                                    embeds=message.embeds, 
                                    files=files
                                )
                            
                            # 元のチャンネルに通知 (リプライ形式で)
                            await message.reply(f"記録を <#{new_channel.id}> にコピーしました。", mention_author=False)

                        except discord.errors.Forbidden:
                            logging.error(f"エラー: カテゴリー/チャンネルの作成またはメッセージ送信の権限がありません。")
                            await message.channel.send("エラー: 権限不足で処理を実行できませんでした。サーバー管理者にご確認ください。")
                        except Exception as e:
                            logging.error(f"アーカイブ処理中に予期せぬエラーが発生: {e}", exc_info=True)
                            await message.channel.send(f"予期せぬエラーが発生しました: {e}")
                        
                        return # アーカイブ処理が完了したら以降の処理は不要
                
                # --- 既存のメンションコマンド処理 ---
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