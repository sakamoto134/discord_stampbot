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
NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
REACTION_EMOJIS = ["⭕", "❌", "🔺"]
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]
TOKEN = os.getenv('DISCORD_TOKEN')
PORT = int(os.getenv('PORT', 8080)) # KoyebはPORT環境変数を設定してくれる

# --- ▼▼▼ sesh連携機能のための定数を追加 ▼▼▼ ---
SESH_BOT_ID = 616754792965865495 # (これは公式seshのIDです。必要に応じて変更してください)
TARGET_SESH_CHANNEL_NAME = "calender🗓️"
MENTION_ROLES_FOR_SESH = ["sesh"]
# --- ▲▲▲ sesh連携機能のための定数を追加 ▲▲▲ ---

# --- ▼▼▼ /baseコマンド連携機能のための定数を追加 ▼▼▼ ---
TARGET_BOT_ID_FOR_BASE = 824653933347209227
TARGET_CHANNEL_NAME_FOR_BASE = "未耐久"
TARGET_CHANNEL_NAME_FOR_LINKS = "base-link"
# --- ▲▲▲ /baseコマンド連携機能のための定数を追加 ▲▲▲ ---

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

    # 二重実行防止のためのメッセージIDキャッシュ
    processed_messages = set()

    while True:
        try:
            intents = discord.Intents.default() # より多くのイベントを検知できるIntents.default()に変更
            intents.message_content = True
            client = discord.Client(intents=intents, max_messages=None)

            # --- 定期実行タスクの定義 ---
            # 日本時間 (JST, UTC+9) の20:00を指定
            JST = timezone(timedelta(hours=9), 'JST')
            scheduled_time = dtime(hour=20, minute=0, tzinfo=JST)

            @tasks.loop(time=scheduled_time)
            async def send_weekly_schedule():
                """毎週水曜日の20:00に週間予定を投稿するタスク"""
                # ボットが完全に起動するまで待機
                await client.wait_until_ready()

                # 実行日が水曜日(weekday()==2)でなければ処理を中断
                if datetime.now(JST).weekday() != 2:
                    return

                logging.info("定期実行タスク: 週間予定の投稿を開始します。")

                # 送信先のチャンネル名とメンションするロール名
                CHANNEL_NAME = "attendance"
                ROLE_NAMES = ["player", "guest"]

                # ボットが参加している全てのサーバーをループ
                for guild in client.guilds:
                    # チャンネルを名前で検索
                    channel = discord.utils.get(guild.text_channels, name=CHANNEL_NAME)
                    # リストにあるロールをすべて取得し、見つかったものだけをリスト化
                    roles_to_mention = [discord.utils.get(guild.roles, name=name) for name in ROLE_NAMES]
                    found_roles = [role for role in roles_to_mention if role is not None]

                    # チャンネルと、メンション対象のロールが1つ以上見つかった場合のみ処理を実行
                    if channel and found_roles:
                        try:
                            logging.info(f"サーバー'{guild.name}'のチャンネル'{channel.name}'にメッセージを送信します。")

                            # 見つかったすべてのロールに対してメンションを作成
                            mentions = " ".join(role.mention for role in found_roles)
                            message_text = (
                                f"【出欠投票】 {mentions}\n"
                                "21:00~25:00辺りに可能なら投票\n"
                                "（細かい時間の可否は各自連絡）"
                            )
                            await channel.send(message_text)

                            # 翌週(月曜日)から1週間分の日付を投稿
                            start_date = datetime.now(JST).date() + timedelta(days=5)
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
                    
                    elif channel and not found_roles:
                        logging.warning(f"サーバー'{guild.name}'でチャンネル'{CHANNEL_NAME}'は見つかりましたが、ロール'{', '.join(ROLE_NAMES)}'のいずれも見つかりませんでした。")

            @client.event
            async def on_ready():
                logging.info(f'{client.user.name} が起動しました！')
                # 定期実行タスクを開始
                if not send_weekly_schedule.is_running():
                    send_weekly_schedule.start()

            @client.event
            async def on_message(message):
                # 自分自身のメッセージは無視
                if message.author == client.user:
                    return
                # 処理済みのメッセージは無視（二重実行防止）
                if message.id in processed_messages:
                    return

                # --- ▼▼▼ seshのcreateコマンドに応答するロジック ▼▼▼ ---
                if (message.channel.name == TARGET_SESH_CHANNEL_NAME and
                    message.author.id == SESH_BOT_ID and
                    message.interaction is not None and
                    message.interaction.name == 'create' and
                    not message.interaction.user.bot):

                    logging.info(f"seshのcreateコマンド応答を'{message.channel.name}'チャンネルで検知しました。")
                    try:
                        guild = message.guild
                        roles_to_mention = [discord.utils.get(guild.roles, name=name) for name in MENTION_ROLES_FOR_SESH]
                        found_roles = [role for role in roles_to_mention if role is not None]

                        if found_roles:
                            mentions = " ".join(role.mention for role in found_roles)
                            await message.channel.send(mentions)
                        else:
                            logging.warning(f"サーバー'{guild.name}'で、メンション対象のロールが見つかりませんでした。")

                    except discord.errors.Forbidden:
                        logging.error(f"エラー: チャンネル'{message.channel.name}'への投稿権限がありません。")
                    except Exception as e:
                        logging.error(f"sesh連携機能の実行中に予期せぬエラーが発生: {e}", exc_info=True)
                    
                    return
                # --- ▲▲▲ seshのcreateコマンドに応答するロジック ▲▲▲ ---

                # --- ▼▼▼ 未耐久チャンネルでTARGET_BOTが発言したら応答するロジック ▼▼▼ ---
                if (message.channel.name == TARGET_CHANNEL_NAME_FOR_BASE and
                    message.author.id == TARGET_BOT_ID_FOR_BASE):

                    processed_messages.add(message.id)
                    logging.info(f"Bot(ID:{TARGET_BOT_ID_FOR_BASE})の発言を'{message.channel.name}'チャンネルで検知しました。")
                    try:
                        guild = message.guild
                        command_time = message.created_at.astimezone(JST)

                        category_name = command_time.strftime("%B").lower()
                        category = discord.utils.get(guild.categories, name=category_name)

                        if category is None:
                            overwrites = {
                                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                            }
                            player_role = discord.utils.get(guild.roles, name="player")
                            if player_role:
                                overwrites[player_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                            
                            # builderロールの取得と設定を追加
                            builder_role = discord.utils.get(guild.roles, name="builder")
                            if builder_role:
                                overwrites[builder_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                            # -----------------------

                            category = await guild.create_category(category_name, overwrites=overwrites)
                            logging.info(f"プライベートカテゴリ '{category_name}' を作成しました。")

                        prefix = command_time.strftime("%b").lower()
                        max_num = 0
                        for ch in category.text_channels:
                            m = re.match(rf"^{re.escape(prefix)}(\d+)", ch.name, re.IGNORECASE)
                            if m:
                                num = int(m.group(1))
                                max_num = max(max_num, num)
                        new_channel_name = f"{prefix}{max_num + 1}"

                        if discord.utils.get(category.text_channels, name=new_channel_name):
                            return

                        new_channel = await guild.create_text_channel(new_channel_name, category=category)
                        original_link = message.jump_url
                        sent_msg = await new_channel.send(original_link)
                        return_link = sent_msg.jump_url
                        await message.channel.send(return_link)

                    except Exception as e:
                        logging.error(f"連携機能(未耐久)でエラー: {e}", exc_info=True)
                    
                    return
                # --- ▲▲▲ 未耐久チャンネルでTARGET_BOTが発言したら応答するロジック ▲▲▲ ---

                # --- ▼▼▼ 【修正】リンク置き場(base-link)チャンネルの応答ロジック ▼▼▼ ---
                if (message.channel.name == TARGET_CHANNEL_NAME_FOR_LINKS and
                    message.author.id == TARGET_BOT_ID_FOR_BASE):

                    processed_messages.add(message.id)
                    logging.info(f"Botの発言を'{TARGET_CHANNEL_NAME_FOR_LINKS}'で検知しました。")

                    try:
                        guild = message.guild
                        current_category = message.channel.category
                        if not current_category:
                            logging.warning("base-linkがカテゴリーに属していません。")
                            return

                        # カテゴリー名によって接頭辞(prefix)を判定
                        if "up" in current_category.name.lower():
                            prefix = "up"
                        elif "ことら" in current_category.name:
                            prefix = "kotora"
                        else:
                            # どちらでもない場合はupをデフォルトにするか、必要に応じて追加
                            prefix = "up"

                        # --- 1. カテゴリー内のチャンネルから連番を探す ---
                        max_num = 0
                        for ch in current_category.text_channels:
                            m = re.match(rf"^{re.escape(prefix)}(\d+)$", ch.name, re.IGNORECASE)
                            if m:
                                num = int(m.group(1))
                                max_num = max(max_num, num)
                        new_channel_name = f"{prefix}{max_num + 1}"

                        # --- 2. チャンネル作成とリンク送信 ---
                        if not discord.utils.get(current_category.text_channels, name=new_channel_name):
                            new_channel = await guild.create_text_channel(new_channel_name, category=current_category)
                            original_link = message.jump_url
                            sent_msg = await new_channel.send(original_link)
                            
                            # 元のbase-linkへ作成したチャンネルのリンクを貼る
                            return_link = sent_msg.jump_url
                            await message.channel.send(return_link)
                            logging.info(f"新チャンネル '{new_channel.name}' を作成しリンクを送信しました。")

                    except Exception as e:
                        logging.error(f"リンク置き場連携機能でエラー: {e}", exc_info=True)

                    return
                # --- ▲▲▲ 【修正】リンク置き場(base-link)チャンネルの応答ロジック ▲▲▲ ---


                # --- 既存の機能：ボットへのメンションに反応するロジック ---
                if not client.user.mentioned_in(message):
                    return

                pattern = rf'<@!?{client.user.id}>\s*(.*)'
                match = re.search(pattern, message.content, re.DOTALL)
                if not match:
                    return

                command_text = match.group(1).strip()

                # 日付コマンドの処理
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
                        await message.channel.send(f"エラーが発生しました。")
                        return

                # 数字リアクション
                num_match = re.fullmatch(r'num:(\d+)', command_text, re.IGNORECASE)
                if num_match:
                    count = int(num_match.group(1))
                    if 1 <= count <= 10:
                        for i in range(count):
                            await message.add_reaction(NUMBER_EMOJIS[i])
                    return

                # デフォルトのリアクション
                if command_text == "":
                    for emoji in REACTION_EMOJIS:
                        await message.add_reaction(emoji)
                    return

            client.run(TOKEN)

        except Exception as e:
            logging.error(f"ボットの実行中にエラーが発生: {e}", exc_info=True)
            time.sleep(10)

# --- メインの実行ブロック ---
if __name__ == '__main__':
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    
    run_bot()