import asyncio
import random
import os
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration from environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN_HERE")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "YOUR_OPENROUTER_API_KEY_HERE")
MODEL_NAME = os.getenv("MODEL_NAME", "meta-llama/llama-3.1-8b-instruct:free")

# Initialize OpenRouter client (uses OpenAI-compatible API)
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

# --- 1. ПАМЯТЬ ПОЛЬЗОВАТЕЛЕЙ ---
user_states = {}

# --- 2. ВЕСА И ГРУППЫ МЫШЦ УПРАЖНЕНИЙ ---
EXERCISE_WEIGHTS = {
    "Cluster / Кластер": (5, "total"), 
    "Clean and jerk (C&J) / Взятие на грудь и толчок штанги": (5, "total"),
    "Thruster / Выброс штанги": (5, "total"), 
    "Bar Muscle-up (BMU) / Выход на турнике": (5, "upper_pull"),
    "Push Jerk (PJ) / Швунг толчковый": (5, "upper_push"), 
    "Power Snatch (PSN) / Рывок": (5, "lower_pull"),
    "Overhead Squat (OHS) / Приседания со штангой над головой": (5, "lower_push"),
    "Deadlift (DL) / Становая тяга штанги": (4, "lower_pull"), 
    "Handstand Push-ups (HSPU) / Отжимания вниз головой": (4, "upper_push"),
    "Wall Walk / Подъемы по стене": (4, "upper_push"), 
    "Chest To Bar Pull-up (C2B)": (4, "upper_pull"),
    "Shoulder Press / MP / Жим стоя": (4, "upper_push"), 
    "Clean (CLN) / Взятие штанги на грудь": (4, "lower_pull"),
    "Push Press (PP) Швунг жимовой": (4, "upper_push"), 
    "Front Squat (FS) / Приседания со штангой на груди": (4, "lower_push"),
    "Back Squat (BS) / Приседания на плечах": (3, "lower_push"), 
    "Burpee + Box Jump / Бёрпи через коробку": (3, "total"),
    "Kettlebell (KB) Swing / Махи гири": (3, "total"), 
    "Box Jump / Запрыгивание на ящик": (3, "lower_push"),
    "Pull-ups (PU) / Подтягивания": (3, "upper_pull"), 
    "Sumo Dead Lift High Pull (SDHP)": (3, "lower_pull"),
    "Double Lunges / Выпады": (3, "lower_push"), 
    "Wall Ball (WB) / Броски мяча": (3, "total"),
    "Burpee / Бёрпи": (3, "total"), 
    "Toes To Bar (T2B) / Ноги к турнику": (3, "core"),
    "V-ups / V-образные скручивания": (2, "core"), 
    "One Legged Squat (The Pistol) / Пистолетик": (2, "lower_push"),
    "Double Unders (DU) / Двойные прыжки": (2, "total"), 
    "Gymnastics Air Squat / Приседания": (1, "lower_push"),
    "Sit-ups / Скручивания": (1, "core"), 
    "Push-up / Отжимания": (1, "upper_push")
}

CARDIO_MACHINES = ["Rowing / Гребля", "Assault Bike / Велотренажер", "SkiErg / Лыжный тренажер", "Run / Бег"]

def get_rest_time(total_weight):
    if total_weight >= 8: 
        return "Отдых 1 минута"
    return "Без отдыха, переход к следующему блоку"

# --- 3. МОЗГ АГЕНТА ---

async def generate_ai_response(user_id, user_text):
    now = datetime.now()
    user_text_lower = user_text.lower()
    week_parity = now.isocalendar()[1] % 2 
    
    current_format = "standard"
    if any(w in user_text_lower for w in ["amrap", "амрап"]):
        current_format = "amrap"
    elif any(w in user_text_lower for w in ["emom", "эмом", "емом"]):
        current_format = "emom"

    days_map = {"понедельник": 0, "пн": 0, "вт": 1, "вторник": 1, "сред": 2, "ср": 2, "четверг": 3, "чт": 3, "пятниц": 4, "пт": 4, "суббот": 5, "сб": 5, "воскрес": 6, "вс": 6, "завтра": (now.weekday() + 1) % 7}
    target_weekday = now.weekday()
    day_found = False
    
    for day_word, day_idx in days_map.items():
        if day_word in user_text_lower:
            target_weekday = day_idx
            day_found = True
            break
            
    if user_id not in user_states:
        user_states[user_id] = {"last_day": now.weekday(), "last_format": "standard"}
        
    is_another_request = any(word in user_text_lower for word in ["другой", "еще", "другую", "замени", "поменяй"])
    
    if is_another_request:
        if not day_found: target_weekday = user_states[user_id]["last_day"]
        if current_format == "standard": current_format = user_states[user_id]["last_format"]
    else:
        if not day_found: target_weekday = now.weekday()

    user_states[user_id]["last_day"] = target_weekday
    user_states[user_id]["last_format"] = current_format

    days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    target_day_name = days_ru[target_weekday]

    blocks_data = []
    
    if target_weekday == 1: # ВТОРНИК (Кардио)
        gym_dict = {k: v for k, v in EXERCISE_WEIGHTS.items() if v[0] <= 2}
        num_blocks = 3 if current_format != "standard" else 4
        
        # Перемешиваем тренажеры, чтобы они не повторялись в этот день
        today_machines = random.sample(CARDIO_MACHINES, len(CARDIO_MACHINES))
        
        for i in range(1, num_blocks + 1):
            machine = today_machines[i-1]
            ex1 = random.choice(list(gym_dict.keys()))
            group1 = gym_dict[ex1][1]
            valid_second_exercises = [k for k, v in gym_dict.items() if v[1] != group1]
            
            if not valid_second_exercises:
                valid_second_exercises = [k for k in gym_dict.keys() if k != ex1]
                
            ex2 = random.choice(valid_second_exercises)
            
            if current_format == "amrap":
                duration = random.choice([10, 12, 15])
                blocks_data.append(f"**БЛОК {i}**\nAMRAP {duration} МИНУТ:\n- {random.randint(15, 25)} калорий {machine}\n- 15 {ex1}\n- 15 {ex2}\n👉 Отдых 2 минуты между блоками")
            elif current_format == "emom":
                duration = random.choice([12, 15])
                blocks_data.append(f"**БЛОК {i}**\nEMOM {duration} МИНУТ:\n- Мин 1: {random.randint(15, 20)} калорий {machine}\n- Мин 2: 15 {ex1}\n- Мин 3: 15 {ex2}\n👉 Отдых 2 минуты между блоками")
            else:
                blocks_data.append(f"**БЛОК {i}**\n- {random.randint(20, 35)} калорий {machine}\n2 КРУГА:\n- 15 {ex1}\n- 15 {ex2}\n👉 (Без отдыха)")
            
    else: # ПН / ЧТ (Сила)
        if week_parity == 0:
            focus_groups = ["lower_push", "lower_pull", "core"] if target_weekday == 0 else ["upper_push", "upper_pull", "total"]
        else:
            focus_groups = ["upper_push", "upper_pull", "total"] if target_weekday == 0 else ["lower_push", "lower_pull", "core"]
            
        power_pool = [k for k, v in EXERCISE_WEIGHTS.items() if v[0] >= 3 and v[1] in focus_groups]
        
        if len(power_pool) < 4:
            power_pool = [k for k, v in EXERCISE_WEIGHTS.items() if v[0] >= 3]

        for i in range(1, 4 if current_format != "standard" else 5):
            ex1, ex2 = random.sample(power_pool, 2)
            w1, w2 = EXERCISE_WEIGHTS[ex1][0], EXERCISE_WEIGHTS[ex2][0]
            total_score = w1 + w2
            
            rep1 = 8 if w1 == 5 else 12
            rep2 = 8 if w2 == 5 else 12
            
            if current_format == "amrap":
                duration = random.choice([8, 10, 12])
                blocks_data.append(f"**БЛОК {i}**\nAMRAP {duration} МИНУТ:\n- {rep1} {ex1}\n- {rep2} {ex2}\n👉 Отдых 2 минуты между блоками")
            elif current_format == "emom":
                duration = random.choice([10, 12, 14])
                blocks_data.append(f"**БЛОК {i}**\nEMOM {duration} МИНУТ:\n- Нечетная мин: {rep1} {ex1}\n- Четная мин: {rep2} {ex2}\n👉 Отдых 2 минуты между блоками")
            else:
                rest = get_rest_time(total_score)
                blocks_data.append(f"**БЛОК {i}**\n3 КРУГА:\n- {rep1} {ex1}\n- {rep2} {ex2}\n👉 {rest}")

    # --- ВОТ ЭТА СТРОКА ПОТЕРЯЛАСЬ В ПРОШЛЫЙ РАЗ ---
    raw_workout_text = "\n\n".join(blocks_data)

    system_prompt = f"""Ты — элитный методист CrossFit. Сегодня {target_day_name}.
Твоя задача — ТОЛЬКО КРАСИВО ОФОРМИТЬ предоставленный черновик тренировки.

КРИТИЧЕСКИЕ ПРАВИЛА (НАРУШАТЬ НЕЛЬЗЯ):
1. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать разминку (warm up).
2. ЗАПРЕЩЕНО придумывать свои упражнения, менять цифры, минуты, калории или количество кругов.
3. НЕ ПИШИ вводные слова. Сразу начинай с "**БЛОК 1**".
4. СТРОГО КОПИРУЙ ЗАГОЛОВКИ ИЗ ЧЕРНОВИКА. Если там написано "AMRAP 12 МИНУТ" или "3 КРУГА" — пиши так же. НИКОГДА не пиши букву "X" вместо цифр!
5. ОБЯЗАТЕЛЬНО сохраняй строку с инструкцией по отдыху (например, "👉 Отдых 1 минута" или "👉 Отдых 2 минуты между блоками") в конце каждого блока!
"""

    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Оформи этот черновик:\n\n{raw_workout_text}"}
            ],
            temperature=0.1
        )
        ai_response = response.choices[0].message.content.strip()

        # Validate that all exercises in the response exist in EXERCISE_WEIGHTS
        import re

        # Extract all exercise names from raw_workout_text
        raw_exercises = set()
        for exercise in EXERCISE_WEIGHTS.keys():
            # Check if exercise is in raw_workout_text
            if exercise.lower() in raw_workout_text.lower():
                raw_exercises.add(exercise.lower())
                # Also add the English part only
                english_part = exercise.split(" / ")[0].lower()
                raw_exercises.add(english_part)

        # Extract exercise names from AI response
        # Pattern to match exercise names after numbers (e.g., "- 15 Exercise Name")
        exercise_pattern = r'-\s*\d+\s+([^\n]+)'
        found_exercises = re.findall(exercise_pattern, ai_response)

        invalid_found = False
        for found_exercise in found_exercises:
            found_exercise = found_exercise.strip().lower()
            # Check if this exercise exists in our raw workout
            exercise_exists = False
            for raw_ex in raw_exercises:
                if raw_ex in found_exercise or found_exercise in raw_ex:
                    exercise_exists = True
                    break

            if not exercise_exists:
                print(f"Warning: Invalid exercise found in AI response: {found_exercise}")
                invalid_found = True

        # If invalid exercises found, return raw_workout_text instead
        if invalid_found:
            print("AI generated invalid exercises, using raw workout instead")
            return raw_workout_text

        return ai_response
    except Exception as e:
        print(f"Error calling API: {e}")
        return raw_workout_text 

# --- 4. ЛОГИКА TELEGRAM ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_msg = update.message.text
    
    warm_up_fixed = (
        "🔥 РАЗМИНКА (WARM UP) — 2 КРУГА:\n"
        "- 10 Deadlift\n"
        "- 8 Front Squat\n"
        "- 5 Push Press\n"
        "- 20 V-ups\n"
        "- 7 Push-up\n"
        "- 3 Pull-up\n"
        "--------------------------------\n\n"
    )
    
    status_msg = await update.message.reply_text("⚖️ Алгоритм компилирует программу...")
    
    ai_reply = await generate_ai_response(user_id, user_msg)
    
    try:
        await status_msg.delete()
    except:
        pass
        
    final_text = warm_up_fixed + ai_reply
    
    await update.message.reply_text(final_text)

def main():
    print("--- БОТ-МЕТОДИСТ ЗАПУЩЕН ---")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Use webhook for cloud deployment, fallback to polling for local development
    webhook_url = os.getenv("WEBHOOK_URL")
    port = int(os.getenv("PORT", 8443))

    if webhook_url:
        print(f"Starting with webhook: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TELEGRAM_TOKEN,
            webhook_url=f"{webhook_url}/{TELEGRAM_TOKEN}"
        )
    else:
        print("Starting with polling (local development)")
        # Fix for Python 3.14 compatibility
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            app.run_polling(drop_pending_updates=True)
        except RuntimeError:
            # Fallback for older Python versions
            app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()