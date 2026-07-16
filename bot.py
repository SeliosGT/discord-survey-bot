import discord
import os
import requests
import json
from datetime import datetime
import asyncio
from flask import Flask, request, jsonify
import threading

# ============================================================
# НАСТРОЙКА БОТА
# ============================================================

TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
ADMIN_USER_ID = int(os.environ.get('ADMIN_USER_ID', '0'))
SERVER_URL = os.environ.get('SERVER_URL', 'https://opros-app.onrender.com')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

# ============================================================
# СОБЫТИЕ: БОТ ГОТОВ
# ============================================================

@client.event
async def on_ready():
    print(f'✅ Бот {client.user.name} запущен!')
    print(f'📊 На серверах: {len(client.guilds)}')
    
    try:
        user = await client.fetch_user(ADMIN_USER_ID)
        await user.send('🤖 **Бот запущен!** Готов принимать уведомления о новых заявках.')
        print('✅ Приветствие отправлено админу')
    except Exception as e:
        print(f'⚠️ Не удалось отправить приветствие: {e}')

@client.event
async def on_message(message):
    if message.author.bot:
        return

# ============================================================
# ФУНКЦИЯ: ОТПРАВКА УВЕДОМЛЕНИЯ
# ============================================================

async def send_notification(survey_type, answer_data, answer_id, date_str):
    try:
        user = await client.fetch_user(ADMIN_USER_ID)
        
        type_names = {
            'discipline': '🏛️ Дисциплинарный инспектор',
            'hr': '👔 HR-менеджер'
        }
        type_name = type_names.get(survey_type, '📋 Новая заявка')
        
        embed = discord.Embed(
            title="🔔 **Новая заявка!**",
            color=0x5865F2,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="🆔 Номер заявки", value=f"`#{answer_id}`", inline=True)
        embed.add_field(name="📋 Куда устроиться", value=type_name, inline=True)
        embed.add_field(name="👤 Имя персонажа (IC)", value=answer_data.get('q1', '—'), inline=True)
        embed.add_field(name="👤 Ваше имя (OOC)", value=answer_data.get('q2', '—'), inline=True)
        embed.add_field(name="📅 Дата подачи", value=date_str, inline=True)
        embed.add_field(name="🔗 Ссылка", value=f"[Открыть админ-панель]({SERVER_URL}/admin.html)", inline=False)
        
        embed.set_footer(text="by Rubi Antwoord", icon_url="https://cdn-icons-png.flaticon.com/512/3196/3196109.png")
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="📋 Перейти к админ-панели",
            url=f"{SERVER_URL}/admin.html",
            style=discord.ButtonStyle.link
        ))
        
        await user.send(content=f"🔔 **Поступила новая заявка #{answer_id}!**", embed=embed, view=view)
        print(f'✅ Уведомление отправлено админу (заявка #{answer_id})')
        
    except Exception as e:
        print(f'⚠️ Ошибка отправки уведомления: {e}')

# ============================================================
# ВЕБ-СЕРВЕР ДЛЯ ПРИЁМА ЗАПРОСОВ
# ============================================================

app = Flask(__name__)

@app.route('/notify', methods=['POST'])
def notify():
    try:
        data = request.json
        survey_type = data.get('survey_type')
        answer_data = data.get('answer_data')
        answer_id = data.get('answer_id')
        date_str = data.get('date_str')
        
        asyncio.create_task(send_notification(survey_type, answer_data, answer_id, date_str))
        
        return jsonify({"success": True}), 200
        
    except Exception as e:
        print(f'⚠️ Ошибка в /notify: {e}')
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/')
def index():
    return "🤖 Discord Survey Bot is running!"

# ============================================================
# ЗАПУСК БОТА В ОТДЕЛЬНОМ ПОТОКЕ
# ============================================================

def run_bot():
    client.run(TOKEN)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    app.run(host='0.0.0.0', port=8080)
