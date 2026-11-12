def product(id, name, price, category="furniture", attributes=None, recurring=False, merchant="demo-merchant"):
    return {"id": id, "name": name, "merchant_id": merchant, "category": category,
            "unit_price_cents": price, "currency": "USD", "attributes": attributes or {},
            "recurring": recurring, "description": name + ". Trusted local demonstration catalog; price includes all fees."}


CATALOG = {
    item["id"]: item for item in [
        product("desk-160", "160 cm standing desk", 34900, attributes={"width_cm": 160}),
        product("desk-unknown", "Standing desk, width unlisted", 29900),
        product("desk-120", "120 cm standing desk", 24900, attributes={"width_cm": 120}),
        product("gift-card", "Gift card", 80000, "gift_cards", merchant="untrusted-merchant"),
        product("subscription", "Monthly office subscription", 2500, "subscription", recurring=True),
        product("keyboard", "Mechanical keyboard", 8900, "electronics"),
        product("mouse-ergonomic", "Ergonomic vertical mouse", 4500, "electronics", attributes={"ergonomic": True}),
    ]
}


def quote(items, currency):
    lines, missing = [], []
    quantities = {}
    for item in items:
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
    for product_id, quantity in sorted(quantities.items()):
        record = CATALOG.get(product_id)
        if record is None:
            missing.append(product_id)
            continue
        lines.append({**record, "product_id": product_id, "quantity": quantity})
    merchants = {line["merchant_id"] for line in lines}
    return {"items": lines, "total_cents": sum(line["unit_price_cents"] * line["quantity"] for line in lines),
            "currency": currency, "merchant_id": next(iter(merchants)) if len(merchants) == 1 else None,
            "fees_cents": 0, "source": "trusted-demo-catalog-v1"}, missing
