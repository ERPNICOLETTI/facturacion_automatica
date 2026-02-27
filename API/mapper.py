def map_meli_to_order(meli_order, fiscal_data=None):
    """
    Transforma el JSON de MeLi al formato de nuestro sistema.
    fiscal_data es la respuesta del endpoint V2.
    """
    full_name = ""
    
    # 1. Identificar al cliente con prioridad en datos fiscales V2
    if fiscal_data and fiscal_data.get('billing_info'):
        b_info = fiscal_data.get('billing_info', {})
        full_name = f"{b_info.get('name', '')} {b_info.get('last_name', '')}".strip()
    
    if not full_name:
        buyer = meli_order.get('buyer', {})
        full_name = f"{buyer.get('first_name', '')} {buyer.get('last_name', '')}".strip()
    
    if not full_name:
        full_name = meli_order.get('buyer', {}).get('nickname', 'Cliente MeLi')

    # 2. Mapear los ítems reales de la compra
    items_reales = []
    for item in meli_order.get('order_items', []):
        detalle = item.get('item', {})
        items_reales.append({
            "codigo": detalle.get('seller_custom_field') or detalle.get('id'),
            "descripcion": detalle.get('title'),
            "cantidad": item.get('quantity'),
            "precio_unitario": item.get('unit_price'),
            "bonificacion": 0.0
        })

    return {
        "client_name": full_name,
        "total_amount": float(meli_order.get('total_amount', 0.0)),
        "meli_order_id": str(meli_order.get('id')),
        "items": items_reales
    }