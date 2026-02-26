from flask import Flask, render_template, jsonify
from API.meli_client import MeliClient
import os

app = Flask(__name__)

# Configuración
HOST = '192.168.1.29'
PORT = 5001

# Inicializar clientes (esto se podría mover a un gestor de estados más adelante)
meli = MeliClient()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/stats')
def get_stats():
    # Mock de datos por ahora, integrando con MeliClient
    try:
        # Intentamos obtener info básica de MELI
        meli_user = meli.get_my_user_id()
        meli_status = "Online" if meli_user else "Offline"
        
        stats = {
            "meli": {
                "status": meli_status,
                "user": meli_user.get('nickname') if meli_user else "N/A",
                "sales_today": 12, # Mock
                "pending": 3
            },
            "tiendanube": {
                "status": "Configurando",
                "sales_today": 5,
                "pending": 1
            },
            "system": {
                "last_sync": "Hace 5 minutos",
                "cpu_usage": "12%"
            }
        }
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print(f"🚀 Iniciando Dashboard en http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=True)
