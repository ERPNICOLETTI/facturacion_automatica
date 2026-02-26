import csv
import os

def export_iva_10_5_skus():
    csv_file = r"C:\Users\Usuario\Desktop\ERP-PINO\Stock ML\setart_exportado.csv"
    output_file = r"C:\Users\Usuario\Desktop\ERP-PINO\Facturación Automática\skus_iva_10_5.txt"
    
    if not os.path.exists(csv_file):
        print(f"❌ Error: No se encontró el archivo CSV en {csv_file}")
        return

    skus_10_5 = []
    
    iva_seen = set()
    
    try:
        # Abrimos con latin-1 por si el CSV tiene caracteres especiales de Clipper
        with open(csv_file, mode='r', encoding='latin-1') as f:
            reader = csv.reader(f)
            header = next(reader)
            
            print(f"DEBUG: Header crudo -> {header}")
            
            # Buscamos indices de forma mas flexible (por si hay basura de encoding)
            idx_sku = -1
            idx_iva = -1
            
            for i, h in enumerate(header):
                if 'INVCOD' in h.upper(): idx_sku = i
                if 'INVIVA' in h.upper(): idx_iva = i
                
            if idx_sku == -1 or idx_iva == -1:
                print(f"Error: No se encontro SKU ({idx_sku}) o IVA ({idx_iva})")
                return

            print(f"DEBUG: Usando columnas indices SKU={idx_sku}, IVA={idx_iva}")

            for row in reader:
                if len(row) <= max(idx_sku, idx_iva):
                    continue
                    
                iva_code = row[idx_iva].strip()
                if not iva_code:
                    continue
                    
                iva_seen.add(iva_code)
                
                # Normalizamos: '2' -> '02', '02' -> '02'
                clean_iva = iva_code.zfill(2) if iva_code.isdigit() else iva_code
                
                if clean_iva == '02':
                    sku = row[idx_sku].strip()
                    if sku:
                        skus_10_5.append(sku)
        
        # Guardamos la lista en un .txt simple (uno por línea)
        with open(output_file, mode='w', encoding='utf-8') as out:
            for sku in skus_10_5:
                out.write(f"{sku}\n")
        
        print(f"DONE: Se encontraron {len(skus_10_5)} productos con IVA 10.5%.")
        print(f"Codigos detectados en columna INVIVA: {sorted(list(iva_seen))}")
        
        if len(skus_10_5) > 0:
            print(f"Ejemplos de SKUs detectados: {skus_10_5[:10]}")
        else:
            print("ATENCION: No se encontro ningun SKU con INVIVA 02")

    except Exception as e:
        print(f"Error procesando el CSV: {e}")

if __name__ == "__main__":
    export_iva_10_5_skus()
