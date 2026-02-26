"""
auto_facturador.py - Bot que revisa Mercado Libre y factura automáticamente las ventas nuevas.
"""
import time
from datetime import datetime
import datetime as dt_lib
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

def emitir_nota_credito(session, client, afip, orden_db):
    """Genera una Nota de Crédito para una orden cancelada/devuelta."""
    if orden_db.status_afip_nc == "NC_EMITIDA": return
    
    meli_id = orden_db.meli_order_id
    print(f"📉 Emitiendo NOTA DE CRÉDITO para Orden {meli_id} (Cancelada/Devuelta)...")
    
    # 1. Buscar la factura original para referenciarla
    factura_orig = orden_db.factura
    if not factura_orig:
        print(f"⚠️ No hay factura original para la orden {meli_id}. Nada que anular.")
        orden_db.status_afip_nc = "NC_OMITIDA" # No hay nada que anular
        session.commit()
        return

    # 2. Pedir CAE de NC al Simulador AFIP (Tipo 08 para NC B o 03 para NC A)
    # Por ahora simplificamos a NC B siempre para el PoC
    try:
        payload_nc = {
            "client_name": orden_db.client_name,
            "total_amount": orden_db.total_amount,
            "punto_venta": 14,
            "tipo_cbte": 8, # Nota de Crédito B
            "referencia": f"Anula Factura ID {factura_orig.id}"
        }
        res_nc = afip.emitir_factura(payload_nc) # El simulador sirve para ambos
        
        orden_db.nc_cae = res_nc["CAE"]
        orden_db.nc_cae_expiration = res_nc["CAEFchVto"]
        orden_db.status_afip_nc = "NC_EMITIDA"
        session.commit()
        
        # 3. Generar PDF de la Nota de Crédito
        # (Reutilizamos la lógica del PDF pero cambiamos el título)
        # Aquí llamaríamos a una función similar a facturar_existente pero con título "NOTA DE CRÉDITO"
        print(f"✅ ¡ÉXITO! Nota de Crédito emitida: CAE {res_nc['CAE']}")
        
    except Exception as e:
        print(f"❌ Error al emitir NC para {meli_id}: {e}")
        orden_db.status_afip_nc = "PENDIENTE"
        session.commit()

def facturar_orden_nueva(session, client, afip, orden_real, datos_fiscales):
    """Mapea, guarda en DB (como pendiente) y luego llama a facturar_existente."""
    datos_mapeados = map_meli_to_order(orden_real, datos_fiscales)
    meli_id = datos_mapeados['meli_order_id']

    # DETERMINACIÓN CRÍTICA: ¿FULL o MADRYN?
    shipping = orden_real.get('shipping', {})
    shipping_id = shipping.get('id')
    shipping_mode = shipping.get('mode', '')
    logistic_type = shipping.get('logistic_type', '')
    tags = orden_real.get('tags', [])

    # Si en la orden no viene el tipo de logística, lo buscamos en el shipment (API externa)
    if not logistic_type and shipping_id:
        shipment = client.get_shipment_details(shipping_id)
        if shipment:
            # En x-format-new puede venir en la raíz o dentro de un objeto 'logistic'
            logistic_obj = shipment.get('logistic', {})
            logistic_type = shipment.get('logistic_type') or logistic_obj.get('type') or ''
            shipping_mode = shipment.get('mode') or logistic_obj.get('mode') or ''
    
    # REGLA DE ORO DE MERCADO LIBRE:
    if logistic_type == "fulfillment" or shipping_mode == "fulfillment" or "fulfillment" in tags:
        stype = "FULL"
    else:
        stype = "MADRYN"

    print(f"🚀 {meli_id} clasificada como: {stype} (Logística: {logistic_type or 'N/A'})")

    nueva_orden = Orden(
        client_name=datos_mapeados['client_name'],
        total_amount=datos_mapeados['total_amount'],
        meli_order_id=meli_id,
        shipping_type=stype,
        status="PENDIENTE",
        meli_status=orden_real.get('status', 'paid'),
        is_refunded=1 if orden_real.get('feedback', {}).get('sale', {}).get('fulfilled') == False else 0 # Simplificado
    )
    session.add(nueva_orden)
    session.flush() 
    
    # Solo facturar si está pagada y no cancelada
    if nueva_orden.meli_status == "paid":
        facturar_existente(session, client, afip, nueva_orden)
    else:
        print(f"⏩ Saltando facturación para {meli_id} (Estado: {nueva_orden.meli_status})")
        session.commit()


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
            
            # 2. Buscar ventas nuevas directamente en MeLi (Últimas 48hs para asegurar)
            user_data = client.get_my_user_id()
            if user_data:
                my_id = user_data.get('id')
                fecha_limit = (datetime.now() - dt_lib.timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.000-00:00')
                
                # Traer más resultados (limit 50) y filtrar por fecha de creación reciente
                search_url = f"{client.api_url}/orders/search?seller={my_id}&order.date_created.from={fecha_limit}&limit=50&sort=date_desc"
                ventas = client._make_request("GET", search_url)
                
                if ventas and ventas.get('results'):
                    print(f"[{ahora}] 🔍 MeLi devolvió {len(ventas['results'])} órdenes de las últimas 24hs.")
                    for v in ventas['results']:
                        order_id = str(v['id'])
                        m_status = v.get('status', 'paid')
                        
                        existente = session.query(Orden).filter_by(meli_order_id=order_id).first()
                        if not existente:
                            print(f"✨ Nueva venta detectada: {order_id} (Status: {m_status})")
                            orden_real = client.get_order_details(order_id)
                            fiscal = client.get_billing_info(order_id)
                            if orden_real:
                                facturar_orden_nueva(session, client, afip, orden_real, fiscal)
                        else:
                            # Sincronizar status (si se canceló, por ejemplo)
                            if existente.meli_status != m_status:
                                print(f"🔄 Actualizando status de {order_id}: {existente.meli_status} -> {m_status}")
                                existente.meli_status = m_status
                                
                                # Si se canceló y tenía factura, gatillar NC
                                if m_status == "cancelled" and existente.status == "FACTURADA":
                                    emitir_nota_credito(session, client, afip, existente)
                                
                                session.commit()
                            
                            # Si ya estaba cancelada pero falta la NC, intentarlo
                            if existente.meli_status == "cancelled" and existente.status == "FACTURADA" and existente.status_afip_nc == "N/A":
                                emitir_nota_credito(session, client, afip, existente)
                else:
                    print(f"[{ahora}] No se encontraron ventas en las últimas 48hs.")
                        
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