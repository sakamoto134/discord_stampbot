import os
import re
import logging
import time
from datetime import datetime, timedelta, time as dtime, timezone
from threading import Thread

import discord
from discord.ext import tasks
from flask import Flask

# ==========================================
# ▼▼▼ 設定セクション (ここを変更してください) ▼▼▼
# ==========================================

# --- 基本設定 ---
# タイムゾーン (JST)
JST = timezone(timedelta(hours=9), 'JST')
# 曜日表示
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]
# リアクション用絵文字
NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
REACTION_EMOJIS = ["⭕", "❌", "🔺"]

# --- 機能1: 週間予定 (毎週水曜20:00) ---
SCHEDULE_CHANNEL_NAME = "attendance"       # 投稿先チャンネル
SCHEDULE_MENTION_ROLES = ["player", "guest"] # メンションするロール

# --- 機能2: sesh連携 ---
SESH_BOT_ID = 616754792965865495           # seshボットのID
SESH_TARGET_CHANNEL = "calender🗓️"         # 監視するチャンネル
SESH_MENTION_ROLES = ["sesh"]              # create時にメンションするロール

# --- 機能3: /baseコマンド連携 (未耐久 & リンク置き場) ---
BASE_TARGET_BOT_ID = 824653933347209227    # 監視対象のボットID
BASE_TRIGGER_CHANNEL = "未耐久"            # カテゴリ作成のトリガーとなるチャンネル
BASE_LINK_CHANNEL = "base-link"            # リンク転送用のチャンネル

# ★★★ カテゴリ作成時のアクセス権限ロール ★★★
# ここに含まれるロールは、自動作成された月次カテゴリ・チャンネルが見えるようになります
CATEGORY_ACCESS_ROLES = ["player", "builder", "supporter"] 

# ==========================================
# ▲▲▲ 設定セクション終了 ▲▲▲
# ==========================================

# --- 環境変数 ---
TOKEN = os.getenv('DISCORD_TOKEN')
PORT = int(os.getenv('PORT', 8080))

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
            intents = discord.Intents.default()
            intents.message_content = True
            client = discord.Client(intents=intents, max_messages=None)

            # --- 定期実行タスク: 週間予定 ---
            scheduled_time = dtime(hour=20, minute=0, tzinfo=JST)

            @tasks.loop(time=scheduled_time)
            async def send_weekly_schedule():
                """毎週水曜日の20:00に週間予定を投稿するタスク"""
                await client.wait_until_ready()

                if datetime.now(JST).weekday() != 2: # 2 = 水曜日
                    return

                logging.info("定期実行タスク: 週間予定の投稿を開始します。")

                for guild in client.guilds:
                    channel = discord.utils.get(guild.text_channels, name=SCHEDULE_CHANNEL_NAME)
                    roles_to_mention = [discord.utils.get(guild.roles, name=name) for name in SCHEDULE_MENTION_ROLES]
                    found_roles = [role for role in roles_to_mention if role is not None]

                    if channel and found_roles:
                        try:
                            logging.info(f"サーバー'{guild.name}'のチャンネル'{channel.name}'にメッセージを送信します。")
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
                            logging.info(f"サーバー'{guild.name}'への週間予定の投稿が完了しました。")

                        except discord.errors.Forbidden:
                            logging.error(f"エラー: チャンネル'{channel.name}'への投稿権限がありません。")
                        except Exception as e:
                            logging.error(f"定期タスク実行中に予期せぬエラーが発生: {e}", exc_info=True)
                    
                    elif channel and not found_roles:
                        logging.warning(f"サーバー'{guild.name}'でチャンネル'{SCHEDULE_CHANNEL_NAME}'は見つかりましたが、ロールが見つかりませんでした。")

            @client.event
            async def on_ready():
                logging.info(f'{client.user.name} が起動しました！')
                if not send_weekly_schedule.is_running():
                    send_weekly_schedule.start()

            @client.event
            async def on_message(message):
                if message.author == client.user:
                    return
                if message.id in processed_messages:
                    return

                # --- ▼▼▼ sesh連携機能 ▼▼▼ ---
                if (message.channel.name == SESH_TARGET_CHANNEL and
                    message.author.id == SESH_BOT_ID and
                    message.interaction is not None and
                    message.interaction.name == 'create' and
                    not message.interaction.user.bot):

                    logging.info(f"seshのcreateコマンド応答を'{message.channel.name}'チャンネルで検知しました。")
                    try:
                        guild = message.guild
                        roles_to_mention = [discord.utils.get(guild.roles, name=name) for name in SESH_MENTION_ROLES]
                        found_roles = [role for role in roles_to_mention if role is not None]

                        if found_roles:
                            mentions = " ".join(role.mention for role in found_roles)
                            await message.channel.send(mentions)
                        else:
                            logging.warning(f"サーバー'{guild.name}'でsesh用メンション対象ロールが見つかりませんでした。")

                    except Exception as e:
                        logging.error(f"sesh連携機能のエラー: {e}", exc_info=True)
                    
                    return

                # --- ▼▼▼ 未耐久チャンネル連携 (カテゴリ作成) ▼▼▼ ---
                if (message.channel.name == BASE_TRIGGER_CHANNEL and
                    message.author.id == BASE_TARGET_BOT_ID):

                    processed_messages.add(message.id)
                    logging.info(f"Bot(ID:{BASE_TARGET_BOT_ID})の発言を'{message.channel.name}'で検知。")
                    try:
                        guild = message.guild
                        command_time = message.created_at.astimezone(JST)

                        category_name = command_time.strftime("%B").lower()
                        category = discord.utils.get(guild.categories, name=category_name)

                        if category is None:
                            # 権限設定の構築
                            overwrites = {
                                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                            }
                            
                            # ★設定リストにあるロールに対して権限を付与 (player, builderなど)
                            for role_name in CATEGORY_ACCESS_ROLES:
                                role = discord.utils.get(guild.roles, name=role_name)
                                if role:
                                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                            
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

                        if not discord.utils.get(category.text_channels, name=new_channel_name):
                            new_channel = await guild.create_text_channel(new_channel_name, category=category)
                            original_link = message.jump_url
                            sent_msg = await new_channel.send(original_link)
                            return_link = sent_msg.jump_url
                            await message.channel.send(return_link)

                    except Exception as e:
                        logging.error(f"連携機能(未耐久)でエラー: {e}", exc_info=True)
                    
                    return

                # --- ▼▼▼ リンク置き場連携 (base-link) ▼▼▼ ---
                if (message.channel.name == BASE_LINK_CHANNEL and
                    message.author.id == BASE_TARGET_BOT_ID):

                    processed_messages.add(message.id)
                    logging.info(f"Botの発言を'{BASE_LINK_CHANNEL}'で検知しました。")

                    try:
                        guild = message.guild
                        current_category = message.channel.category
                        if not current_category:
                            logging.warning(f"{BASE_LINK_CHANNEL}がカテゴリーに属していません。")
                            return

                        if "up" in current_category.name.lower():
                            prefix = "up"
                        elif "ことら" in current_category.name:
                            prefix = "kotora"
                        else:
                            prefix = "up"

                        max_num = 0
                        for ch in current_category.text_channels:
                            m = re.match(rf"^{re.escape(prefix)}(\d+)$", ch.name, re.IGNORECASE)
                            if m:
                                max_num = max(max_num, int(m.group(1)))
                        new_channel_name = f"{prefix}{max_num + 1}"

                        if not discord.utils.get(current_category.text_channels, name=new_channel_name):
                            new_channel = await guild.create_text_channel(new_channel_name, category=current_category)
                            original_link = message.jump_url
                            sent_msg = await new_channel.send(original_link)
                            
                            return_link = sent_msg.jump_url
                            await message.channel.send(return_link)
                            logging.info(f"新チャンネル '{new_channel.name}' を作成しリンクを送信しました。")

                    except Exception as e:
                        logging.error(f"リンク置き場連携機能でエラー: {e}", exc_info=True)

                    return

                # --- 既存の機能：ボットへのメンション ---
                if not client.user.mentioned_in(message):
                    return

                pattern = rf'<@!?{client.user.id}>\s*(.*)'
                match = re.search(pattern, message.content, re.DOTALL)
                if not match:
                    return

                command_text = match.group(1).strip()

                # 日付コマンド
                date_match = re.fullmatch(r'(\d{1,2})/(\d{1,2})(?:\s+day:(\d+))?', command_text, re.IGNORECASE)
                if date_match:
                    try:
                        date_str = f"{date_match.group(1)}/{date_match.group(2)}"
                        days_to_show = int(date_match.group(3)) if date_match.group(3) else 7

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
                        await message.channel.send("エラーが発生しました。")
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

if __name__ == '__main__':
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    run_bot()