import asyncio
import httpx


class ToolAPIError(Exception):
    pass


class AppointmentClient:
    def __init__(self, url, access_token):
        self.client = httpx.AsyncClient(
            base_url=url, timeout=3,
            headers={"Authorization": f"Bearer {access_token}"},
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
        self.writes = set()

    async def _request(self, method, path, **kwargs):
        try:
            async with asyncio.timeout(5):
                response = await self.client.request(method, path, **kwargs)
            if response.status_code in (409, 422):
                raise ToolAPIError(response.json().get("detail", "Invalid appointment"))
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, TimeoutError):
            raise ToolAPIError("Appointment service unavailable; do not claim a booking succeeded") from None

    async def availability(self, day):
        return await self._request("GET", "/api/availability", params={"day": day})

    async def book(self, payload):
        # Speech interruption must not ambiguously cancel an in-flight database write.
        # A stable request key makes repeating the same booking safe after uncertainty.
        task = asyncio.create_task(self._request("POST", "/api/bookings", json=payload))
        self.writes.add(task)
        task.add_done_callback(self._completed)
        return await asyncio.shield(task)

    def _completed(self, task):
        self.writes.discard(task)
        if not task.cancelled():
            task.exception()  # Retrieve errors even if the awaiting speech turn was canceled.

    async def close(self):
        if self.writes:
            await asyncio.gather(*tuple(self.writes), return_exceptions=True)
        await self.client.aclose()
