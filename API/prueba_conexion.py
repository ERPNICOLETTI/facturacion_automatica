from meli_client import MeliClient
from mapper import map_meli_to_order
import json

def ejecutar_poc():
    client = MeliClient()
    
    # Buscamos una orden que sirva para facturar
    orden_real = client.find_order_with_billing(limit=5)
    
    if orden_real:
        site_id = orden_real.get('site_id')
        b_info = orden_real.get('buyer', {}).get('billing_info', {})
        b_id = b_info.get('id')
        
        datos_fiscales = None
        if b_id:
            datos_fiscales = client.get_billing_info(site_id, b_id)
        
        # Mapeamos los datos
        order_mapped = map_meli_to_order(orden_real, datos_fiscales)
        
        print("\n--- OBJETO LISTO PARA TU BASE DE DATOS ---")
        print(order_mapped)
        
        if datos_fiscales:
            print("\n--- DATOS FISCALES REALES (MOCK DATA) ---")
            print(json.dumps(datos_fiscales, indent=2))

if __name__ == "__main__":
    ejecutar_poc()