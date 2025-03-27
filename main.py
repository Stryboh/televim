import os
import curses
import asyncio
import signal
from model import TelegramModel
from view import TelegramView
from viewmodel import TelegramViewModel
import credentials

# Флаг для Ctrl+C
exit_requested = False

def handle_sigint(signum, frame):
    """Обработчик сигнала Ctrl+C"""
    global exit_requested
    exit_requested = True

async def interactive_auth(model):
    """Выполняет интерактивную авторизацию через консоль"""
    print("Требуется авторизация в Telegram")
    while True:
        phone = input("Введите номер телефона (с кодом страны, например +7...): ")
        try:
            await model.login(phone)
            print("Авторизация успешна!")
            return True
        except Exception as e:
            print(f"Ошибка авторизации: {e}")
            retry = input("Попробовать снова? (y/n): ")
            if retry.lower() != 'y':
                return False

async def main(stdscr):
    global exit_requested
    
    # Инициализация модели
    model = TelegramModel(credentials.name(), credentials.key(), credentials.hash())
    
    # Инициализация представления
    view = TelegramView(stdscr)
    
    # Инициализация ViewModel
    viewmodel = TelegramViewModel(model, view)
    
    # Запуск приложения
    try:
        await viewmodel.initialize()
        
        # Основной цикл приложения
        while not exit_requested:
            # viewmodel.run теперь возвращает True, если пользователь хочет выйти
            exit_app = await viewmodel.run(check_exit=lambda: exit_requested)
            if exit_app:
                break
            
    finally:
        # Гарантируем, что отключимся от сервера и очистим ресурсы
        await viewmodel.cleanup()

async def auth_and_setup():
    """Аутентификация и инициализация перед запуском curses"""
    # Создаем директорию для загрузок, если её нет
    os.makedirs("downloads", exist_ok=True)
    
    # Инициализируем модель
    model = TelegramModel(credentials.name(), credentials.key(), credentials.hash())
    
    # Подключаемся к API
    await model.connect()
    
    # Проверяем, авторизован ли пользователь
    if not await model.is_user_authorized():
        # Если нет, запускаем интерактивную авторизацию
        auth_success = await interactive_auth(model)
        if not auth_success:
            print("Авторизация не удалась. Завершение работы.")
            await model.disconnect()
            return False
    
    # Отключаемся, так как соединение будет установлено заново в основном приложении
    await model.disconnect()
    return True

def start_app():
    # Регистрируем обработчик Ctrl+C
    signal.signal(signal.SIGINT, handle_sigint)
    
    # Выполняем авторизацию перед запуском curses
    auth_success = asyncio.run(auth_and_setup())
    
    if auth_success:
        # Запуск приложения через curses
        try:
            curses.wrapper(lambda stdscr: asyncio.run(main(stdscr)))
        except KeyboardInterrupt:
            # Обрабатываем KeyboardInterrupt во время работы curses
            pass
        finally:
            # Восстанавливаем консоль
            try:
                curses.endwin()
            except:
                pass
            os.system("clear")
            print("Bye!")
    
if __name__ == "__main__":
    start_app() 