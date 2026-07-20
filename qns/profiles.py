"""Per-model hardware profiles for the BNS device family.

Each profile captures the static wiring of one hardware model — ports,
peripherals, power-latch family — plus the firmware addresses recovered
from the supplied update packages (see NOTES.md for the derivations).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareProfile:
    """Static wiring and firmware addresses for one BNS hardware model."""

    name: str
    family: str
    """I/O wiring family: "bsp" (BSPLUS/B_LITE), "bsnew" (BS2/BL2),
    "bl4", or "tns"."""

    flash_size: int
    ssi263_port: int
    keyboard_port: int
    keyclr_port: int | None
    """Key-clear port, or None when the model has no keyclr latch (TNS)."""

    display: str | None
    """Built-in Braille display bus: None, "csio" (Z180 CSI/O serial),
    or "parallel" (shifted through 8255 port C)."""

    display_cells: int
    has_clock_pic: bool
    has_gas_gauge: bool
    parallel_port_base: int
    power_on_input_proven: bool
    """Whether the power-on input dialogue boundary is proven for this
    model, enabling --power-on-input."""

    # Firmware addresses recovered from the supplied update packages.
    keyboard_input_buffer: int
    """Physical address of the firmware chord input buffer."""

    command_loop_timer: int
    """Physical address of the timer cleared at each command-loop epoch."""

    command_loop_timer_pc: int
    """Linked address of the STARTA instruction that clears that timer."""



PROFILES: dict[str, HardwareProfile] = {
    profile.name: profile
    for profile in (
        HardwareProfile(
            name="bsp",
            family="bsp",
            flash_size=0,
            ssi263_port=0xC0,
            keyboard_port=0x40,
            keyclr_port=0x20,
            display=None,
            display_cells=0,
            has_clock_pic=False,
            has_gas_gauge=False,
            parallel_port_base=0x80,
            power_on_input_proven=False,
            keyboard_input_buffer=0x4327C,
            command_loop_timer=0x41653,
            command_loop_timer_pc=0x0A0D,
        ),
        HardwareProfile(
            name="bs2",
            family="bsnew",
            flash_size=2 * 1024 * 1024,
            ssi263_port=0xC0,
            keyboard_port=0x40,
            keyclr_port=0x20,
            display=None,
            display_cells=0,
            has_clock_pic=True,
            has_gas_gauge=True,
            parallel_port_base=0x80,
            power_on_input_proven=True,
            keyboard_input_buffer=0x4327D,
            command_loop_timer=0x41654,
            command_loop_timer_pc=0x0A7E,
        ),
        HardwareProfile(
            name="bsl",
            family="bsp",
            flash_size=0,
            ssi263_port=0xC0,
            keyboard_port=0x40,
            keyclr_port=0x20,
            display="csio",
            display_cells=18,
            has_clock_pic=False,
            has_gas_gauge=False,
            parallel_port_base=0x80,
            power_on_input_proven=False,
            keyboard_input_buffer=0x433E5,
            command_loop_timer=0x41653,
            command_loop_timer_pc=0x0A97,
        ),
        HardwareProfile(
            name="bl2",
            family="bsnew",
            flash_size=2 * 1024 * 1024,
            ssi263_port=0xC0,
            keyboard_port=0x40,
            keyclr_port=0x20,
            display="parallel",
            display_cells=18,
            has_clock_pic=True,
            has_gas_gauge=True,
            parallel_port_base=0x80,
            power_on_input_proven=True,
            keyboard_input_buffer=0x433E6,
            command_loop_timer=0x41654,
            command_loop_timer_pc=0x0AF5,
        ),
        HardwareProfile(
            name="bl4",
            family="bl4",
            flash_size=4 * 1024 * 1024,
            ssi263_port=0x90,
            keyboard_port=0xB0,
            keyclr_port=0xD0,
            display="parallel",
            display_cells=40,
            has_clock_pic=True,
            has_gas_gauge=True,
            parallel_port_base=0xA0,
            power_on_input_proven=True,
            keyboard_input_buffer=0x433F0,
            command_loop_timer=0x4165A,
            command_loop_timer_pc=0x0B36,
        ),
        HardwareProfile(
            name="tns",
            family="tns",
            flash_size=0,
            ssi263_port=0x90,
            keyboard_port=0xD0,
            keyclr_port=None,
            display=None,
            display_cells=0,
            has_clock_pic=True,
            has_gas_gauge=False,
            parallel_port_base=0xC0,
            power_on_input_proven=False,
            keyboard_input_buffer=0x4329D,
            command_loop_timer=0x41659,
            command_loop_timer_pc=0x0AF9,
        ),
    )
}
