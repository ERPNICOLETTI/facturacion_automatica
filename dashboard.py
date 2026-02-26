from flask import Flask, render_template, jsonify, send_from_directory
from API.meli_client import MeliClient
from PoC_AFIP.database import SessionLocal, Orden, Factura, init_db
import os
import time
from pathlib import Path
from API.mapper import map_meli_to_order

app = Flask(__name__)

# Configuración
HOST = '192.168.1.29'
PORT = 5001
PDF_DIR = Path(__file__).parent / "PoC_AFIP"

# Inicializar clientes
meli = MeliClient()

def get_shipping_type(orden_real):
    shipping = orden_real.get('shipping', {})
    shipping_mode = shipping.get('mode', '')
    tags = orden_real.get('tags', [])
    if "fulfillment" in tags or shipping_mode == "fulfillment":
        return "FULL"
    return "MADRYN"

# Cache para MeLi (para no saturar la API con el refresh del Dashboard)
cache_meli_user = None
cache_last_check = 0

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/stats')
def get_stats():
    session = SessionLocal()
    try:
        # 1. Info de MeLi con Caché (1 minuto)
        global cache_meli_user, cache_last_check
        import time
        ahora = time.time()

        if not cache_meli_user or (ahora - cache_last_check) > 60:
            cache_meli_user = meli.get_my_user_id()
            cache_last_check = ahora
            print("🔄 [Dashboard] API MeLi consultada (Caché actualizada)")
        
        meli_user = cache_meli_user
        
        # 2. Resumen de ventas de la DB
        todas = session.query(Orden).all()
        
        # 3. Filtrar ventas por tipo y estado
        ventas_list = []
        total_refunded_global = 0
        for o in todas:
            # Determinar color y estado visual combinando status interno y de MeLi
            color = "#f87171" # Red (Error o Cancelado)
            display_status = o.status
            total_refunded_global += (o.amount_refunded or 0)

            if o.meli_status == "cancelled":
                display_status = "CANCELADA"
                color = "#94a3b8" # Gris
            elif o.status == "FACTURADA":
                color = "#4ade80" # Green (Success)
            
            if o.status_afip_nc == "NC_EMITIDA":
                display_status = "NOTA CRÉDITO"
                color = "#fca5a5" # Rojo suave

            if o.is_refunded and o.meli_status != "cancelled":
                display_status += f" (REF. ${o.amount_refunded:,.0f})"

            ext_id = o.meli_order_id or o.tn_order_id
            letra = o.factura.letra if o.factura else (o.nc_type or "B")

            ventas_list.append({
                "id": ext_id,
                "cliente": o.client_name,
                "monto": f"$ {o.total_amount:,.2f}",
                "tipo": o.shipping_type, 
                "source": o.source,
                "status": display_status,
                "color": color,
                "has_pdf": o.status == "FACTURADA",
                "pdf_url": f"/api/pdf/factura_{letra}_{o.source}_{ext_id}.pdf" if o.status == "FACTURADA" else None,
                "has_nc": o.status_afip_nc == "NC_EMITIDA",
                "nc_url": f"/api/pdf/nc_{letra}_{o.source}_{ext_id}.pdf" if o.status_afip_nc == "NC_EMITIDA" else None
            })

        stats = {
            "meli": {
                "status": "Online" if meli_user else "Offline",
                "user": meli_user.get('nickname') if meli_user else "N/A",
                "sales_count": len(todas),
                "full_count": len([o for o in todas if o.shipping_type == "FULL"]),
                "madryn_count": len([o for o in todas if o.shipping_type == "MADRYN"]),
                "total_refunded": total_refunded_global
            },
            "ventas": ventas_list[::-1][:20] # Últimas 20
        }
        return jsonify(stats)
    except Exception as e:
        print(f"Error stats: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@app.route('/api/pdf/<filename>')
def serve_pdf(filename):
    # Buscamos el archivo recursivamente en la carpeta FACTURAS
    base_path = PDF_DIR / "FACTURAS"
    for path in base_path.rglob(filename):
        return send_from_directory(path.parent, path.name)
    
    # Por compatibilidad (si quedó alguno afuera)
    if (PDF_DIR / filename).exists():
        return send_from_directory(PDF_DIR, filename)
        
    return f"Archivo {filename} no encontrado", 404

if __name__ == '__main__':
    init_db()  # Crear las tablas si no existen
    print(f"🚀 Iniciando Dashboard Pro en http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=True)
