import sqlite3
import shutil
import os
from pathlib import Path
from datetime import datetime

# Rutas del WMS
WMS_ROOT = Path(r"C:\Users\Usuario\Desktop\ERP-PINO\Programa Stock")
WMS_DB = WMS_ROOT / "pickeo.db"
WMS_STATIC_FACTURAS = WMS_ROOT / "static" / "facturas"

def enviar_orden_al_wms(order_data, items_list, pdf_local_path):
    """
    Inserta una orden y sus ítems directamente en la base de datos del WMS
    y copia el PDF de la factura a la carpeta estática del WMS.
    """
    if not WMS_DB.exists():
        print(f"Error: No se encontró la DB del WMS en {WMS_DB}")
        return False

    try:
        # 1. Asegurar que existe la carpeta de facturas en el WMS
        WMS_STATIC_FACTURAS.mkdir(parents=True, exist_ok=True)

        # 2. Copiar el PDF al WMS
        pdf_filename = f"FACT_{order_data['source']}_{order_data['order_id']}.pdf"
        pdf_dest_path = WMS_STATIC_FACTURAS / pdf_filename
        shutil.copy2(pdf_local_path, pdf_dest_path)
        
        # Ruta relativa para la URL en la DB (como lo hace el WMS)
        factura_url = f"/static/facturas/{pdf_filename}"

        # 3. Conectar a la DB de SQLite del WMS
        conn = sqlite3.connect(str(WMS_DB))
        cursor = conn.cursor()

        # Determinar numero_orden único para el WMS
        prefix = "TN" if order_data['source'] == "TN" else "ML"
        nro_ord_wms = f"{prefix}-{order_data['order_id']}"

        # Evitar duplicados
        cursor.execute("SELECT id FROM orden WHERE numero_orden = ?", (nro_ord_wms,))
        if cursor.fetchone():
            print(f"⚠️ La orden {nro_ord_wms} ya existe en el WMS. Saltando inserción.")
            conn.close()
            return True

        # 4. Insertar la Orden
        # Campos según el schema detectado
        sql_orden = """
            INSERT INTO orden (
                numero_orden, origen, cliente_nombre, dni, email, direccion, localidad, cp, 
                nro_factura, factura_url, estado, fecha_creacion, tipo_flujo, estado_factura,
                tracking_number, empresa_transporte, link_seguimiento
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        fecha_texto = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute(sql_orden, (
            nro_ord_wms,
            order_data['source'],
            order_data.get('client_name', 'Consumidor Final'),
            order_data.get('client_dni', ''),
            order_data.get('client_email', ''),
            order_data.get('client_address', ''),
            order_data.get('localidad', ''),
            order_data.get('cp', ''),
            order_data.get('nro_factura', ''),
            factura_url,
            'PENDIENTE',
            fecha_texto,
            order_data['source'], 
            'FACTURADO',
            order_data.get('tracking_number', ''),
            order_data.get('empresa_transporte', ''),
            order_data.get('tracking_url', '')
        ))
        
        orden_id_internal = cursor.lastrowid

        # 5. Insertar los Items
        sql_item = """
            INSERT INTO item (orden_id, sku, descripcion, cantidad_pedida, cantidad_pickeada)
            VALUES (?, ?, ?, ?, ?)
        """
        
        for item in items_list:
            cursor.execute(sql_item, (
                orden_id_internal,
                item.get('codigo', 'S/C').strip().upper(),
                item.get('descripcion', 'Producto'),
                item.get('cantidad', 1),
                0
            ))

        conn.commit()
        conn.close()
        
        print(f"OK: Orden {nro_ord_wms} enviada exitosamente al WMS.")
        return True

    except Exception as e:
        print(f"Error enviando orden al WMS: {e}")
        return False
