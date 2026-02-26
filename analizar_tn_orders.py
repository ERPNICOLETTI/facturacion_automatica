import sys
import os
import json
# Agregar el directorio actual al path para importar el cliente
sys.path.append(os.getcwd())

from API.tn_client import TNClient

def analizar_datos_tn():
    print("🔍 Analizando las últimas 20 órdenes de Tiendanube...")
    client = TNClient()
    
    orders = client.get_orders(per_page=20)
    
    if orders is None:
        print("❌ No se pudo conectar con la API.")
        return

    print(f"✅ Se recuperaron {len(orders)} órdenes.\n")
    print("="*80)
    
    for o in orders:
        customer = o.get('customer', {})
        # Manejo robusto de direcciones que pueden venir como dict, lista o string
        def get_addr_str(addr):
            if isinstance(addr, dict):
                return f"{addr.get('address', '')}, {addr.get('city', '')}, {addr.get('province', '')}"
            return str(addr)

        billing_addr = o.get('billing_address') or o.get('shipping_address')
        
        print(f"📦 ORDEN #{o.get('id')} | Correlativo: {o.get('number')}")
        print(f"📅 Fecha: {o.get('created_at')}")
        print(f"👤 CLIENTE: {customer.get('name')} ({customer.get('email')})")
        print(f"🆔 ID CLIENTE (DNI/CUIT): {customer.get('identification') or 'No disponible'}")
        
        # Tiendanube a veces tiene la identificación en la dirección de facturación
        if isinstance(billing_addr, dict) and not customer.get('identification'):
            print(f"🆔 ID EN DIRECCIÓN: {billing_addr.get('identification') or 'No disponible'}")

        print(f"📍 DIRECCIÓN: {get_addr_str(billing_addr)}")
        
        print(f"💰 TOTAL: $ {o.get('total')}")
        print(f"💳 ESTADO PAGO: {o.get('payment_status')} | MÉTODO: {o.get('payment_details', {}).get('method', 'N/A')}")
        
        print(f"📝 ITEMS ({len(o.get('products', []))}):")
        for p in o.get('products', []):
            print(f"   - {p.get('quantity')}x {p.get('name')} (SKU: {p.get('sku') or 'S/C'}) - ${p.get('price')}")
        
        # Analizar si hay datos adicionales de empresa (factura A)
        # Tiendanube a veces usa campos extras para CUIT/Razón Social
        extra_info = o.get('extra_attributes', {})
        if extra_info:
            print(f"📎 DATOS EXTRAS: {json.dumps(extra_info)}")
            
        print("-" * 40)

if __name__ == "__main__":
    analizar_datos_tn()
