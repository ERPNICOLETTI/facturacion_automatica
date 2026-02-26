"""
auto_facturador.py - Bot que revisa Mercado Libre y factura automáticamente las ventas nuevas.
"""
import time
from datetime import datetime
from pathlib import Path

from API.meli_client import MeliClient
from API.mapper import map_meli_to_order
from PoC_AFIP.database import SessionLocal, Orden, Factura, init_db
from PoC_AFIP.simulador_afip import SimuladorAFIP
from PoC_AFIP.generador_pdf import generar_pdf

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
# Cada cuántos minutos querés que el bot revise si hay ventas nuevas
MINUTOS_REVISION = 15
# ──────────────────────────────────────────────────────────────────────────────

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
        
        # 🔍 NUEVO: Buscamos primero el SKU oficial. 
        # Si por algún motivo no lo cargaste en MeLi, cae al custom_field o al ID de publicación.
        sku_real = prod.get('seller_sku') or prod.get('seller_custom_field') or prod.get('id', 'S/C')
        
        items_procesados.append({
            "codigo": sku_real,
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

def facturar_existente(session, client, afip, orden_db):
    """Procesa una orden que ya está en la DB pero sigue PENDIENTE."""
    meli_id = orden_db.meli_order_id
    print(f"📄 Procesando facturación para Orden {meli_id}...")
    
    # Traemos la orden real y sus datos fiscales (V2)
    orden_real = client.get_order_details(meli_id)
    datos_fiscales = client.get_billing_info(meli_id)
    
    if not orden_real:
        print(f"⚠️ No se pudo obtener info de la orden {meli_id}")
        return

    # 2. Calcular importes
    items_calc, subtotal_neto, iva_contenido, total = calcular_totales(orden_real.get('order_items', []))
    
    # 3. Determinar dinámicamente si es Factura A o B
    letra = "B"
    cod = "06"
    condicion_iva = "CONSUMIDOR FINAL"
    dni_cuit = "-"
    
    if datos_fiscales and datos_fiscales.get('billing_info'):
        b_info = datos_fiscales['billing_info']
        doc_type = b_info.get('identification', {}).get('type', '')
        doc_num = b_info.get('identification', {}).get('number', '')
        dni_cuit = f"{doc_type} {doc_num}"
        
        # Revisamos si es Responsable Inscripto y pasó CUIT
        tax_desc = b_info.get('taxes', {}).get('taxpayer_type', {}).get('description', '') or b_info.get('taxpayer_type', {}).get('description', '')
        if "Inscripto" in tax_desc and doc_type == "CUIT":
            letra = "A"
            cod = "01"
            condicion_iva = "IVA RESPONSABLE INSCRIPTO"

    # 4. Pedir CAE al Simulador AFIP
    try:
        payload_afip = {
            "client_name": orden_db.client_name,
            "total_amount": orden_db.total_amount,
            "punto_venta": 14,
            "tipo_cbte": int(cod) 
        }
        respuesta_afip = afip.emitir_factura(payload_afip)
        
        # 5. Guardar la factura en la base de datos
        factura_db = Factura(
            orden_id=orden_db.id,
            cae=respuesta_afip["CAE"],
            cae_expiration=respuesta_afip["CAEFchVto"]
        )
        session.add(factura_db)
        orden_db.status = "FACTURADA"
        session.commit()
    except Exception as e:
        print(f"❌ Error AFIP en orden {meli_id}: {e}")
        orden_db.status = "ERROR"
        orden_db.error_message = str(e)
        session.commit()
        return
    
    # 6. Preparar datos para el PDF
    raw = factura_db.cae_expiration
    cae_exp_legible = f"{raw[6:8]}/{raw[4:6]}/{raw[0:4]}" if len(raw) == 8 else raw
    nro_factura = f"Nº00014-{str(factura_db.id).zfill(8)}"
    
    factura_data = {
        "letra_factura": letra,
        "nro_factura": nro_factura,
        "client_name": orden_db.client_name,
        "client_address": "Mercado Libre - Envío",
        "client_dni": dni_cuit, 
        "client_email": "-",
        "client_condicion": condicion_iva,
        "condicion_venta": "MercadoPago",
        "tipo_venta": "Producto",
        "orden_compra": str(meli_id),
        "pages": [{"items": items_calc, "page_num": 1, "total_pages": 1, "is_last": True}],
        "subtotal_gravado": f"$ {subtotal_neto:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "total": f"$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "iva_contenido": f"$ {iva_contenido:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "cae": factura_db.cae,
        "cae_expiration": cae_exp_legible,
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    
    # 7. Generar y guardar el PDF
    output_path = Path(__file__).parent / "PoC_AFIP" / f"factura_{letra}_{meli_id}.pdf"
    generar_pdf(factura_data, output_path=output_path)
    print(f"✅ ¡ÉXITO! Factura {letra} generada: {output_path.name}")

def facturar_orden_nueva(session, client, afip, orden_real, datos_fiscales):
    """Mapea, guarda en DB (como pendiente) y luego llama a facturar_existente."""
    datos_mapeados = map_meli_to_order(orden_real, datos_fiscales)
    meli_id = datos_mapeados['meli_order_id']

    # Determinar tipo de envío
    shipping = orden_real.get('shipping', {})
    shipping_mode = shipping.get('mode', '')
    tags = orden_real.get('tags', [])
    stype = "FULL" if ("fulfillment" in tags or shipping_mode == "fulfillment") else "MADRYN"

    nueva_orden = Orden(
        client_name=datos_mapeados['client_name'],
        total_amount=datos_mapeados['total_amount'],
        meli_order_id=meli_id,
        shipping_type=stype,
        status="PENDIENTE"
    )
    session.add(nueva_orden)
    session.flush() 
    
    facturar_existente(session, client, afip, nueva_orden)


def ejecutar_bot():
    """Bucle infinito que revisa y factura."""
    init_db()
    client = MeliClient()
    afip = SimuladorAFIP()
    
    print("\n" + "="*60)
    print("🤖 BOT FACTURADOR PINO S.A. INICIADO")
    print("El sistema está corriendo. Presioná Ctrl+C para detenerlo.")
    print("="*60)
    
    while True:
        ahora = datetime.now().strftime("%H:%M:%S")
        session = SessionLocal()
        
        try:
            # 1. Facturar órdenes que estén PENDIENTES en la base de datos (Ej: las del Dashboard)
            pendientes = session.query(Orden).filter_by(status="PENDIENTE").all()
            if pendientes:
                print(f"\n[{ahora}] 🔍 Encontradas {len(pendientes)} órdenes pendientes de facturación.")
                for p in pendientes:
                    facturar_existente(session, client, afip, p)
            
            # 2. Buscar ventas nuevas directamente en MeLi (por si el dashboard no las vio)
            user_data = client.get_my_user_id()
            if user_data:
                my_id = user_data.get('id')
                search_url = f"{client.api_url}/orders/search?seller={my_id}&limit=10"
                ventas = client._make_request("GET", search_url)
                
                if ventas and ventas.get('results'):
                    for v in ventas['results']:
                        order_id = str(v['id'])
                        existente = session.query(Orden).filter_by(meli_order_id=order_id).first()
                        if not existente:
                            print(f"\n✨ Nueva venta directa detectada en MeLi: {order_id}")
                            orden_real = client.get_order_details(order_id)
                            fiscal = client.get_billing_info(order_id)
                            if orden_real:
                                facturar_orden_nueva(session, client, afip, orden_real, fiscal)
                        
            print(f"\n[{ahora}] Revisión terminada. Todo al día.")
        except Exception as e:
            print(f"❌ Error en el loop del bot: {e}")
            import traceback
            traceback.print_exc()
        finally:
            session.close()

        # Esperar X minutos antes de la siguiente revisión
        time.sleep(MINUTOS_REVISION * 60)

if __name__ == "__main__":
    try:
        ejecutar_bot()
    except KeyboardInterrupt:
        print("\n\n🛑 Bot detenido manualmente por el usuario. ¡Hasta luego!")