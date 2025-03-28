# TeleVim

Консольный клиент Telegram с управлением в стиле Vim.

```bash
git clone https://github.com/Stryboh/televim
cd televim
```

- Получите API ID и хеш с [core.telegram.org](https://core.telegram.org/api/obtaining_api_id)

- Поместите в credentials_example.py

```bash
mv credentials_example.py credentials.py

python -m venv venv

source venv/bin/activate

pip install -r requirements.txt

python main.py
```

### Управление

**Режим списка чатов:**
- `j` или `DOWN` - Следующий чат
- `k` или `UP` - Предыдущий чат
- `Enter` - Открыть чат
- `q` - Выход из программы
- `/` - Поиск по чатам

**Режим чата:**
- `j` или `DOWN` - Следующее сообщение
- `k` или `UP` - Предыдущее сообщение
- `Esc` - Вернуться к списку чатов
- `G` - Перейти к последнему сообщению
- `i` - Написать новое сообщение
- `r` - Ответить на выбранное сообщение
- `y` - Копировать сообщение
- `/` - Поиск по сообщениям
- `Enter` - Загрузить/открыть файл (для сообщений с файлами) 

### Конфиг
Измените значение переменной в файле .config

- removedownloadsonexit = 0
  
на 1, если хотите чтобы файлы загрузок удалялись автоматически
