"""
simulador_afip.py - Simulador local del Web Service de Facturación Electrónica de AFIP.
Emula la respuesta del WSFE sin realizar ninguna conexión real.
"""
import random
import string
import time
from datetime import date, timedelta


class SimuladorAFIP:
    """
    Simula las respuestas del servicio WSFE de AFIP para entornos de prueba locales.
    En un entorno real, este módulo sería reemplazado por la integración con afip.py
    y los certificados de homologación/producción correspondientes.
    """

    def __init__(self):
        print("[AFIP] Simulador inicializado — modo HOMOLOGACIÓN ficticio.")

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _generar_cae() -> str:
        """Genera un CAE ficticio de 14 dígitos numéricos."""
        return "".join(random.choices(string.digits, k=14))

    @staticmethod
    def _generar_fecha_vencimiento() -> str:
        """Calcula la fecha de vencimiento: hoy + 10 días, formato YYYYMMDD."""
        vto = date.today() + timedelta(days=10)
        return vto.strftime("%Y%m%d")

    # ── Métodos públicos ──────────────────────────────────────────────────────
    def emitir_factura(self, payload: dict) -> dict:
        """
        Simula el llamado a FECAESolicitar del WSFE.

        Args:
            payload: Diccionario con datos de la factura
                     (client_name, total_amount, etc.)

        Returns:
            Diccionario con CAE y CAEFchVto tal como respondería AFIP.
        """
        print(f"[AFIP] Enviando solicitud de CAE para: {payload.get('client_name', 'N/A')} ...")
        time.sleep(1)   # Simula latencia de red

        cae = self._generar_cae()
        fecha_vto = self._generar_fecha_vencimiento()

        respuesta = {
            "resultado": "A",          # A = Aprobado
            "CAE": cae,
            "CAEFchVto": fecha_vto,
            "observaciones": [],
        }

        print(f"[AFIP] [OK] CAE recibido: {cae}  |  Vencimiento: {fecha_vto}")
        return respuesta