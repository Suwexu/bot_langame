
# ДОБАВИТЬ В КЛАСС LangameAPI

async def get_products(self) -> Dict:
    return await self._request("/products/list")

async def get_products_expense(self, date_from: str, date_to: str, page: int = 1) -> Dict:
    params = {
        "date_from": date_from,
        "date_to": date_to,
        "page": page
    }
    return await self._request("/products/expense", params=params)


# ПОЛНОСТЬЮ ЗАМЕНИТЬ get_stats_for_period НА ЭТУ ВЕРСИЮ

async def get_stats_for_period(date_from: datetime, date_to: datetime) -> Dict:
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str = date_to.strftime("%Y-%m-%d")

    operations = await api.get_operations(date_from_str, date_to_str)
    operations_data = operations.get("data", []) if operations.get("status") else []

    total_income = 0
    sessions_count = 0
    unique_guests = set()
    club_name = "CyberX"

    for item in operations_data:
        op_sum = safe_float(item.get("sum", 0))
        op_type = item.get("type", "")
        op_name = str(item.get("name", "")).lower()

        club_name = item.get("club_name", club_name)

        if op_type == "Пополнение" and op_sum > 0:
            total_income += op_sum

        if "сессия" in op_name or "session" in op_name:
            sessions_count += 1

        guest_name = item.get("name", "")
        if guest_name:
            unique_guests.add(guest_name)

    products = await api.get_products()

    goods_map = {}
    if products.get("status"):
        for product in products.get("data", []):
            goods_map[product["id"]] = product["name"]

    sales_by_product = {}

    first_page = await api.get_products_expense(
        date_from_str,
        date_to_str,
        page=1
    )

    total_pages = first_page.get("total_pages", 1)

    all_sales = []

    for page in range(1, total_pages + 1):
        response = await api.get_products_expense(
            date_from_str,
            date_to_str,
            page=page
        )

        if not response.get("status"):
            continue

        all_sales.extend(response.get("data", []))

    for sale in all_sales:

        if sale.get("cancel", 0) == 1:
            continue

        goods_id = sale.get("list_goods_id")

        if not goods_id:
            continue

        product_name = goods_map.get(
            goods_id,
            f"Товар #{goods_id}"
        )

        count = safe_float(sale.get("count", 1))
        price_sale = safe_float(sale.get("price_sale", 0))

        revenue = count * price_sale

        if product_name not in sales_by_product:
            sales_by_product[product_name] = 0

        sales_by_product[product_name] += revenue

    top_products = sorted(
        sales_by_product.items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]

    bar_revenue = sum(sales_by_product.values())

    days_count = max((date_to - date_from).days + 1, 1)

    avg_check = (
        total_income / sessions_count
        if sessions_count > 0 else 0
    )

    avg_daily = (
        total_income / days_count
        if days_count > 0 else 0
    )

    return {
        "period_from": date_from,
        "period_to": date_to,
        "days_count": days_count,
        "total_income": total_income,
        "avg_check": avg_check,
        "bar_revenue": bar_revenue,
        "sessions_count": sessions_count,
        "unique_guests": len(unique_guests),
        "top_products": top_products,
        "raw_operations": len(operations_data),
        "club_name": club_name,
        "avg_daily": avg_daily
    }
