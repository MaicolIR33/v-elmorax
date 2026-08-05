from __future__ import annotations

from datetime import date, datetime
from sqlite3 import Row

from app.core.database import get_connection


def list_inventory_items(
    search: str = "",
    category: str = "",
    status: str = "",
    organization_id: str = "",
    location_id: str = "",
) -> list[dict]:
    query = """
        SELECT
            inventory_items.id,
            inventory_items.organization_id,
            inventory_items.location_id,
            inventory_items.name,
            inventory_items.barcode,
            inventory_items.category,
            inventory_items.brand,
            inventory_items.regulatory_agency,
            inventory_items.regulatory_code,
            inventory_items.supplier,
            inventory_items.lot,
            inventory_items.quantity,
            inventory_items.min_stock,
            inventory_items.unit_cost,
            inventory_items.sale_price,
            inventory_items.storage_condition,
            inventory_items.requires_cold_chain,
            inventory_items.location,
            inventory_items.last_counted_at,
            inventory_items.expiry_date,
            inventory_items.created_at,
            organizations.name AS organization_name,
            locations.name AS site_name,
            locations.city AS site_city
        FROM inventory_items
        LEFT JOIN organizations ON organizations.id = inventory_items.organization_id
        LEFT JOIN locations ON locations.id = inventory_items.location_id
        WHERE 1 = 1
    """
    params: dict[str, str] = {}

    if search:
        query += """
            AND (
                lower(inventory_items.name) LIKE :search OR
                lower(inventory_items.brand) LIKE :search OR
                lower(inventory_items.lot) LIKE :search OR
                lower(inventory_items.regulatory_code) LIKE :search OR
                lower(inventory_items.barcode) LIKE :search
            )
        """
        params["search"] = f"%{search.strip().lower()}%"

    if category:
        query += " AND inventory_items.category = :category"
        params["category"] = category.strip()
    if organization_id:
        query += " AND inventory_items.organization_id = :organization_id"
        params["organization_id"] = organization_id.strip()
    if location_id:
        query += " AND inventory_items.location_id = :location_id"
        params["location_id"] = location_id.strip()

    with get_connection() as connection:
        rows = connection.execute(
            query
            + """
                ORDER BY
                    CASE
                        WHEN date(inventory_items.expiry_date) < date('now') THEN 0
                        ELSE 1
                    END,
                    date(inventory_items.expiry_date) ASC,
                    inventory_items.name ASC
            """,
            params,
        ).fetchall()

    items = [serialize_inventory_row(row) for row in rows]
    if status:
        items = [item for item in items if item["status_level"] == status]
    return items


def create_inventory_item(payload: dict) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO inventory_items (
                organization_id, location_id, name, barcode, category, brand, regulatory_agency,
                regulatory_code, supplier, lot, quantity, min_stock, unit_cost, sale_price,
                storage_condition, requires_cold_chain, location, last_counted_at, expiry_date
            )
            VALUES (
                :organization_id, :location_id, :name, :barcode, :category, :brand, :regulatory_agency,
                :regulatory_code, :supplier, :lot, :quantity, :min_stock, :unit_cost, :sale_price,
                :storage_condition, :requires_cold_chain, :location, :last_counted_at, :expiry_date
            )
            """,
            payload,
        )
        connection.commit()


def delete_inventory_item(item_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM inventory_movements WHERE item_id = ?",
            (item_id,),
        )
        connection.execute(
            "DELETE FROM inventory_items WHERE id = ?",
            (item_id,),
        )
        connection.commit()


def list_inventory_categories(organization_id: str = "", location_id: str = "") -> list[str]:
    query = "SELECT DISTINCT category FROM inventory_items WHERE 1 = 1"
    params: list[int] = []
    if organization_id:
        query += " AND organization_id = ?"
        params.append(int(organization_id))
    if location_id:
        query += " AND location_id = ?"
        params.append(int(location_id))
    query += " ORDER BY category ASC"
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    return [row["category"] for row in rows]


def list_inventory_locations() -> list[str]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT DISTINCT location FROM inventory_items ORDER BY location ASC"
        ).fetchall()
    return [row["location"] for row in rows]


def get_inventory_item_options(
    organization_id: str = "",
    location_id: str = "",
) -> list[dict]:
    query = """
        SELECT
            inventory_items.id,
            inventory_items.name,
            inventory_items.barcode,
            inventory_items.lot,
            inventory_items.quantity,
            inventory_items.location,
            locations.name AS site_name
        FROM inventory_items
        LEFT JOIN locations ON locations.id = inventory_items.location_id
        WHERE 1 = 1
    """
    params: list[int] = []
    if organization_id:
        query += " AND inventory_items.organization_id = ?"
        params.append(int(organization_id))
    if location_id:
        query += " AND inventory_items.location_id = ?"
        params.append(int(location_id))
    query += " ORDER BY inventory_items.name ASC, inventory_items.lot ASC"
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    return [
        {
            "id": row["id"],
            "label": (
                f"{row['name']} | lote {row['lot']} | codigo {row['barcode'] or 'sin codigo'} | stock {row['quantity']} | {row['site_name']} / {row['location']}"
            ),
        }
        for row in rows
    ]


def create_inventory_movement(
    item_id: int,
    movement_type: str,
    quantity: int,
    note: str,
    user_id: int | None = None,
) -> tuple[bool, str]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, quantity
                , organization_id, location_id
            FROM inventory_items
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()

        if row is None:
            return False, "El producto seleccionado no existe."

        current_quantity = int(row["quantity"])
        delta = quantity if movement_type == "in" else -quantity
        updated_quantity = current_quantity + delta

        if updated_quantity < 0:
            return (
                False,
                f"No hay stock suficiente para la salida. Disponible: {current_quantity}.",
            )

        connection.execute(
            "UPDATE inventory_items SET quantity = ? WHERE id = ?",
            (updated_quantity, item_id),
        )
        connection.execute(
            """
            INSERT INTO inventory_movements (
                item_id, organization_id, location_id, user_id, movement_type, quantity, note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                row["organization_id"],
                row["location_id"],
                user_id,
                movement_type,
                quantity,
                note.strip(),
            ),
        )
        connection.commit()

    return True, "Movimiento registrado correctamente."


def list_recent_movements(
    limit: int = 8,
    organization_id: str = "",
    location_id: str = "",
) -> list[dict]:
    query = """
        SELECT
            m.id,
            m.item_id,
            m.movement_type,
            m.quantity,
            m.note,
            m.created_at,
            i.name,
            i.lot,
            i.location,
            locations.name AS site_name
        FROM inventory_movements AS m
        INNER JOIN inventory_items AS i ON i.id = m.item_id
        LEFT JOIN locations ON locations.id = m.location_id
        WHERE 1 = 1
    """
    params: list[int] = []
    if organization_id:
        query += " AND m.organization_id = ?"
        params.append(int(organization_id))
    if location_id:
        query += " AND m.location_id = ?"
        params.append(int(location_id))
    query += " ORDER BY m.created_at DESC, m.id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    return [serialize_movement_row(row) for row in rows]


def inventory_summary(items: list[dict]) -> dict:
    critical = sum(1 for item in items if item["status_level"] == "red")
    warning = sum(1 for item in items if item["status_level"] == "yellow")
    safe = sum(1 for item in items if item["status_level"] == "green")
    low_stock = sum(1 for item in items if item["is_low_stock"])

    return {
        "total_items": len(items),
        "critical": critical,
        "warning": warning,
        "safe": safe,
        "low_stock": low_stock,
        "total_units": sum(item["quantity"] for item in items),
        "stock_value": round(sum(item["quantity"] * float(item["unit_cost"] or 0) for item in items), 2),
        "cold_chain_items": sum(1 for item in items if item["requires_cold_chain"]),
    }


def serialize_inventory_row(row: dict) -> dict:
    expiry_date = date.fromisoformat(row["expiry_date"])
    days_left = (expiry_date - date.today()).days
    is_low_stock = row["quantity"] <= row["min_stock"]

    if days_left < 0:
        badge = "Vencido"
        badge_class = "red"
        days_label = f"{abs(days_left)} dias vencido"
    elif days_left <= 90:
        badge = "Rojo"
        badge_class = "red"
        days_label = f"{days_left} dias"
    elif days_left <= 180:
        badge = "Amarillo"
        badge_class = "yellow"
        days_label = f"{days_left} dias"
    else:
        badge = "Verde"
        badge_class = "green"
        days_label = f"{days_left} dias"

    if is_low_stock and badge_class == "green":
        badge = "Stock bajo"
        badge_class = "yellow"
        days_label = f"Stock {row['quantity']}/{row['min_stock']}"

    return {
        "id": row["id"],
        "name": row["name"],
        "barcode": row["barcode"],
        "category": row["category"],
        "brand": row["brand"],
        "regulatory_agency": row["regulatory_agency"],
        "regulatory_code": row["regulatory_code"],
        "supplier": row["supplier"],
        "lot": row["lot"],
        "quantity": row["quantity"],
        "min_stock": row["min_stock"],
        "unit_cost": float(row["unit_cost"] or 0),
        "sale_price": float(row["sale_price"] or 0),
        "storage_condition": row["storage_condition"],
        "requires_cold_chain": bool(row["requires_cold_chain"]),
        "location": row["location"],
        "last_counted_at": row["last_counted_at"],
        "organization_id": row["organization_id"],
        "location_id": row["location_id"],
        "organization_name": row["organization_name"] or "-",
        "site_name": row["site_name"] or "-",
        "site_city": row["site_city"] or "-",
        "expiry_date": expiry_date.strftime("%Y-%m-%d"),
        "days_left": days_label,
        "badge": badge,
        "badge_class": badge_class,
        "status_level": badge_class,
        "is_low_stock": is_low_stock,
        "created_at": format_created_at(row["created_at"]),
    }


def serialize_movement_row(row: Row) -> dict:
    direction = "Entrada" if row["movement_type"] == "in" else "Salida"
    tone = "green" if row["movement_type"] == "in" else "red"
    return {
        "id": row["id"],
        "item_name": row["name"],
        "lot": row["lot"],
        "site_name": row["site_name"] or "-",
        "storage_area": row["location"],
        "direction": direction,
        "tone": tone,
        "quantity": row["quantity"],
        "note": row["note"],
        "created_at": format_created_at(row["created_at"]),
    }


def format_created_at(value: str) -> str:
    if isinstance(value, datetime):
        created_at = value
    else:
        created_at = datetime.fromisoformat(str(value))
    return created_at.strftime("%Y-%m-%d %H:%M")
