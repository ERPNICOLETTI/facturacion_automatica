def map_tn_to_order(tn_order):
    """
    Transforma el JSON de Tiendanube al formato de nuestro sistema.
    """
    customer = tn_order.get('customer', {})
    full_name = customer.get('name', 'Cliente Tiendanube')
    
    # 2. Mapear los ítems reales de la compra
    items_reales = []
    for product in tn_order.get('products', []):
        items_reales.append({
            "codigo": product.get('sku') or str(product.get('product_id')),
            "descripcion": product.get('name'),
            "cantidad": product.get('quantity'),
            "precio_unitario": float(product.get('price')),
            "bonificacion": 0 
        })

    return {
        "client_name": full_name,
        "total_amount": float(tn_order.get('total', 0.0)),
        "tn_order_id": str(tn_order.get('id')),
        "items": items_reales,
        "client_dni": customer.get('identification', ''),
        "client_email": customer.get('email', '')
    }
