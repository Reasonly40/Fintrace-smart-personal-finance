from app.core.errors import ConflictError, ForbiddenError, NotFoundError


class CategoryNotFoundError(NotFoundError):
    code = "category_not_found"
    message = "Kategori tidak ditemukan."


class CategoryReadOnlyError(ForbiddenError):
    code = "category_read_only"
    message = "Kategori bawaan tidak bisa diubah atau diarsipkan."


class CategoryNameTakenError(ConflictError):
    code = "category_name_taken"
    message = "Anda sudah memiliki kategori dengan nama itu untuk tipe yang sama."


class CategoryNameReservedError(ConflictError):
    code = "category_name_reserved"
    message = "Nama itu sudah dipakai oleh kategori bawaan."


class CategoryArchivedError(ConflictError):
    code = "category_archived"
    message = "Kategori sudah diarsipkan dan tidak bisa diubah."


class CategoryAlreadyArchivedError(ConflictError):
    code = "category_already_archived"
    message = "Kategori sudah diarsipkan."


class CategoryNotArchivedError(ConflictError):
    code = "category_not_archived"
    message = "Kategori ini tidak sedang diarsipkan."