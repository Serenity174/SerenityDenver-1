from decimal import ROUND_HALF_UP, Decimal

ITEM_PRICES = {
    "Марлин": 0.858,
    "Красный горбыль": 0.858,
    "Тёмный горбыль": 0.793,
    "Железо": 61,
    "Серебро": 130,
    "Медь": 250,
    "Олово": 265,
    "Золото": 398,
    "Рубашки": 1400,
    "Апельсины": 44,
    "Шампиньоны": 82,
    "Гипсизикусы": 112,
    "Вешенки": 95,
    "Сосновые брёвна": 190,
    "Дубовые бревна": 231,
    "Пшеница": 364,
    "Мухоморы": 124,
    "Подболотники": 150,
    "Подберёзовики": 173,
    "Берёза": 280,
    "Клён": 337,
    "Картофель": 480,
    "Капуста": 641,
    "Кукуруза": 971,
    "Тыквы": 1208,
    "Бананы": 1882,
}


def report_total(category, quantity):
    from serenity.services.settings import prices

    current_prices = prices()
    if category not in current_prices:
        raise ValueError("Неизвестная категория отчёта.")
    if not 1 <= quantity <= 1_000_000:
        raise ValueError("Количество должно быть от 1 до 1 000 000.")
    total = (Decimal(str(current_prices[category])) * quantity).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if total > Decimal("9999999999.99"):
        raise ValueError("Сумма отчёта слишком велика. Уменьшите количество или проверьте цену.")
    return total
