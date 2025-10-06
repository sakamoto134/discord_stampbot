import os
import re
import logging
import time
from datetime import datetime, timedelta, time, timezone
from threading import Thread

import discord
from discord import app_commands # スラッシュコマンドのために追加
from discord.ext import tasks
from flask import Flask

# --- 定数 ---
NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
REACTION_EMOJIS = ["⭕", "❌", "🔺"]
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]
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

    # 日本時間 (JST, UTC+9)
    JST = timezone(timedelta(hours=9), 'JST')

    while True:
        try:
            # --- ▼▼▼ 変更 ▼▼▼ ---
            # intentsにmembersを追加（ロール情報を取得するため）
            intents = discord.Intents.default()
            intents.guilds = True
            intents.guild_messages = True
            intents.message_content = True
            intents.members = True # ユーザーのロール情報を取得するために必要
            # --- ▲▲▲ 変更 ▲▲▲ ---
            client = discord.Client(intents=intents, max_messages=None)
            
            # --- ▼▼▼ 追加 ▼▼▼ ---
            # スラッシュコマンド用のツリーを定義
            tree = app_commands.CommandTree(client)
            # --- ▲▲▲ 追加 ▲▲▲ ---

            # --- 定期実行タスクの定義 ---
            scheduled_time = time(hour=20, minute=0, tzinfo=JST)

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
                # --- ▼▼▼ 追加 ▼▼▼ ---
                # スラッシュコマンドをDiscordに同期
                await tree.sync()
                logging.info("スラッシュコマンドを同期しました。")
                # --- ▲▲▲ 追加 ▲▲▲ ---
                if not send_weekly_schedule.is_running():
                    send_weekly_schedule.start()

            # --- ▼▼▼ 変更 ▼▼▼ ---
            # on_messageは新機能専用に書き換え
            @client.event
            async def on_message(message):
                # ボット自身のメッセージは無視
                if message.author == client.user:
                    return

                # --- 新機能：未耐久チャンネルの監視 ---
                TARGET_CHANNEL_NAME = "未耐久"
                TARGET_ROLE_NAME = "ClashKing"

                # チャンネル名が一致するかチェック
                if message.channel.name == TARGET_CHANNEL_NAME:
                    # 投稿者がMemberオブジェクトであり、特定のロールを持っているかチェック
                    if isinstance(message.author, discord.Member) and discord.utils.get(message.author.roles, name=TARGET_ROLE_NAME):
                        try:
                            logging.info(f"'{TARGET_CHANNEL_NAME}'で'{TARGET_ROLE_NAME}'を持つユーザー'{message.author.display_name}'の投稿を検知。")
                            guild = message.guild
                            
                            # 1. 月カテゴリーの決定と作成
                            created_at_jst = message.created_at.astimezone(JST)
                            category_name = created_at_jst.strftime('%B').lower() # 例: 'october'
                            
                            category = discord.utils.get(guild.categories, name=category_name)
                            if not category:
                                logging.info(f"カテゴリ '{category_name}' が見つからないため作成します。")
                                category = await guild.create_category(category_name)
                            
                            # 2. 新しいチャンネル名の決定 (例: october1, october2)
                            max_num = 0
                            pattern = re.compile(rf'^{re.escape(category_name)}(\d+)')
                            for ch in category.text_channels:
                                match = pattern.match(ch.name)
                                if match:
                                    num = int(match.group(1))
                                    if num > max_num:
                                        max_num = num
                            new_channel_number = max_num + 1
                            new_channel_name = f"{category_name}{new_channel_number}"
                            
                            # 3. チャンネルの作成
                            logging.info(f"新しいチャンネル '{new_channel_name}' を作成します。")
                            new_channel = await guild.create_text_channel(name=new_channel_name, category=category)
                            
                            # 4. メッセージと添付ファイルのコピー
                            content = message.content
                            files_to_send = [await attachment.to_file() for attachment in message.attachments]
                            
                            if content or files_to_send:
                                await new_channel.send(content=content, files=files_to_send)
                                logging.info(f"チャンネル '{new_channel_name}' にメッセージと添付ファイルをコピーしました。")
                            
                        except discord.errors.Forbidden:
                            logging.error(f"エラー: カテゴリ/チャンネルの作成、またはメッセージ送信の権限がありません。")
                        except Exception as e:
                            logging.error(f"未耐久チャンネルの処理中に予期せぬエラーが発生: {e}", exc_info=True)

            # --- スラッシュコマンドの定義 ---

            @tree.command(name="schedule", description="指定した期間の出欠投票を作成します。")
            @app_commands.describe(
                start_date="開始日 (例: 10/1)",
                days="表示する日数 (1～10、デフォルトは7)"
            )
            async def schedule(interaction: discord.Interaction, start_date: str, days: app_commands.Range[int, 1, 10] = 7):
                date_match = re.fullmatch(r'(\d{1,2})/(\d{1,2})', start_date)
                if not date_match:
                    await interaction.response.send_message("開始日の形式が正しくありません。`M/D` (例: `10/1`) の形式で入力してください。", ephemeral=True)
                    return

                await interaction.response.defer() # 処理に時間がかかる可能性があるため

                try:
                    now = datetime.now(JST)
                    # replaceで年を今年に設定。過去の日付なら来年にする
                    start_dt = datetime.strptime(start_date, '%m/%d').replace(year=now.year, tzinfo=JST)
                    if start_dt.date() < now.date():
                        start_dt = start_dt.replace(year=now.year + 1)

                    await interaction.followup.send(f"`{start_date}` から `{days}` 日間の投票を作成します。")
                    for i in range(days):
                        current_date = start_dt.date() + timedelta(days=i)
                        date_text = f"{current_date.month}/{current_date.day}({WEEKDAYS_JP[current_date.weekday()]})"
                        sent_message = await interaction.channel.send(date_text)
                        for emoji in REACTION_EMOJIS:
                            await sent_message.add_reaction(emoji)
                except Exception as e:
                    logging.error(f"/schedule コマンドの処理中にエラー: {e}", exc_info=True)
                    await interaction.followup.send("エラーが発生しました。", ephemeral=True)

            @tree.command(name="stamp", description="数字のリアクションを付けます。")
            @app_commands.describe(count="リアクションの数 (1～10)")
            async def stamp(interaction: discord.Interaction, count: app_commands.Range[int, 1, 10]):
                # コマンド実行の応答としてメッセージを送信し、それにリアクションをつける
                await interaction.response.send_message(f"{interaction.user.mention} が {count} 個のスタンプをリクエストしました。")
                message = await interaction.original_response()
                for i in range(count):
                    await message.add_reaction(NUMBER_EMOJIS[i])

            @tree.command(name="marubatsu", description="⭕❌🔺のリアクションを付けます。")
            async def marubatsu(interaction: discord.Interaction):
                # コマンド実行の応答としてメッセージを送信し、それにリアクションをつける
                await interaction.response.send_message(f"{interaction.user.mention} がリアクションをリクエストしました。")
                message = await interaction.original_response()
                for emoji in REACTION_EMOJIS:
                    await message.add_reaction(emoji)
            
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