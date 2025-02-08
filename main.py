
import curses
import glob
import os
import textwrap
import asyncio
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
        stdscr.attron(curses.color_pair(1))
        textpad.rectangle(stdscr, top - 1, left - 1, top + height, left + width)
        stdscr.attroff(curses.color_pair(1))
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
                win.addstr(i, 0, line, curses.A_REVERSE)
            else:
                win.addstr(i, 0, line)
        except curses.error:
            pass
    win.noutrefresh()


# --- Асинхронная загрузка сообщений ---
async def fetch_messages(client, dialog, limit=50, offset_id=0):
    messages = await client.get_messages(dialog.entity, limit=limit, offset_id=offset_id)
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

        # Формирование блока сообщения.
        # Если сообщение исходящее (ваше), выравниваем его вправо.
        if getattr(msg, 'out', False):
            block_width = border_width + 2  # учитываем рамку с обеих сторон
            left_padding = max_width - block_width if max_width > block_width else 0

            block = []
            sender_line = pad_to_width(slice_by_width(sender, block_width), block_width)
            sender_line = " " * left_padding + sender_line
            block.append(sender_line)

            top_border = "╭" + "─" * border_width + "╮"
            top_border = " " * left_padding + top_border
            block.append(top_border)

            for line in wrapped:
                line_display_width = wcswidth(line)
                padding = border_width - line_display_width
                content_line = "│" + line + " " * padding + "│"
                content_line = " " * left_padding + content_line
                block.append(content_line)

            bot_border = "╰" + "─" * border_width + "╯"
            bot_border = " " * left_padding + bot_border
            block.append(bot_border)
        else:
            # Сообщение от собеседника: выравниваем слева
            block = []
            sender_line = pad_to_width(slice_by_width(sender, max_width), max_width)
            block.append(sender_line)

            top_border = "╭" + "─" * border_width + "╮"
            block.append(top_border)

            for line in wrapped:
                line_display_width = wcswidth(line)
                padding = border_width - line_display_width
                block.append("│" + line + " " * padding + "│")

            bot_border = "╰" + "─" * border_width + "╯"
            block.append(bot_border)

        blocks.append(block)
        blocks.append('\n')  # разделитель между сообщениями
    return blocks


# --- Функция для преобразования списка блоков в список строк ---
def flatten_blocks(blocks):
    lines = []
    for block in blocks:
        if isinstance(block, list):
            lines.extend(block)
        else:
            # Если не список (например, разделитель), считаем как пустую строку
            lines.append("")
    return lines


# --- Отрисовка сообщений построчно (с использованием line_offset) ---
def draw_message_lines(win, lines, line_offset, width, height):
    win.erase()
    for i in range(height):
        if line_offset + i < len(lines):
            line = lines[line_offset + i]
            display_line = pad_to_width(slice_by_width(line, width), width)
            try:
                win.addstr(i, 0, display_line)
            except curses.error:
                pass
        else:
            break
    win.noutrefresh()


# --- Функция для ввода сообщения (всплывающее окно) с сузенной текстовой областью и голубой рамкой ---
def message_input_window(stdscr, win_width, win_height):
    # Определяем позицию окна по центру экрана
    start_y = (curses.LINES - win_height) // 2
    start_x = (curses.COLS - win_width) // 2
    win = curses.newwin(win_height, win_width, start_y, start_x)
    win.keypad(True)
    # Отрисовываем рамку голубым цветом (цветовая пара 1)
    win.attron(curses.color_pair(1))
    win.border()
    win.attroff(curses.color_pair(1))
    prompt = "Input>"
    try:
        win.addstr(0, 2, prompt)
    except curses.error:
        pass
    win.refresh()

    # Буфер для ввода (список строк)
    buffer = [""]
    # Сужаем отступы: текстовая область начинается с col=2 и заканчивается на win_width-3
    cur_y = 1
    cur_x = 2
    win.move(cur_y, cur_x)

    while True:
        try:
            ch = win.get_wch()  # Используем get_wch для поддержки Unicode (например, кириллицы)
        except curses.error:
            continue

        if isinstance(ch, str):
            # Отмена ввода (Esc)
            if ch == '\x1b':
                return None
            # Завершение ввода (Enter) — отправка сообщения
            elif ch in ('\n', '\r'):
                return "\n".join(buffer)
            else:
                # Добавляем символ в текущую строку
                buffer[cur_y - 1] += ch
                try:
                    win.addstr(cur_y, cur_x, ch)
                except curses.error:
                    pass
                cur_x += 1
                if cur_x >= win_width - 2:  # правый предел с учетом сузенной области
                    if cur_y < win_height - 2:
                        cur_y += 1
                        cur_x = 2
                        buffer.append("")
                    else:
                        cur_x = win_width - 3
                win.move(cur_y, cur_x)
        elif isinstance(ch, int):
            # Обработка Shift+Enter (предполагаем, что возвращается curses.KEY_ENTER)
            if ch == curses.KEY_ENTER:
                buffer.append("")
                cur_y += 1
                cur_x = 2
                if cur_y >= win_height - 1:
                    cur_y = win_height - 2
                win.move(cur_y, cur_x)
                continue
            # Обработка Backspace
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                if cur_x > 2 or cur_y > 1:
                    if cur_x > 2:
                        buffer[cur_y - 1] = buffer[cur_y - 1][:-1]
                        cur_x -= 1
                    else:
                        prev_line = buffer[cur_y - 2]
                        buffer[cur_y - 2] = prev_line + buffer[cur_y - 1]
                        del buffer[cur_y - 1]
                        cur_y -= 1
                        cur_x = len(buffer[cur_y - 1]) + 2
                    # Перерисовываем текущую строку в области ввода, не затрагивая правую границу
                    win.move(cur_y, 2)
                    clear_length = win_width - 4  # число символов для очистки в текстовой области
                    win.addstr(" " * clear_length)
                    win.move(cur_y, 2)
                    try:
                        win.addstr(buffer[cur_y - 1])
                    except curses.error:
                        pass
                    win.move(cur_y, cur_x)
                continue
            else:
                continue


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

    # Для сообщений используем "line_offset" – сколько строк пропущено от начала списка
    messages = []
    message_blocks = []
    flat_lines = []
    line_offset = 0

    while True:
        # Обновляем окно чатов
        if selected_chat < chat_offset:
            chat_offset = selected_chat
        elif selected_chat >= chat_offset + chat_win_height:
            chat_offset = selected_chat - chat_win_height + 1

        draw_chat_window(chat_win, chat_list, selected_chat, chat_offset, chat_win_width, chat_win_height)

        if focus == "msg" and flat_lines:
            sender_name = chat_list[selected_chat].title if chat_list[selected_chat].title else "No Name"
            display_sender = pad_to_width(slice_by_width(sender_name, msg_win_width), msg_win_width)
            draw_message_lines(msg_win, flat_lines, line_offset, msg_win_width, msg_win_height)
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
                # При выборе чата загружаем первые 50 сообщений и подготавливаем отображение
                messages = await fetch_messages(client, chat_list[selected_chat], limit=50)
                message_blocks = await prepare_message_blocks(messages, msg_win_width, client)
                flat_lines = flatten_blocks(message_blocks)
                if len(flat_lines) > msg_win_height:
                    line_offset = len(flat_lines) - msg_win_height
                else:
                    line_offset = 0
                focus = "msg"
            elif key in (ord('q'), 27):
                break

        elif focus == "msg":
            # Возможность отправки сообщения: клавиша i
            if key == ord('i'):
                # Открываем окно ввода (размер окна: 7 строк, ширина: msg_win_width-4)
                input_text = message_input_window(stdscr, msg_win_width - 4, 7)
                if input_text is not None and input_text.strip() != "":
                    # Отправляем сообщение
                    sent_msg = await client.send_message(chat_list[selected_chat].entity, input_text)
                    # Добавляем отправленное сообщение в историю (новое сообщение будет выравнено вправо)
                    new_block = await prepare_message_blocks([sent_msg], msg_win_width, client)
                    new_flat_lines = flatten_blocks(new_block)
                    flat_lines.extend(new_flat_lines)
                    total_lines = len(flat_lines)
                    if total_lines > msg_win_height:
                        line_offset = total_lines - msg_win_height
                    else:
                        line_offset = 0
                continue

            total_lines = len(flat_lines)
            if key in (ord('j'), curses.KEY_DOWN):
                if line_offset < total_lines - msg_win_height:
                    line_offset += 1
            elif key in (ord('k'), curses.KEY_UP):
                if line_offset > 0:
                    line_offset -= 1
                else:
                    if messages:
                        oldest_message_id = messages[0].id
                        older_messages = await fetch_messages(client, chat_list[selected_chat], limit=50, offset_id=oldest_message_id)
                        if older_messages:
                            new_blocks = await prepare_message_blocks(older_messages, msg_win_width, client)
                            new_flat_lines = flatten_blocks(new_blocks)
                            messages = older_messages + messages
                            message_blocks = new_blocks + message_blocks
                            flat_lines = flatten_blocks(message_blocks)
                            line_offset += len(new_flat_lines)
            elif key in (ord('h'), ord('q'), 27):
                focus = "chat"


# --- Точка входа ---
def main(stdscr):
    curses.start_color()
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
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
    except Exception:
        pass

    # Очистка папки downloads
    downloads_path = os.path.join(os.getcwd(), "downloads", "*")
    files = glob.glob(downloads_path)
    for file in files:
        os.remove(file)


if __name__ == "__main__":
    if os.path.exists(f'{credentials.name()}.session'):
        curses.wrapper(main)
