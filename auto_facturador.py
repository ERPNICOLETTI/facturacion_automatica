"""
auto_facturador.py - Bot que revisa Mercado Libre y factura automáticamente las ventas nuevas.
"""
import time
from datetime import datetime
import datetime as dt_lib
from pathlib import Path

from API.meli_client import MeliClient
from API.mapper import map_meli_to_order
from API.tn_client import TNClient
from API.mapper_tn import map_tn_to_order
from PoC_AFIP.database import SessionLocal, Orden, Factura, init_db
from PoC_AFIP.simulador_afip import SimuladorAFIP
from PoC_AFIP.generador_pdf import generar_pdf

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
# Cada cuántos minutos querés que el bot revise si hay ventas nuevas
MINUTOS_REVISION = 15
# ──────────────────────────────────────────────────────────────────────────────

def cargar_skus_iva_reducido():
    """Carga la lista de SKUs que graban 10.5% desde el archivo txt."""
    path = Path(__file__).parent / "skus_iva_10_5.txt"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def calcular_totales(items_list, skus_105=None):
    """Calcula subtotales e IVA discriminado por ítem (21% o 10.5%)."""
    if skus_105 is None: skus_105 = []
    
    items_procesados = []
    neto_total = 0.0
    iva_total = 0.0
    total_gral = 0.0
    
    for item in items_list:
        precio = float(item.get('precio_unitario', 0))
        cantidad = int(item.get('cantidad', 1))
        sku = str(item.get('codigo', '')).strip()
        
        subtotal = round(precio * cantidad, 2)
        
        # Determinar si es 21% o 10.5%
        if sku in skus_105:
            divisor = 1.105
            tasa = 0.105
            tipo_iva = "10.5%"
        else:
            divisor = 1.21
            tasa = 0.21
            tipo_iva = "21%"
            
        neto_item = round(subtotal / divisor, 2)
        iva_item = round(subtotal - neto_item, 2)
        
        neto_total += neto_item
        iva_total += iva_item
        total_gral += subtotal
        
        items_procesados.append({
            "codigo": sku or 'S/C',
            "descripcion": f"{item.get('descripcion', 'Producto')} ({tipo_iva})",
            "cantidad": cantidad,
            "precio_unitario": precio,
            "bonificacion": 0.0,
            "subtotal": subtotal,
            "iva_item": iva_item,
            "neto_item": neto_item
        })
        
    return items_procesados, round(neto_total, 2), round(iva_total, 2), round(total_gral, 2)

def facturar_existente(session, meli_client, tn_client, afip, orden_db):
    """Procesa una orden que ya está en la DB pero sigue PENDIENTE."""
    ext_id = orden_db.meli_order_id or orden_db.tn_order_id
    print(f"📄 Procesando facturación para Orden {orden_db.source} {ext_id}...")
    
    items_mapeados = []
    dni_cuit = "-"
    condicion_iva = "CONSUMIDOR FINAL"
    letra = "B"
    cod = "06"
    address = "Envío"

    if orden_db.source == "MELI":
        details = meli_client.get_order_details(ext_id)
        fiscal = meli_client.get_billing_info(ext_id)
        mapeo = map_meli_to_order(details, fiscal) if details else None
        if not mapeo: return
        items_mapeados = mapeo['items']
        address = "Mercado Libre - Envío"
        
        if fiscal and fiscal.get('billing_info'):
            b_info = fiscal['billing_info']
            doc_type = b_info.get('identification', {}).get('type', '')
            doc_num = b_info.get('identification', {}).get('number', '')
            dni_cuit = f"{doc_type} {doc_num}"
            tax_desc = b_info.get('taxes', {}).get('taxpayer_type', {}).get('description', '') or b_info.get('taxpayer_type', {}).get('description', '')
            if "Inscripto" in tax_desc and doc_type == "CUIT":
                letra, cod, condicion_iva = "A", "01", "IVA RESPONSABLE INSCRIPTO"
    else:
        details = tn_client.get_order(ext_id)
        mapeo = map_tn_to_order(details) if details else None
        if not mapeo: return
        items_mapeados = mapeo['items']
        dni_cuit = mapeo.get('client_dni', '-')
        address = "Tiendanube - Despacho"
        # TN no suele dar condición de IVA directa, asumimos B/CF a menos que detectemos CUIT largo
        if len(dni_cuit.replace("-","")) > 10:
             # Heurística mínima o podrías pedirle al simulador que decida
             pass

    # 2. Calcular importes final para el PDF y AFIP basándose ÚNICAMENTE en los SKUs
    skus_105 = cargar_skus_iva_reducido()
    items_calc, subtotal_neto, iva_contenido, total_factura = calcular_totales(items_mapeados, skus_105)

    # 4. Pedir CAE al Simulador AFIP con el total de los PRODUCTOS
    try:
        payload_afip = {
            "client_name": orden_db.client_name,
            "total_amount": total_factura, # <--- Usamos el total de los SKUs
            "punto_venta": 14,
            "tipo_cbte": int(cod) 
        }
        respuesta_afip = afip.emitir_factura(payload_afip)
        
        # Guardar la factura en la base de datos
        factura_db = Factura(
            orden_id=orden_db.id,
            cae=respuesta_afip["CAE"],
            cae_expiration=respuesta_afip["CAEFchVto"],
            letra=letra
        )
        session.add(factura_db)
        # Actualizamos el total de la orden con lo que REALMENTE se facturó
        orden_db.total_amount = total_factura 
        orden_db.status = "FACTURADA"
        session.commit()
    except Exception as e:
        print(f"❌ Error AFIP en orden {ext_id}: {e}")
        orden_db.status = "ERROR"
        orden_db.error_message = str(e)
        session.commit()
        return
    
    # 6. Preparar datos para el PDF
    ahora_dt = datetime.now()
    raw = factura_db.cae_expiration
    cae_exp_legible = f"{raw[6:8]}/{raw[4:6]}/{raw[0:4]}" if len(raw) == 8 else raw
    nro_factura = f"Nº00014-{str(factura_db.id).zfill(8)}"
    
    factura_data = {
        "titulo_comprobante": "FACTURA",
        "letra_factura": letra,
        "nro_factura": nro_factura,
        "client_name": orden_db.client_name,
        "client_address": address,
        "client_dni": dni_cuit, 
        "client_email": mapeo.get('client_email', '-'),
        "client_condicion": condicion_iva,
        "condicion_venta": mapeo.get('payment_method', 'Online'),
        "tipo_venta": "Producto",
        "orden_compra": str(ext_id),
        "pages": [{"items": items_calc, "page_num": 1, "total_pages": 1, "is_last": True}],
        "subtotal_gravado": f"$ {subtotal_neto:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "total": f"$ {total_factura:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "iva_contenido": f"$ {iva_contenido:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "cae": factura_db.cae,
        "cae_expiration": cae_exp_legible,
        "created_at": ahora_dt.strftime("%d/%m/%Y %H:%M"),
    }
    
    # 7. Generar y guardar el PDF en carpeta organizada por año/mes
    anio = ahora_dt.strftime("%Y")
    mes = ahora_dt.strftime("%m")
    
    # Ruta: PoC_AFIP/FACTURAS/2026/02/factura_B_123.pdf
    folder_path = Path(__file__).parent / "PoC_AFIP" / "FACTURAS" / anio / mes
    folder_path.mkdir(parents=True, exist_ok=True)
    
    output_path = folder_path / f"factura_{letra}_{orden_db.source}_{ext_id}.pdf"
    generar_pdf(factura_data, output_path=output_path)
    print(f"✅ ¡ÉXITO! Factura {letra} generada ({orden_db.source}): {output_path.relative_to(Path(__file__).parent)}")

def emitir_nota_credito(session, meli_client, tn_client, afip, orden_db):
    """Genera una Nota de Crédito para una orden cancelada/devuelta."""
    if orden_db.status_afip_nc == "NC_EMITIDA": return
    
    ext_id = orden_db.meli_order_id or orden_db.tn_order_id
    print(f"📉 Emitiendo NOTA DE CRÉDITO para {orden_db.source} {ext_id} (Cancelada/Devuelta)...")
    
    # 1. Buscar la factura original para referenciarla
    factura_orig = orden_db.factura
    if not factura_orig:
        print(f"⚠️ No hay factura original para la orden {ext_id}. Nada que anular.")
        orden_db.status_afip_nc = "NC_OMITIDA" # No hay nada que anular
        session.commit()
        return

    # 2. Determinar tipo de comprobante (A vs B) basado en la factura original
    letra_orig = factura_orig.letra # Recuperamos si fue A o B
    tipo_nc = 3 if letra_orig == "A" else 8 # 3 = NC A, 8 = NC B
    
    print(f"📉 Emitiendo NOTA DE CRÉDITO {letra_orig} para {orden_db.source} {ext_id}...")

    try:
        payload_nc = {
            "client_name": orden_db.client_name,
            "total_amount": orden_db.total_amount,
            "punto_venta": 14,
            "tipo_cbte": tipo_nc,
            "referencia": f"Anula Factura {letra_orig} ID {factura_orig.id}"
        }
        res_nc = afip.emitir_factura(payload_nc)
        
        orden_db.nc_cae = res_nc["CAE"]
        orden_db.nc_cae_expiration = res_nc["CAEFchVto"]
        orden_db.nc_type = letra_orig
        orden_db.status_afip_nc = "NC_EMITIDA"
        session.commit()
        
        # 3. Generar PDF de la Nota de Crédito en carpeta organizada
        ahora_dt = datetime.now()
        anio = ahora_dt.strftime("%Y")
        mes = ahora_dt.strftime("%m")
        folder_path = Path(__file__).parent / "PoC_AFIP" / "FACTURAS" / anio / mes
        folder_path.mkdir(parents=True, exist_ok=True)
        
        # Necesitamos la info detallada para el PDF de la NC (items, etc.)
        items_calc = []
        skus_105 = cargar_skus_iva_reducido()

        if orden_db.source == "MELI":
            detalles = meli_client.get_order_details(ext_id)
            mapeo = map_meli_to_order(detalles) if detalles else None
            items_calc, subtotal_neto, iva_contenido, total = calcular_totales(mapeo['items'] if mapeo else [], skus_105)
        else:
            detalles = tn_client.get_order(ext_id)
            mapeo = map_tn_to_order(detalles) if detalles else None
            items_calc, subtotal_neto, iva_contenido, total = calcular_totales(mapeo['items'] if mapeo else [], skus_105)
        
        raw_vto = res_nc['CAEFchVto']
        vto_legible = f"{raw_vto[6:8]}/{raw_vto[4:6]}/{raw_vto[0:4]}" if len(raw_vto) == 8 else raw_vto

        factura_data = {
            "titulo_comprobante": "NOTA DE CRÉDITO",
            "letra_factura": letra_orig,
            "nro_factura": f"Nº00014-{str(orden_db.id).zfill(8)}",
            "client_name": orden_db.client_name,
            "client_address": "Mercado Libre - Reembolso",
            "client_dni": "-", 
            "client_email": "-",
            "client_condicion": "CONSUMIDOR FINAL" if letra_orig == "B" else "RESPONSABLE INSCRIPTO",
            "payment_method": "Online",
            "tipo_venta": "Anulación",
            "orden_compra": str(ext_id),
            "pages": [{"items": items_calc, "page_num": 1, "total_pages": 1, "is_last": True}],
            "subtotal_gravado": f"$ {subtotal_neto:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "total": f"$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "iva_contenido": f"$ {iva_contenido:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "cae": res_nc["CAE"],
            "cae_expiration": vto_legible,
            "created_at": ahora_dt.strftime("%d/%m/%Y %H:%M"),
        }
        
        output_path = folder_path / f"nc_{letra_orig}_{orden_db.source}_{ext_id}.pdf"
        generar_pdf(factura_data, output_path=output_path)
        print(f"✅ ¡ÉXITO! Nota de Crédito {letra_orig} generada ({orden_db.source}): {output_path.relative_to(Path(__file__).parent)}")
        
    except Exception as e:
        print(f"❌ Error al emitir NC para {orden_db.source} {ext_id}: {e}")
        orden_db.status_afip_nc = "PENDIENTE"
        session.commit()

def facturar_orden_tn(session, tn_client, afip, tn_order):
    """Mapea una orden de Tiendanube y la procesa."""
    mapeo = map_tn_to_order(tn_order)
    tn_id = mapeo['tn_order_id']

    print(f"🚀 Tiendanube {tn_id} detectada. Cliente: {mapeo['client_name']}")

    nueva_orden = Orden(
        source="TN",
        client_name=mapeo['client_name'],
        total_amount=mapeo['total_amount'],
        tn_order_id=tn_id,
        shipping_type="NORMAL",
        status="PENDIENTE",
        meli_status=tn_order.get('status', 'open'), # Mapeamos status de TN aquí
        amount_paid=mapeo['total_amount'], # En TN solemos asumir pago total si está cerrada/paid
        amount_refunded=0.0,
        is_refunded=0
    )
    session.add(nueva_orden)
    session.flush() 

    # En TN, usualmente facturamos si el pago está confirmado
    p_status = tn_order.get('payment_status', 'pending')
    if p_status == "paid":
        facturar_existente(session, None, tn_client, afip, nueva_orden)
    else:
        print(f"⏩ Saltando facturación para TN {tn_id} (Pago: {p_status})")
        session.commit()

def facturar_orden_meli(session, meli_client, afip, orden_real, datos_fiscales):
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
        shipment = meli_client.get_shipment_details(shipping_id)
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

    # Extraer montos reales al centavo desde los pagos
    payments = orden_real.get('payments', [])
    total_paid = sum(p.get('total_paid_amount', 0) for p in payments if p.get('status') == 'approved')
    total_refunded = sum(p.get('transaction_amount_refunded', 0) for p in payments)

    nueva_orden = Orden(
        source="MELI",
        client_name=datos_mapeados['client_name'],
        total_amount=datos_mapeados['total_amount'],
        meli_order_id=meli_id,
        shipping_type=stype,
        status="PENDIENTE",
        meli_status=orden_real.get('status', 'paid'),
        amount_paid=total_paid,
        amount_refunded=total_refunded,
        is_refunded=1 if total_refunded > 0 else 0
    )
    session.add(nueva_orden)
    session.flush() 
    
    # Solo facturar si está pagada y no cancelada (y no reembolsada totalmente)
    if nueva_orden.meli_status == "paid" and total_refunded < nueva_orden.total_amount:
        facturar_existente(session, meli_client, None, afip, nueva_orden)
    elif total_refunded >= nueva_orden.total_amount:
        print(f"⏩ Venta {meli_id} está TOTALMENTE REEMBOLSADA. Marcando como NC directa.")
        nueva_orden.status = "FACTURADA" # Simulamos que pasó por facturada para poder hacer la NC
        emitir_nota_credito(session, meli_client, None, afip, nueva_orden)
    else:
        print(f"⏩ Saltando facturación para {meli_id} (Estado: {nueva_orden.meli_status})")
        session.commit()


def ejecutar_bot():
    """Bucle infinito que revisa y factura."""
    init_db()
    meli_client = MeliClient()
    tn_client = TNClient()
    afip = SimuladorAFIP()
    
    print("\n" + "="*60)
    print("🤖 BOT FACTURADOR MULTI-PLATAFORMA (MeLi + TN)")
    print("El sistema está corriendo. Presioná Ctrl+C para detenerlo.")
    print("="*60)
    
    while True:
        ahora = datetime.now().strftime("%H:%M:%S")
        session = SessionLocal()
        
        try:
            # 1. Facturar órdenes que estén PENDIENTES en la base de datos (Ej: las del Dashboard)
            pendientes = session.query(Orden).filter_by(status="PENDIENTE").all()
            if pendientes:
                print(f"\n[{ahora}] 🔍 Encontradas {len(pendientes)} órdenes pendientes.")
                for p in pendientes:
                    facturar_existente(session, meli_client, tn_client, afip, p)
            
            # 2. Buscar ventas nuevas en Mercado Libre
            user_meli = meli_client.get_my_user_id()
            if user_meli:
                my_id_meli = user_meli.get('id')
                fecha_limit = (datetime.now() - dt_lib.timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.000-00:00')
                search_url = f"{meli_client.api_url}/orders/search?seller={my_id_meli}&order.date_created.from={fecha_limit}&limit=50&sort=date_desc"
                ventas_meli = meli_client._make_request("GET", search_url)
                
                if ventas_meli and ventas_meli.get('results'):
                    print(f"[{ahora}] 🔍 MeLi devolvió {len(ventas_meli['results'])} órdenes.")
                    for v in ventas_meli['results']:
                        order_id = str(v['id'])
                        m_status = v.get('status', 'paid')
                        
                        existente = session.query(Orden).filter_by(meli_order_id=order_id).first()
                        if not existente:
                            print(f"✨ Nueva venta detectada: {order_id} (Status: {m_status})")
                            orden_real = meli_client.get_order_details(order_id)
                            fiscal = meli_client.get_billing_info(order_id)
                            if orden_real:
                                facturar_orden_meli(session, meli_client, afip, orden_real, fiscal)
                        else:
                            # Sincronizar status y montos (REEMBOLSOS "AL CENTAVO")
                            dirty = False
                            if existente.meli_status != m_status:
                                existente.meli_status = m_status
                                dirty = True
                            
                            # Revisamos si hubo reembolsos nuevos
                            orden_detallada = meli_client.get_order_details(order_id)
                            if orden_detallada:
                                payments = orden_detallada.get('payments', [])
                                total_refunded = sum(p.get('transaction_amount_refunded', 0) for p in payments)
                                
                                if existente.amount_refunded != total_refunded:
                                    print(f"💰 Reembolso detectado en {order_id}: ${existente.amount_refunded} -> ${total_refunded}")
                                    existente.amount_refunded = total_refunded
                                    existente.is_refunded = 1 if total_refunded > 0 else 0
                                    dirty = True
                                    
                                    # Si el reembolso es total o parcial y estaba facturada, NC automática
                                    if total_refunded > 0 and existente.status == "FACTURADA" and existente.status_afip_nc == "N/A":
                                        emitir_nota_credito(session, meli_client, tn_client, afip, existente)
                            
                            if dirty:
                                session.commit()
                else:
                    print(f"[{ahora}] No se encontraron ventas en las últimas 48hs de MeLi.")
            
            # 3. Buscar ventas nuevas en Tiendanube
            ventas_tn = tn_client.get_orders(per_page=20) # Ajustar per_page si es necesario
            if ventas_tn:
                print(f"[{ahora}] 🔍 Tiendanube devolvió {len(ventas_tn)} órdenes.")
                for v in ventas_tn:
                    tn_id = str(v['id'])
                    existente = session.query(Orden).filter_by(tn_order_id=tn_id).first()
                    if not existente:
                        # Si es nueva y está paga, facturamos
                        if v.get('payment_status') == "paid":
                            print(f"✨ Nueva venta detectada en TN: {tn_id} (Paga)")
                            facturar_orden_tn(session, tn_client, afip, v)
                    else:
                        # Sincronización de status para TN
                        dirty = False
                        tn_order_status = v.get('status', 'open') # open, closed, cancelled
                        tn_payment_status = v.get('payment_status', 'pending') # paid, refunded, voided...
                        
                        # REGLA AFIP: Solo NC si fue facturada y luego se canceló o reembolsó
                        necesita_nc = tn_order_status == 'cancelled' or tn_payment_status == 'refunded'
                        
                        if necesita_nc and existente.status == "FACTURADA" and existente.status_afip_nc == "N/A":
                            print(f"📉 Orden TN #{tn_id} REEMBOLSADA/CANCELADA. Generando Nota de Crédito...")
                            emitir_nota_credito(session, meli_client, tn_client, afip, existente)
                            existente.meli_status = tn_payment_status
                            dirty = True
                        
                        elif existente.meli_status != tn_payment_status:
                            existente.meli_status = tn_payment_status
                            dirty = True
                        
                        if dirty:
                            session.commit()
            else:
                print(f"[{ahora}] No se encontraron ventas en Tiendanube.")
                        
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