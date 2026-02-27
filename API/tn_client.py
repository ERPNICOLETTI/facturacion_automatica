import requests
import json
import os
import time

class TNClient:
    def __init__(self, token_path=r"C:\Users\Usuario\Desktop\ERP-PINO\Tiendanube API\tiendanube_tokens.json"):
        self.token_path = token_path
        self.creds = self._load_creds()
        self.store_id = self.creds.get("store_id")
        self.access_token = self.creds.get("access_token")
        self.api_url = f"https://api.tiendanube.com/v1/{self.store_id}"
        self.headers = {
            "Authentication": f"bearer {self.access_token}",
            "User-Agent": self.creds.get("user_agent", "ERP-PINO (lacasadelbuceador16@gmail.com)"),
            "Content-Type": "application/json"
        }

    def _load_creds(self):
        try:
            with open(self.token_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Error leyendo credenciales de Tiendanube: {e}")
            return {}

    def _make_request(self, method, endpoint, params=None, data=None):
        url = f"{self.api_url}/{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, params=params, json=data)
            if response.status_code in [200, 201]:
                return response.json()
            else:
                print(f"[TN API] Error {response.status_code} en {endpoint}: {response.text}")
                return None
        except Exception as e:
            print(f"[TN API] Error de conexion con Tiendanube: {e}")
            return None

    def get_orders(self, page=1, per_page=50, status=None, updated_at_min=None):
        params = {
            "page": page,
            "per_page": per_page
        }
        if status: params["status"] = status
        if updated_at_min: params["updated_at_min"] = updated_at_min
        
        return self._make_request("GET", "orders", params=params)

    def get_order(self, order_id):
        return self._make_request("GET", f"orders/{order_id}")

    def mark_as_packed(self, order_id):
        """Marca una orden como empaquetada en Tiendanube."""
        return self._make_request("POST", f"orders/{order_id}/pack")
