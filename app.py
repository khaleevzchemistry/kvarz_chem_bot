import os
import json
import random
import logging
import threading
from dotenv import load_dotenv
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Токен не найден! Проверь переменную BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

# Загружаем вопросы
with open("questions.json", "r", encoding="utf-8") as f:
    ALL_QUESTIONS = json.load(f)

# Статистика
STATS_FILE = "stats.json"
if os.path.exists(STATS_FILE):
    with open(STATS_FILE, "r", encoding="utf-8") as f:
        stats = json.load(f)
else:
    stats = {}

user_state = {}

def save_stats():
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

# ---------- Обработчики бота (те же самые) ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    unique_topics = sorted(set(q["topic"].strip() for q in ALL_QUESTIONS))
    context.bot_data['topics_list'] = unique_topics
    keyboard = []
    for idx, topic in enumerate(unique_topics):
        keyboard.append([InlineKeyboardButton(f"🧪 {topic}", callback_data=f"topic_{idx}")])
    keyboard.append([InlineKeyboardButton("📊 Моя статистика", callback_data="show_stats")])
    keyboard.append([InlineKeyboardButton("🏆 Рейтинг", callback_data="show_rating")])
    keyboard.append([InlineKeyboardButton("🗑 Сбросить статистику", callback_data="reset_stats")])
    await update.message.reply_text(
        "👋 Привет! Я помогу тебе выучить химию.\n"
        "Выбери тему для викторины или воспользуйся кнопками ниже:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def setname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    name = ' '.join(context.args)
    if not name:
        await update.message.reply_text("❌ Напиши имя после команды, например: /setname Алексей")
        return
    if user_id not in stats:
        stats[user_id] = {"username": name, "total_correct": 0, "total_wrong": 0, "topics": {}}
    else:
        stats[user_id]["username"] = name
    save_stats()
    await update.message.reply_text(f"✅ Имя сохранено как «{name}»")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    data = query.data

    if data.startswith("topic_"):
        idx = int(data.split("_")[1])
        topics_list = context.bot_data.get('topics_list', [])
        if idx < 0 or idx >= len(topics_list):
            await query.edit_message_text("❌ Ошибка: тема не найдена. Нажми /start")
            return
        topic = topics_list[idx]
        user_state[user_id] = {"topic": topic, "step": "choose_count"}
        keyboard = [
            [InlineKeyboardButton("5", callback_data=f"count_5_{idx}"),
             InlineKeyboardButton("10", callback_data=f"count_10_{idx}")],
            [InlineKeyboardButton("20", callback_data=f"count_20_{idx}"),
             InlineKeyboardButton("Все", callback_data=f"count_all_{idx}")]
        ]
        await query.edit_message_text(
            f"📚 Тема: {topic}\nСколько вопросов хочешь получить?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("count_"):
        parts = data.split("_")
        count_str = parts[1]
        idx = int(parts[2])
        topics_list = context.bot_data.get('topics_list', [])
        if idx < 0 or idx >= len(topics_list):
            await query.edit_message_text("❌ Ошибка: тема не найдена. Нажми /start")
            return
        topic = topics_list[idx]
        filtered = [q for q in ALL_QUESTIONS if q["topic"].strip() == topic]
        if not filtered:
            await query.edit_message_text("❌ Вопросов по этой теме пока нет.")
            return
        shuffled = random.sample(filtered, len(filtered))
        if count_str == "all":
            count = len(shuffled)
        else:
            count = int(count_str)
            if count > len(shuffled):
                count = len(shuffled)
        selected = shuffled[:count]
        user_state[user_id] = {
            "questions": selected,
            "index": 0,
            "correct": 0,
            "wrong": 0,
            "topic": topic
        }
        await send_question(query, user_id)
        return

    if data.startswith("answer_"):
        parts = data.split("_")
        q_index = int(parts[1])
        answer_index = int(parts[2])
        state = user_state.get(user_id)
        if not state:
            await query.edit_message_text("❌ Сессия не найдена. Нажми /start")
            return
        question = state["questions"][q_index]
        is_correct = (answer_index == question["correct"])
        if is_correct:
            state["correct"] += 1
        else:
            state["wrong"] += 1

        if user_id not in stats:
            stats[user_id] = {"username": None, "total_correct": 0, "total_wrong": 0, "topics": {}}
        if state["topic"] not in stats[user_id]["topics"]:
            stats[user_id]["topics"][state["topic"]] = {"correct": 0, "wrong": 0}
        if is_correct:
            stats[user_id]["total_correct"] += 1
            stats[user_id]["topics"][state["topic"]]["correct"] += 1
        else:
            stats[user_id]["total_wrong"] += 1
            stats[user_id]["topics"][state["topic"]]["wrong"] += 1
        save_stats()

        correct_option = question["options"][question["correct"]]
        result_text = "✅ Верно!" if is_correct else f"❌ Неверно. Правильный ответ: {correct_option}"
        result_text += f"\n\n💡 {question['explanation']}"

        if q_index + 1 < len(state["questions"]):
            keyboard = [[InlineKeyboardButton("➡️ Следующий вопрос", callback_data=f"next_{q_index+1}")]]
        else:
            keyboard = [[InlineKeyboardButton("🏁 Завершить викторину", callback_data="finish_quiz")]]
        await query.edit_message_text(
            text=result_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("next_"):
        next_index = int(data.split("_")[1])
        state = user_state.get(user_id)
        if state and next_index < len(state["questions"]):
            state["index"] = next_index
            await send_question(query, user_id)
        else:
            await query.edit_message_text("❌ Ошибка. Нажми /start")
        return

    if data == "finish_quiz":
        state = user_state.get(user_id)
        if state:
            total = state["correct"] + state["wrong"]
            percent = round(state["correct"] / total * 100, 1) if total > 0 else 0
            await query.edit_message_text(
                f"🎉 Викторина завершена!\n"
                f"Тема: {state['topic']}\n"
                f"✅ Правильных: {state['correct']}\n"
                f"❌ Неправильных: {state['wrong']}\n"
                f"🎯 Точность: {percent}%\n\n"
                "Чтобы начать заново, нажми /start"
            )
            user_state.pop(user_id, None)
        else:
            await query.edit_message_text("❌ Ошибка. Нажми /start")
        return

    if data == "show_stats":
        user_stats = stats.get(user_id)
        if not user_stats:
            await query.edit_message_text("📭 У тебя пока нет статистики. Пройди викторину!")
            return
        text = "📊 *Твоя статистика:*\n"
        text += f"Всего правильно: {user_stats['total_correct']}\n"
        text += f"Всего неправильно: {user_stats['total_wrong']}\n"
        for topic, data_topic in user_stats["topics"].items():
            total = data_topic["correct"] + data_topic["wrong"]
            percent = round(data_topic["correct"] / total * 100, 1) if total > 0 else 0
            text += f"\n*{topic}:* {data_topic['correct']} верно, {data_topic['wrong']} неверно ({percent}%)"
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    if data == "show_rating":
        if not stats:
            await query.edit_message_text("Пока никто не проходил викторину. Будь первым!")
            return
        sorted_users = sorted(stats.items(), key=lambda x: x[1]["total_correct"], reverse=True)
        top = sorted_users[:10]
        text = "🏆 *Рейтинг участников:*\n\n"
        for i, (uid, stat) in enumerate(top, 1):
            name = stat.get("username")
            if not name:
                name = f"ID {uid}"
            text += f"{i}. {name} — {stat['total_correct']} правильных ответов\n"
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    if data == "reset_stats":
        keyboard = [
            [InlineKeyboardButton("✅ Да, сбросить", callback_data="confirm_reset")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_reset")]
        ]
        await query.edit_message_text(
            "⚠️ Ты уверен, что хочешь сбросить всю статистику?\nЭто необратимо.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "confirm_reset":
        if user_id in stats:
            stats[user_id]["total_correct"] = 0
            stats[user_id]["total_wrong"] = 0
            stats[user_id]["topics"] = {}
            save_stats()
            await query.edit_message_text("✅ Статистика сброшена. Нажми /start")
        else:
            await query.edit_message_text("У тебя нет статистики для сброса.")
        return

    if data == "cancel_reset":
        await query.edit_message_text("Сброс отменён. Нажми /start")
        return

async def send_question(query, user_id):
    state = user_state.get(user_id)
    if not state:
        await query.edit_message_text("❌ Сессия не найдена. Нажми /start")
        return
    q_index = state["index"]
    question = state["questions"][q_index]
    text = f"📚 *{question['topic']}* (вопрос {q_index+1}/{len(state['questions'])})\n\n{question['question']}"
    keyboard = []
    for i, option in enumerate(question['options']):
        keyboard.append([InlineKeyboardButton(option, callback_data=f"answer_{q_index}_{i}")])
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ---------- Запуск бота в отдельном потоке ----------
def run_bot():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setname", setname))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("🤖 Бот запущен...")
    app.run_polling()

# ---------- Flask-сервер для Render ----------
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "🤖 Бот работает!"

@app_flask.route('/health')
def health():
    return "OK", 200

if __name__ == "__main__":
    # Запускаем бота в фоновом потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    # Запускаем Flask-сервер (Render требует открытый порт)
    port = int(os.environ.get("PORT", 5000))
    app_flask.run(host="0.0.0.0", port=port)