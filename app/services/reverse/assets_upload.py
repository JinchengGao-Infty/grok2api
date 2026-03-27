"""
Reverse interface: upload asset.
"""

from typing import Any
from curl_cffi.requests import AsyncSession

from app.core.logger import logger
from app.core.config import get_config
from app.core.proxy_pool import (
    build_http_proxies,
    get_current_proxy_from,
    rotate_proxy,
    should_rotate_proxy,
)
from app.core.exceptions import UpstreamException
from app.services.token.service import TokenService
from app.services.reverse.utils.headers import build_headers
from app.services.reverse.utils.retry import retry_on_status
from app.services.reverse.utils.cf_refresh import trigger_cf_refresh_on_403 as _trigger_cf_refresh_on_403

UPLOAD_API = "https://grok.com/rest/app-chat/upload-file"


class AssetsUploadReverse:
    """/rest/app-chat/upload-file reverse interface."""

    @staticmethod
    async def request(session: AsyncSession, token: str, fileName: str, fileMimeType: str, content: str) -> Any:
        """Upload asset to Grok.

        Args:
            session: AsyncSession, the session to use for the request.
            token: str, the SSO token.
            fileName: str, the name of the file.
            fileMimeType: str, the MIME type of the file.
            content: str, the content of the file.

        Returns:
            Any: The response from the request.
        """
        try:
            # Build headers
            headers = build_headers(
                cookie_token=token,
                content_type="application/json",
                origin="https://grok.com",
                referer="https://grok.com/",
            )

            # Build payload
            payload = {
                "fileName": fileName,
                "fileMimeType": fileMimeType,
                "content": content,
            }

            # Curl Config
            timeout = get_config("asset.upload_timeout")
            browser = get_config("proxy.browser")
            active_proxy_key = None

            async def _do_request():
                nonlocal active_proxy_key
                active_proxy_key, proxy_url = get_current_proxy_from(
                    "proxy.asset_proxy_url",
                    "proxy.base_proxy_url",
                )
                proxies = build_http_proxies(proxy_url)
                response = await session.post(
                    UPLOAD_API,
                    headers=headers,
                    json=payload,
                    proxies=proxies,
                    timeout=timeout,
                    impersonate=browser,
                )
                if response.status_code != 200:
                    logger.error(
                        f"AssetsUploadReverse: Upload failed, {response.status_code}",
                        extra={"error_type": "UpstreamException"},
                    )
                    raise UpstreamException(
                        message=f"AssetsUploadReverse: Upload failed, {response.status_code}",
                        details={"status": response.status_code},
                    )
                return response

            async def _on_retry(attempt: int, status_code: int, error: Exception, delay: float):
                if active_proxy_key and should_rotate_proxy(status_code):
                    rotate_proxy(active_proxy_key)
                if status_code == 403:
                    await _trigger_cf_refresh_on_403()

            return await retry_on_status(_do_request, on_retry=_on_retry)

        except Exception as e:
            # Handle upstream exception
            if isinstance(e, UpstreamException):
                status = None
                if e.details and "status" in e.details:
                    status = e.details["status"]
                else:
                    status = getattr(e, "status_code", None)
                if status == 401:
                    try:
                        await TokenService.record_fail(token, status, "assets_upload_auth_failed")
                    except Exception:
                        pass
                raise

            # Handle other non-upstream exceptions
            logger.error(
                f"AssetsUploadReverse: Upload failed, {str(e)}",
                extra={"error_type": type(e).__name__},
            )
            raise UpstreamException(
                message=f"AssetsUploadReverse: Upload failed, {str(e)}",
                details={"status": 502, "error": str(e)},
            )


__all__ = ["AssetsUploadReverse"]
