import requests
import json
import os
import time

class MeliClient:
    # Variable de clase para control de flujo global (pacing)
    _last_request_time = 0

    def __init__(self, token_path=r"C:\Users\Usuario\Desktop\ERP-PINO\Stock ML\tokens.json"):
        self.token_path = token_path
        self.api_url = "https://api.mercadolibre.com"
        self.headers = {
            "User-Agent": "ERP-PINO-Automation/1.0 (Facturador-Automatico)",
            "Accept": "application/json"
        }

    def _get_access_token(self):
        try:
            with open(self.token_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Revisar si está vencido (damos 20 minutos de margen por seguridad)
            expires_at = data.get('expires_at', 0)
            tiempo_actual = int(time.time())
            
            if expires_at < (tiempo_actual + 1200): # 1200 segundos = 20 minutos
                print("🔄 [MeLi Client] Token vencido o por vencer. Renovando automáticamente...")
                return self._refresh_token(data)
                
            return data.get('access_token')

        except Exception as e:
            print(f"❌ Error leyendo token: {e}")
            return None

    def _refresh_token(self, current_data):
        url = f"{self.api_url}/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": current_data.get("client_id"),
            "client_secret": current_data.get("client_secret"),
            "refresh_token": current_data.get("refresh_token")
        }
        try:
            r = requests.post(url, data=payload, headers=self.headers)
            if r.status_code == 200:
                new_data = r.json()
                current_data["access_token"] = new_data["access_token"]
                current_data["refresh_token"] = new_data.get("refresh_token", current_data["refresh_token"])
                current_data["expires_at"] = int(time.time()) + new_data.get("expires_in", 21600)
                
                with open(self.token_path, 'w', encoding='utf-8') as f:
                    json.dump(current_data, f, indent=4)
                print("✅ [MeLi Client] Token renovado exitosamente y guardado en tokens.json")
                return current_data["access_token"]
            else:
                print(f"❌ Error de MeLi al renovar token: {r.text}")
                return None
        except Exception as e:
            print(f"❌ Error de conexión al intentar renovar: {e}")
            return None

    def _make_request(self, method, url, params=None, extra_headers=None):
        token = self._get_access_token()
        if not token: return None
        
        headers = self.headers.copy()
        headers["Authorization"] = f"Bearer {token}"
        
        # Inyectar headers adicionales si existen (ej. x-version: 2)
        if extra_headers:
            headers.update(extra_headers)
            
        # Control de Rate Limit (Pacing)
        # Aseguramos un mínimo de 500ms entre cualquier consulta a MeLi
        tiempo_desde_ultima = time.time() - MeliClient._last_request_time
        if tiempo_desde_ultima < 0.5:
            time.sleep(0.5 - tiempo_desde_ultima)
        
        MeliClient._last_request_time = time.time()
        
        try:
            response = requests.request(method, url, headers=headers, params=params)
            if response.status_code == 200:
                return response.json()
            # 204 (No Content) y 404 (Not Found) son normales en algunos endpoints
            if response.status_code not in [204, 404]: 
                print(f"⚠️ Error {response.status_code} en {url}: {response.text}")
            return None
        except Exception as e:
            print(f"❌ Error de conexión: {e}")
            return None

    def get_my_user_id(self):
        return self._make_request("GET", f"{self.api_url}/users/me")

    def get_order_details(self, order_id):
        return self._make_request("GET", f"{self.api_url}/orders/{order_id}")

    def get_shipment_details(self, shipment_id):
        return self._make_request("GET", f"{self.api_url}/shipments/{shipment_id}", extra_headers={"x-format-new": "true"})

    def get_billing_info(self, order_id):
        # Endpoint V2 oficial: más corto y limpio
        url = f"{self.api_url}/orders/{order_id}/billing_info"
        return self._make_request("GET", url, extra_headers={"x-version": "2"})

    def find_order_with_billing(self, limit=10):
        user_data = self.get_my_user_id()
        if not user_data: return None, None
        
        my_id = user_data.get('id')
        search_url = f"{self.api_url}/orders/search?seller={my_id}&limit={limit}"
        ventas = self._make_request("GET", search_url)
        
        if not ventas or not ventas.get('results'): return None, None
        
        for v in ventas['results']:
            time.sleep(1.0)
            order_id = v['id']
            # En la V2 consultamos la facturación directamente
            fiscal = self.get_billing_info(order_id)
            
            if fiscal and fiscal.get('billing_info'):
                print(f"✨ ¡Encontrada! Orden {order_id} tiene datos fiscales V2.")
                detalles = self.get_order_details(order_id)
                return detalles, fiscal
                
        print("ℹ️ Ninguna de las últimas órdenes tiene datos fiscales.")
        # Si no hay ninguna, devolvemos la primera para Factura B
        primer_id = ventas['results'][0]['id']
        return self.get_order_details(primer_id), None