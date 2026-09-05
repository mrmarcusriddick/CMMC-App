from dataclasses import dataclass
import httpx
from azure.identity import AzureAuthorityHosts, ClientSecretCredential, DefaultAzureCredential
from .config import get_settings


@dataclass(frozen=True)
class GraphCloud:
    base_url: str
    scope: str
    authority: str


GRAPH_CLOUDS = {
    "public": GraphCloud("https://graph.microsoft.com", "https://graph.microsoft.com/.default", AzureAuthorityHosts.AZURE_PUBLIC_CLOUD),
    "usgovernment": GraphCloud("https://graph.microsoft.us", "https://graph.microsoft.us/.default", AzureAuthorityHosts.AZURE_GOVERNMENT),
    "usgovernmentdod": GraphCloud("https://dod-graph.microsoft.us", "https://dod-graph.microsoft.us/.default", AzureAuthorityHosts.AZURE_GOVERNMENT),
}


def graph_cloud(name: str) -> GraphCloud:
    try:
        return GRAPH_CLOUDS[name.strip().lower()]
    except KeyError as exc:
        raise ValueError("AZURE_CLOUD must be public, usgovernment, or usgovernmentdod.") from exc


class GraphClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.cloud = graph_cloud(settings.azure_cloud)
        if settings.azure_use_managed_identity:
            self.credential = DefaultAzureCredential(authority=self.cloud.authority)
        elif settings.azure_tenant_id and settings.azure_client_id and settings.azure_client_secret:
            self.credential = ClientSecretCredential(settings.azure_tenant_id, settings.azure_client_id, settings.azure_client_secret, authority=self.cloud.authority)
        else:
            self.credential = None

    async def get_json(self, path: str, required_permission: str = "the required Microsoft Graph read permission") -> dict:
        if not self.credential:
            raise RuntimeError("Azure credentials are not configured. Use managed identity or environment variables.")
        token = self.credential.get_token(self.cloud.scope).token
        return await self._get_url(f"{self.cloud.base_url}/v1.0{path}", token, required_permission)

    async def get_collection(self, path: str, required_permission: str = "the required Microsoft Graph read permission") -> list[dict]:
        """Read every page of a Graph collection without allowing off-cloud next links."""
        if not self.credential:
            raise RuntimeError("Azure credentials are not configured. Use managed identity or environment variables.")
        token = self.credential.get_token(self.cloud.scope).token
        url = f"{self.cloud.base_url}/v1.0{path}"
        values: list[dict] = []
        while url:
            payload = await self._get_url(url, token, required_permission)
            values.extend(item for item in payload.get("value", []) if isinstance(item, dict))
            next_link = payload.get("@odata.nextLink")
            if next_link and not str(next_link).startswith(self.cloud.base_url):
                raise RuntimeError("Microsoft Graph returned a next-page link outside the selected cloud.")
            url = str(next_link) if next_link else ""
        return values

    async def _get_url(self, url: str, token: str, required_permission: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
                response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.TimeoutException as exc:
            raise RuntimeError("Microsoft Graph request timed out") from exc
        if response.status_code == 403:
            raise PermissionError(f"Microsoft Graph denied access. Grant {required_permission} application permission and tenant-wide admin consent in the selected cloud.")
        response.raise_for_status()
        return response.json()
