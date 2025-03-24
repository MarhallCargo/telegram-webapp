# utils.py
from aiogram import Bot
from config import TELEGRAM_BOT_TOKEN, MANAGER_CHAT_ID
from math import ceil

bot = Bot(token=TELEGRAM_BOT_TOKEN)

async def notify_manager(text: str):
    # Отправляем сообщение менеджеру
    await bot.send_message(chat_id=MANAGER_CHAT_ID, text=text)

def calculate_rub_by_yuan(cny_amount: int, base_cny_rate: float = 12.8):
    """
    Расчет рублевой суммы по введенному количеству юаней с учетом комиссии.
    Возвращает округленную сумму в рублях, итоговый курс и процент комиссии.
    """
    thresholds = [
        (30000, 3.5),
        (10000, 4),
        (2500, 5),
        (350, 8)
    ]

    for threshold, commission in thresholds:
        if cny_amount >= threshold:
            rate_with_commission = base_cny_rate * (1 + commission / 100)
            rub_amount = cny_amount * rate_with_commission
            return ceil(rub_amount), round(rate_with_commission, 2), commission

    return 0, 0, 0
