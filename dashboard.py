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
        for o in todas:
            # Determinar color y estado visual combinando status interno y de MeLi
            color = "#f87171" # Red (Error o Cancelado)
            display_status = o.status

            if o.meli_status == "cancelled":
                display_status = "CANCELADA"
                color = "#94a3b8" # Gris
            elif o.status == "FACTURADA":
                color = "#4ade80" # Green (Success)
            elif o.status == "PENDIENTE":
                color = "#fbbf24" # Yellow (Pending)
            
            if o.is_refunded:
                display_status += " (DEVUELTA)"

            ventas_list.append({
                "id": o.meli_order_id,
                "cliente": o.client_name,
                "monto": f"$ {o.total_amount:,.2f}",
                "tipo": o.shipping_type, 
                "status": display_status,
                "color": color,
                "has_pdf": o.status == "FACTURADA" and o.meli_status != "cancelled",
                "pdf_url": f"/api/pdf/factura_B_{o.meli_order_id}.pdf" if o.status == "FACTURADA" else None
            })

        stats = {
            "meli": {
                "status": "Online" if meli_user else "Offline",
                "user": meli_user.get('nickname') if meli_user else "N/A",
                "sales_count": len(todas),
                "full_count": len([o for o in todas if o.shipping_type == "FULL"]),
                "madryn_count": len([o for o in todas if o.shipping_type == "MADRYN"])
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
def get_pdf(filename):
    return send_from_directory(PDF_DIR, filename)

if __name__ == '__main__':
    init_db()  # Crear las tablas si no existen
    print(f"🚀 Iniciando Dashboard Pro en http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=True)
