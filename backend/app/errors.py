"""Structured error responses: {error_code, message, details}."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.paypal.errors import PayPalError

log = logging.getLogger("staycovered")


class AppError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error_code": code, "message": message, "details": details or {}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.error_code, exc.message, exc.details), exc.status_code)

    @app.exception_handler(PayPalError)
    async def _paypal_error(_: Request, exc: PayPalError):
        if exc.status_code == 404:
            return JSONResponse(
                _body("PAY-09", "We couldn't find this PayPal transaction.", exc.public_details()),
                404,
            )
        if exc.retryable:
            return JSONResponse(
                _body("SYS-02", "PayPal is unavailable right now — please retry.", exc.public_details()),
                503,
            )
        return JSONResponse(
            _body("PAYPAL_ERROR", exc.human_message(), exc.public_details()), 502
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return JSONResponse(
            _body("VALIDATION_ERROR", "The request was not valid.", {"errors": exc.errors()}), 422
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(_body("INTERNAL_ERROR", "Something went wrong on our side."), 500)
