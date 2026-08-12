from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TourCodeParts:
    mm: str          # "12"
    type_code: str   # "WBMXMN"
    suffix: str      # "10/26MF"

    @property
    def full(self) -> str:
        return f"{self.mm}{self.type_code}{self.suffix}"


def derive_tour_code(departure: date, type_code: str, airline: str) -> TourCodeParts:
    """`MM + TYPE + DD/YY + AIRLINE`. UAT 实测样例 (2026-12-10, WBMXMN, MF) → 12WBMXMN10/26MF."""
    if not type_code:
        raise ValueError("type_code is required")
    if not airline:
        raise ValueError("airline is required")
    return TourCodeParts(
        mm=f"{departure.month:02d}",
        type_code=type_code,
        suffix=f"{departure.day:02d}/{departure.year % 100:02d}{airline}",
    )
