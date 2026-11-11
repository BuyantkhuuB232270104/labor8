"""US-04 / US-05 төлөвийн дүрмийн unit тест (Лаб 8, Даалгавар 2)."""
import pytest

from src.workflow import (
    NOT_CONFIRMED,
    TransitionError,
    allowed_next,
    progress_percent,
    ready_label,
    validate_transition,
)


@pytest.mark.parametrize("current,new", [
    ("received", "cleaning"),
    ("cleaning", "quality_check"),
    ("quality_check", "ready"),
])
def test_forward_transitions_allowed(current, new):
    assert validate_transition(current, new) == ""


@pytest.mark.parametrize("current,new", [
    ("received", "ready"),          # алгассан шилжилт
    ("requested", "cleaning"),      # хүлээн аваагүй захиалга
    ("ready", "delivered"),         # олголт нь хүлээн авагчийн үүрэг
    ("cleaning", "received"),       # ухрах шилжилт
])
def test_invalid_transitions_rejected(current, new):
    with pytest.raises(TransitionError):
        validate_transition(current, new)


def test_unknown_status_rejected():
    with pytest.raises(TransitionError):
        validate_transition("cleaning", "lost")


def test_return_to_cleaning_requires_reason():
    with pytest.raises(TransitionError):
        validate_transition("quality_check", "cleaning", "   ")
    assert validate_transition("quality_check", "cleaning", "  Толбо арилаагүй ") == "Толбо арилаагүй"


def test_reason_length_limit():
    with pytest.raises(TransitionError):
        validate_transition("received", "cleaning", "x" * 501)
    assert validate_transition("received", "cleaning", "x" * 500) == "x" * 500


def test_allowed_next():
    assert allowed_next("quality_check") == ["cleaning", "ready"]
    assert allowed_next("requested") == []


@pytest.mark.parametrize("status,expected", [
    ("requested", 0), ("received", 20), ("cleaning", 40),
    ("quality_check", 60), ("ready", 80), ("delivered", 100),
])
def test_progress_percent(status, expected):
    assert progress_percent(status) == expected


def test_ready_label():
    assert ready_label(None) == NOT_CONFIRMED
    assert ready_label("2026-10-16T18:00:00+08:00") == "2026-10-16T18:00:00+08:00"
