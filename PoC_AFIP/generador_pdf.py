"""
generador_pdf.py - Genera el PDF de la factura a partir de la plantilla HTML utilizando Playwright.
"""
import asyncio
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright

# ─── Configuración de rutas ───────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_PDF = BASE_DIR / "factura_generada.pdf"

async def _generar_pdf_async(html_content: str, output_path: Path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html_content, wait_until="networkidle")
        await page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )
        await browser.close()


import base64
import io
import qrcode

def get_b64_image(path: Path) -> str:
    if path.exists():
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    return ""

def generar_qr_b64(cae: str) -> str:
    # URL simulada de AFIP con un JSON en base64 (estándar comprobantes fiscales)
    dummy_data = f'{{"ver":1,"fecha":"2026-02-25","cuit":30564068388,"ptoVta":1,"tipoCmp":6,"nroCmp":1,"importe":15000,"moneda":"PES","ctz":1,"tipoDocRec":99,"nroDocRec":0,"tipoCodAut":"E","codAut":{cae}}}'
    dummy_b64 = base64.b64encode(dummy_data.encode("utf-8")).decode("utf-8")
    url = f"https://www.afip.gob.ar/fe/qr/?p={dummy_b64}"
    
    qr = qrcode.QRCode(version=1, box_size=4, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def generar_pdf(factura_data: dict, output_path: Path = OUTPUT_PDF) -> Path:
    """
    Renderiza la plantilla HTML con los datos de la factura y la convierte a PDF usando Playwright.
    """
    # Inyectar logo en base64 para evitar problemas de rutas locales
    # Inyectar logo en base64 para evitar problemas de rutas locales
    if "logo_lcb_b64" not in factura_data:
        factura_data["logo_lcb_b64"] = get_b64_image(BASE_DIR / "logo_lcb.png")
    if "arca_jpg_b64" not in factura_data:
        factura_data["arca_jpg_b64"] = get_b64_image(BASE_DIR / "arca.jpg")
    
    # Inyectar QR
    if "qr_b64" not in factura_data:
        factura_data["qr_b64"] = generar_qr_b64(factura_data.get("cae", "12345678901234"))

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("factura_template.html")
    html_renderizado = template.render(**factura_data)

    output_path = Path(output_path)
    asyncio.run(_generar_pdf_async(html_renderizado, output_path))

    print(f"[PDF] [OK] Factura generada por Playwright: {output_path}")
    return output_path
