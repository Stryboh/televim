import asyncio
import curses
import glob
import os
import textwrap
from curses import textpad

from telethon import TelegramClient
from wcwidth import wcswidth

import credentials

client = TelegramClient(credentials.name(), credentials.key(), credentials.hash())

try:
    client.start()
finally:
    client.disconnect()


# --- Функции для работы с дисплейной шириной строк (учитывают эмодзи и широкие символы) ---
def slice_by_width(text, max_width):
    """Обрезает строку так, чтобы её дисплейная ширина не превышала max_width."""
    current_width = 0
    result = ""
    for ch in text:
        ch_width = wcswidth(ch)
        if current_width + ch_width > max_width:
            break
        result += ch
        current_width += ch_width
    return result


def pad_to_width(text, width):
    """Дополняет строку пробелами, чтобы её дисплейная ширина стала равна width."""
    current_width = wcswidth(text)
    if current_width < width:
        return text + " " * (width - current_width)
    return text


def draw_msg_border(stdscr, top, left, height, width):
    try:
        textpad.rectangle(stdscr, top - 1, left - 1, top + height, left + width)
    except curses.error:
        pass


# --- Отрисовка списка чатов (левое окно) с учетом смещения ---
def draw_chat_window(win, chat_list, selected, offset, width, height):
    win.erase()
    for i in range(height):
        index = i + offset
        if index >= len(chat_list):
            break
        title = chat_list[index].title if chat_list[index].title else "No Title"
        # Обрезаем и дополняем строку с учетом дисплейной ширины
        line = pad_to_width(slice_by_width(title, width), width)
        try:
            if index == selected:
                # Выделяем выбранную строку через передачу атрибута напрямую
                win.addstr(i, 0, line, curses.A_REVERSE)
            else:
                win.addstr(i, 0, line)
        except curses.error:
            pass
    win.noutrefresh()


# --- Асинхронная загрузка сообщений ---
async def fetch_messages(client, dialog, limit=50):
    messages = await client.get_messages(dialog.entity, limit=limit)
    messages.reverse()
    return messages


# --- Подготовка блоков сообщений для отображения ---
async def prepare_message_blocks(messages, max_width, client):
    blocks = []
    for msg in messages:
        # Определяем имя отправителя
        try:
            sender = msg.sender.first_name if (msg.sender and hasattr(msg.sender, 'first_name')) else "Unknown"
        except Exception:
            sender = "Unknown"

        # Текст сообщения (если отсутствует – пустая строка)
        text = msg.text if msg.text else ""
        if msg.photo:
            path = await client.download_media(msg.media, f"downloads/{msg.id}.jpg")
            path = "file://" + os.getcwd() + "/downloads/" + path[10:]
            text += path

        # Оборачиваем текст по (max_width-2) символов (учитывая боковые границы)
        wrapped = []
        for paragraph in text.splitlines():
            wrapped.extend(textwrap.wrap(paragraph, width=max_width - 2) or [""])
        if not wrapped:
            wrapped = [""]

        # Определяем дисплейную ширину рамки – максимальная ширина обернутых строк
        border_width = max((wcswidth(line) for line in wrapped), default=0)
        if border_width <= 0:
            border_width = max_width - 2

        block = []
        sender_line = pad_to_width(slice_by_width(sender, max_width), max_width)
        block.append(sender_line)
        top_border = "+" + "-" * border_width + "+"
        block.append(top_border)

        for line in wrapped:
            line_display_width = wcswidth(line)
            padding = border_width - line_display_width
            block.append("|" + line + " " * padding + "|")

        block.append(top_border)
        blocks.append(block)
        blocks.append('\n')
    return blocks


# --- Отрисовка блоков сообщений (правое окно) ---
def draw_message_blocks(win, blocks, block_index, width, height):
    win.erase()
    y = 0
    # Выводим блоки начиная с block_index до тех пор, пока есть место в окне
    for i in range(block_index, len(blocks)):
        block = blocks[i]
        if isinstance(block, list):
            block_height = len(block)
            if y + block_height > height:
                break
            for line in block:
                try:
                    display_line = pad_to_width(slice_by_width(line, width), width)
                    win.addstr(y, 0, display_line)
                except curses.error:
                    pass
                y += 1
        else:
            if y < height:
                try:
                    win.addstr(y, 0, "")
                except curses.error:
                    pass
            y += 1
    win.noutrefresh()


# --- Вычисление начального индекса блоков для вывода сообщений так,
# чтобы при открытии чата в окне сообщений сразу отображалась нижняя (новейшая) часть ---
def calc_block_index(blocks, win_height):
    total_lines = 0
    for block in blocks:
        if isinstance(block, list):
            total_lines += len(block)
        else:
            total_lines += 1
    if total_lines <= win_height:
        return 0
    lines_to_skip = total_lines - win_height
    current_skip = 0
    for i, block in enumerate(blocks):
        block_height = len(block) if isinstance(block, list) else 1
        if current_skip + block_height > lines_to_skip:
            return i
        current_skip += block_height
    return 0


# --- Основной цикл приложения ---
async def main_loop(stdscr, client, chat_list):
    curses.curs_set(0)
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    chat_win_width = int(width * 0.3)
    msg_win_width = width - chat_win_width - 2
    chat_win_height = height
    msg_win_height = height - 2

    chat_win = curses.newwin(chat_win_height, chat_win_width, 0, 0)
    msg_win = curses.newwin(msg_win_height, msg_win_width, 2, chat_win_width + 1)

    focus = "chat"
    selected_chat = 0
    chat_offset = 0
    block_index = 0
    messages = []
    message_blocks = []

    while True:
        if selected_chat < chat_offset:
            chat_offset = selected_chat
        elif selected_chat >= chat_offset + chat_win_height:
            chat_offset = selected_chat - chat_win_height + 1

        draw_chat_window(chat_win, chat_list, selected_chat, chat_offset, chat_win_width, chat_win_height)

        if focus == "msg" and message_blocks:
            sender_name = chat_list[selected_chat].title if chat_list[selected_chat].title else "No Name"
            display_sender = pad_to_width(slice_by_width(sender_name, msg_win_width), msg_win_width)
            draw_message_blocks(msg_win, message_blocks, block_index, msg_win_width, msg_win_height)
            draw_msg_border(stdscr, 2, chat_win_width + 1, msg_win_height, msg_win_width)
            try:
                stdscr.addstr(0, chat_win_width + 1, display_sender)
            except curses.error:
                pass
        else:
            msg_win.erase()
            msg_win.noutrefresh()
            draw_msg_border(stdscr, 2, chat_win_width + 1, msg_win_height, msg_win_width)
            try:
                stdscr.addstr(0, chat_win_width + 1, pad_to_width("No messages", msg_win_width))
            except curses.error:
                pass

        stdscr.noutrefresh()
        curses.doupdate()

        key = stdscr.getch()
        if focus == "chat":
            if key in (ord('j'), curses.KEY_DOWN):
                if selected_chat < len(chat_list) - 1:
                    selected_chat += 1
            elif key in (ord('k'), curses.KEY_UP):
                if selected_chat > 0:
                    selected_chat -= 1
            elif key in (ord('l'), 10, 13):
                # Асинхронная загрузка сообщений
                messages = await fetch_messages(client, chat_list[selected_chat], limit=50)
                message_blocks = await prepare_message_blocks(messages, msg_win_width, client)
                block_index = calc_block_index(message_blocks, msg_win_height)
                focus = "msg"
            elif key in (ord('q'), 27):
                break
        elif focus == "msg":
            if key in (ord('j'), curses.KEY_DOWN):
                if block_index < len(message_blocks) - 1:
                    block_index += 1
            elif key in (ord('k'), curses.KEY_UP):
                if block_index > 0:
                    block_index -= 1
            elif key in (ord('h'), ord('q'), 27):
                focus = "chat"


# --- Точка входа ---
def main(stdscr):
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    curses.curs_set(0)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(client.connect())
    chat_list = loop.run_until_complete(client.get_dialogs())
    loop.run_until_complete(main_loop(stdscr, client, chat_list))
    try:
        loop.run_until_complete(client.disconnect())
    except:
        pass

    f = os.getcwd() + "/downloads/*"
    files = glob.glob(f'{f}')
    for file in files:
        os.remove(file)


if __name__ == "__main__":
    if os.path.exists(f'{credentials.name()}.session'):
        curses.wrapper(main)
