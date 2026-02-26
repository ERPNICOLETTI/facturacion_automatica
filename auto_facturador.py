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

def facturar_orden_nueva(session, client, afip, orden_real, datos_fiscales):
    """Mapea, guarda en DB, pide CAE y genera el PDF de una orden nueva."""
    datos_mapeados = map_meli_to_order(orden_real, datos_fiscales)
    meli_id = datos_mapeados['meli_order_id']
    
    # 1. Guardar la orden en la base de datos
    nueva_orden = Orden(
        client_name=datos_mapeados['client_name'],
        total_amount=datos_mapeados['total_amount'],
        meli_order_id=meli_id
    )
    session.add(nueva_orden)
    session.flush() # Guardamos temporalmente para obtener el ID

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
    payload_afip = {
        "client_name": nueva_orden.client_name,
        "total_amount": nueva_orden.total_amount,
        "punto_venta": 14,
        "tipo_cbte": int(cod) 
    }
    respuesta_afip = afip.emitir_factura(payload_afip)
    
    # 5. Guardar la factura en la base de datos
    factura_db = Factura(
        orden_id=nueva_orden.id,
        cae=respuesta_afip["CAE"],
        cae_expiration=respuesta_afip["CAEFchVto"]
    )
    session.add(factura_db)
    session.commit()
    
    # 6. Preparar datos para el PDF
    raw = factura_db.cae_expiration
    cae_exp_legible = f"{raw[6:8]}/{raw[4:6]}/{raw[0:4]}" if len(raw) == 8 else raw
    nro_factura = f"Nº00014-{str(factura_db.id).zfill(8)}"
    
    factura_data = {
        "letra_factura": letra,
        "nro_factura": nro_factura,
        "client_name": nueva_orden.client_name,
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
        print(f"\n[{ahora}] Buscando ventas en Mercado Libre...")
        
        session = SessionLocal()
        try:
            # Pedimos nuestro propio ID para buscar nuestras ventas
            user_data = client.get_my_user_id()
            if user_data:
                my_id = user_data.get('id')
                # Buscamos las últimas 15 ventas
                search_url = f"{client.api_url}/orders/search?seller={my_id}&limit=15"
                ventas = client._make_request("GET", search_url)
                
                if ventas and ventas.get('results'):
                    nuevas_encontradas = 0
                    
                    # Recorremos las ventas encontradas
                    for v in ventas['results']:
                        order_id = str(v['id'])
                        
                        # ¿Ya está facturada en nuestra base de datos?
                        existente = session.query(Orden).filter_by(meli_order_id=order_id).first()
                        
                        if not existente:
                            nuevas_encontradas += 1
                            print(f"\n✨ Nueva venta sin facturar detectada: {order_id}")
                            
                            # Traemos la orden real y sus datos fiscales (V2)
                            orden_real = client.get_order_details(order_id)
                            datos_fiscales = client.get_billing_info(order_id)
                            
                            if orden_real:
                                facturar_orden_nueva(session, client, afip, orden_real, datos_fiscales)
                                
                            time.sleep(1) # Pausita corta para no saturar a MeLi
                            
                    if nuevas_encontradas == 0:
                        print("ℹ️ No hay ventas nuevas. Todas están facturadas.")
                else:
                    print("ℹ️ No se encontraron ventas recientes.")
        except Exception as e:
            print(f"❌ Error durante la revisión: {e}")
        finally:
            session.close() # Siempre cerramos la conexión a la base de datos
            
        print(f"\n⏳ Ciclo terminado. Durmiendo por {MINUTOS_REVISION} minutos...")
        time.sleep(MINUTOS_REVISION * 60) # Pausa el script 

if __name__ == "__main__":
    try:
        ejecutar_bot()
    except KeyboardInterrupt:
        print("\n\n🛑 Bot detenido manualmente por el usuario. ¡Hasta luego!")