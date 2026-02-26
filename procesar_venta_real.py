import json
from API.meli_client import MeliClient
from API.mapper import map_meli_to_order
from PoC_AFIP.database import SessionLocal, Orden, init_db

def ejecutar():
    init_db()
    session = SessionLocal()
    client = MeliClient()
    
    print("--- Buscando datos en Mercado Libre (API V2) ---")
    orden_real, datos_fiscales = client.find_order_with_billing(limit=5)
    
    if orden_real:
        datos_mapeados = map_meli_to_order(orden_real, datos_fiscales)
        meli_id = datos_mapeados['meli_order_id']
        
        existente = session.query(Orden).filter_by(meli_order_id=meli_id).first()
        if not existente:
            nueva_orden = Orden(
                client_name=datos_mapeados['client_name'],
                total_amount=datos_mapeados['total_amount'],
                meli_order_id=meli_id
            )
            session.add(nueva_orden)
            session.commit()
            print(f"✅ Orden {meli_id} guardada exitosamente en la base de datos.")
        else:
            print(f"ℹ️ La orden {meli_id} ya estaba registrada.")
    else:
        print("⚠️ No se encontraron órdenes para procesar.")
        
    session.close()

if __name__ == "__main__":
    ejecutar()