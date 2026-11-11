"""Захиалгын төлөвийн дүрэм (US-04, US-05).

Энэ модуль өгөгдлийн сан, HTTP-ээс хамааралгүй цэвэр функцүүдтэй тул
unit тестээр шууд шалгагдана. CI-ийн гол шалгалт энэ дүрэм дээр хийгдэнэ.
"""

# Бүтэн мөчлөг (Лаб 2, Лаб 5)
STATUS_FLOW = [
    "requested",      # Хүсэлт илгээсэн
    "received",       # Хүлээн авсан
    "cleaning",       # Цэвэрлэж байгаа
    "quality_check",  # Чанар шалгаж байгаа
    "ready",          # Бэлэн болсон
    "delivered",      # Хүлээлгэн өгсөн
]

STATUS_LABELS = {
    "requested": "Хүсэлт илгээсэн",
    "received": "Хүлээн авсан",
    "cleaning": "Цэвэрлэж байгаа",
    "quality_check": "Чанар шалгаж байгаа",
    "ready": "Бэлэн болсон",
    "delivered": "Хүлээлгэн өгсөн",
}

# Цэвэрлэгээний ажилтан зөвхөн хүлээн авснаас бэлэн болох хүртэл шилжүүлнэ.
WORKER_TRANSITIONS = {
    ("received", "cleaning"),
    ("cleaning", "quality_check"),
    ("quality_check", "ready"),
    ("quality_check", "cleaning"),  # чанарын шалгалтаас буцаах
}

# Буцаах шилжилтэд шалтгаан заавал өгнө.
REASON_REQUIRED = {("quality_check", "cleaning")}

MAX_REASON_LENGTH = 500
NOT_CONFIRMED = "Хугацаа баталгаажаагүй"


class TransitionError(ValueError):
    """Хүчингүй төлөвийн шилжилт."""


def validate_transition(current, new, reason=""):
    """Ажилтны төлөвийн шилжилтийг шалгаж, цэвэрлэсэн шалтгааныг буцаана."""
    if new not in STATUS_LABELS:
        raise TransitionError("Төлөв буруу байна.")
    if not isinstance(reason, str):
        raise TransitionError("Шалтгаан текст байх ёстой.")
    reason = reason.strip()
    if len(reason) > MAX_REASON_LENGTH:
        raise TransitionError("Шалтгаан 500 тэмдэгтээс хэтэрсэн.")
    if (current, new) not in WORKER_TRANSITIONS:
        raise TransitionError("Энэ төлөвийн шилжилт зөвшөөрөгдөөгүй.")
    if (current, new) in REASON_REQUIRED and not reason:
        raise TransitionError("Буцаах шалтгааныг заавал бичнэ.")
    return reason


def allowed_next(current):
    """Тухайн төлөвөөс ажилтны шилжүүлж болох төлөвүүд."""
    return sorted(new for (cur, new) in WORKER_TRANSITIONS if cur == current)


def progress_percent(status):
    """Бүтэн мөчлөгт хэдэн хувь явсныг буцаана (requested = 0, delivered = 100)."""
    if status not in STATUS_FLOW:
        raise ValueError("Төлөв буруу байна.")
    return round(STATUS_FLOW.index(status) * 100 / (len(STATUS_FLOW) - 1))


def ready_label(ready_at):
    """AC-05-2: батлагдаагүй хугацааг тусгай текстээр харуулна."""
    return ready_at if ready_at else NOT_CONFIRMED
