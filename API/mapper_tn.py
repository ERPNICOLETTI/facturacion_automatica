def map_tn_to_order(tn_order):
    """
    Transforma el JSON de Tiendanube al formato de nuestro sistema con inteligencia de datos.
    """
    customer = tn_order.get('customer', {})
    full_name = customer.get('name', 'Cliente Tiendanube')
    
    # 1. Identificación y Lógica de IVA (Heurística: 11 dígitos = CUIT)
    dni_cuit = str(customer.get('identification') or '').strip()
    is_cuit = len(dni_cuit.replace("-", "")) == 11
    
    # 2. Traducción de Métodos de Pago
    raw_method = tn_order.get('payment_details', {}).get('method', 'online')
    metodos = {
        "credit_card": "Tarjeta de Crédito",
        "wire_transfer": "Transferencia Bancaria",
        "debit_card": "Tarjeta de Débito",
        "wallet": "Billetera Virtual",
        "cash": "Efectivo / Punto de Pago"
    }
    payment_method = metodos.get(raw_method, "Pago Online")

    # 3. Mapear los ítems
    items_reales = []
    for product in tn_order.get('products', []):
        items_reales.append({
            "codigo": product.get('sku') or str(product.get('product_id')),
            "descripcion": product.get('name'),
            "cantidad": int(product.get('quantity', 1)),
            "precio_unitario": float(product.get('price', 0)),
            "bonificacion": 0 
        })

    # 4. Dirección (Manejo de string o dict)
    addr_obj = tn_order.get('billing_address') or tn_order.get('shipping_address')
    if isinstance(addr_obj, dict):
        address = f"{addr_obj.get('address', '')}, {addr_obj.get('city', '')}".strip(", ")
    else:
        address = str(addr_obj or "No especificada")

    return {
        "client_name": full_name,
        "total_amount": float(tn_order.get('total', 0.0)),
        "tn_order_id": str(tn_order.get('id')),
        "items": items_reales,
        "client_dni": dni_cuit,
        "client_email": customer.get('email', '-'),
        "payment_method": payment_method,
        "is_cuit": is_cuit,
        "address": address
    }
