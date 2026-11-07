"""Column layouts of the 4 table shapes in the data PDF.

Each layout lists the keys the vision model must return for every row, with the header text as it
appears in the PDF, so the model maps printed columns to keys without guessing.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    key: str
    header: str  # how the column is printed in the PDF


PART = Column("part_number", "Base Part Number (copy exactly, keep a trailing '*' if printed)")

_SPEED_CURRENT_60_50 = [
    Column("speed_s_60hz", "Operating Speed (sec), 60 Hz"),
    Column("speed_s_50hz", "Operating Speed (sec), 50 Hz"),
    Column("fla_a_60hz", "Full Load Current (FLA) [A], 60 Hz"),
    Column("fla_a_50hz", "Full Load Current (FLA) [A], 50 Hz"),
    Column("lra_a_60hz", "Locked Rotor Current (LRA) [A], 60 Hz"),
    Column("lra_a_50hz", "Locked Rotor Current (LRA) [A], 50 Hz"),
]
_SPEED_CURRENT_SINGLE = [
    Column("speed_s", "Operating Speed, Sec"),
    Column("fla_a", "Full Load Current (FLA), Amps"),
    Column("lra_a", "Locked Rotor Current (LRA), Amps"),
]
_POWER = Column("motor_power_w", "Motor Power, Watts (merged cell: repeat its value on every row)")

LAYOUTS: dict[str, list[Column]] = {
    "single_phase": [
        PART,
        Column("onoff_torque_inlb", "On/Off Output Torque, In-Lbs."),
        Column("onoff_torque_nm", "On/Off Output Torque, Nm"),
        Column("onoff_duty_cycle_pct", "On/Off Duty Cycle, S4%"),
        Column("onoff_cycles_per_hour", "Cycles Per Hour, Cycles"),
        Column("mod_torque_inlb", "Modulating Output Torque, In-Lbs."),
        Column("mod_torque_nm", "Modulating Output Torque, Nm"),
        Column("mod_duty_cycle_pct", "Modulating Duty Cycle, S4%"),
        Column("mod_starts_per_hour", "Starts Per Hour, Starts"),
        *_SPEED_CURRENT_60_50,
        _POWER,
    ],
    "three_phase": [
        PART,
        Column("torque_inlb", "Output Torque, In-Lbs."),
        Column("torque_nm", "Output Torque, Nm"),
        Column("duty_cycle_pct", "Duty Cycle, S4%"),
        Column("cycles_per_hour", "Cycles per Hour, Cycles"),
        Column("starts_per_hour", "Starts per Hour, Starts"),
        *_SPEED_CURRENT_60_50,
        _POWER,
    ],
    "onoff_only": [
        PART,
        Column("torque_inlb", "On/Off Output Torque, In-Lbs."),
        Column("torque_nm", "On/Off Output Torque, Nm"),
        Column("duty_cycle_pct", "On/Off Duty Cycle, S4%"),
        Column("cycles_per_hour", "Cycles per Hour, Cycles"),
        *_SPEED_CURRENT_SINGLE,
        _POWER,
    ],
    "modulating_only": [
        PART,
        Column("torque_inlb", "Modulating Output Torque, In-Lbs."),
        Column("torque_nm", "Modulating Output Torque, Nm"),
        Column("duty_cycle_pct", "Modulating Duty Cycle, S4%"),
        Column("starts_per_hour", "Starts per Hour, Starts"),
        *_SPEED_CURRENT_SINGLE,
        _POWER,
    ],
}


def keys(layout: str) -> list[str]:
    return [c.key for c in LAYOUTS[layout]]


def value_keys(layout: str) -> list[str]:
    return [c.key for c in LAYOUTS[layout] if c.key != "part_number"]
