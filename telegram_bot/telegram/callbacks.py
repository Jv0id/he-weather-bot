from aiogram import types

from telegram_bot.database import crud, models
from telegram_bot.database.database import get_db_session
from telegram_bot.intergration import he_weather
from telegram_bot.service.telegram import TelegramMessageService
from telegram_bot.settings import aio_lru_cache_24h
from telegram_bot.telegram.add_qweather_api_key import update_api_key
from telegram_bot.telegram.dispatcher import dp
from telegram_bot.telegram.keyboard.keyboard_markup_factory import (
    BACK,
    DISABLE_SUB,
    ENABLE_SUB,
    GET_WEATHER,
    HOURS_TEMPLATE,
    REMOVE_LOCATION_PREFIX,
    UPDATE_LOCATION,
    UPDATE_SUB_CRON,
    WELCOME_TEXT,
    KeyboardMarkUpFactory,
    hour_decode,
)
from telegram_bot.telegram.update_location import update_location


def registered(func):
    async def wrapper(message: types.Message):
        chat_id = str(message.chat.id)
        with get_db_session() as db:
            if not crud.is_user_exists(db, chat_id):
                return await update_location(message)
            if not crud.is_user_api_key_exists(db, chat_id):
                return await update_api_key(message)
        await func(message)

    return wrapper


@dp.message_handler(commands=["weather"])
@registered
async def handle_weather(message: types.Message) -> None:
    chat_id = str(message.chat.id)
    with get_db_session() as db:
        locations = crud.get_user_locations(db, chat_id)

    for location in locations:
        text = await he_weather.get_weather_forecast(location)
        await TelegramMessageService.send_text(dp.bot, chat_id, text)


async def do_send_warning_message(chat: models.Chat, text: str):
    await TelegramMessageService.send_text(dp.bot, chat.chat_id, text)
    # 注意：必须返回值，以确保缓存生效
    return True


notify_with_24h_cache = aio_lru_cache_24h(do_send_warning_message)


@dp.message_handler(commands=["warning"])
@registered
async def handle_weather(message: types.Message) -> None:
    chat_id = str(message.chat.id)
    with get_db_session() as db:
        user = crud.get_user(db, chat_id)
        locations = crud.get_user_locations(db, chat_id)

    for location in locations:
        if text := await he_weather.get_weather_warning(location):
            await notify_with_24h_cache(user, text)


@dp.message_handler(commands=["weather_6h"])
@registered
async def handle_weather(message: types.Message) -> None:
    chat_id = str(message.chat.id)
    with get_db_session() as db:
        locations = crud.get_user_locations(db, chat_id)

    for location in locations:
        text = await he_weather.get_weather_6h_forecast_text(location)
        await TelegramMessageService.send_text(dp.bot, chat_id, text)


@dp.message_handler(commands=["id"])
@registered
async def handle_chat_id(message: types.Message) -> None:
    chat_id = message.chat.id
    await TelegramMessageService.send_text(dp.bot, chat_id, chat_id)


@dp.message_handler(commands=["help", "start"])
async def handle_help(message: types.Message) -> None:
    with get_db_session() as db:
        user = crud.get_user(db, message.chat.id)
    reply_markup = KeyboardMarkUpFactory.build_main_menu(user)
    await TelegramMessageService.send_keyboard_markup(
        dp.bot, message.chat.id, WELCOME_TEXT, reply_markup
    )


@dp.message_handler(commands=["subscribe"])
@registered
async def handle_sub(message: types.Message) -> None:
    with get_db_session() as db:
        crud.update_user_status(db, message.chat.id, True)
        await TelegramMessageService.send_text(
            dp.bot, message.chat.id, "已开启定时订阅"
        )

        user = crud.get_user(db, message.chat.id)
        reply_markup = KeyboardMarkUpFactory.build_cron_options(user)
        await TelegramMessageService.send_keyboard_markup(
            dp.bot, message.chat.id, WELCOME_TEXT, reply_markup
        )


@dp.message_handler(commands=["unsubscribe"])
@registered
async def handle_unsub(message: types.Message) -> None:
    with get_db_session() as db:
        crud.update_user_status(db, message.chat.id, False)
    await TelegramMessageService.send_text(dp.bot, message.chat.id, "已关闭定时订阅")


@dp.callback_query_handler(text=GET_WEATHER)
async def weather_callback_handler(query: types.CallbackQuery):
    await handle_weather(query.message)
    await query.answer("")


@dp.callback_query_handler(text=UPDATE_LOCATION)
async def location_callback_handler(query: types.CallbackQuery):
    await update_location(query.message)
    await query.answer("")


@dp.callback_query_handler(text=ENABLE_SUB)
@dp.callback_query_handler(text=DISABLE_SUB)
async def update_subscription_callback_handler(query: types.CallbackQuery):
    is_enable = query.data == ENABLE_SUB
    with get_db_session() as db:
        crud.update_user_status(db, query.message.chat.id, is_enable)
        text = "已开启订阅" if is_enable else "已关闭订阅"
        user = crud.get_user(db, query.message.chat.id)
        await query.answer(text)
        await query.message.edit_reply_markup(
            KeyboardMarkUpFactory.build_cron_options(user)
        )


@dp.callback_query_handler(text=UPDATE_SUB_CRON)
async def sub_cron_callback_handler(query: types.CallbackQuery):
    with get_db_session() as db:
        chat_id = str(query.message.chat.id)
        user = crud.get_user(db, chat_id)
        await query.message.edit_reply_markup(
            KeyboardMarkUpFactory.build_cron_options(user)
        )
        await query.answer("")


@dp.callback_query_handler(text=BACK)
async def exit_callback_handler(query: types.CallbackQuery):
    with get_db_session() as db:
        user = crud.get_user(db, query.message.chat.id)
        await query.message.edit_reply_markup(
            KeyboardMarkUpFactory.build_main_menu(user)
        )
        await query.answer("")


@dp.callback_query_handler(lambda callback_query: callback_query.data in HOURS_TEMPLATE)
async def sub_cron_update_callback_handler(query: types.CallbackQuery):
    hour = hour_decode(query.data)
    chat_id = query.message.chat.id

    with get_db_session() as db:
        if not crud.is_user_api_key_exists(db, chat_id):
            return await update_api_key(query.message)

        # 激活用户
        crud.update_user_status(db, query.message.chat.id, True)
        user = crud.get_user(db, query.message.chat.id)

        # 新增/删除订阅
        cron_job, created = crud.create_or_delete_cron_job(db, chat_id, hour)
        if created:
            await query.answer("订阅成功")
        else:
            await query.answer("已取消")

        db.refresh(user)
        cron_sub_menu = KeyboardMarkUpFactory.build_cron_options(user)
        await query.message.edit_reply_markup(cron_sub_menu)


@dp.message_handler(commands=["delete_sub_locations"])
async def remove_ding_token(message: types.Message) -> None:
    chat_id = str(message.chat.id)
    with get_db_session() as db:
        locations = crud.filter_locations(db, chat_id)
    if not locations:
        await message.reply("不存在其他子位置")
        return

    mark_up = KeyboardMarkUpFactory.build_sub_locations(locations)
    await TelegramMessageService.send_keyboard_markup(
        dp.bot, chat_id, "单击城市删除👇", mark_up
    )


@dp.callback_query_handler(
    lambda callback_query: REMOVE_LOCATION_PREFIX in callback_query.data
)
async def delete_sub_location_update_callback_handler(query: types.CallbackQuery):
    location_id = query.data.replace(REMOVE_LOCATION_PREFIX, "")
    chat_id = str(query.message.chat.id)

    with get_db_session() as db:
        deleted = crud.remove_sub_location(db, location_id)
        if not deleted:
            return

        await query.answer("删除成功")

        locations = crud.filter_locations(db, chat_id)
        cron_sub_menu = KeyboardMarkUpFactory.build_sub_locations(locations)
        await query.message.edit_reply_markup(cron_sub_menu)
