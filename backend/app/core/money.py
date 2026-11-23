from typing import Annotated

from pydantic import Field

# 15 digit: masih di bawah batas bilangan bulat aman JavaScript (2^53 - 1)
MAX_RUPIAH = 999_999_999_999_999

# Integer ketat: pecahan, float, string, dan boolean ditolak (FIN-010).
# Ini wajib karena PostgreSQL membulatkan pecahan ke NUMERIC(20,0)
# secara diam-diam, bukan menolaknya.
Rupiah = Annotated[int, Field(strict=True, gt=0, le=MAX_RUPIAH)]