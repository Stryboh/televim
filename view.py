import curses
import textwrap
from curses import textpad
from wcwidth import wcswidth
import os
import asyncio

class TelegramView:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.setup_colors()
        self.setup_screen()
        
        # Получаем размеры экрана
        self.height, self.width = self.stdscr.getmaxyx()
        self.chat_win_width = int(self.width * 0.3)
        self.msg_win_width = self.width - self.chat_win_width - 2
        self.chat_win_height = self.height
        self.msg_win_height = self.height - 2
        
        # Создаем окна
        self.chat_win = curses.newwin(self.chat_win_height, self.chat_win_width, 0, 0)
        self.msg_win = curses.newwin(self.msg_win_height, self.msg_win_width, 2, self.chat_win_width + 1)
        
        # Окно для прогресс-бара
        self.progress_win = None
        self.is_showing_progress = False
        
    def setup_colors(self):
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)  # Стандартный цвет рамки
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # Оранжевый для курсора
        curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Зеленый для текста (файл скачан)
        curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)    # Красный для текста (файл не скачан)
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE)   # Для выделения даты
        
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
            line = self.pad_to_width(self.slice_by_width(title, self.chat_win_width), self.chat_win_width)
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
        """Отрисовывает сообщения с учетом стилей
        
        Args:
            lines_with_style: Список строк с информацией о стиле
            line_offset: Смещение от начала списка
            message_map: Карта соответствия строк ID сообщений
        """
        self.msg_win.erase()
        
        lines, _ = lines_with_style if isinstance(lines_with_style, tuple) else (lines_with_style, {})
        
        # Проверяем, нужно ли корректировать смещение, чтобы не "отрезать" сообщение посередине
        if line_offset > 0 and line_offset < len(lines):
            # Проверим, не находимся ли мы посреди сообщения
            current_msg_id = None
            for i in range(line_offset - 1, -1, -1):
                if i in message_map:
                    current_msg_id = message_map[i]
                    break
                    
            if current_msg_id:
                # Найдем первую строку текущего сообщения
                first_line_of_message = line_offset
                for i in range(line_offset - 1, -1, -1):
                    if i in message_map and message_map[i] == current_msg_id:
                        first_line_of_message = i
                    elif i in message_map and message_map[i] != current_msg_id:
                        break
                        
                # Если мы начинаем не с первой строки сообщения, корректируем смещение
                if first_line_of_message < line_offset:
                    line_offset = first_line_of_message
        
        for i in range(self.msg_win_height):
            if line_offset + i < len(lines):
                line = lines[line_offset + i]
                
                # Проверяем, является ли строка разделителем даты
                if isinstance(line, tuple) and len(line) == 3 and line[2] == "date_separator":
                    text, _ = line[:2]
                    # Центрируем разделитель даты
                    text_len = len(text)
                    padding = (self.msg_win_width - text_len) // 2
                    try:
                        # Рисуем дату с фоном
                        self.msg_win.addstr(i, padding, text, curses.color_pair(5))
                    except curses.error:
                        pass
                    continue
                
                # Определяем текст и стиль
                if isinstance(line, tuple):
                    # Проверяем формат кортежа - содержит ли он метки цветного текста
                    if len(line) >= 3 and isinstance(line[2], list):
                        text, border_style, color_ranges = line
                    else:
                        text, border_style = line
                        color_ranges = []
                else:
                    text, border_style, color_ranges = line, 1, []
                    
                display_line = self.pad_to_width(self.slice_by_width(text, self.msg_win_width), self.msg_win_width)
                current_pos = 0
                
                # Если есть цветные участки текста, рисуем их с соответствующими цветами
                if color_ranges:
                    for start, end, color in color_ranges:
                        # Рисуем текст до цветного участка
                        if current_pos < start:
                            segment = display_line[current_pos:start]
                            for symbol in segment:
                                try:
                                    if symbol in ['╰', '─', '╯', '╭', '╮', '│']:
                                        self.msg_win.addstr(i, current_pos, symbol, curses.color_pair(border_style))
                                    else:
                                        self.msg_win.addstr(i, current_pos, symbol)
                                except curses.error:
                                    pass
                                current_pos += 1
                        
                        # Рисуем цветной участок
                        segment = display_line[start:end]
                        for symbol in segment:
                            try:
                                self.msg_win.addstr(i, current_pos, symbol, curses.color_pair(color))
                            except curses.error:
                                pass
                            current_pos += 1
                    
                    # Рисуем оставшийся текст
                    segment = display_line[current_pos:]
                    for symbol in segment:
                        try:
                            if symbol in ['╰', '─', '╯', '╭', '╮', '│']:
                                self.msg_win.addstr(i, current_pos, symbol, curses.color_pair(border_style))
                            else:
                                self.msg_win.addstr(i, current_pos, symbol)
                        except curses.error:
                            pass
                        current_pos += 1
                else:
                    # Рисуем текст обычным способом
                    for j, symbol in enumerate(display_line):
                        try:
                            if symbol in ['╰', '─', '╯', '╭', '╮', '│']:
                                self.msg_win.addstr(i, j, symbol, curses.color_pair(border_style))
                            else:
                                self.msg_win.addstr(i, j, symbol)
                        except curses.error:
                            pass
                
                self.msg_win.addstr(i, 0, "")  # Устанавливаем курсор в начало строки
            else:
                break
        self.msg_win.noutrefresh()
        
    def draw_msg_border(self):
        try:
            self.stdscr.attron(curses.color_pair(1))
            textpad.rectangle(self.stdscr, 1, self.chat_win_width, self.msg_win_height + 2, self.chat_win_width + self.msg_win_width + 1)
            self.stdscr.attroff(curses.color_pair(1))
        except curses.error:
            pass
            
    def set_dialog_title(self, title):
        display_title = self.pad_to_width(self.slice_by_width(title, self.msg_win_width), self.msg_win_width)
        try:
            self.stdscr.addstr(0, self.chat_win_width + 1, display_title)
        except curses.error:
            pass
            
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
        
        # Сохраняем текущее состояние курсора и делаем его видимым
        old_cursor = curses.curs_set(1)
        
        buffer = [""]
        cur_y = 1
        cur_x = 2
        win.move(cur_y, cur_x)
        win.refresh()
        
        # Позиция скроллинга для длинных сообщений
        view_y_offset = 0
        max_view_lines = win_height - 2  # -2 для верхней и нижней границы
    
        # Флаг для отслеживания Alt
        alt_pressed = False
    
        while True:
            try:
                ch = win.get_wch()
            except curses.error:
                continue
    
            if isinstance(ch, str):
                if ch == '\x1b':  # Escape или начало Alt+клавиша
                    # Проверяем, нет ли следующего символа (для комбинаций с Alt)
                    try:
                        win.nodelay(True)  # Не блокировать при чтении
                        next_ch = win.get_wch()
                        
                        # Если получили следующий символ, это комбинация Alt+клавиша
                        if next_ch == '\n' or next_ch == 10 or next_ch == 13:
                            # Alt+Enter - отправляем сообщение
                            win.nodelay(False)  # Возвращаем блокирующий режим
                            curses.curs_set(old_cursor)  # Восстанавливаем курсор
                            return "\n".join(buffer)
                        
                        # Если это другая комбинация с Alt, игнорируем
                        win.nodelay(False)  # Возвращаем блокирующий режим
                    except:
                        # Если второго символа нет, это обычный Escape
                        win.nodelay(False)  # Возвращаем блокирующий режим
                        curses.curs_set(old_cursor)  # Восстанавливаем состояние курсора
                        return None
                        
                elif ch == '\n':  # Enter - просто добавляем новую строку, а не отправляем
                    if cur_y - 1 >= len(buffer) - 1:
                        buffer.append("")
                    else:
                        # Вставляем новую строку, разделяя текущую
                        remainder = buffer[cur_y - 1][cur_x-2:]
                        buffer[cur_y - 1] = buffer[cur_y - 1][:cur_x-2]
                        buffer.insert(cur_y, remainder)
                    
                    cur_y += 1
                    cur_x = 2
                    
                    # Если курсор выходит за пределы видимой области, скроллим
                    if cur_y - view_y_offset > max_view_lines:
                        view_y_offset += 1
                    
                    # Перерисовываем буфер с новой позицией скроллинга
                    self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)
                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()
                else:
                    # Вставка символа
                    buffer[cur_y - 1] = buffer[cur_y - 1][:cur_x-2] + ch + buffer[cur_y - 1][cur_x-2:]
                    
                    # Перерисовываем всю видимую часть буфера
                    self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)
                    
                    cur_x += 1
                    if cur_x >= win_width - 2:
                        # При достижении края переходим на новую строку
                        if cur_y - view_y_offset < max_view_lines:
                            cur_y += 1
                            if cur_y - 1 >= len(buffer):
                                buffer.append("")
                        else:
                            # Если курсор в нижней части видимого окна, скроллим вниз
                            view_y_offset += 1
                            cur_y += 1
                            if cur_y - 1 >= len(buffer):
                                buffer.append("")
                        cur_x = 2
                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()
                
            elif isinstance(ch, int):
                if ch == 10 or ch == curses.KEY_ENTER:  # Enter
                    if cur_y - 1 >= len(buffer) - 1:
                        buffer.append("")
                    else:
                        # Вставляем новую строку, разделяя текущую
                        remainder = buffer[cur_y - 1][cur_x-2:]
                        buffer[cur_y - 1] = buffer[cur_y - 1][:cur_x-2]
                        buffer.insert(cur_y, remainder)
                    
                    cur_y += 1
                    cur_x = 2
                    
                    # Если курсор выходит за пределы видимой области, скроллим
                    if cur_y - view_y_offset > max_view_lines:
                        view_y_offset += 1
                    
                    # Перерисовываем буфер с новой позицией скроллинга
                    self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)
                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()
                    continue
                elif ch == 27:  # Escape/Alt key
                    # Активируем режим без блокировки для проверки последующих клавиш
                    win.nodelay(True)
                    try:
                        next_ch = win.getch()
                        if next_ch == 10 or next_ch == 13:  # Alt+Enter
                            win.nodelay(False)
                            curses.curs_set(old_cursor)
                            return "\n".join(buffer)
                        elif next_ch != -1:  # Другая комбинация с Alt
                            # Игнорируем и продолжаем 
                            pass
                        else:  # Просто Esc
                            win.nodelay(False)
                            curses.curs_set(old_cursor)
                            return None
                    except:
                        # Возвращаем режим блокировки и выходим
                        win.nodelay(False)
                        curses.curs_set(old_cursor)
                        return None
                    win.nodelay(False)
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    # Удаление символа
                    if cur_x > 2:
                        # Удаляем символ из текущей строки
                        buffer[cur_y - 1] = buffer[cur_y - 1][:cur_x-3] + buffer[cur_y - 1][cur_x-2:]
                        cur_x -= 1
                    elif cur_y > 1:
                        # Удаляем символ перенося часть строки на предыдущую
                        prev_line_len = len(buffer[cur_y - 2])
                        buffer[cur_y - 2] += buffer[cur_y - 1]
                        del buffer[cur_y - 1]
                        cur_y -= 1
                        cur_x = prev_line_len + 2
                        
                        # Если мы в начале видимой области и удаляем строку, скроллим вверх
                        if cur_y <= view_y_offset:
                            view_y_offset = max(0, view_y_offset - 1)
                    
                    # Перерисовываем буфер
                    self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)
                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()
                    continue
                    
                elif ch == curses.KEY_UP:
                    # Курсор вверх
                    if cur_y > 1:
                        cur_y -= 1
                        # Если новая строка короче текущей позиции курсора
                        if len(buffer[cur_y - 1]) + 2 < cur_x:
                            cur_x = len(buffer[cur_y - 1]) + 2
                            
                        # Если курсор выходит за верхнюю границу видимой области
                        if cur_y <= view_y_offset:
                            view_y_offset = max(0, cur_y - 1)
                            self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)
                            
                        win.move(cur_y - view_y_offset, cur_x)
                        win.refresh()
                        
                elif ch == curses.KEY_DOWN:
                    # Курсор вниз
                    if cur_y < len(buffer):
                        cur_y += 1
                        # Если новая строка короче текущей позиции курсора
                        if len(buffer[cur_y - 1]) + 2 < cur_x:
                            cur_x = len(buffer[cur_y - 1]) + 2
                            
                        # Если курсор выходит за нижнюю границу видимой области
                        if cur_y - view_y_offset > max_view_lines:
                            view_y_offset += 1
                            self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)
                            
                        win.move(cur_y - view_y_offset, cur_x)
                        win.refresh()
                        
                elif ch == curses.KEY_LEFT:
                    # Курсор влево
                    if cur_x > 2:
                        cur_x -= 1
                    elif cur_y > 1:
                        cur_y -= 1
                        cur_x = len(buffer[cur_y - 1]) + 2
                        
                        # Если курсор выходит за верхнюю границу видимой области
                        if cur_y <= view_y_offset:
                            view_y_offset = max(0, cur_y - 1)
                            self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)
                            
                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()
                    
                elif ch == curses.KEY_RIGHT:
                    # Курсор вправо
                    if cur_x < len(buffer[cur_y - 1]) + 2:
                        cur_x += 1
                    elif cur_y < len(buffer):
                        cur_y += 1
                        cur_x = 2
                        
                        # Если курсор выходит за нижнюю границу видимой области
                        if cur_y - view_y_offset > max_view_lines:
                            view_y_offset += 1
                            self._redraw_input_buffer(win, buffer, view_y_offset, max_view_lines)
                            
                    win.move(cur_y - view_y_offset, cur_x)
                    win.refresh()
                    
                else:
                    continue
        
    def _redraw_input_buffer(self, win, buffer, view_y_offset, max_view_lines):
        """Перерисовывает буфер ввода с учетом смещения прокрутки"""
        # Очищаем область ввода
        for i in range(1, max_view_lines + 1):
            win.move(i, 2)
            win.clrtoeol()
            
        # Отображаем видимую часть буфера
        for i in range(min(max_view_lines, len(buffer) - view_y_offset)):
            line_idx = i + view_y_offset
            if line_idx < len(buffer):
                if len(buffer[line_idx]) > 0:
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

    @staticmethod
    async def prepare_message_blocks(messages, max_width, model=None, chat_title=None, selected_msg_id=None, downloaded_msg_id=None):
        """Подготавливает блоки сообщений для отображения
        
        Args:
            messages: Список сообщений
            max_width: Максимальная ширина для отображения
            model: Модель для загрузки файлов
            chat_title: Название чата для именования файлов
            selected_msg_id: ID выделенного сообщения (для курсора)
            downloaded_msg_id: ID сообщения с загруженным файлом (для зеленой рамки)
            
        Returns:
            Список блоков сообщений
        """
        blocks = []
        last_date = None
        
        for msg in messages:
            # Проверяем дату сообщения и добавляем разделитель при необходимости
            message_date = msg.date.date()
            if last_date is None or message_date != last_date:
                # Добавляем разделитель даты
                date_str = message_date.strftime('%d.%m.%Y')
                blocks.append((f"-- {date_str} --", 1, "date_separator"))
                last_date = message_date
            
            # Получаем информацию об отправителе
            sender_name = "Unknown"
            try:
                if msg.sender:
                    if hasattr(msg.sender, 'first_name') and msg.sender.first_name:
                        sender_name = msg.sender.first_name
                    elif hasattr(msg.sender, 'title') and msg.sender.title:
                        sender_name = msg.sender.title
                    elif hasattr(msg.sender, 'username') and msg.sender.username:
                        sender_name = msg.sender.username
                
                # Для групповых чатов или каналов
                if hasattr(msg, 'chat') and msg.chat:
                    if hasattr(msg.chat, 'title') and msg.chat.title and sender_name == "Unknown":
                        sender_name = msg.chat.title
                
                # Для пересланных сообщений
                if hasattr(msg, 'forward') and msg.forward:
                    if hasattr(msg.forward.sender, 'first_name') and msg.forward.sender.first_name:
                        sender_name = f"Fwd: {msg.forward.sender.first_name}"
                    elif hasattr(msg.forward.sender, 'title') and msg.forward.sender.title:
                        sender_name = f"Fwd: {msg.forward.sender.title}"
            except Exception:
                pass  # В случае ошибки, оставляем Unknown
                
            # Добавляем время отправки к имени
            time_str = msg.date.strftime('%H:%M')
            sender_with_time = f"{sender_name} [{time_str}]"
                
            text = msg.text if msg.text else ""
            
            # Обработка файлов
            color_ranges = []  # Для хранения цветовых диапазонов текста
            if msg.file and model and chat_title:
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
    
            wrapped = []
            for paragraph in text.splitlines():
                wrapped.extend(textwrap.wrap(paragraph, width=max_width - 2) or [""])
            if not wrapped:
                wrapped = [""]
    
            border_width = max((wcswidth(line) for line in wrapped), default=0)
            if border_width <= 0:
                border_width = max_width - 2
    
            # Выбираем цвет рамки для выделенного сообщения
            border_style = 1  # Обычный цвет
            if msg.id == selected_msg_id:
                border_style = 2  # Оранжевый для выделенного сообщения
                
            if getattr(msg, 'out', False):
                block_width = border_width + 2
                left_padding = max_width - block_width if max_width > block_width else 0
                block = []
                sender_line = TelegramView.pad_to_width(TelegramView.slice_by_width(sender_with_time, block_width), block_width)
                sender_line = " " * left_padding + sender_line
                block.append(sender_line)
                top_border = "╭" + "─" * border_width + "╮"
                top_border = " " * left_padding + top_border
                block.append((top_border, border_style))  # Добавляем информацию о стиле
                
                # Обрабатываем каждую строку текста
                for line in wrapped:
                    line_display_width = wcswidth(line)
                    padding = border_width - line_display_width
                    content_line = "│" + line + " " * padding + "│"
                    content_line = " " * left_padding + content_line
                    
                    # Проверяем наличие цветных участков в этой строке
                    line_start = text.find(line)
                    line_end = line_start + len(line)
                    
                    # Находим цветные участки, которые пересекаются с текущей строкой
                    line_colors = []
                    for start, end, color in color_ranges:
                        if start < line_end and end > line_start:
                            # Пересчитываем индексы относительно текущей строки
                            adjusted_start = max(0, start - line_start) + 1  # +1 для символа '│'
                            adjusted_end = min(len(line), end - line_start) + 1  # +1 для символа '│'
                            if adjusted_end > adjusted_start:
                                # Учитываем левый отступ для исходящих сообщений
                                adjusted_start += len(" " * left_padding)
                                adjusted_end += len(" " * left_padding)
                                line_colors.append((adjusted_start, adjusted_end, color))
                    
                    if line_colors:
                        block.append((content_line, border_style, line_colors))
                    else:
                        block.append((content_line, border_style))
                
                bot_border = "╰" + "─" * border_width + "╯"
                bot_border = " " * left_padding + bot_border
                block.append((bot_border, border_style))
            else:
                block = []
                sender_line = TelegramView.pad_to_width(TelegramView.slice_by_width(sender_with_time, max_width), max_width)
                block.append(sender_line)
                top_border = "╭" + "─" * border_width + "╮"
                block.append((top_border, border_style))
                
                # Обрабатываем каждую строку текста
                for line in wrapped:
                    line_display_width = wcswidth(line)
                    padding = border_width - line_display_width
                    content_line = "│" + line + " " * padding + "│"
                    
                    # Проверяем наличие цветных участков в этой строке
                    line_start = text.find(line)
                    line_end = line_start + len(line)
                    
                    # Находим цветные участки, которые пересекаются с текущей строкой
                    line_colors = []
                    for start, end, color in color_ranges:
                        if start < line_end and end > line_start:
                            # Пересчитываем индексы относительно текущей строки
                            adjusted_start = max(0, start - line_start) + 1  # +1 для символа '│'
                            adjusted_end = min(len(line), end - line_start) + 1  # +1 для символа '│'
                            if adjusted_end > adjusted_start:
                                line_colors.append((adjusted_start, adjusted_end, color))
                    
                    if line_colors:
                        block.append((content_line, border_style, line_colors))
                    else:
                        block.append((content_line, border_style))
                
                bot_border = "╰" + "─" * border_width + "╯"
                block.append((bot_border, border_style))
                
            blocks.append((block, msg.id))  # Добавляем ID сообщения для дальнейшей обработки
            blocks.append('\n')
        return blocks
        
    @staticmethod
    def flatten_blocks(blocks):
        """Преобразует блоки сообщений в линейный список строк
        
        Returns:
            Список строк с информацией о стиле и ID сообщения
        """
        lines = []
        message_map = {}  # Сопоставление номеров строк с ID сообщений
        
        line_idx = 0
        for block in blocks:
            if isinstance(block, tuple) and isinstance(block[0], list):
                block_content, msg_id = block
                start_line = line_idx
                
                # Первая строка с именем отправителя
                lines.append(block_content[0])
                line_idx += 1
                
                # Остальные строки с рамкой и текстом
                for i in range(1, len(block_content)):
                    if isinstance(block_content[i], tuple):
                        lines.append(block_content[i])  # Это уже кортеж (текст, стиль)
                    else:
                        lines.append((block_content[i], 1))  # Обычный стиль для обычного текста
                    line_idx += 1
                    
                # Запоминаем соответствие строк сообщению
                end_line = line_idx - 1
                for i in range(start_line, end_line + 1):
                    message_map[i] = msg_id
            else:
                lines.append(block)
                line_idx += 1
                
        return lines, message_map  # Возвращаем и карту сообщений 

    async def chat_search_window(self, chat_list):
        """Отображает окно поиска по чатам
        
        Args:
            chat_list: Список чатов для поиска
            
        Returns:
            индекс выбранного чата или None, если поиск отменен
        """
        import curses
        
        # Определяем размеры окна поиска (половина высоты экрана)
        height = min(20, curses.LINES // 2)
        width = curses.COLS - 4
        
        # Создаем окно поиска
        search_win = curses.newwin(height, width, (curses.LINES - height) // 2, 2)
        search_win.keypad(1)
        
        # Создаем панель для ввода поиска
        input_height = 3
        input_win = curses.newwin(input_height, width, (curses.LINES - height) // 2 + height - input_height, 2)
        input_win.keypad(1)
        
        # Инициализируем переменные
        buffer = [""]  # Буфер для ввода текста поиска
        filtered_chats = []
        selected_idx = 0
        
        # Сохраняем текущее состояние курсора и делаем его видимым
        old_cursor = curses.curs_set(1)
        
        # Обновляем список отфильтрованных чатов
        def update_filtered_chats():
            nonlocal filtered_chats, selected_idx
            search_query = buffer[0]
            if not search_query:
                filtered_chats = [(i, chat) for i, chat in enumerate(chat_list)]
            else:
                # Фильтрация по имени чата, нечувствительно к регистру
                query_lower = search_query.lower()
                filtered_chats = [(i, chat) for i, chat in enumerate(chat_list) 
                                if query_lower in (chat.title or "").lower()]
            
            # Сбрасываем выделение, если список пуст
            if not filtered_chats:
                selected_idx = 0
            elif selected_idx >= len(filtered_chats):
                selected_idx = len(filtered_chats) - 1
        
        # Отрисовка окна поиска
        def draw_search_window():
            search_win.erase()
            search_win.box()
            search_win.addstr(0, 2, "Поиск чатов")
            
            # Отображаем результаты поиска
            available_height = height - 2
            start_idx = max(0, selected_idx - available_height // 2)
            end_idx = min(len(filtered_chats), start_idx + available_height)
            
            for i, (orig_idx, chat) in enumerate(filtered_chats[start_idx:end_idx], 0):
                y = i + 1
                chat_name = chat.title if chat.title else "No Name"
                # Обрезаем до ширины окна
                chat_name = chat_name[:width - 4]
                
                # Выделяем выбранный чат
                if start_idx + i == selected_idx:
                    search_win.attron(curses.A_REVERSE)
                    search_win.addstr(y, 1, f" {chat_name} ".ljust(width - 2))
                    search_win.attroff(curses.A_REVERSE)
                else:
                    search_win.addstr(y, 1, f" {chat_name} "[:width - 2])
                    
            search_win.noutrefresh()
        
        # Отрисовка поля ввода
        def draw_input_field():
            input_win.erase()
            input_win.box()
            input_win.addstr(1, 1, f" {buffer[0]} ".ljust(width - 2))
            input_win.move(1, len(buffer[0]) + 2)
            input_win.noutrefresh()
            
        # Сначала обновляем список и отрисовываем окна
        update_filtered_chats()
        draw_search_window()
        draw_input_field()
        curses.doupdate()
        
        # Основной цикл обработки ввода
        while True:
            try:
                ch = input_win.get_wch()
            except curses.error:
                continue
                
            # Обработка клавиш
            if isinstance(ch, str):
                if ch == '\x1b':  # ESC
                    try:
                        input_win.nodelay(True)
                        next_ch = input_win.get_wch()
                        input_win.nodelay(False)
                    except:
                        curses.curs_set(old_cursor)
                        return None
                elif ch == '\n':  # Enter
                    if filtered_chats and selected_idx < len(filtered_chats):
                        curses.curs_set(old_cursor)
                        return filtered_chats[selected_idx][0]
                    curses.curs_set(old_cursor)
                    return None
                else:
                    # Добавляем символ в буфер
                    buffer[0] += ch
                    update_filtered_chats()
            elif isinstance(ch, int):
                if ch == 27:  # ESC
                    curses.curs_set(old_cursor)
                    return None
                elif ch == 10 or ch == curses.KEY_ENTER:  # Enter
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
                elif ch == curses.KEY_DC:  # Delete key
                    if buffer[0]:
                        buffer[0] = buffer[0][:-1]
                        update_filtered_chats()
                    
            # Обновляем отображение
            draw_search_window()
            draw_input_field()
            curses.doupdate() 

    async def message_search_window(self, messages, load_more_callback=None):
        """Отображает окно поиска по сообщениям с поддержкой пагинации
        
        Args:
            messages: Список сообщений для поиска
            load_more_callback: Функция для загрузки дополнительных сообщений
            
        Returns:
            индекс выбранного сообщения или None, если поиск отменен
        """
        import curses
        import threading
        import time
        
        # Определяем размеры окна поиска (половина высоты экрана)
        height = min(20, curses.LINES // 2)
        width = curses.COLS - 4
        
        # Создаем окно поиска
        search_win = curses.newwin(height, width, (curses.LINES - height) // 2, 2)
        search_win.keypad(1)
        
        # Создаем панель для ввода поиска
        input_height = 3
        input_win = curses.newwin(input_height, width, (curses.LINES - height) // 2 + height - input_height, 2)
        input_win.keypad(1)
        
        # Инициализируем переменные
        buffer = [""]  # Буфер для ввода текста поиска
        filtered_messages = []
        selected_idx = 0
        current_messages = messages.copy()  # Локальная копия сообщений для поиска
        
        # Флаг, указывающий, что идет загрузка сообщений
        is_loading = False
        # Флаг для отмены загрузки
        cancel_loading = False
        # Анимация загрузки
        loading_chars = ['-', '\\', '|', '/']
        loading_idx = 0
        
        # Режим работы: обычный поиск, или режим перехода к следующему совпадению
        next_match_mode = False
        # Счетчик нажатий Escape
        escape_count = 0
        # Последнее время нажатия Escape
        last_escape_time = 0
        
        # Сохраняем текущее состояние курсора и делаем его видимым
        old_cursor = curses.curs_set(1)
        
        # Вспомогательная функция для получения текста сообщения
        def get_message_text(msg):
            # Получаем текст сообщения или пустую строку, если текста нет
            text = msg.text if msg.text else ""
            
            # Если у сообщения есть файл, добавляем информацию о нём
            if msg.file:
                text += f" [File: {getattr(msg.file, 'name', 'Attachment')}]"
                
            # Добавляем информацию об отправителе, если доступна
            sender = ""
            try:
                if msg.sender:
                    if hasattr(msg.sender, 'first_name') and msg.sender.first_name:
                        sender = msg.sender.first_name
                    elif hasattr(msg.sender, 'title') and msg.sender.title:
                        sender = msg.sender.title
                    elif hasattr(msg.sender, 'username') and msg.sender.username:
                        sender = msg.sender.username
            except:
                pass
                
            # Добавляем время отправки
            time_str = msg.date.strftime('%H:%M')
            
            # Если есть отправитель, добавляем информацию о нём
            full_text = f"[{time_str}]"
            if sender:
                full_text += f" {sender}:"
            
            full_text += f" {text}"
            return full_text
        
        # Поиск по сообщениям
        def search_messages(query=""):
            nonlocal filtered_messages, selected_idx
            query = query.lower()  # Поиск нечувствителен к регистру
            
            if not query:
                # Если запрос пустой, показываем все сообщения
                filtered_messages = [(i, msg) for i, msg in enumerate(current_messages)]
            else:
                # Фильтруем сообщения по тексту и информации об отправителе
                filtered_messages = []
                for i, msg in enumerate(current_messages):
                    full_text = get_message_text(msg).lower()
                    if query in full_text:
                        filtered_messages.append((i, msg))
            
            # Сбрасываем выделение, если список пуст
            if not filtered_messages:
                selected_idx = 0
            elif selected_idx >= len(filtered_messages):
                selected_idx = len(filtered_messages) - 1
                
            return len(filtered_messages) > 0
        
        # Асинхронная загрузка дополнительных сообщений
        async def load_more_messages():
            nonlocal is_loading, current_messages, cancel_loading, next_match_mode
            
            if not load_more_callback or is_loading:
                return False
                
            is_loading = True
            
            # Если есть сообщения, используем самое старое как offset
            offset_id = 0
            if current_messages:
                offset_id = current_messages[0].id
                
            try:
                # Загружаем дополнительные сообщения
                new_messages = await load_more_callback(offset_id)
                
                # Проверяем флаг отмены
                if cancel_loading:
                    is_loading = False
                    return False
                    
                # Добавляем новые сообщения к текущим
                if new_messages:
                    current_messages = new_messages + current_messages
                    # Обновляем результаты поиска
                    has_results = search_messages(buffer[0])
                    is_loading = False
                    
                    # Если в режиме поиска следующего совпадения найдены результаты,
                    # выходим из режима следующего совпадения
                    if next_match_mode and has_results:
                        next_match_mode = False
                        
                    return True
                else:
                    # Нет новых сообщений, выходим из режима следующего совпадения
                    next_match_mode = False
            except Exception as e:
                is_loading = False
                return False
                
            is_loading = False
            return False
        
        # Отрисовка окна поиска
        def draw_search_window():
            search_win.erase()
            search_win.box()
            search_win.addstr(0, 2, "Поиск сообщений")
            
            # Отображаем индикатор режима поиска
            mode_text = "[Нажмите n для поиска следующего]" if next_match_mode else "[Режим поиска]"
            try:
                search_win.addstr(0, width - len(mode_text) - 2, mode_text)
            except:
                pass
                
            # Отображаем результаты поиска или информацию об отсутствии совпадений
            if not filtered_messages:
                search_win.addstr(height // 2, width // 2 - 8, "Нет совпадений")
            else:
                available_height = height - 2
                start_idx = max(0, selected_idx - available_height // 2)
                end_idx = min(len(filtered_messages), start_idx + available_height)
                
                for i, (orig_idx, msg) in enumerate(filtered_messages[start_idx:end_idx], 0):
                    y = i + 1
                    # Получаем текст сообщения
                    msg_text = get_message_text(msg)
                    
                    # Обрезаем до ширины окна
                    display_text = self.slice_by_width(msg_text, width - 4)
                    
                    # Выделяем выбранное сообщение
                    if start_idx + i == selected_idx:
                        search_win.attron(curses.A_REVERSE)
                        search_win.addstr(y, 1, f" {display_text} ".ljust(width - 2))
                        search_win.attroff(curses.A_REVERSE)
                    else:
                        search_win.addstr(y, 1, f" {display_text} ")
            
            # Отображаем индикатор загрузки, если идет загрузка
            if is_loading:
                search_win.addstr(height - 1, width - 12, f"Загрузка {loading_chars[loading_idx]}")
                
            # Отображаем подсказку для выхода
            exit_text = "ESC x2: Выход"
            try:
                search_win.addstr(height - 1, 2, exit_text)
            except:
                pass
                
            search_win.noutrefresh()
        
        # Отрисовка поля ввода
        def draw_input_field():
            input_win.erase()
            input_win.box()
            input_win.addstr(1, 1, f" {buffer[0]} ".ljust(width - 2))
            input_win.move(1, len(buffer[0]) + 2)
            input_win.noutrefresh()
        
        # Обработка нажатия клавиши 'n' - поиск следующего совпадения
        async def handle_next_search():
            nonlocal next_match_mode
            
            # Включаем режим поиска следующего совпадения
            next_match_mode = True
            
            # Если нет загрузки, запускаем
            if not is_loading and load_more_callback and not cancel_loading:
                await load_more_messages()
            
        # Инициализация поиска
        search_messages()
        draw_search_window()
        draw_input_field()
        curses.doupdate()
        
        # Основной цикл обработки ввода
        while True:
            try:
                # Устанавливаем таймаут для обновления анимации загрузки
                input_win.timeout(200)
                ch = input_win.get_wch()
                
                # Обновляем анимацию загрузки при каждом цикле
                if is_loading:
                    loading_idx = (loading_idx + 1) % len(loading_chars)
                    draw_search_window()
                    draw_input_field()
                    curses.doupdate()
            except curses.error:
                # Таймаут - обновляем анимацию, если идет загрузка
                if is_loading:
                    loading_idx = (loading_idx + 1) % len(loading_chars)
                    draw_search_window()
                    draw_input_field()
                    curses.doupdate()
                continue
                
            # Сбрасываем таймаут для нормальной работы клавиш
            input_win.timeout(-1)
                
            # Обработка клавиш
            if isinstance(ch, str):
                if ch == '\x1b':  # ESC
                    # Проверяем двойное нажатие ESC
                    current_time = time.time()
                    if current_time - last_escape_time < 0.5:  # 500 мс для считывания двойного нажатия
                        escape_count += 1
                    else:
                        escape_count = 1
                    
                    last_escape_time = current_time
                    
                    if escape_count >= 2:
                        # Останавливаем загрузку и выходим при двойном ESC
                        cancel_loading = True
                        curses.curs_set(old_cursor)
                        return None
                    
                    # При одиночном ESC продолжаем работу, но показываем подсказку
                    draw_search_window()
                    draw_input_field()
                    curses.doupdate()
                    
                elif ch == '\n':  # Enter
                    if filtered_messages and selected_idx < len(filtered_messages):
                        curses.curs_set(old_cursor)
                        return filtered_messages[selected_idx][0]
                    else:
                        # Если нет результатов, пробуем загрузить больше сообщений
                        if not is_loading and load_more_callback and not cancel_loading:
                            asyncio.create_task(load_more_messages())
                    curses.curs_set(old_cursor)
                elif ch == 'n':  # Режим поиска следующего совпадения
                    await handle_next_search()
                else:
                    # Добавляем символ в буфер
                    buffer[0] += ch
                    has_results = search_messages(buffer[0])
                    
                    # Если нет результатов, загружаем больше сообщений
                    if not has_results and not is_loading and load_more_callback and not cancel_loading:
                        asyncio.create_task(load_more_messages())
            elif isinstance(ch, int):
                if ch == 27:  # ESC
                    # Проверяем двойное нажатие ESC
                    current_time = time.time()
                    if current_time - last_escape_time < 0.5:  # 500 мс для считывания двойного нажатия
                        escape_count += 1
                    else:
                        escape_count = 1
                    
                    last_escape_time = current_time
                    
                    if escape_count >= 2:
                        # Останавливаем загрузку и выходим при двойном ESC
                        cancel_loading = True
                        curses.curs_set(old_cursor)
                        return None
                    
                    # При одиночном ESC продолжаем работу, но показываем подсказку
                    draw_search_window()
                    draw_input_field()
                    curses.doupdate()
                    
                elif ch == 10 or ch == curses.KEY_ENTER:  # Enter
                    if filtered_messages and selected_idx < len(filtered_messages):
                        curses.curs_set(old_cursor)
                        return filtered_messages[selected_idx][0]
                    else:
                        # Если нет результатов, пробуем загрузить больше сообщений
                        if not is_loading and load_more_callback and not cancel_loading:
                            asyncio.create_task(load_more_messages())
                    curses.curs_set(old_cursor)
                elif ch == ord('n'):  # Режим поиска следующего совпадения
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
                elif ch == curses.KEY_DC:  # Delete key
                    if buffer[0]:
                        buffer[0] = buffer[0][:-1]
                        has_results = search_messages(buffer[0])
                        
            # Обновляем отображение
            draw_search_window()
            draw_input_field()
            curses.doupdate()

    def show_download_progress(self, current, total):
        """Отображает прогресс загрузки файла
        
        Args:
            current: Текущий прогресс
            total: Общий размер файла
        """
        import curses
        
        # Вычисляем ширину прогресс-бара (адаптируем под ширину окна сообщений)
        progress_height = 3
        progress_width = min(self.msg_win_width - 4, 50)
        
        # Размещаем прогресс-бар внизу окна сообщений
        # Убедимся, что он находится в пределах окна и не перекрывает интерфейс
        start_y = self.msg_win_height - progress_height - 1
        start_x = self.chat_win_width + (self.msg_win_width - progress_width) // 2 + 1
        
        # Первый вызов - создаем окно прогресса
        if not self.is_showing_progress:
            # Создаем окно прогресса как подокно окна сообщений
            # это позволит прогресс-бару не мешать скроллингу
            self.progress_win = curses.newwin(progress_height, progress_width, start_y, start_x)
            self.is_showing_progress = True
            
        if self.progress_win:
            self.progress_win.erase()
            self.progress_win.box()
            
            # Вычисляем процент загрузки
            percent = int(current / total * 100) if total > 0 else 0
            
            # Определяем ширину прогресс-бара
            bar_width = progress_width - 12  # Оставляем место для процентов
            filled_width = int(bar_width * current / total) if total > 0 else 0
            bar = "█" * filled_width + "░" * (bar_width - filled_width)
            
            try:
                # Отображаем процент
                self.progress_win.addstr(1, 2, f"{percent}%")
                
                # Отображаем прогресс-бар
                self.progress_win.addstr(1, 7, f"{bar}")
            except curses.error:
                pass
                
            # Обновляем окно
            self.progress_win.refresh()
            
            # Обновляем окно сообщений, чтобы не терять содержимое
            self.msg_win.noutrefresh()
            curses.doupdate()
            
    def hide_progress_bar(self):
        """Скрывает прогресс-бар"""
        if self.is_showing_progress and self.progress_win:
            self.progress_win.erase()
            self.progress_win.refresh()
            self.is_showing_progress = False
            self.progress_win = None
            
            # Обновляем окно сообщений
            self.msg_win.noutrefresh()
            curses.doupdate() 