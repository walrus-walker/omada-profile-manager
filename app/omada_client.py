"""
omada_client.py

All Omada Open API interactions are isolated in this module.
All raw endpoint paths live here — nowhere else in the app.

Authentication uses the Omada Open API client credentials flow:
  POST {base_url}/openapi/authorize/token
  -> Bearer-style token valid for ~7200 seconds

The block/unblock endpoints are marked TODO because the exact Open API
paths vary by Omada firmware version and need to be confirmed against
your running controller's API documentation page or Swagger UI.
"""

import time
import httpx

from app.config import get_settings

# Module-level caches — shared across requests in the same process
_token_cache: dict = {"access_token": None, "expires_at": 0.0}
_controller_id_cache: str | None = None


class OmadaAPIError(Exception):
    """Raised when the Omada API returns an unexpected response."""


class OmadaClient:
    def __init__(self):
        global _controller_id_cache
        s = get_settings()
        self.base_url = s.OMADA_BASE_URL.rstrip("/")
        self.controller_id = s.OMADA_CONTROLLER_ID  # optional override
        self.client_id = s.OMADA_CLIENT_ID
        self.client_secret = s.OMADA_CLIENT_SECRET
        self.verify_ssl = s.OMADA_VERIFY_SSL
        self.ui_username = s.OMADA_UI_USERNAME
        self.ui_password = s.OMADA_UI_PASSWORD
        # Clear cached controller ID so a changed config takes effect
        _controller_id_cache = None

    def _http(self) -> httpx.Client:
        return httpx.Client(verify=self.verify_ssl, timeout=15.0)

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    def get_access_token(self) -> str:
        """
        Return a valid access token, fetching a new one if expired.
        Caches the token in memory for the lifetime of the process.
        """
        global _token_cache
        now = time.monotonic()

        if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
            return _token_cache["access_token"]

        url = f"{self.base_url}/openapi/authorize/token?grant_type=client_credentials"
        payload = {
            "omadacId": self.controller_id,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        with self._http() as client:
            resp = client.post(url, headers={"Content-Type": "application/json"}, json=payload)

        try:
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise OmadaAPIError(
                f"Token request failed: {exc} — response: {resp.text[:400]}"
            ) from exc

        # Omada Open API response format:
        # {"errorCode": 0, "msg": "...", "result": {"accessToken": "...", "expiresIn": 7200}}
        if data.get("errorCode", -1) != 0:
            raise OmadaAPIError(
                f"Omada API error {data.get('errorCode')}: {data.get('msg')} "
                f"— full response: {resp.text[:400]}"
            )

        result = data.get("result", {})
        token = result.get("accessToken")
        expires_in = int(result.get("expiresIn", 7200))

        if not token:
            raise OmadaAPIError(f"No accessToken in response: {data}")

        _token_cache["access_token"] = token
        _token_cache["expires_at"] = now + expires_in
        return token

    def _headers(self) -> dict:
        return {"Authorization": f"AccessToken={self.get_access_token()}"}

    def _ui_login(self) -> httpx.Client:
        if not self.ui_username or not self.ui_password:
            raise OmadaAPIError("OMADA_UI_USERNAME and OMADA_UI_PASSWORD are required for block/unblock")

        session = httpx.Client(verify=self.verify_ssl, timeout=15.0, follow_redirects=True)

        resp = session.post(
            f"{self.base_url}/api/v2/login",
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            },
            json={"username": self.ui_username, "password": self.ui_password},
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("errorCode", -1) != 0:
            raise OmadaAPIError(f"UI login failed {data.get('errorCode')}: {data.get('msg')}")

        csrf_resp = session.get(
            f"{self.base_url}/api/v2/current/login-status?needToken=true",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        csrf_resp.raise_for_status()
        csrf_data = csrf_resp.json()

        csrf = csrf_data.get("result", {}).get("csrfToken")
        if not csrf:
            raise OmadaAPIError(f"Could not retrieve CSRF token: {csrf_data}")

        session.headers.update({
            "Csrf-Token": csrf,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.base_url}/",
            "Origin": self.base_url,
        })

        return session

    @staticmethod
    def _ui_mac(mac: str) -> str:
        return mac.strip().upper().replace(":", "-")

    # -------------------------------------------------------------------------
    # Controller ID discovery
    # -------------------------------------------------------------------------

    def _resolve_controller_id(self) -> str:
        """
        Return the omadacId to use in API URL paths.

        Prefer OMADA_CONTROLLER_ID from .env.
        Only try /openapi/v1/information if OMADA_CONTROLLER_ID is blank.
        """
        global _controller_id_cache

        if self.controller_id:
            _controller_id_cache = self.controller_id
            return self.controller_id

        if _controller_id_cache:
            return _controller_id_cache

        url = f"{self.base_url}/openapi/v1/information"
        with self._http() as client:
            resp = client.get(url, headers=self._headers())

        try:
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise OmadaAPIError(
                f"Could not discover controller ID from {url}: {exc}"
            ) from exc

        omadac_id = data.get("result", {}).get("omadacId") or data.get("omadacId")
        if not omadac_id:
            raise OmadaAPIError(
                f"omadacId not found in /openapi/v1/information response: {data}"
            )

        _controller_id_cache = omadac_id
        return _controller_id_cache

    # -------------------------------------------------------------------------
    # Connectivity test
    # -------------------------------------------------------------------------

    def test_connection(self) -> dict:
        """
        Try to authenticate and list sites.
        Returns: {"success": bool, "message": str, "sites": list[dict]}
        """
        try:
            self.get_access_token()
            controller_id = self._resolve_controller_id()
            sites = self.list_sites()
            return {
                "success": True,
                "message": f"Connected. Controller ID: {controller_id}",
                "sites": sites,
            }
        except OmadaAPIError as exc:
            return {"success": False, "message": f"Omada API error: {exc}", "sites": []}
        except httpx.ConnectError as exc:
            return {"success": False, "message": f"Cannot reach Omada controller: {exc}", "sites": []}
        except httpx.SSLError as exc:
            return {
                "success": False,
                "message": (
                    f"TLS/SSL error: {exc}. "
                    "Try setting OMADA_VERIFY_SSL=false if using a self-signed certificate."
                ),
                "sites": [],
            }
        except Exception as exc:
            return {"success": False, "message": f"Unexpected error: {exc}", "sites": []}

    # -------------------------------------------------------------------------
    # Sites
    # -------------------------------------------------------------------------

    def list_sites(self) -> list[dict]:
        """
        List all sites from the Omada controller.

        Endpoint: GET /openapi/v1/{omadacId}/sites
        Response: {"errorCode": 0, "result": {"data": [...], "totalRows": N}}
        """
        url = f"{self.base_url}/openapi/v1/{self._resolve_controller_id()}/sites"
        with self._http() as client:
            resp = client.get(url, headers=self._headers())

        resp.raise_for_status()
        data = resp.json()

        if data.get("errorCode", -1) != 0:
            raise OmadaAPIError(f"list_sites error {data.get('errorCode')}: {data.get('msg')}")

        return data.get("result", {}).get("data", [])

    # -------------------------------------------------------------------------
    # Clients
    # -------------------------------------------------------------------------

    def list_clients(self, site_id: str) -> list[dict]:
        """
        List all clients visible in the given site.

        Endpoint: GET /openapi/v1/{omadacId}/sites/{siteId}/clients
        Paginates automatically up to 10 pages × 200 clients.

        Each client dict from Omada typically includes:
          mac, name, ip, active (bool), blocked (bool), and more.
        """
        url = f"{self.base_url}/openapi/v2/{self._resolve_controller_id()}/sites/{site_id}/clients"
        all_clients: list[dict] = []
        page = 1
        page_size = 200

        with self._http() as client:
            while True:
                resp = client.post(
                    url,
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json={"page": page, "pageSize": page_size},
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("errorCode", -1) != 0:
                    raise OmadaAPIError(
                        f"list_clients error {data.get('errorCode')}: {data.get('msg')}"
                    )

                result = data.get("result", {})
                batch = result.get("data", [])
                all_clients.extend(batch)

                total = result.get("totalRows", 0)
                if len(all_clients) >= total or len(batch) < page_size:
                    break

                page += 1
                if page > 10:
                    # Safety limit
                    break

        return all_clients

    @staticmethod
    def normalize_client(raw: dict) -> dict:
        """
        Normalize a raw Omada client dict into a consistent shape for the app.
        Field names differ slightly between Omada firmware versions.
        """
        return {
            "mac": raw.get("mac", "").lower(),
            "name": raw.get("name") or raw.get("hostName") or raw.get("hostname") or "",
            "ip": raw.get("ip", ""),
            "online": bool(raw.get("active", raw.get("online", False))),
            "blocked": bool(raw.get("blocked", False)),
        }

    # -------------------------------------------------------------------------
    # Block / Unblock
    # -------------------------------------------------------------------------

    def block_client(self, site_id: str, mac: str) -> dict:
        mac_dash = self._ui_mac(mac)
        url = (
            f"{self.base_url}/"
            f"{self._resolve_controller_id()}"
            f"/api/v2/sites/{site_id}/cmd/clients/{mac_dash}/block"
        )

        session = self._ui_login()
        resp = session.post(url)
        resp.raise_for_status()

        if resp.text.strip():
            data = resp.json()
            if data.get("errorCode", 0) != 0:
                raise OmadaAPIError(f"block_client error {data.get('errorCode')}: {data.get('msg')}")
            return data

        return {"success": True}

    def unblock_client(self, site_id: str, mac: str) -> dict:
        mac_dash = self._ui_mac(mac)
        url = (
            f"{self.base_url}/"
            f"{self._resolve_controller_id()}"
            f"/api/v2/sites/{site_id}/cmd/clients/{mac_dash}/unblock"
        )

        session = self._ui_login()
        resp = session.post(url)
        resp.raise_for_status()

        if resp.text.strip():
            data = resp.json()
            if data.get("errorCode", 0) != 0:
                raise OmadaAPIError(f"unblock_client error {data.get('errorCode')}: {data.get('msg')}")
            return data

        return {"success": True}
