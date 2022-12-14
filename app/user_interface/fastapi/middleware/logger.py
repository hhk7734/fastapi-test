import json
import logging
import time
import traceback
from http import HTTPStatus
from logging import Formatter, LogRecord
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)


class Logger(BaseHTTPMiddleware):
    @staticmethod
    async def _dump_request(request: Request, body: bool = False) -> str:
        headers = {k: v for k, v in request.headers.items()}
        dump = f"{request.method} {request.url.path} HTTP/{request.scope.get('http_version')}\r\n"
        dump += f"Host: {headers.pop('host', '')}\r\n"
        for k, v in headers.items():
            dump += f"{k.title()}: {v}\r\n"

        if body:
            dump += (await request.body()).decode()
            dump += "\r\n"

        return dump

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start_time = time.time()
        path = request.url.path

        request.state.errors = []
        res = await call_next(request)

        latency = time.time() - start_time
        user_id = getattr(request.state, "user_id", -1)
        client_ip = request.client.host if request.client is not None else ""

        errors = request.state.errors
        if len(errors) > 0:
            errors.append(await self._dump_request(request))

            for i, error in enumerate(errors):
                logger.error(
                    str(i),
                    extra={
                        "method": request.method,
                        "url": path,
                        "status": res.status_code,
                        "user_id": user_id,
                        "request_id": request.headers.get("x-request-id", ""),
                        "remote_address": client_ip,
                        "user_agent": request.headers.get("user-agent", ""),
                        "error": str(error),
                        "latency": latency,
                    },
                )
        else:
            logger.info(
                path,
                extra={
                    "method": request.method,
                    "url": path,
                    "status": res.status_code,
                    "user_id": user_id,
                    "request_id": request.headers.get("x-request-id", ""),
                    "remote_address": client_ip,
                    "user_agent": request.headers.get("user-agent", ""),
                    "latency": latency,
                },
            )
        return res


class Recovery(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            return await call_next(request)
        except:
            request.state.errors.append(traceback.format_exc())
            return Response(status_code=HTTPStatus.INTERNAL_SERVER_ERROR)


class JsonFormatter(Formatter):
    # https://docs.python.org/3/library/logging.html#logrecord-attributes
    _DEFAULT_KEYS = (
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    )

    _LEVEL_TO_UPPER_NAME = {
        logging.CRITICAL: "FATAL",
        logging.ERROR: "ERROR",
        logging.WARNING: "WARN",
        logging.INFO: "INFO",
        logging.DEBUG: "DEBUG",
    }

    _LEVEL_TO_LOWER_NAME = {
        logging.CRITICAL: "fatal",
        logging.ERROR: "error",
        logging.WARNING: "warn",
        logging.INFO: "info",
        logging.DEBUG: "debug",
    }

    def __init__(self, time_format: str = "seconds", indent: Optional[int] = None):
        super().__init__()

        if time_format == "seconds":
            self._convert_time = self._seconds
        else:
            self._convert_time = self._iso8601

        self._indent = indent

    def _seconds(self, record: LogRecord) -> float:
        return record.created

    def _iso8601(self, record: LogRecord) -> str:
        return (
            time.strftime("%Y-%m-%dT%H:%M:%S.%%03d%z", time.localtime(record.created))
            % record.msecs
        )

    def format(self, record: LogRecord):
        msg_dict = {
            "level": self._LEVEL_TO_LOWER_NAME[record.levelno],
            "time": self._convert_time(record),
            "caller": "/".join(record.pathname.split("/")[-2:]) + f":{record.lineno}",
            "msg": record.msg,
        }

        # extra
        for k, v in record.__dict__.items():
            if k not in self._DEFAULT_KEYS and not k.startswith("_"):
                msg_dict[k] = v

        return json.dumps(msg_dict, indent=self._indent)


logging.logThreads = False
logging.logMultiprocessing = False
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(handlers=[handler], level=logging.INFO)
