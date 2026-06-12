FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем pip и system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Убеждаемся, что pip установлен и обновлен
RUN python -m ensurepip --upgrade

# Копируем requirements сначала (для кэширования слоев)
COPY requirements.txt .

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем весь код
COPY bot.py .
COPY utils/ ./utils/

# Команда запуска
CMD ["python", "-u", "bot.py"]