import curses
import textwrap
from curses import textpad
from wcwidth import wcswidth
import os
import asyncio
import time

class TelegramView:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.setup_colors()
        self.setup_screen()

        self.height, self.width = self.stdscr.getmaxyx()
        self.chat_win_width = int(self.width * 0.3)
        self.msg_win_width = self.width - self.chat_win_width - 2
        self.chat_win_height = self.height
        self.msg_win_height = self.height - 2

        self.chat_win = curses.newwin(self.chat_win_height, self.chat_win_width, 0, 0)
        self.msg_win = curses.newwin(self.msg_win_height, self.msg_win_width, 2, self.chat_win_width + 1)

        self.progress_win = None
        self.is_showing_progress = False

    def setup_colors(self):
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)  # Borders
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK) # Selected message
        curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Downloaded file
        curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)    # Not downloaded
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE)   # Date separator

    def setup_screen(self):
        curses.noecho()
        curses.cbreak()
        self.stdscr.keypad(True)
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.erase()

    def draw_chat_window(self, chat_list, selected, offset):
        self.chat_win.erase()
        for i in range(self.chat_win_height):
            index = i + offset
            if index >= len(chat_list):
                break
            title = chat_list[index].title if chat_list[index].title else "No Title"
            
            # Вычисляем общую длину строки
            line = self.pad_to_width(self.slice_by_width(title, self.chat_win_width), self.chat_win_width)
            
            # Добавляем метку непрочитанных сообщений
            if hasattr(chat_list[index], 'unread_count') and chat_list[index].unread_count and chat_list[index].unread_count > 0:
                line = line[:-1] + '+'
                
            try:
                if index == selected:
                    self.chat_win.addstr(i, 0, line, curses.A_REVERSE)
                else:
                    self.chat_win.addstr(i, 0, line)
            except curses.error:
                pass
        self.chat_win.noutrefresh()

    def draw_message_lines(self, lines_with_style, line_offset, message_map=None):
        self.msg_win.erase()
        lines, _ = lines_with_style if isinstance(lines_with_style, tuple) else (lines_with_style, {})

        max_lines = min(self.msg_win_height, len(lines) - line_offset)
        if line_offset + max_lines > len(lines):
            max_lines = len(lines) - line_offset

        selected_msg_id = None
        message_start = None
        message_end = None

        for i in range(max_lines):
            current_line = line_offset + i
            if current_line >= len(lines):
                break

            line = lines[current_line]

            if isinstance(line, tuple) and len(line) == 3 and line[2] == "date_separator":
                text, _ = line[:2]
                text_len = len(text)
                padding = (self.msg_win_width - text_len) // 2
                try:
                    self.msg_win.addstr(i, padding, text, curses.color_pair(5))
                except curses.error:
                    pass
                continue

            if isinstance(line, tuple):
                text, border_style = line[:2]
                color_ranges = line[2] if len(line) >= 3 else []
            else:
                text, border_style, color_ranges = line, 1, []

            display_line = self.pad_to_width(self.slice_by_width(text, self.msg_win_width), self.msg_win_width)
            current_pos = 0

            if color_ranges:
                for start, end, color in color_ranges:
                    if current_pos < start:
                        segment = display_line[current_pos:start]
                        self._add_str_with_border(i, current_pos, segment, border_style)
                        current_pos += len(segment)
                    segment = display_line[start:end]
                    try:
                        self.msg_win.addstr(i, current_pos, segment, curses.color_pair(color))
                    except curses.error:
                        pass
                    current_pos += len(segment)
                segment = display_line[current_pos:]
                self._add_str_with_border(i, current_pos, segment, border_style)
            else:
                self._add_str_with_border(i, 0, display_line, border_style)

        self.msg_win.noutrefresh()

    def _add_str_with_border(self, y, x, text, border_style):
        for j, ch in enumerate(text):
            try:
                if ch in ['╭', '╮', '╰', '╯', '─', '│']:
                    self.msg_win.addstr(y, x + j, ch, curses.color_pair(border_style))
                else:
                    self.msg_win.addstr(y, x + j, ch)
            except curses.error:
                pass

    def draw_msg_border(self):
        try:
            self.stdscr.attron(curses.color_pair(1))
            textpad.rectangle(self.stdscr, 1, self.chat_win_width, self.msg_win_height + 2, self.chat_win_width + self.msg_win_width + 1)
            self.stdscr.attroff(curses.color_pair(1))
        except curses.error:
            pass

    def set_dialog_title(self, title):
        """Отображает заголовок чата"""
        try:
            # Очищаем заголовок
            self.stdscr.move(0, self.chat_win_width + 1)
            self.stdscr.clrtoeol()
            
            # Отображаем заголовок
            title_to_show = self.slice_by_width(title, self.msg_win_width)
            self.stdscr.addstr(0, self.chat_win_width + 1, title_to_show)
            
            self.stdscr.refresh()
        except curses.error:
            pass  # Игнорируем ошибки curses (защита от выхода за границы)

    def message_input_window(self):
        win_width = self.msg_win_width - 4
        win_height = 7
        start_y = (curses.LINES - win_height) // 2
        start_x = (curses.COLS - win_width) // 2
        win = curses.newwin(win_height, win_width, start_y, start_x)
        win.keypad(True)
        win.attron(curses.color_pair(1))
        win.border()
        win.attroff(curses.color_pair(1))
        prompt = "Input> (Alt+Enter для отправки)"
        try:
            win.addstr(0, 2, prompt)
        except curses.error:
            pass

        old_cursor = curses.curs_set(1)
        buffer = [""]
        cur_y = 1
        cur_x = 2
        win.move(cur_y, cur_x)
        win.refresh()

        view_y_offset = 0
        max_view_lines = win_height - 2

        alt_pressed = False

        while True:
            try:
                ch = win.get_wch()
            except curses.error:
                continue

            if isinstance(ch, str):
                if ch == '\x1b':
                    try:
                        win.nodelay(True)
                        next_ch = win.get_wch()
                        if next_ch == '\n' or next_ch == 10 or next_ch == 13:
                            win.nodelay(False)
                            curses.curs_set(old_cursor)
                            return "\n".join(buffer)
                        win.nodelay(False)
                    except:
                        win.nodelay(False)
                        curses.curs_set(old_cursor)
                        return None

                elif ch == '\n':
                    if cur_y - 1 >= len(buffer) - 1:
                        buffer.append("")
                    else:
                        remainder = buffer[cur_y - 1][cur_x-2:]
                        buffer[cur_y - 1] = buffer[cur_y - 1][:cur_x-2]
                        buffer.insert(cur_y, remainder)

                    cur_y += 1
                    cur_x = 2

                    if cur_y - view_y_offset > max_view_lines:
                        view_y_offset += 1

                    self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)
                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()
                else:
                    buffer[cur_y - 1] = buffer[cur_y - 1][:cur_x-2] + ch + buffer[cur_y - 1][cur_x-2:]
                    self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)

                    cur_x += 1
                    if cur_x >= win_width - 2:
                        if cur_y - view_y_offset < max_view_lines:
                            cur_y += 1
                            if cur_y - 1 >= len(buffer):
                                buffer.append("")
                        else:
                            view_y_offset += 1
                            cur_y += 1
                            if cur_y - 1 >= len(buffer):
                                buffer.append("")
                        cur_x = 2
                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()

            elif isinstance(ch, int):
                if ch == 10 or ch == curses.KEY_ENTER:
                    if cur_y - 1 >= len(buffer) - 1:
                        buffer.append("")
                    else:
                        remainder = buffer[cur_y - 1][cur_x-2:]
                        buffer[cur_y - 1] = buffer[cur_y - 1][:cur_x-2]
                        buffer.insert(cur_y, remainder)

                    cur_y += 1
                    cur_x = 2

                    if cur_y - view_y_offset > max_view_lines:
                        view_y_offset += 1

                    self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)
                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()
                    continue
                elif ch == 27:
                    win.nodelay(True)
                    try:
                        next_ch = win.getch()
                        if next_ch == 10 or next_ch == 13:
                            win.nodelay(False)
                            curses.curs_set(old_cursor)
                            return "\n".join(buffer)
                    except:
                        win.nodelay(False)
                        curses.curs_set(old_cursor)
                        return None
                    win.nodelay(False)
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    if cur_x > 2:
                        buffer[cur_y - 1] = buffer[cur_y - 1][:cur_x-3] + buffer[cur_y - 1][cur_x-2:]
                        cur_x -= 1
                    elif cur_y > 1:
                        prev_line_len = len(buffer[cur_y - 2])
                        buffer[cur_y - 2] += buffer[cur_y - 1]
                        del buffer[cur_y - 1]
                        cur_y -= 1
                        cur_x = prev_line_len + 2

                        if cur_y <= view_y_offset:
                            view_y_offset = max(0, view_y_offset - 1)

                    self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)
                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()
                    continue

                elif ch == curses.KEY_UP:
                    if cur_y > 1:
                        cur_y -= 1
                        if len(buffer[cur_y - 1]) + 2 < cur_x:
                            cur_x = len(buffer[cur_y - 1]) + 2

                        if cur_y <= view_y_offset:
                            view_y_offset = max(0, cur_y - 1)
                            self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)

                        win.move(cur_y - view_y_offset, cur_x)
                        win.refresh()

                elif ch == curses.KEY_DOWN:
                    if cur_y < len(buffer):
                        cur_y += 1
                        if len(buffer[cur_y - 1]) + 2 < cur_x:
                            cur_x = len(buffer[cur_y - 1]) + 2

                        if cur_y - view_y_offset > max_view_lines:
                            view_y_offset += 1
                            self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)

                        win.move(cur_y - view_y_offset, cur_x)
                        win.refresh()

                elif ch == curses.KEY_LEFT:
                    if cur_x > 2:
                        cur_x -= 1
                    elif cur_y > 1:
                        cur_y -= 1
                        cur_x = len(buffer[cur_y - 1]) + 2

                        if cur_y <= view_y_offset:
                            view_y_offset = max(0, cur_y - 1)
                            self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)

                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()

                elif ch == curses.KEY_RIGHT:
                    if cur_x < len(buffer[cur_y - 1]) + 2:
                        cur_x += 1
                    elif cur_y < len(buffer):
                        cur_y += 1
                        cur_x = 2

                        if cur_y - view_y_offset > max_view_lines:
                            view_y_offset += 1
                            self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)

                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()

                else:
                    continue

    def _redraw_input_buffer(self, win, buffer, view_y_offset, max_view_lines):
        for i in range(1, max_view_lines + 1):
            win.move(i, 2)
            win.clrtoeol()

        for i in range(min(max_view_lines, len(buffer) - view_y_offset)):
            line_idx = i + view_y_offset
            if line_idx < len(buffer):
                try:
                    win.addstr(i + 1, 2, buffer[line_idx][:win.getmaxyx()[1] - 4])
                except curses.error:
                    pass
        win.refresh()

    @staticmethod
    def slice_by_width(text, max_width):
        current_width = 0
        result = ""
        for ch in text:
            ch_width = wcswidth(ch)
            if current_width + ch_width > max_width:
                break
            result += ch
            current_width += ch_width
        return result

    @staticmethod
    def pad_to_width(text, width):
        current_width = wcswidth(text)
        if current_width < width:
            return text + " " * (width - current_width)
        return text

    def get_key(self):
        return self.stdscr.getch()

    def refresh(self):
        self.stdscr.noutrefresh()
        curses.doupdate()

    async def chat_search_window(self, chat_list):
        import curses

        height = min(20, curses.LINES // 2)
        width = curses.COLS - 4

        search_win = curses.newwin(height, width, (curses.LINES - height) // 2, 2)
        search_win.keypad(1)

        input_height = 3
        input_win = curses.newwin(input_height, width, (curses.LINES - height) // 2 + height - input_height, 2)
        input_win.keypad(1)

        buffer = [""]
        filtered_chats = []
        selected_idx = 0

        old_cursor = curses.curs_set(1)

        def update_filtered_chats():
            nonlocal filtered_chats, selected_idx
            search_query = buffer[0]
            if not search_query:
                filtered_chats = [(i, chat) for i, chat in enumerate(chat_list)]
            else:
                query_lower = search_query.lower()
                filtered_chats = [(i, chat) for i, chat in enumerate(chat_list)
                                if query_lower in (chat.title or "").lower()]

            if not filtered_chats:
                selected_idx = 0
            elif selected_idx >= len(filtered_chats):
                selected_idx = len(filtered_chats) - 1

        def draw_search_window():
            search_win.erase()
            search_win.box()
            search_win.addstr(0, 2, "Поиск чатов")

            available_height = height - 2
            start_idx = max(0, selected_idx - available_height // 2)
            end_idx = min(len(filtered_chats), start_idx + available_height)

            for i, (orig_idx, chat) in enumerate(filtered_chats[start_idx:end_idx], 0):
                y = i + 1
                chat_name = chat.title if chat.title else "No Name"
                chat_name = chat_name[:width - 4]

                if start_idx + i == selected_idx:
                    search_win.attron(curses.A_REVERSE)
                    search_win.addstr(y, 1, f" {chat_name} ".ljust(width - 2))
                    search_win.attroff(curses.A_REVERSE)
                else:
                    search_win.addstr(y, 1, f" {chat_name} "[:width - 2])

            search_win.noutrefresh()

        def draw_input_field():
            input_win.erase()
            input_win.box()
            input_win.addstr(1, 1, f" {buffer[0]} ".ljust(width - 2))
            input_win.move(1, len(buffer[0]) + 2)
            input_win.noutrefresh()

        update_filtered_chats()
        draw_search_window()
        draw_input_field()
        curses.doupdate()

        while True:
            try:
                ch = input_win.get_wch()
            except curses.error:
                continue

            if isinstance(ch, str):
                if ch == '\x1b':
                    try:
                        input_win.nodelay(True)
                        next_ch = input_win.get_wch()
                        input_win.nodelay(False)
                    except:
                        curses.curs_set(old_cursor)
                        return None
                elif ch == '\n':
                    if filtered_chats and selected_idx < len(filtered_chats):
                        curses.curs_set(old_cursor)
                        return filtered_chats[selected_idx][0]
                    curses.curs_set(old_cursor)
                    return None
                else:
                    buffer[0] += ch
                    update_filtered_chats()
            elif isinstance(ch, int):
                if ch == 27:
                    curses.curs_set(old_cursor)
                    return None
                elif ch == 10 or ch == curses.KEY_ENTER:
                    if filtered_chats and selected_idx < len(filtered_chats):
                        curses.curs_set(old_cursor)
                        return filtered_chats[selected_idx][0]
                    curses.curs_set(old_cursor)
                    return None
                elif ch == curses.KEY_DOWN or ch == ord('j'):
                    if filtered_chats and selected_idx < len(filtered_chats) - 1:
                        selected_idx += 1
                elif ch == curses.KEY_UP or ch == ord('k'):
                    if selected_idx > 0:
                        selected_idx -= 1
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    if buffer[0]:
                        buffer[0] = buffer[0][:-1]
                        update_filtered_chats()
                elif ch == curses.KEY_DC:
                    if buffer[0]:
                        buffer[0] = buffer[0][:-1]
                        update_filtered_chats()

            draw_search_window()
            draw_input_field()
            curses.doupdate()

    async def message_search_window(self, messages, load_more_callback=None, model=None, chat_title=None):
        import curses
        import threading

        height = min(20, curses.LINES // 2)
        width = curses.COLS - 4

        search_win = curses.newwin(height, width, (curses.LINES - height) // 2, 2)
        search_win.keypad(1)

        input_height = 3
        input_win = curses.newwin(input_height, width, (curses.LINES - height) // 2 + height - input_height, 2)
        input_win.keypad(1)

        buffer = [""]
        filtered_messages = []
        selected_idx = 0
        current_messages = messages.copy()

        is_loading = False
        cancel_loading = False
        loading_chars = ['-', '\\', '|', '/']
        loading_idx = 0
        escape_count = 0
        last_escape_time = 0

        old_cursor = curses.curs_set(1)

        async def get_message_text(msg):
            text = msg.text if msg.text else ""
            if msg.file:
                path = await model.download_media(
                    msg.media,
                    chat_title,
                    msg.id,
                    force_download=False
                )

                # Проверка статуса файла
                file_exists = os.path.exists(path) and os.path.getsize(path) > 1000
                status_color = 3 if file_exists else 4  # 3 = зелёный, 4 = красный
                file_info = "Открыть файл (Enter)" if file_exists else "Нажмите Enter для загрузки"
                file_path = f"file://{os.path.abspath(path)}"

                # Добавление информации о файле
                text += f"\n{file_info}\n{file_path}\n"
                # Добавляем цвет только для строки file_info
                color_ranges = [(len(text) - len(file_path) - len(file_info) - 1, 
                               len(text) - len(file_path) - 1, 
                               status_color)]

            sender = ""
            try:
                if msg.sender:
                    if msg.sender.first_name:
                        sender = msg.sender.first_name
                    elif msg.sender.title:
                        sender = msg.sender.title
                    elif msg.sender.username:
                        sender = msg.sender.username
            except:
                pass
            time_str = msg.date.strftime('%H:%M')
            full_text = f"[{time_str}]"
            if sender:
                full_text += f" {sender}:"
            full_text += f" {text}"
            return full_text

        def search_messages(query=""):
            nonlocal filtered_messages, selected_idx
            query = query.lower()

            if not query:
                filtered_messages = [(i, msg) for i, msg in enumerate(current_messages)]
            else:
                filtered_messages = []
                for i, msg in enumerate(current_messages):
                    # Нельзя использовать asyncio.run() внутри уже запущенного цикла событий
                    # Помечаем сообщения чтобы потом обработать их асинхронно
                    filtered_messages.append((i, msg))
                
                # Фильтрация будет произведена при отрисовке

            if not filtered_messages:
                selected_idx = 0
            elif selected_idx >= len(filtered_messages):
                selected_idx = len(filtered_messages) - 1

            return len(filtered_messages) > 0

        async def load_more_messages():
            nonlocal is_loading, current_messages, cancel_loading
            if not load_more_callback or is_loading:
                return False

            is_loading = True
            offset_id = 0
            if current_messages:
                offset_id = current_messages[0].id

            try:
                new_messages = await load_more_callback(offset_id)
                if cancel_loading:
                    is_loading = False
                    return False

                if new_messages:
                    current_messages = new_messages + current_messages
                    search_messages(buffer[0])
                    is_loading = False
                    return True
            except Exception as e:
                is_loading = False
                return False

            is_loading = False
            return False

        async def draw_search_window():
            search_win.erase()
            search_win.box()
            search_win.addstr(0, 2, "Поиск сообщений")

            if not filtered_messages:
                search_win.addstr(height // 2, width // 2 - 8, "Нет совпадений")
            else:
                available_height = height - 2
                start_idx = max(0, selected_idx - available_height // 2)
                end_idx = min(len(filtered_messages), start_idx + available_height)

                # Если есть поисковый запрос, фильтруем сообщения асинхронно
                if buffer[0]:
                    # Временно храним отфильтрованные сообщения
                    actual_matches = []
                    query = buffer[0].lower()
                    
                    # Проверяем только отображаемые сообщения для ускорения
                    for i, (orig_idx, msg) in enumerate(filtered_messages[start_idx:end_idx], 0):
                        msg_text = await get_message_text(msg)
                        if query in msg_text.lower():
                            actual_matches.append((orig_idx, msg))
                            y = i + 1
                            msg_text = await get_message_text(msg)
                            display_text = TelegramView.slice_by_width(msg_text, width - 4)

                            try:
                                if start_idx + i == selected_idx:
                                    search_win.attron(curses.A_REVERSE)
                                    search_win.addstr(y, 1, f" {display_text} ".ljust(width - 2)[:width - 2])
                                    search_win.attroff(curses.A_REVERSE)
                                else:
                                    search_win.addstr(y, 1, f" {display_text} "[:width - 2])
                            except curses.error:
                                # Игнорируем ошибки curses при выводе
                                pass
                else:
                    # Если запроса нет, показываем все сообщения
                    for i, (orig_idx, msg) in enumerate(filtered_messages[start_idx:end_idx], 0):
                        y = i + 1
                        msg_text = await get_message_text(msg)
                        display_text = TelegramView.slice_by_width(msg_text, width - 4)

                        try:
                            if start_idx + i == selected_idx:
                                search_win.attron(curses.A_REVERSE)
                                search_win.addstr(y, 1, f" {display_text} ".ljust(width - 2)[:width - 2])
                                search_win.attroff(curses.A_REVERSE)
                            else:
                                search_win.addstr(y, 1, f" {display_text} "[:width - 2])
                        except curses.error:
                            # Игнорируем ошибки curses при выводе
                            pass

            if is_loading:
                search_win.addstr(height - 1, width - 12, f"Загрузка {loading_chars[loading_idx]}")

            search_win.noutrefresh()

        def draw_input_field():
            input_win.erase()
            input_win.box()
            input_win.addstr(1, 1, f" {buffer[0]} ".ljust(width - 2))
            input_win.move(1, len(buffer[0]) + 2)
            input_win.noutrefresh()

        search_messages()
        
        # Изменяем на асинхронный вызов
        await draw_search_window()
        draw_input_field()
        curses.doupdate()

        while True:
            try:
                input_win.timeout(200)
                ch = input_win.get_wch()

                if is_loading:
                    loading_idx = (loading_idx + 1) % len(loading_chars)
                    await draw_search_window()
                    draw_input_field()
                    curses.doupdate()
            except curses.error:
                if is_loading:
                    loading_idx = (loading_idx + 1) % len(loading_chars)
                    await draw_search_window()
                    draw_input_field()
                    curses.doupdate()
                continue

            input_win.timeout(-1)

            if isinstance(ch, str):
                if ch == '\x1b':
                    current_time = time.time()
                    if current_time - last_escape_time < 0.5:
                        escape_count += 1
                    else:
                        escape_count = 1

                    last_escape_time = current_time

                    if escape_count >= 2:
                        cancel_loading = True
                        curses.curs_set(old_cursor)
                        return None

                    await draw_search_window()
                    draw_input_field()
                    curses.doupdate()

                elif ch == '\n':
                    if filtered_messages and selected_idx < len(filtered_messages):
                        curses.curs_set(old_cursor)
                        return filtered_messages[selected_idx][0]
                    else:
                        if not is_loading and load_more_callback and not cancel_loading:
                            asyncio.create_task(load_more_messages())
                    curses.curs_set(old_cursor)
                elif ch == 'n':
                    await handle_next_search()
                else:
                    buffer[0] += ch
                    has_results = search_messages(buffer[0])

                    if not has_results and not is_loading and load_more_callback and not cancel_loading:
                        asyncio.create_task(load_more_messages())
            elif isinstance(ch, int):
                if ch == 27:
                    current_time = time.time()
                    if current_time - last_escape_time < 0.5:
                        escape_count += 1
                    else:
                        escape_count = 1

                    last_escape_time = current_time

                    if escape_count >= 2:
                        cancel_loading = True
                        curses.curs_set(old_cursor)
                        return None

                    await draw_search_window()
                    draw_input_field()
                    curses.doupdate()

                elif ch == 10 or ch == curses.KEY_ENTER:
                    if filtered_messages and selected_idx < len(filtered_messages):
                        curses.curs_set(old_cursor)
                        return filtered_messages[selected_idx][0]
                    else:
                        if not is_loading and load_more_callback and not cancel_loading:
                            asyncio.create_task(load_more_messages())
                    curses.curs_set(old_cursor)
                elif ch == ord('n'):
                    await handle_next_search()
                elif ch == curses.KEY_DOWN or ch == ord('j'):
                    if filtered_messages and selected_idx < len(filtered_messages) - 1:
                        selected_idx += 1
                elif ch == curses.KEY_UP or ch == ord('k'):
                    if selected_idx > 0:
                        selected_idx -= 1
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    if buffer[0]:
                        buffer[0] = buffer[0][:-1]
                        has_results = search_messages(buffer[0])
                elif ch == curses.KEY_DC:
                    if buffer[0]:
                        buffer[0] = buffer[0][:-1]
                        has_results = search_messages(buffer[0])

            await draw_search_window()
            draw_input_field()
            curses.doupdate()

    def show_download_progress(self, current, total):
        progress_height = 3
        progress_width = min(self.msg_win_width - 4, 50)
        start_y = self.msg_win_height - progress_height - 1
        start_x = self.chat_win_width + (self.msg_win_width - progress_width) // 2 + 1

        if not self.is_showing_progress:
            self.progress_win = curses.newwin(progress_height, progress_width, start_y, start_x)
            self.is_showing_progress = True

        if self.progress_win:
            self.progress_win.erase()
            self.progress_win.box()

            percent = int(current / total * 100) if total > 0 else 0
            bar_width = progress_width - 12
            filled_width = int(bar_width * current / total) if total > 0 else 0
            bar = "█" * filled_width + "░" * (bar_width - filled_width)

            try:
                self.progress_win.addstr(1, 2, f"{percent}%")
                self.progress_win.addstr(1, 7, f"{bar}")
            except curses.error:
                pass

            self.progress_win.refresh()
            self.msg_win.noutrefresh()
            curses.doupdate()

    def hide_progress_bar(self):
        if self.is_showing_progress and self.progress_win:
            self.progress_win.erase()
            self.progress_win.refresh()
            self.is_showing_progress = False
            self.progress_win = None
            self.msg_win.noutrefresh()
            curses.doupdate()

    @staticmethod
    async def prepare_message_blocks(messages, max_width, model=None, chat_title=None, selected_msg_id=None, downloaded_msg_id=None):
        """Форматирует сообщения для отображения с рамками и цветовой разметкой"""
        blocks = []
        last_date = None

        for msg in messages:
            try:
                # Проверяем, что сообщение имеет необходимые атрибуты
                if not hasattr(msg, 'date') or msg.date is None:
                    # Пропускаем сообщения без даты
                    continue

                # Обработка разделителя даты
                message_date = msg.date.date()
                if last_date is None or message_date != last_date:
                    date_str = message_date.strftime('%d.%m.%Y')
                    blocks.append((f"-- {date_str} --", 1, "date_separator"))
                    last_date = message_date

                # Определение отправителя
                sender_name = "Unknown"
                try:
                    if msg.sender:
                        if hasattr(msg.sender, 'first_name') and msg.sender.first_name:
                            sender_name = msg.sender.first_name
                        elif hasattr(msg.sender, 'title') and msg.sender.title:
                            sender_name = msg.sender.title
                        elif hasattr(msg.sender, 'username') and msg.sender.username:
                            sender_name = msg.sender.username
                except Exception:
                    pass

                # Форматирование времени и заголовка
                time_str = msg.date.strftime('%H:%M')
                sender_with_time = f"{sender_name} [{time_str}]"
                text = msg.text if msg.text else ""
                
                # Обработка файлов
                color_ranges = []  # Для хранения цветовых диапазонов текста
                if hasattr(msg, 'file') and msg.file and model and chat_title:
                    # Создаем заглушку для файла
                    path = await model.download_media(msg.media, chat_title, msg.id, force_download=False)
                    
                    # Проверяем, действительно ли файл был загружен по размеру
                    file_exists = os.path.exists(path) and os.path.getsize(path) > 1
                    
                    # Определяем статус и цвет
                    if file_exists:
                        # Проверяем размер файла - если > 1KB, считаем загруженным
                        if os.path.getsize(path) > 1000:
                            file_info = "Открыть файл (Enter) | Копировать (y)"
                            status_color = 3  # Зеленый
                        else:
                            file_info = "Нажмите Enter для загрузки файла"
                            status_color = 4  # Красный
                    else:
                        file_info = "Нажмите Enter для загрузки файла"
                        status_color = 4  # Красный
                    
                    # Используем относительный путь 
                    file_path = f"file://{os.path.abspath(path)}"
                    text_addition = f"\n{file_info}\n{file_path}\n"
                    
                    # Сохраняем информацию о цветном тексте
                    current_len = len(text)
                    status_start = current_len + 1  # +1 для символа новой строки
                    status_end = status_start + len(file_info)
                    color_ranges.append((status_start, status_end, status_color))
                    
                    text += text_addition

                # Перенос текста сообщения
                wrapped = []
                for paragraph in text.split('\n'):
                    if not paragraph.strip():
                        wrapped.append('')  # Сохраняем пустые строки
                    else:
                        wrapped.extend(textwrap.wrap(
                            paragraph,
                            width=max_width - 4,
                            replace_whitespace=False,
                            drop_whitespace=False
                        ))

                # Гарантируем хотя бы одну строку для пустых сообщений
                if not wrapped:
                    wrapped.append('')

                # Определение стиля рамки
                border_style = 2 if msg.id == selected_msg_id else 1
                border_width = max((wcswidth(line) for line in wrapped), default=0)

                # Форматирование исходящих сообщений (справа)
                if getattr(msg, 'out', False):
                    block = [
                        sender_with_time.rjust(max_width),  # Выравнивание по правому краю
                        f"╭{'─' * border_width}╮".rjust(max_width)  # Выравнивание рамки по правому краю
                    ]
                    for line in wrapped:
                        block.append(f"│{line.ljust(border_width)}│".rjust(max_width))  # Выравнивание содержимого по правому краю
                    block.append(f"╰{'─' * border_width}╯".rjust(max_width))  # Выравнивание нижней рамки по правому краю
                else:
                    # Форматирование входящих сообщений (слева)
                    block = [
                        sender_with_time,
                        f"╭{'─' * border_width}╮"
                    ]
                    for line in wrapped:
                        block.append(f"│{line.ljust(border_width)}│")
                    block.append(f"╰{'─' * border_width}╯")

                # Добавление цветовых диапазонов
                formatted_block = []
                for idx, line in enumerate(block):
                    if idx == 0:
                        formatted_block.append(line)  # Строка с отправителем без стиля
                    else:
                        # Для рамки используем только border_style без дополнительных цветов
                        if idx == 2 or idx == 3:  # Строки с содержимым сообщения (предполагая файл на 3й строке)
                            # Проверяем, соответствует ли эта строка строке с file_info
                            if "Открыть файл" in line or "Нажмите Enter для загрузки" in line:
                                # Для строки с file_info создаем цветовой диапазон
                                content_start = line.find('│') + 1
                                content_end = line.rfind('│')
                                content = line[content_start:content_end].strip()
                                
                                # Только текст внутри строки
                                formatted_block.append((
                                    line,
                                    border_style,
                                    [(content_start, content_start + len(content), status_color)]
                                ))
                            else:
                                # Для остальных строк без цветовых диапазонов
                                formatted_block.append((line, border_style, []))
                        else:
                            # Для рамок без цветовых диапазонов
                            formatted_block.append((line, border_style, []))

                blocks.append((formatted_block, msg.id))
                blocks.append('\n')  # Разделитель между сообщениями
            except Exception as e:
                # При любой ошибке с сообщением просто пропускаем его
                continue

        return blocks

    @staticmethod
    def flatten_blocks(blocks):
        """Преобразует блоки сообщений в плоский список строк"""
        lines = []
        message_map = {}
        line_idx = 0

        for block in blocks:
            if isinstance(block, tuple) and isinstance(block[0], list):
                block_content, msg_id = block
                start_line = line_idx

                # Добавляем все строки блока
                for line in block_content:
                    if isinstance(line, tuple):
                        lines.append(line)
                    else:
                        lines.append((line, 1))
                    line_idx += 1

                # Заполняем карту сообщений
                for i in range(start_line, line_idx):
                    message_map[i] = msg_id
            else:
                lines.append(block)
                line_idx += 1

        return lines, message_map
