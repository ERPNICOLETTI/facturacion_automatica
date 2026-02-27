
import os
import shutil
import sqlite3
from pathlib import Path
import time
import logging
logging.getLogger("pypdf").setLevel(logging.ERROR)
from pypdf import PdfReader

# Configuración de Rutas
DOWNLOADS_FOLDER = Path(r"C:\Users\Usuario\Downloads")
WMS_ROOT = Path(r"C:\Users\Usuario\Desktop\ERP-PINO\Programa Stock")
WMS_DB = WMS_ROOT / "pickeo.db"
WMS_STATIC_ETIQUETAS = WMS_ROOT / "static" / "etiquetas"

def buscar_texto_en_pdf(pdf_path, terminos):
    """Lee el PDF y busca si alguno de los términos aparece en el texto."""
    try:
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            # Solo revisamos las primeras páginas para velocidad
            all_text = ""
            for page in reader.pages[:3]:
                text = page.extract_text()
                if text:
                    all_text += text
            
            if not all_text:
                return False
                
            # Limpiamos el texto para búsqueda flexible
            all_text = all_text.replace(" ", "").replace("-", "")
            
            for termino in terminos:
                clean_term = str(termino).replace(" ", "").replace("-", "")
                if clean_term in all_text:
                    return True
    except Exception as e:
        # Silenciamos errores de lectura para no ensuciar
        pass
    return False

def escanear_y_vincular_etiquetas():
    """
    Escanea la carpeta de descargas, lee el CONTENIDO de los PDFs
    y los vincula con las órdenes correspondientes en el WMS.
    """
    if not WMS_DB.exists():
        print(f"Error: No se encontró la base de datos en {WMS_DB}")
        return

    print(f"Iniciando escaneo inteligente en {DOWNLOADS_FOLDER}...")
    
    WMS_STATIC_ETIQUETAS.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(WMS_DB))
    cursor = conn.cursor()

    # 1. Obtener órdenes que NO tienen etiqueta aún
    cursor.execute("SELECT id, numero_orden, meli_order_id, tracking_number FROM orden WHERE etiqueta_url IS NULL OR etiqueta_url = ''")
    ordenes_pendientes = cursor.fetchall()

    if not ordenes_pendientes:
        print("No hay órdenes pendientes de etiqueta en el WMS.")
        return

    # 2. Listar PDFs recientes (Aumentamos el límite para asegurar que encuentre el de la prueba)
    ahora = time.time()
    pdfs = [f for f in DOWNLOADS_FOLDER.glob("*.pdf") if ahora - f.stat().st_mtime < 172800] # 48 horas

    votos_vinculados = 0

    for pdf_path in pdfs:
        print(f"Buscando en {pdf_path.name}...")
        # Para cada PDF, buscamos si pertenece a alguna de nuestras órdenes
        for o_id, nro_ord, meli_id, track in ordenes_pendientes:
            
            # Definimos qué términos buscar dentro del PDF
            terminos_busqueda = []
            if track: terminos_busqueda.append(track)
            if meli_id: terminos_busqueda.append(meli_id)
            if nro_ord:
                # Si es TN-1234, buscamos "1234"
                clean_id = nro_ord.replace("TN-", "").replace("ML-", "")
                terminos_busqueda.append(clean_id)

            if buscar_texto_en_pdf(pdf_path, terminos_busqueda):
                print(f"   >>> MATCH OK!! Encontrado {terminos_busqueda} en '{pdf_path.name}' para Orden {nro_ord}")
                
                # Copiar al WMS
                dest_filename = f"ETIQUETA_{nro_ord}.pdf"
                dest_path = WMS_STATIC_ETIQUETAS / dest_filename
                shutil.copy2(pdf_path, dest_path)
                
                # Actualizar DB
                url_relativa = f"/static/etiquetas/{dest_filename}"
                cursor.execute("UPDATE orden SET etiqueta_url = ?, estado = 'EN_PREPARACION' WHERE id = ?", (url_relativa, o_id))
                votos_vinculados += 1
                # Una vez vinculada, ya no está pendiente para otros PDFs
                break 

    conn.commit()
    conn.close()
    print(f"Sincronización finalizada. Se vincularon {votos_vinculados} etiquetas.")

if __name__ == "__main__":
    escanear_y_vincular_etiquetas()
