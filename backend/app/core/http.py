from fastapi import Request


def client_ip(request: Request) -> str:
    """Alamat klien. Di belakang reverse proxy, uvicorn harus memakai
    --proxy-headers dengan daftar proxy tepercaya (Fase 7)."""
    return request.client.host if request.client else "unknown"