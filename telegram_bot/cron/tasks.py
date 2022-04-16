from telegram_bot.database import models
from telegram_bot.intergration import he_weather
from telegram_bot.service.dingtalk import DingBotMessageService
from telegram_bot.service.telegram import TelegramMessageService
from telegram_bot.settings import aio_lru_cache_1h, aio_lru_cache_24h
from telegram_bot.telegram.dispatcher import dp


async def _do_send_weather_message(chat: models.Chat, ding_bot: models.DingBots, text: str):
    await TelegramMessageService.send_text(dp.bot, chat.chat_id, text)
    if ding_bot:
        await DingBotMessageService.send_text(ding_bot.token, text)
    # 注意：必须返回值，以确保缓存生效
    return True


@aio_lru_cache_1h
async def cron_send_weather(chat: models.Chat, ding_bot: models.DingBots):
    """ 定时发送天气预报 """
    text = await he_weather.get_weather_forecast(chat.location)
    cached_notify = aio_lru_cache_1h(_do_send_weather_message)
    await cached_notify(chat, ding_bot, text)


@aio_lru_cache_1h
async def cron_send_warning(chat: models.Chat, ding_bot: models.DingBots):
    """ 定时发送天气预警信息 """
    if warnModel := await he_weather.get_weather_warning(chat.location):
        # 预警信息可能持续超过 1h，故新增幂等操作
        # 如果 24h 内有新增预警信息，不影响发送
        cached_notify = aio_lru_cache_24h(_do_send_weather_message)
        await cached_notify(chat, ding_bot, str(warnModel))