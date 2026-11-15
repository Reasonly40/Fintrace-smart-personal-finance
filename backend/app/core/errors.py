from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Error bisnis yang diterjemahkan menjadi respons JSON konsisten."""

    status_code = 400
    code = "app_error"
    message = "Terjadi kesalahan."

    def __init__(self, message: str | None = None) -> None:
        if message:
            self.message = message
        super().__init__(self.message)


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Data bertentangan dengan data yang sudah ada."


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Hanya lokasi dan pesan; nilai input (misalnya password) tidak ikut
        fields = [
            {
                "field": ".".join(str(part) for part in err["loc"][1:]),
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Data yang dikirim tidak valid.",
                    "fields": fields,
                }
            },
        )