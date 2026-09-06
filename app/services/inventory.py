from __future__ import annotations

from datetime import date, datetime, timedelta
from sqlite3 import Row
from uuid import uuid4

from app.core.database import get_connection


def inventory_item_belongs_to_scope(item_id: int, organization_id: int, location_id: int) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id FROM inventory_items WHERE id=? AND organization_id=? AND location_id=?",
            (item_id, organization_id, location_id),
        ).fetchone()
    return row is not None


def list_inventory_items(
    search: str = "",
    category: str = "",
    status: str = "",
    organization_id: str = "",
    location_id: str = "",
    item_type: str = "",
    storage_area: str = "",
    supplier: str = "",
    expiry: str = "",
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
            inventory_items.product_id,
            inventory_items.item_type,
            inventory_items.unit_measure,
            inventory_items.lot_status,
            inventory_items.retired_at,
            inventory_items.retirement_reason,
            inventory_items.cold_chain_incident,
            inventory_items.manufacturer,
            inventory_items.received_date,
            inventory_items.document_number,
            inventory_items.presentation,
            inventory_items.concentration,
            inventory_items.serial_number,
            inventory_items.reception_temperature_c,
            inventory_items.reception_note,
            inventory_items.received_by_user_id,
            inventory_items.is_test,
            inventory_items.is_quarantined,
            inventory_items.quarantine_reason,
            inventory_items.replenishment_request_id,
            organizations.name AS organization_name,
            locations.name AS site_name,
            locations.city AS site_city
            , receiver.full_name AS received_by_name
        FROM inventory_items
        LEFT JOIN organizations ON organizations.id = inventory_items.organization_id
        LEFT JOIN locations ON locations.id = inventory_items.location_id
        LEFT JOIN users AS receiver ON receiver.id = inventory_items.received_by_user_id
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
    if status == "retired":
        query += " AND inventory_items.lot_status = 'retired'"
    else:
        query += " AND inventory_items.lot_status = 'active'"
    if item_type:
        query += " AND inventory_items.item_type = :item_type"
        params["item_type"] = item_type.strip()
    if storage_area:
        query += " AND inventory_items.location = :storage_area"
        params["storage_area"] = storage_area.strip()
    if supplier:
        query += " AND inventory_items.supplier = :supplier"
        params["supplier"] = supplier.strip()

    with get_connection() as connection:
        rows = connection.execute(
            query
            + """
                ORDER BY
                    CASE
                        WHEN inventory_items.expiry_date < :today THEN 0
                        ELSE 1
                    END,
                    inventory_items.expiry_date ASC,
                    inventory_items.name ASC
            """,
            {**params, "today": date.today().isoformat()},
        ).fetchall()

    items = [serialize_inventory_row(row) for row in rows]
    if expiry == "expired":
        items = [item for item in items if item["expiry_days"] < 0]
    elif expiry == "soon":
        items = [item for item in items if 0 <= item["expiry_days"] <= 90]
    if status and status != "retired":
        if status == "low":
            items = [item for item in items if item["is_low_stock"]]
        else:
            items = [item for item in items if item["status_level"] == status]
    return items


def create_inventory_item(payload: dict) -> None:
    payload = {**payload, "replenishment_request_id": int(payload.get("replenishment_request_id") or 0) or None}
    if date.fromisoformat(payload["expiry_date"]) < date.today():
        raise ValueError("No se puede registrar un lote que ya está vencido.")
    if payload["quantity"] < 0 or payload["min_stock"] < 0 or payload["unit_cost"] < 0 or payload["sale_price"] < 0:
        raise ValueError("Cantidades, costos y precios no pueden ser negativos.")
    if payload.get("requires_cold_chain") and not payload.get("storage_condition", "").strip():
        raise ValueError("Indica la condición de almacenamiento para cadena de frío.")
    if not payload.get("document_number", "").strip():
        raise ValueError("Indica la factura o remisión de recepción.")
    received_date = date.fromisoformat(payload["received_date"])
    if received_date > date.today():
        raise ValueError("La fecha de recepción no puede estar en el futuro.")
    if payload.get("requires_cold_chain") and payload.get("reception_temperature_c") is None:
        raise ValueError("Registra la temperatura recibida para conservar la cadena de frío.")
    with get_connection() as connection:
        if payload.get("product_id"):
            product = connection.execute("SELECT * FROM inventory_products WHERE id=? AND organization_id=?", (payload["product_id"], payload["organization_id"])).fetchone()
            if not product:
                raise ValueError("El producto seleccionado no existe.")
            payload.update(name=product["name"], brand=product["brand"], barcode=product["barcode"], regulatory_agency=product["regulatory_agency"], regulatory_code=product["regulatory_code"], item_type=product["item_type"], unit_measure=product["unit_measure"], storage_condition=payload.get("storage_condition") or product["storage_condition"], requires_cold_chain=product["requires_cold_chain"], manufacturer=product["manufacturer"], presentation=product["presentation"], concentration=product["concentration"])
        duplicate = connection.execute(
            "SELECT id FROM inventory_items WHERE organization_id = ? AND lower(name) = lower(?) AND lower(lot) = lower(?) AND lot_status = 'active'",
            (payload["organization_id"], payload["name"], payload["lot"]),
        ).fetchone()
        if duplicate:
            raise ValueError("Este lote ya existe para el producto seleccionado.")
        product_id = ensure_inventory_product(connection, payload)
        payload = {**payload, "product_id": product_id}
        connection.execute(
            """
            INSERT INTO inventory_items (
                organization_id, location_id, name, barcode, category, brand, regulatory_agency,
                regulatory_code, supplier, lot, quantity, min_stock, unit_cost, sale_price,
                storage_condition, requires_cold_chain, location, last_counted_at, expiry_date,
                product_id, item_type, unit_measure, lot_status
                , manufacturer, received_date, document_number, presentation, concentration,
                serial_number, reception_temperature_c, reception_note, received_by_user_id, is_test
                , replenishment_request_id
            )
            VALUES (
                :organization_id, :location_id, :name, :barcode, :category, :brand, :regulatory_agency,
                :regulatory_code, :supplier, :lot, :quantity, :min_stock, :unit_cost, :sale_price,
                :storage_condition, :requires_cold_chain, :location, :last_counted_at, :expiry_date,
                :product_id, :item_type, :unit_measure, 'active'
                , :manufacturer, :received_date, :document_number, :presentation, :concentration,
                :serial_number, :reception_temperature_c, :reception_note, :received_by_user_id, :is_test
                , :replenishment_request_id
            )
            """,
            payload,
        )
        created = connection.execute(
            "SELECT id FROM inventory_items WHERE organization_id=? AND lower(name)=lower(?) AND lower(lot)=lower(?) ORDER BY id DESC LIMIT 1",
            (payload["organization_id"], payload["name"], payload["lot"]),
        ).fetchone()
        item_id = created["id"]
        replenishment_id = int(payload.get("replenishment_request_id") or 0)
        if replenishment_id:
            request_row = connection.execute(
                "SELECT id FROM inventory_replenishments WHERE id=? AND organization_id=? AND location_id=? AND status='Aprobada'",
                (replenishment_id, payload["organization_id"], payload["location_id"]),
            ).fetchone()
            if request_row is None:
                raise ValueError("La solicitud de abastecimiento no está aprobada para esta sede.")
            connection.execute(
                "UPDATE inventory_replenishments SET status='Recibida', received_inventory_item_id=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
                (item_id, replenishment_id),
            )
        if payload["quantity"] > 0:
            connection.execute(
                """INSERT INTO inventory_movements (item_id,organization_id,location_id,user_id,movement_type,quantity,note,reason_type,stock_before,stock_after)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (item_id, payload["organization_id"], payload["location_id"], payload.get("received_by_user_id"),
                 "in", payload["quantity"], f"Documento {payload['document_number']}", "Recepción", 0, payload["quantity"]),
            )
        if payload.get("requires_cold_chain"):
            temperature = float(payload["reception_temperature_c"])
            incident = int(temperature < 2 or temperature > 8)
            connection.execute(
                "INSERT INTO cold_chain_logs (item_id,organization_id,location_id,user_id,temperature_c,has_incident,note) VALUES (?,?,?,?,?,?,?)",
                (item_id, payload["organization_id"], payload["location_id"], payload.get("received_by_user_id"), temperature, incident, payload.get("reception_note", "")),
            )
            connection.execute("UPDATE inventory_items SET cold_chain_incident=? WHERE id=?", (incident, item_id))
        connection.commit()


def ensure_inventory_product(connection, payload: dict) -> int:
    if payload.get("product_id"):
        row = connection.execute("SELECT id FROM inventory_products WHERE id = ?", (payload["product_id"],)).fetchone()
        if row:
            return row["id"]
    row = connection.execute(
        "SELECT id FROM inventory_products WHERE organization_id = ? AND lower(name) = lower(?) AND lower(brand) = lower(?)",
        (payload["organization_id"], payload["name"], payload["brand"]),
    ).fetchone()
    if row:
        return row["id"]
    connection.execute(
        """INSERT INTO inventory_products (organization_id,name,brand,barcode,regulatory_agency,regulatory_code,item_type,unit_measure,storage_condition,requires_cold_chain,manufacturer,presentation,concentration)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (payload["organization_id"], payload["name"], payload["brand"], payload.get("barcode", ""),
         payload["regulatory_agency"], payload["regulatory_code"], payload["item_type"], payload["unit_measure"],
         payload.get("storage_condition", ""), payload.get("requires_cold_chain", 0), payload.get("manufacturer", ""),
         payload.get("presentation", ""), payload.get("concentration", "")),
    )
    created = connection.execute(
        "SELECT id FROM inventory_products WHERE organization_id=? AND lower(name)=lower(?) AND lower(brand)=lower(?) ORDER BY id DESC LIMIT 1",
        (payload["organization_id"], payload["name"], payload["brand"]),
    ).fetchone()
    return created["id"]


def list_inventory_products(organization_id: str = "") -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM inventory_products WHERE (? = '' OR organization_id = ?) ORDER BY name",
            (organization_id, int(organization_id) if organization_id else 0),
        ).fetchall()
    return [dict(row) for row in rows]


def list_inventory_replenishments(
    organization_id: str = "",
    location_id: str = "",
    limit: int = 20,
) -> list[dict]:
    query = """
        SELECT r.*, i.name AS item_name, i.lot, i.quantity AS current_quantity,
               i.min_stock, i.unit_measure, requester.full_name AS requested_by_name,
               reviewer.full_name AS reviewed_by_name, locations.name AS site_name
        FROM inventory_replenishments AS r
        INNER JOIN inventory_items AS i ON i.id=r.item_id
        LEFT JOIN users AS requester ON requester.id=r.requested_by_user_id
        LEFT JOIN users AS reviewer ON reviewer.id=r.reviewed_by_user_id
        LEFT JOIN locations ON locations.id=r.location_id
        WHERE 1=1
    """
    params: list[int] = []
    if organization_id:
        query += " AND r.organization_id=?"
        params.append(int(organization_id))
    if location_id:
        query += " AND r.location_id=?"
        params.append(int(location_id))
    query += " ORDER BY CASE r.status WHEN 'Pendiente' THEN 0 WHEN 'Aprobada' THEN 1 ELSE 2 END, r.created_at DESC, r.id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    return [
        {
            **dict(row),
            "created_at": format_created_at(row["created_at"]),
            "requested_by_name": row["requested_by_name"] or "Sistema",
            "reviewed_by_name": row["reviewed_by_name"] or "",
        }
        for row in rows
    ]


def create_inventory_replenishment(
    item_id: int,
    requested_quantity: float,
    supplier: str,
    priority: str,
    note: str,
    user_id: int | None,
) -> tuple[bool, str]:
    if requested_quantity <= 0:
        return False, "La cantidad solicitada debe ser mayor que cero."
    if not supplier.strip():
        return False, "Indica el proveedor sugerido."
    safe_priority = priority if priority in {"Normal", "Urgente"} else "Normal"
    with get_connection() as connection:
        item = connection.execute(
            "SELECT id, organization_id, location_id, name, lot_status FROM inventory_items WHERE id=?",
            (item_id,),
        ).fetchone()
        if item is None or item["lot_status"] != "active":
            return False, "El lote seleccionado no está disponible."
        duplicate = connection.execute(
            "SELECT id FROM inventory_replenishments WHERE item_id=? AND status IN ('Pendiente','Aprobada')",
            (item_id,),
        ).fetchone()
        if duplicate:
            return False, "Ya existe una solicitud abierta para este producto."
        connection.execute(
            """INSERT INTO inventory_replenishments (
                organization_id, location_id, item_id, requested_by_user_id,
                requested_quantity, supplier, priority, note, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pendiente')""",
            (item["organization_id"], item["location_id"], item_id, user_id,
             requested_quantity, supplier.strip(), safe_priority, note.strip()),
        )
        connection.commit()
    return True, "Solicitud de abastecimiento creada."


def review_inventory_replenishment(
    request_id: int,
    decision: str,
    user_id: int | None,
    organization_id: int,
    location_id: int,
) -> tuple[bool, str]:
    target_status = {"approve": "Aprobada", "reject": "Rechazada"}.get(decision)
    if not target_status:
        return False, "Decisión no válida."
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, status FROM inventory_replenishments WHERE id=? AND organization_id=? AND location_id=?",
            (request_id, organization_id, location_id),
        ).fetchone()
        if row is None:
            return False, "La solicitud no existe."
        if row["status"] != "Pendiente":
            return False, "Esta solicitud ya fue revisada."
        connection.execute(
            "UPDATE inventory_replenishments SET status=?, reviewed_by_user_id=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
            (target_status, user_id, request_id),
        )
        connection.commit()
    return True, f"Solicitud {target_status.lower()}."


def inventory_network_summary(organization_id: str = "") -> list[dict]:
    if not organization_id:
        return []
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT l.id, l.name,
                   COUNT(i.id) AS active_lots,
                   COALESCE(SUM(i.quantity), 0) AS total_units,
                   COALESCE(SUM(i.quantity * i.unit_cost), 0) AS stock_value,
                   COALESCE(SUM(CASE WHEN i.id IS NOT NULL AND i.quantity <= i.min_stock THEN 1 ELSE 0 END), 0) AS low_stock,
                   COALESCE(SUM(CASE WHEN i.is_quarantined=1 OR i.expiry_date <= ? THEN 1 ELSE 0 END), 0) AS critical
            FROM locations AS l
            LEFT JOIN inventory_items AS i ON i.location_id=l.id AND i.lot_status='active'
            WHERE l.organization_id=? AND l.is_active=1 AND l.catalog_kind='veterinaria'
            GROUP BY l.id, l.name ORDER BY l.name
            """,
            ((date.today() + timedelta(days=90)).isoformat(), int(organization_id)),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_inventory_item(item_id: int) -> None:
    with get_connection() as connection:
        movements = connection.execute("SELECT COUNT(*) AS total FROM inventory_movements WHERE item_id = ?", (item_id,)).fetchone()
        if movements and movements["total"]:
            raise ValueError("No se puede borrar un lote con historial. Retíralo para conservar la trazabilidad.")
        connection.execute(
            "DELETE FROM inventory_items WHERE id = ?",
            (item_id,),
        )
        connection.commit()


def update_inventory_item(item_id: int, payload: dict) -> None:
    if payload["min_stock"] < 0 or payload["unit_cost"] < 0 or payload["sale_price"] < 0:
        raise ValueError("Los valores numéricos no pueden ser negativos.")
    with get_connection() as connection:
        duplicate = connection.execute(
            "SELECT id FROM inventory_items WHERE organization_id=? AND lower(name)=lower(?) AND lower(lot)=lower(?) AND id!=? AND lot_status='active'",
            (payload["organization_id"], payload["name"], payload["lot"], item_id),
        ).fetchone()
        if duplicate:
            raise ValueError("Ya existe otro lote con esa identificación.")
        connection.execute(
            """UPDATE inventory_items SET name=?,brand=?,supplier=?,barcode=?,regulatory_code=?,lot=?,
               expiry_date=?,min_stock=?,unit_cost=?,sale_price=?,location=?,storage_condition=?,
               requires_cold_chain=?,item_type=?,unit_measure=? WHERE id=?""",
            (payload["name"],payload["brand"],payload["supplier"],payload["barcode"],payload["regulatory_code"],
             payload["lot"],payload["expiry_date"],payload["min_stock"],payload["unit_cost"],payload["sale_price"],
             payload["location"],payload["storage_condition"],payload["requires_cold_chain"],payload["item_type"],
             payload["unit_measure"],item_id),
        )
        connection.commit()


def retire_inventory_lot(item_id: int, quantity: float, reason: str, user_id: int | None = None) -> tuple[bool, str]:
    ok, message = create_inventory_movement(item_id, "out", quantity, reason, user_id, reason_type="Retiro")
    if not ok:
        return ok, message
    with get_connection() as connection:
        row = connection.execute("SELECT quantity FROM inventory_items WHERE id=?", (item_id,)).fetchone()
        if row and float(row["quantity"]) <= 0:
            connection.execute("UPDATE inventory_items SET lot_status='retired',retired_at=CURRENT_TIMESTAMP,retirement_reason=? WHERE id=?", (reason.strip(),item_id))
            connection.commit()
    return True, "Retiro registrado con trazabilidad."


def count_inventory_item(item_id: int, counted_quantity: float, note: str, user_id: int | None = None) -> tuple[bool, str]:
    with get_connection() as connection:
        row = connection.execute("SELECT quantity FROM inventory_items WHERE id=?", (item_id,)).fetchone()
    if row is None or counted_quantity < 0:
        return False, "Cantidad de conteo inválida."
    difference = counted_quantity - float(row["quantity"])
    if difference:
        ok, message = create_inventory_movement(item_id, "in" if difference > 0 else "out", abs(difference), note, user_id, reason_type="Conteo físico")
        if not ok: return ok, message
    with get_connection() as connection:
        connection.execute("UPDATE inventory_items SET last_counted_at=CURRENT_TIMESTAMP WHERE id=?", (item_id,))
        connection.commit()
    return True, f"Conteo guardado. Diferencia: {difference:g}."


def record_cold_chain(item_id: int, temperature_c: float, note: str, user_id: int | None = None) -> tuple[bool, str]:
    with get_connection() as connection:
        row = connection.execute("SELECT organization_id,location_id,requires_cold_chain FROM inventory_items WHERE id=?", (item_id,)).fetchone()
        if row is None or not row["requires_cold_chain"]:
            return False, "El lote no está marcado para cadena de frío."
        incident = int(temperature_c < 2 or temperature_c > 8)
        connection.execute("INSERT INTO cold_chain_logs (item_id,organization_id,location_id,user_id,temperature_c,has_incident,note) VALUES (?,?,?,?,?,?,?)", (item_id,row["organization_id"],row["location_id"],user_id,temperature_c,incident,note.strip()))
        connection.execute("UPDATE inventory_items SET cold_chain_incident=? WHERE id=?", (incident, item_id))
        connection.commit()
    return True, "Temperatura registrada." + (" Se detectó una incidencia." if incident else "")


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
            inventory_items.expiry_date,
            inventory_items.unit_measure,
            inventory_items.is_quarantined,
            locations.name AS site_name
        FROM inventory_items
        LEFT JOIN locations ON locations.id = inventory_items.location_id
        WHERE inventory_items.lot_status = 'active'
    """
    params: list[int] = []
    if organization_id:
        query += " AND inventory_items.organization_id = ?"
        params.append(int(organization_id))
    if location_id:
        query += " AND inventory_items.location_id = ?"
        params.append(int(location_id))
    query += " ORDER BY inventory_items.name ASC, inventory_items.expiry_date ASC"
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    return [
        {
            "id": row["id"],
            "label": (
                f"{row['name']} · lote {row['lot']} · vence {row['expiry_date']} · {row['quantity']} {row['unit_measure']}"
                f"{' · CUARENTENA' if row['is_quarantined'] else ''}"
            ),
            "is_quarantined": bool(row["is_quarantined"]),
            "is_expired": date.fromisoformat(row["expiry_date"]) < date.today(),
            "quantity": float(row["quantity"]),
        }
        for row in rows
    ]


def create_inventory_movement(
    item_id: int,
    movement_type: str,
    quantity: float,
    note: str,
    user_id: int | None = None,
    reason_type: str = "Movimiento",
    temperature_c: float | None = None,
    patient_id: int | None = None,
    appointment_id: int | None = None,
    priority: str = "Normal",
    external_reference: str = "",
) -> tuple[bool, str]:
    if movement_type not in {"in", "out"}:
        return False, "La operación debe ser una entrada o una salida."
    if not note.strip():
        return False, "Agrega una referencia breve para conservar la trazabilidad."
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, quantity, expiry_date, lot_status, is_quarantined
                , organization_id, location_id
            FROM inventory_items
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()

        if row is None:
            return False, "El producto seleccionado no existe."

        linked_patient_id = int(patient_id or 0) or None
        linked_appointment_id = int(appointment_id or 0) or None
        if reason_type.strip() == "Consumo clínico":
            if row["lot_status"] != "active":
                return False, "El lote está cerrado y no puede utilizarse en pacientes."
            if row["is_quarantined"]:
                return False, "El lote está en cuarentena y no puede utilizarse en pacientes."
            if date.fromisoformat(row["expiry_date"]) < date.today():
                return False, "El lote está vencido y no puede utilizarse en pacientes."
            if linked_appointment_id:
                appointment = connection.execute(
                    "SELECT patient_id, organization_id, location_id FROM appointments WHERE id=?",
                    (linked_appointment_id,),
                ).fetchone()
                if appointment is None or appointment["organization_id"] != row["organization_id"] or appointment["location_id"] != row["location_id"]:
                    return False, "La cita seleccionada no pertenece a la sede del lote."
                linked_patient_id = appointment["patient_id"] or linked_patient_id
            if not linked_patient_id:
                return False, "Selecciona el paciente en el que se utilizó el insumo."
            patient = connection.execute(
                "SELECT id FROM patients WHERE id=? AND organization_id=? AND location_id=?",
                (linked_patient_id, row["organization_id"], row["location_id"]),
            ).fetchone()
            if patient is None:
                return False, "El paciente seleccionado no pertenece a la sede del lote."

        if quantity <= 0:
            return False, "La cantidad debe ser mayor que cero."
        delta = quantity if movement_type == "in" else -quantity
        if movement_type == "out":
            updated = connection.execute(
                "UPDATE inventory_items SET quantity=quantity-? WHERE id=? AND quantity>=?",
                (quantity, item_id, quantity),
            )
            if updated.rowcount != 1:
                available = connection.execute("SELECT quantity FROM inventory_items WHERE id=?", (item_id,)).fetchone()
                return False, f"No hay stock suficiente para la salida. Disponible: {float(available['quantity']):g}."
        else:
            connection.execute("UPDATE inventory_items SET quantity=quantity+? WHERE id=?", (quantity, item_id))
        updated_row = connection.execute("SELECT quantity FROM inventory_items WHERE id=?", (item_id,)).fetchone()
        updated_quantity = float(updated_row["quantity"])
        current_quantity = updated_quantity - delta
        connection.execute(
            """
            INSERT INTO inventory_movements (
                item_id, organization_id, location_id, user_id, movement_type, quantity, note,
                reason_type, stock_before, stock_after, temperature_c, patient_id, appointment_id,
                priority, external_reference
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                row["organization_id"],
                row["location_id"],
                user_id,
                movement_type,
                quantity,
                note.strip(),
                reason_type.strip(), current_quantity, updated_quantity, temperature_c,
                linked_patient_id, linked_appointment_id,
                priority.strip() or "Normal", external_reference.strip(),
            ),
        )
        connection.commit()

    return True, "Movimiento registrado correctamente."


def set_inventory_quarantine(item_id: int, enabled: bool, reason: str) -> tuple[bool, str]:
    if enabled and not reason.strip():
        return False, "Indica el motivo de la cuarentena."
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, lot_status FROM inventory_items WHERE id=?",
            (item_id,),
        ).fetchone()
        if row is None:
            return False, "El lote seleccionado no existe."
        if row["lot_status"] != "active":
            return False, "Un lote cerrado no puede cambiar de cuarentena."
        connection.execute(
            "UPDATE inventory_items SET is_quarantined=?, quarantine_reason=? WHERE id=?",
            (int(enabled), reason.strip() if enabled else "", item_id),
        )
        connection.commit()
    return True, "Lote puesto en cuarentena." if enabled else "Lote liberado para uso."


def transfer_inventory_item(
    item_id: int,
    quantity: float,
    destination_location_id: int,
    destination_storage: str,
    note: str,
    user_id: int | None = None,
) -> tuple[bool, str, str]:
    if quantity <= 0:
        return False, "La cantidad debe ser mayor que cero.", ""
    if not destination_storage.strip() or not note.strip():
        return False, "Indica la ubicación de destino y una referencia del traslado.", ""
    transfer_reference = f"TR-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"
    with get_connection() as connection:
        source = connection.execute("SELECT * FROM inventory_items WHERE id=?", (item_id,)).fetchone()
        if source is None:
            return False, "El lote seleccionado no existe.", ""
        destination = connection.execute(
            "SELECT id, name FROM locations WHERE id=? AND organization_id=? AND is_active=1",
            (destination_location_id, source["organization_id"]),
        ).fetchone()
        if destination is None or destination_location_id == source["location_id"]:
            return False, "Selecciona otra sede activa de la misma organización.", ""
        if source["lot_status"] != "active" or source["is_quarantined"]:
            return False, "El lote está cerrado o en cuarentena y no puede trasladarse.", ""
        if date.fromisoformat(source["expiry_date"]) < date.today():
            return False, "Un lote vencido no puede trasladarse.", ""
        source_before = float(source["quantity"])

        target = connection.execute(
            "SELECT * FROM inventory_items WHERE organization_id=? AND location_id=? AND product_id=? AND lower(lot)=lower(?) AND lot_status='active'",
            (source["organization_id"], destination_location_id, source["product_id"], source["lot"]),
        ).fetchone()
        if target is None:
            connection.execute(
                """INSERT INTO inventory_items (
                    organization_id, location_id, name, barcode, category, brand, regulatory_agency,
                    regulatory_code, supplier, lot, quantity, min_stock, unit_cost, sale_price,
                    storage_condition, requires_cold_chain, location, last_counted_at, expiry_date,
                    product_id, item_type, unit_measure, lot_status, manufacturer, received_date,
                    document_number, presentation, concentration, serial_number,
                    reception_temperature_c, reception_note, received_by_user_id, is_test,
                    is_quarantined, quarantine_reason
                ) SELECT organization_id, ?, name, barcode, category, brand, regulatory_agency,
                    regulatory_code, supplier, lot, 0, min_stock, unit_cost, sale_price,
                    storage_condition, requires_cold_chain, ?, '', expiry_date,
                    product_id, item_type, unit_measure, 'active', manufacturer, received_date,
                    ?, presentation, concentration, serial_number,
                    reception_temperature_c, ?, ?, is_test, 0, ''
                  FROM inventory_items WHERE id=?""",
                (destination_location_id, destination_storage.strip(), transfer_reference, f"Traslado desde {source['location_id']}", user_id, item_id),
            )
            target = connection.execute(
                "SELECT * FROM inventory_items WHERE organization_id=? AND location_id=? AND product_id=? AND lower(lot)=lower(?) AND lot_status='active' ORDER BY id DESC LIMIT 1",
                (source["organization_id"], destination_location_id, source["product_id"], source["lot"]),
            ).fetchone()

        target_before = float(target["quantity"])
        source_update = connection.execute(
            "UPDATE inventory_items SET quantity=quantity-? WHERE id=? AND quantity>=?",
            (quantity, source["id"], quantity),
        )
        if source_update.rowcount != 1:
            available = connection.execute("SELECT quantity FROM inventory_items WHERE id=?", (source["id"],)).fetchone()
            return False, f"No hay stock suficiente. Disponible: {float(available['quantity']):g}.", ""
        source_after_row = connection.execute("SELECT quantity FROM inventory_items WHERE id=?", (source["id"],)).fetchone()
        source_after = float(source_after_row["quantity"])
        source_before = source_after + quantity
        target_after = target_before + quantity
        connection.execute("UPDATE inventory_items SET quantity=quantity+?, location=? WHERE id=?", (quantity, destination_storage.strip(), target["id"]))
        movement_sql = """INSERT INTO inventory_movements (
            item_id, organization_id, location_id, user_id, movement_type, quantity, note,
            reason_type, stock_before, stock_after, priority, external_reference,
            counterparty_location_id, transfer_reference
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Normal', ?, ?, ?)"""
        connection.execute(movement_sql, (
            source["id"], source["organization_id"], source["location_id"], user_id, "out", quantity,
            note.strip(), "Traslado enviado", source_before, source_after, transfer_reference,
            destination_location_id, transfer_reference,
        ))
        connection.execute(movement_sql, (
            target["id"], source["organization_id"], destination_location_id, user_id, "in", quantity,
            note.strip(), "Traslado recibido", target_before, target_after, transfer_reference,
            source["location_id"], transfer_reference,
        ))
        connection.commit()
    return True, f"Traslado completado hacia {destination['name']}.", transfer_reference


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
            m.reason_type,
            m.stock_before,
            m.stock_after,
            m.temperature_c,
            m.patient_id,
            m.appointment_id,
            m.priority,
            m.external_reference,
            m.counterparty_location_id,
            m.transfer_reference,
            m.created_at,
            i.name,
            i.lot,
            i.location,
            locations.name AS site_name,
            users.full_name AS responsible_name
            , patients.display_name AS patient_name
            , appointments.appointment_date
            , appointments.appointment_time
            , counterparty.name AS counterparty_location_name
        FROM inventory_movements AS m
        INNER JOIN inventory_items AS i ON i.id = m.item_id
        LEFT JOIN locations ON locations.id = m.location_id
        LEFT JOIN users ON users.id = m.user_id
        LEFT JOIN patients ON patients.id = m.patient_id
        LEFT JOIN appointments ON appointments.id = m.appointment_id
        LEFT JOIN locations AS counterparty ON counterparty.id = m.counterparty_location_id
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

    if row["is_quarantined"]:
        badge = "Cuarentena"
        badge_class = "red"
        days_label = row["quarantine_reason"] or "Uso bloqueado"

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
        "item_type": row["item_type"],
        "unit_measure": row["unit_measure"],
        "lot_status": row["lot_status"],
        "retired_at": row["retired_at"],
        "retirement_reason": row["retirement_reason"],
        "product_id": row["product_id"],
        "cold_chain_incident": bool(row["cold_chain_incident"]),
        "manufacturer": row["manufacturer"],
        "received_date": row["received_date"],
        "document_number": row["document_number"],
        "presentation": row["presentation"],
        "concentration": row["concentration"],
        "serial_number": row["serial_number"],
        "reception_temperature_c": row["reception_temperature_c"],
        "reception_note": row["reception_note"],
        "received_by_user_id": row["received_by_user_id"],
        "is_test": bool(row["is_test"]),
        "is_quarantined": bool(row["is_quarantined"]),
        "quarantine_reason": row["quarantine_reason"] or "",
        "replenishment_request_id": row["replenishment_request_id"],
        "received_by_name": row["received_by_name"] or "Sistema",
        "expiry_days": days_left,
        "created_at": format_created_at(row["created_at"]),
    }


def serialize_movement_row(row: Row) -> dict:
    direction = row["reason_type"] or ("Entrada" if row["movement_type"] == "in" else "Salida")
    tone = "green" if row["movement_type"] == "in" else "red"
    return {
        "id": row["id"],
        "item_name": row["name"],
        "lot": row["lot"],
        "site_name": row["site_name"] or "-",
        "storage_area": row["location"],
        "direction": direction,
        "reason_type": row["reason_type"] or direction,
        "tone": tone,
        "quantity": row["quantity"],
        "note": row["note"],
        "stock_before": row["stock_before"],
        "stock_after": row["stock_after"],
        "temperature_c": row["temperature_c"],
        "patient_id": row["patient_id"],
        "patient_name": row["patient_name"] or "",
        "appointment_id": row["appointment_id"],
        "appointment_label": (
            f"{row['appointment_date']} · {row['appointment_time']}"
            if row["appointment_id"] else ""
        ),
        "priority": row["priority"] or "Normal",
        "external_reference": row["external_reference"] or "",
        "counterparty_location_name": row["counterparty_location_name"] or "",
        "transfer_reference": row["transfer_reference"] or "",
        "responsible_name": row["responsible_name"] or "Sistema",
        "created_at": format_created_at(row["created_at"]),
    }


def format_created_at(value: str) -> str:
    if isinstance(value, datetime):
        created_at = value
    else:
        created_at = datetime.fromisoformat(str(value))
    return created_at.strftime("%Y-%m-%d %H:%M")
