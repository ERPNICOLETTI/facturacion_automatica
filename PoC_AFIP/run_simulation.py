# -*- coding: utf-8 -*-
"""
run_simulation.py - Orquestador principal del PoC de Facturacion Electronica.

Flujo:
  1. Inicializa la base de datos SQLite.
  2. Crea una Orden de prueba con 20 artículos.
  3. Llama al SimuladorAFIP para obtener un CAE ficticio para Factura A y B.
  4. Genera ambos PDFs con sus respectivos tipos de comprobante.
"""
from datetime import datetime

from database import Factura, Orden, SessionLocal, init_db
from generador_pdf import generar_pdf, OUTPUT_PDF
from simulador_afip import SimuladorAFIP
from pathlib import Path

# ── Catálogo de artículos de prueba (20 ítems) ─────────────────────────────
ITEMS_PRUEBA = [
    {"codigo": "BUC001", "descripcion": "Traje de Neoprene 5mm Talle M",         "cantidad": 1, "precio_unitario": 45000.00, "bonificacion": 0},
    {"codigo": "BUC002", "descripcion": "Regulador de Buceo Dual Stage Pro",     "cantidad": 1, "precio_unitario": 82000.00, "bonificacion": 5},
    {"codigo": "BUC003", "descripcion": "Máscara de Buceo Full Face HD",         "cantidad": 2, "precio_unitario": 18500.00, "bonificacion": 0},
    {"codigo": "BUC004", "descripcion": "Aletas Largas Carbono Racing",           "cantidad": 1, "precio_unitario": 32000.00, "bonificacion": 10},
    {"codigo": "BUC005", "descripcion": "Ordenador de Buceo Digital W300",       "cantidad": 1, "precio_unitario": 125000.00,"bonificacion": 0},
    {"codigo": "BUC006", "descripcion": "Chaleco Hidrostático Talle XL",         "cantidad": 1, "precio_unitario": 67000.00, "bonificacion": 0},
    {"codigo": "BUC007", "descripcion": "Linterna Subacuática LED 3000 Lúmenes","cantidad": 2, "precio_unitario": 9800.00,  "bonificacion": 0},
    {"codigo": "BUC008", "descripcion": "Cuchillo de Buceo Inox Titanio",        "cantidad": 1, "precio_unitario": 12500.00, "bonificacion": 0},
    {"codigo": "BUC009", "descripcion": "Botella de Buceo 12L Aluminio",         "cantidad": 1, "precio_unitario": 55000.00, "bonificacion": 0},
    {"codigo": "BUC010", "descripcion": "Guantes de Neoprene 3mm",               "cantidad": 3, "precio_unitario": 4200.00,  "bonificacion": 0},
    {"codigo": "BUC011", "descripcion": "Escarpines Neoprene 5mm Talle 42",      "cantidad": 2, "precio_unitario": 5800.00,  "bonificacion": 0},
    {"codigo": "BUC012", "descripcion": "Capucha de Neoprene 7mm",               "cantidad": 1, "precio_unitario": 7200.00,  "bonificacion": 0},
    {"codigo": "BUC013", "descripcion": "Luz Estroboscópica de Emergencia",      "cantidad": 1, "precio_unitario": 6500.00,  "bonificacion": 0},
    {"codigo": "BUC014", "descripcion": "Brújula Subacuática de Muñeca",         "cantidad": 1, "precio_unitario": 8900.00,  "bonificacion": 0},
    {"codigo": "BUC015", "descripcion": "Snorkel Seco Premium con Válvula",      "cantidad": 2, "precio_unitario": 3400.00,  "bonificacion": 5},
    {"codigo": "BUC016", "descripcion": "Bolsa de Red para Equipos",             "cantidad": 1, "precio_unitario": 2800.00,  "bonificacion": 0},
    {"codigo": "BUC017", "descripcion": "Tablas de Arrastre Dive Scooter Mini",  "cantidad": 1, "precio_unitario": 190000.00,"bonificacion": 0},
    {"codigo": "BUC018", "descripcion": "Pipa Inflado BCD Adaptador Estándar",   "cantidad": 2, "precio_unitario": 1900.00,  "bonificacion": 0},
    {"codigo": "BUC019", "descripcion": "Maletín Rígido de Transporte Equipo",   "cantidad": 1, "precio_unitario": 22000.00, "bonificacion": 0},
    {"codigo": "BUC020", "descripcion": "Kit Limpieza y Mantenimiento Equipos",  "cantidad": 1, "precio_unitario": 3500.00,  "bonificacion": 0},
]


ITEMS_PER_PAGE = 12  # Maximo de articulos por hoja (con encabezado y footer ocupa ~12 filas)


def calcular_items(items: list) -> tuple:
    """Calcula subtotal por item y totales generales. Retorna (items_con_subtotal, subtotal, iva, total)."""
    items_procesados = []
    subtotal_gravado = 0.0
    for item in items:
        bonif_pct = item["bonificacion"]
        precio = item["precio_unitario"]
        cantidad = item["cantidad"]
        descuento = precio * (bonif_pct / 100)
        precio_neto = precio - descuento
        subtotal = round(precio_neto * cantidad, 2)
        subtotal_gravado += subtotal
        items_procesados.append({
            **item,
            "subtotal": subtotal,
        })
    iva = round(subtotal_gravado / 1.21 * 0.21, 2)
    total = round(subtotal_gravado, 2)
    return items_procesados, round(subtotal_gravado / 1.21, 2), iva, total


def build_pages(items_calc: list) -> list:
    """Divide la lista de items en paginas de ITEMS_PER_PAGE items cada una."""
    chunks = [items_calc[i:i + ITEMS_PER_PAGE] for i in range(0, len(items_calc), ITEMS_PER_PAGE)]
    total = len(chunks)
    return [
        {
            "items":       chunk,
            "page_num":    idx + 1,
            "total_pages": total,
            "is_last":     idx == total - 1,
        }
        for idx, chunk in enumerate(chunks)
    ]


def simular_factura(tipo: str, session, afip: SimuladorAFIP):
    """Simula y genera un PDF para el tipo indicado ('A' o 'B')."""
    letra = tipo.upper()
    # tipo_cbte AFIP: 1=A, 6=B
    tipo_cbte = 1 if letra == "A" else 6

    print(f"\n{'-'*55}")
    print(f"   Simulando FACTURA {letra}")
    print(f"{'-'*55}")

    # ── Orden ──────────────────────────────────────────────────────
    items_calc, subtotal_gravado, iva_contenido, total = calcular_items(ITEMS_PRUEBA)
    orden = Orden(client_name="Juan Perez", total_amount=total)
    session.add(orden)
    session.commit()
    session.refresh(orden)
    print(f"  [OK] Orden creada: {orden}")

    # ── CAE ────────────────────────────────────────────────────────
    payload = {
        "client_name": orden.client_name,
        "total_amount": orden.total_amount,
        "punto_venta": 14,
        "tipo_cbte": tipo_cbte,
    }
    respuesta = afip.emitir_factura(payload)
    if respuesta.get("resultado") != "A":
        raise RuntimeError(f"AFIP rechazó la factura: {respuesta}")

    # ── Factura DB ─────────────────────────────────────────────────
    factura = Factura(
        orden_id=orden.id,
        cae=respuesta["CAE"],
        cae_expiration=respuesta["CAEFchVto"],
    )
    session.add(factura)
    session.commit()
    session.refresh(factura)
    print(f"  [OK] Factura {letra} guardada: {factura}")

    # ── PDF ────────────────────────────────────────────────────────
    raw = factura.cae_expiration
    cae_exp_legible = f"{raw[6:8]}/{raw[4:6]}/{raw[0:4]}" if len(raw) == 8 else raw

    # Número de factura formateado
    nro_factura = f"Nº00014-{str(factura.id).zfill(8)}"

    factura_data = {
        # Tipo
        "letra_factura":      letra,
        "nro_factura":        nro_factura,
        # Cliente
        "client_name":        "Juan Perez",
        "client_address":     "BUENOS AIRES, ARGENTINA",
        "client_dni":         "32.456.789",
        "client_email":       "juan.perez@email.com",
        "client_condicion":   "CONSUMIDOR FINAL" if letra == "B" else "IVA RESPONSABLE INSCRITO",
        # Venta
        "condicion_venta":    "Contado",
        "tipo_venta":         "Producto",
        "orden_compra":       str(orden.id).zfill(16),
        # Paginas (items divididos en bloques de ITEMS_PER_PAGE)
        "pages":              build_pages(items_calc),
        # Totales
        "subtotal_gravado":   f"$ {subtotal_gravado:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "total":              f"$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "iva_contenido":      f"$ {iva_contenido:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        # Fiscal
        "cae":                factura.cae,
        "cae_expiration":     cae_exp_legible,
        "created_at":         datetime.now().strftime("%d/%m/%Y %H:%M"),
    }

    output_path = Path(__file__).parent / f"factura_generada_{letra}.pdf"
    generar_pdf(factura_data, output_path=output_path)
    print(f"  [OK] PDF generado: {output_path}")
    return orden, factura, total, cae_exp_legible, output_path


def main():
    print("=" * 55)
    print("   PoC - Simulacion de Facturacion Electronica AFIP")
    print("=" * 55)

    print("\n[1/4] Inicializando base de datos...")
    init_db()

    session = SessionLocal()
    afip = SimuladorAFIP()

    try:
        # Generar Factura B
        orden_b, factura_b, total_b, vto_b, pdf_b = simular_factura("B", session, afip)
        # Generar Factura A
        orden_a, factura_a, total_a, vto_a, pdf_a = simular_factura("A", session, afip)

        print("\n" + "=" * 55)
        print("   [ÉXITO] Simulación completada")
        print("=" * 55)
        print(f"\n  FACTURA B")
        print(f"    Orden ID   : {orden_b.id}")
        print(f"    Total      : $ {total_b:,.2f}")
        print(f"    CAE        : {factura_b.cae}")
        print(f"    Vto. CAE   : {vto_b}")
        print(f"    PDF        : {pdf_b}")
        print(f"\n  FACTURA A")
        print(f"    Orden ID   : {orden_a.id}")
        print(f"    Total      : $ {total_a:,.2f}")
        print(f"    CAE        : {factura_a.cae}")
        print(f"    Vto. CAE   : {vto_a}")
        print(f"    PDF        : {pdf_a}")
        print("=" * 55)

    except Exception as exc:
        session.rollback()
        print(f"\n[ERROR] {exc}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
