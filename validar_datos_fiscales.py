import json
from API.meli_client import MeliClient
from PoC_AFIP.database import SessionLocal, Orden

def validar_datos_para_afip(meli_order_id):
    session = SessionLocal()
    client = MeliClient()
    
    orden_db = session.query(Orden).filter_by(meli_order_id=meli_order_id).first()
    if not orden_db:
        print(f"❌ La orden {meli_order_id} no existe en la base de datos local.")
        return

    print(f"--- Validando Datos Fiscales: Orden {meli_order_id} ---")
    
    meli_order = client.get_order_details(meli_order_id)
    if not meli_order:
        print("❌ No se pudo conectar con Mercado Libre.")
        return

    print("\n🔍 Consultando detalles fiscales en MeLi (API V2)...")
    fiscal = client.get_billing_info(meli_order_id)
    
    checklist = {
        "Nombre Cliente DB": orden_db.client_name,
        "Monto Total": orden_db.total_amount,
        "Items detectados": len(meli_order.get('order_items', [])),
        "Tiene Datos Fiscales": "SÍ" if fiscal and fiscal.get('billing_info') else "NO"
    }

    print("\n📊 RESUMEN DE DATOS:")
    for k, v in checklist.items():
        print(f"   {k}: {v}")

    if fiscal and fiscal.get('billing_info'):
        b_data = fiscal.get('billing_info', {})
        
        doc_type = b_data.get('identification', {}).get('type', 'N/A')
        doc_num = b_data.get('identification', {}).get('number', 'N/A')
        
        # En la V2 la condicion fiscal viene directo aquí
        taxes = b_data.get('taxes', {})
        taxpayer_desc = taxes.get('taxpayer_type', {}).get('description') or b_data.get('taxpayer_type', {}).get('description', 'No definido')
        
        print(f"   Tipo Doc: {doc_type}")
        print(f"   Número: {doc_num}")
        print(f"   Condición IVA: {taxpayer_desc}")
        
        if doc_type == "CUIT" and "Inscripto" in taxpayer_desc:
            print("➡️  RESULTADO: Califica para FACTURA A")
        else:
            print("➡️  RESULTADO: Califica para FACTURA B")
    else:
        print("\nℹ️ El comprador no cargó datos fiscales o no están disponibles.")
        print("➡️  RESULTADO SUGERIDO: Factura B (Consumidor Final)")

    session.close()

if __name__ == "__main__":
    # Asegúrate de poner aquí el ID de la orden que vas a probar
    validar_datos_para_afip("2000010867606020")