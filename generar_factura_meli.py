import os
from pathlib import Path
from datetime import datetime
from API.meli_client import MeliClient
from PoC_AFIP.database import SessionLocal, Orden, Factura
from PoC_AFIP.simulador_afip import SimuladorAFIP
from PoC_AFIP.generador_pdf import generar_pdf

def calcular_totales(items_meli):
    """Calcula subtotales e IVA a partir de los ítems de Mercado Libre"""
    items_procesados = []
    subtotal_gravado = 0.0
    
    for item in items_meli:
        prod = item.get('item', {})
        precio = float(item.get('unit_price', 0))
        cantidad = int(item.get('quantity', 1))
        
        subtotal = round(precio * cantidad, 2)
        subtotal_gravado += subtotal
        
        items_procesados.append({
            "codigo": prod.get('seller_custom_field') or prod.get('id', 'S/C'),
            "descripcion": prod.get('title', 'Producto sin nombre'),
            "cantidad": cantidad,
            "precio_unitario": precio,
            "bonificacion": 0.0,
            "subtotal": subtotal
        })
        
    iva = round(subtotal_gravado / 1.21 * 0.21, 2)
    neto = round(subtotal_gravado / 1.21, 2)
    total = round(subtotal_gravado, 2)
    
    return items_procesados, neto, iva, total

def facturar_orden(meli_order_id):
    session = SessionLocal()
    client = MeliClient()
    afip = SimuladorAFIP()
    
    # 1. Buscar la orden en la base de datos
    orden_db = session.query(Orden).filter_by(meli_order_id=meli_order_id).first()
    if not orden_db:
        print(f"❌ La orden {meli_order_id} no está en la base de datos.")
        return

    print(f"--- Facturando Orden: {meli_order_id} ({orden_db.client_name}) ---")
    
    # 2. Obtener los ítems reales de MeLi
    meli_order = client.get_order_details(meli_order_id)
    items_calc, subtotal_neto, iva_contenido, total = calcular_totales(meli_order.get('order_items', []))
    
    # 3. Solicitar CAE a AFIP (Simulador)
    payload_afip = {
        "client_name": orden_db.client_name,
        "total_amount": orden_db.total_amount,
        "punto_venta": 14,
        "tipo_cbte": 6 # 6 = Factura B
    }
    respuesta_afip = afip.emitir_factura(payload_afip)
    
    # 4. Guardar Factura en DB
    factura_db = Factura(
        orden_id=orden_db.id,
        cae=respuesta_afip["CAE"],
        cae_expiration=respuesta_afip["CAEFchVto"]
    )
    session.add(factura_db)
    session.commit()
    session.refresh(factura_db)
    
    # 5. Formatear datos para el PDF
    raw = factura_db.cae_expiration
    cae_exp_legible = f"{raw[6:8]}/{raw[4:6]}/{raw[0:4]}" if len(raw) == 8 else raw
    nro_factura = f"Nº00014-{str(factura_db.id).zfill(8)}"
    
    factura_data = {
        "letra_factura": "B",
        "nro_factura": nro_factura,
        "client_name": orden_db.client_name,
        "client_address": "Mercado Libre - Envío",
        "client_dni": "-", 
        "client_email": "-",
        "client_condicion": "CONSUMIDOR FINAL",
        "condicion_venta": "MercadoPago",
        "tipo_venta": "Producto",
        "orden_compra": str(meli_order_id),
        "pages": [
            {
                "items": items_calc,
                "page_num": 1,
                "total_pages": 1,
                "is_last": True
            }
        ],
        "subtotal_gravado": f"$ {subtotal_neto:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "total": f"$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "iva_contenido": f"$ {iva_contenido:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "cae": factura_db.cae,
        "cae_expiration": cae_exp_legible,
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    
    # 6. Generar el PDF
    output_path = Path(__file__).parent / "PoC_AFIP" / f"factura_{meli_order_id}.pdf"
    generar_pdf(factura_data, output_path=output_path)
    print(f"✅ ¡ÉXITO! Factura generada en: {output_path}")

    session.close()

if __name__ == "__main__":
    # Facturamos la orden de Paula
    facturar_orden("2000010867606020")