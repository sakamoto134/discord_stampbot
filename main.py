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

# --- sesh連携機能のための定数を追加 ---
SESH_BOT_ID = 616754792965865495 # (これは公式seshのIDです。必要に応じて変更してください)
TARGET_SESH_CHANNEL_NAME = "sesh⚙️"
MENTION_ROLES_FOR_SESH = ["sesh"]

# --- /baseコマンド連携機能のための定数を追加 ---
TARGET_BOT_ID_FOR_BASE = 824653933347209227
TARGET_CHANNEL_NAME_FOR_BASE = "未耐久"
TARGET_COMMAND_NAME_FOR_BASE = "base"

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

            # --- 定期実行タスクの定義 ---
            JST = timezone(timedelta(hours=9), 'JST')
            scheduled_time = time(hour=20, minute=00, tzinfo=JST)

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
                        logging.warning(f"サーバー'{guild.name}'でチャンネル'{CHANNEL_NAME}'は見つかりましたが、ロール'{', '.join(ROLE_NAMES)}'のいずれも見つかりませんでした。")

            @client.event
            async def on_ready():
                logging.info(f'{client.user.name} が起動しました！')
                if not send_weekly_schedule.is_running():
                    send_weekly_schedule.start()

            @client.event
            async def on_message(message):
                if message.author == client.user:
                    return

                # --- seshのcreateコマンドに応答するロジック ---
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
                            logging.info(f"メンションを送信しました: {mentions}")
                        else:
                            logging.warning(f"サーバー'{guild.name}'で、メンション対象のロール'{', '.join(MENTION_ROLES_FOR_SESH)}'が見つかりませんでした。")
                    except discord.errors.Forbidden:
                        logging.error(f"エラー: チャンネル'{message.channel.name}'への投稿権限がありません。")
                    except Exception as e:
                        logging.error(f"sesh連携機能の実行中に予期せぬエラーが発生: {e}", exc_info=True)
                    return

                # --- 未耐久チャンネルで/baseコマンドに応答するロジック ---
                if (message.channel.name == TARGET_CHANNEL_NAME_FOR_BASE and
                    message.author.id == TARGET_BOT_ID_FOR_BASE and
                    message.interaction is not None and
                    message.interaction.name == TARGET_COMMAND_NAME_FOR_BASE and
                    not message.interaction.user.bot):
                    logging.info(f"'/base'コマンド応答を'{message.channel.name}'チャンネルで検知しました。")
                    try:
                        guild = message.guild
                        command_time = message.created_at.astimezone(JST)

                        # 1. 月のカテゴリーを作成または取得
                        category_name = command_time.strftime('%B').lower()
                        category = discord.utils.get(guild.categories, name=category_name)
                        if category is None:
                            logging.info(f"カテゴリー '{category_name}' が見つからないため、新規作成します。")
                            category = await guild.create_category(category_name)
                            logging.info(f"カテゴリー '{category_name}' を作成しました。")
                        else:
                            logging.info(f"既存のカテゴリー '{category_name}' を使用します。")

                        # 2. 新しいチャンネルの連番を決定
                        channel_prefix = command_time.strftime('%b').lower()
                        max_number = 0
                        for ch in category.text_channels:
                            match = re.match(rf'^{re.escape(channel_prefix)}(\d+)', ch.name, re.IGNORECASE)
                            if match:
                                number = int(match.group(1))
                                if number > max_number:
                                    max_number = number
                        next_number = max_number + 1
                        new_channel_name = f"{channel_prefix}{next_number}"
                        logging.info(f"新しいチャンネル名: {new_channel_name}")

                        # 3. チャンネルを作成
                        new_channel = await guild.create_text_channel(new_channel_name, category=category)
                        logging.info(f"チャンネル '{new_channel.name}' をカテゴリー '{category.name}' 内に作成しました。")
                        
                        # ▼▼▼ 変更箇所 ▼▼▼
                        # 4. 応答メッセージのリンクを貼り付け、内容を転送する
                        # on_messageイベントで取得したmessageオブジェクトでは内容が不完全な場合があるため、
                        # fetch_messageでメッセージを再取得して完全な情報を得る
                        logging.info(f"メッセージID {message.id} の内容を再取得します。")
                        original_message = await message.channel.fetch_message(message.id)

                        # 転送用のメッセージを作成 (元のメッセージへのリンクを含む)
                        forward_content = f"元のメッセージ: {original_message.jump_url}"
                        
                        # 元のメッセージにテキスト本文があれば、それも転送メッセージに追加
                        if original_message.content:
                            forward_content += f"\n\n{original_message.content}"
                        
                        # 新しいチャンネルにメッセージリンクと、取得したcontent/embedsを送信
                        await new_channel.send(content=forward_content, embeds=original_message.embeds)
                        logging.info(f"'{new_channel.name}' にメッセージリンクと内容を転送しました。")
                        # ▲▲▲ 変更箇所 ▲▲▲

                    except discord.errors.Forbidden:
                        logging.error(f"エラー: サーバー '{message.guild.name}' でカテゴリーまたはチャンネルの作成、あるいはメッセージの送信に必要な権限がありません。")
                    except Exception as e:
                        logging.error(f"/base連携機能の実行中に予期せぬエラーが発生: {e}", exc_info=True)
                    return

                # --- 既存の機能：ボットへのメンションに反応するロジック ---
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
                        month_str, day_str = date_match.group(1), date_match.group(2)
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

# --- メインの実行ブロック ---
if __name__ == '__main__':
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    
    run_bot()