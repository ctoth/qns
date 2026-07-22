"""Command-line interface for the BNS emulator."""

import argparse
import sys
from collections.abc import Callable
from contextlib import nullcontext, redirect_stdout
from pathlib import Path

from .bns import BNS
from .profiles import PROFILES
from .ssi263 import Phoneme
from .stdio import JSONLOutput

_SPEECH_STYLES = ("codes", "names", "ipa", "examples", "english")


def parse_hex_address(value: str) -> int:
    """Parse a hex address like 0xD468 or D468."""
    try:
        return int(value, 16)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid hex address: {value}")


def _format_phoneme(phoneme: Phoneme, style: str) -> str:
    """Render one phoneme as codes, names, ipa, or examples."""
    if style == "codes":
        return f"{phoneme.code:02X}"
    field = {"names": "name", "ipa": "ipa", "examples": "example"}[style]
    return getattr(phoneme, field)


def build_parser() -> argparse.ArgumentParser:
    """Build the qns.bns argument parser."""
    parser = argparse.ArgumentParser(
        prog="qns.bns",
        description="BNS (Braille 'N Speak) emulator"
    )
    parser.add_argument("rom_file", help="ROM file to load (.bns or raw firmware)")

    # Basic options
    parser.add_argument("--audio", action="store_true",
                        help="Enable SSI-263 audio output")
    parser.add_argument(
        "--synth",
        choices=("pcm", "formant"),
        default="pcm",
        help="Audio backend: AppleWin PCM captures or SC-01 formant synthesis",
    )
    parser.add_argument(
        "--model",
        choices=tuple(PROFILES),
        default="bsp",
        help="Select the hardware profile (default: bsp)",
    )
    parser.add_argument("--trace", action="store_true",
                        help="Show boot trace instead of running")
    parser.add_argument("--input", choices=("keyboard", "serial0", "serial1"),
                        help="Route standard input to the BNS keyboard or an ASCI channel")
    parser.add_argument(
        "--power-on-input",
        action="store_true",
        help=(
            "Read and hold the first keyboard chord during power-on "
            "(BS2 requires uppercase I)"
        ),
    )
    parser.add_argument("--output", choices=("console", "serial0", "serial1"),
                        default="console",
                        help="Show console logs or route one raw ASCI channel to standard output")
    parser.add_argument(
        "--stdio",
        choices=("jsonl",),
        help="Multiplex keyboard, serial, speech, and display events as JSON Lines",
    )
    parser.add_argument(
        "--speech",
        choices=_SPEECH_STYLES,
        help=(
            "Print retained speech as codes, phoneme names, IPA, "
            "datasheet example words, or exact firmware English"
        ),
    )
    parser.add_argument(
        "--speech-stream",
        choices=_SPEECH_STYLES,
        help=(
            "Stream speech as phoneme codes, names, IPA, datasheet example "
            "words, or exact firmware English"
        ),
    )
    parser.add_argument(
        "--display",
        choices=("codes", "unicode"),
        help="Print the final retained Braille display through standard output",
    )

    # Debugging options
    parser.add_argument("--cycles", type=int, default=0, metavar="N",
                        help="Run for N cycles then exit (default: unlimited)")
    parser.add_argument("--trace-io", action="store_true",
                        help="Log all I/O port reads/writes")
    parser.add_argument("--trace-interrupts", action="store_true",
                        help="Log interrupt activity (IRQ lines, ITC register)")
    parser.add_argument("--trace-writes", type=parse_hex_address, metavar="ADDR",
                        help="Log writes to specific physical address (hex, e.g., 0xD468)")
    parser.add_argument(
        "--watch-pc",
        type=parse_hex_address,
        metavar="ADDR",
        help="Emit one JSONL CPU event when execution reaches this logical address",
    )
    parser.add_argument("--trace-writes-range", nargs=2, type=parse_hex_address,
                        metavar=("START", "END"),
                        help="Log writes to physical address range (hex, e.g., 0xD000 0xE000)")
    parser.add_argument("--trace-first-writes", type=int, metavar="N",
                        help="Log first N memory writes with addresses and values")
    parser.add_argument("--dump-writes", type=str, metavar="FILE",
                        help="Dump all unique write addresses to CSV file (address,count)")
    parser.add_argument("--dump-ram", type=str, metavar="FILE",
                        help="Dump RAM contents to file after execution")
    state_group = parser.add_mutually_exclusive_group()
    state_group.add_argument(
        "--state",
        type=str,
        metavar="FILE",
        help="Load binary nonvolatile state before execution and save it afterward",
    )
    state_group.add_argument(
        "--state-dir",
        type=str,
        metavar="DIR",
        help="Load directory-backed nonvolatile state before execution and save it afterward",
    )
    parser.add_argument(
        "--pc-disk-dir",
        type=str,
        metavar="DIR",
        help="Expose a host directory to the firmware as PC Disk on ASCI channel 0",
    )
    parser.add_argument("--stats", action="store_true",
                        help="Show execution statistics at end")
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.stdio and (
        args.input is not None
        or args.output != "console"
        or args.speech is not None
        or args.speech_stream is not None
        or args.display is not None
    ):
        parser.error(
            "--stdio jsonl cannot be combined with --input, --output, "
            "--speech, --speech-stream, or --display"
        )
    if args.watch_pc is not None and not args.stdio:
        parser.error("--watch-pc requires --stdio jsonl")
    if args.watch_pc is not None and not 0 <= args.watch_pc <= 0xFFFF:
        parser.error("--watch-pc must be a logical address from 0x0000 through 0xFFFF")

    pc_disk_dir = None
    if args.pc_disk_dir:
        pc_disk_dir = Path(args.pc_disk_dir)
        if pc_disk_dir.exists() and not pc_disk_dir.is_dir():
            parser.error(f"--pc-disk-dir is not a directory: {pc_disk_dir}")
        pc_disk_dir.mkdir(parents=True, exist_ok=True)

    # Convert range args to tuple if provided
    trace_range = None
    if args.trace_writes_range:
        trace_range = tuple(args.trace_writes_range)

    structured_stdio = args.stdio == "jsonl"
    raw_serial_output = not structured_stdio and args.output != "console"
    serial_output_channel = int(args.output[-1]) if raw_serial_output else None
    serial_output = sys.stdout.buffer if raw_serial_output else None
    stdio_output = JSONLOutput(sys.stdout) if structured_stdio else None
    english_chunks: list[str] = []
    english_callback: Callable[[str], None] | None = None
    if stdio_output is not None:
        def emit_stdio_english(text: str) -> None:
            stdio_output.emit("speech", text=text)

        english_callback = emit_stdio_english
    elif args.speech_stream == "english":
        def stream_english(text: str) -> None:
            print(f"Speech english: {text}", flush=True)

        english_callback = stream_english
    elif args.speech == "english":
        english_callback = english_chunks.append
    output_context = (
        redirect_stdout(sys.stderr)
        if raw_serial_output or structured_stdio
        else nullcontext()
    )
    display_frame_emitted = False

    with output_context:
        bns = BNS(
            audio=args.audio,
            synth_backend=args.synth,
            model=args.model,
            trace_io=args.trace_io,
            trace_interrupts=args.trace_interrupts,
            trace_writes=args.trace_writes,
            trace_writes_range=trace_range,
            trace_first_writes=args.trace_first_writes,
            dump_writes_file=args.dump_writes,
            stdin_device="jsonl" if structured_stdio else (args.input or "keyboard"),
            power_on_input=args.power_on_input,
            serial_output=serial_output,
            serial_output_channel=serial_output_channel,
            pc_disk_dir=pc_disk_dir,
            stdio_output=stdio_output,
            stdio_watch_pc=args.watch_pc,
            english_callback=english_callback,
        )
        if stdio_output is not None:
            def emit_stdio_speech(_code: int, _name: str) -> None:
                phoneme = bns.ssi263.get_phonemes(start=-1)[0]
                stdio_output.emit(
                    "speech",
                    code=phoneme.code,
                    name=phoneme.name,
                    ipa=phoneme.ipa,
                    example=phoneme.example,
                )

            bns.ssi263.set_phoneme_callback(emit_stdio_speech)
            if bns.display is not None:
                bns.display.set_frame_callback(
                    lambda frame: stdio_output.emit("display", cells=list(frame))
                )

        elif args.speech_stream and args.speech_stream != "english":
            def emit_speech_phoneme(code: int, _name: str) -> None:
                if code == 0:
                    return
                phoneme = bns.ssi263.get_phonemes(start=-1)[0]
                speech = _format_phoneme(phoneme, args.speech_stream)
                print(f"Speech {args.speech_stream}: {speech}", flush=True)

            bns.ssi263.set_phoneme_callback(emit_speech_phoneme)

        if args.display:
            if bns.display is None:
                raise RuntimeError(
                    f"{args.model} has no built-in Braille display"
                )

            def emit_display_frame(frame: bytes) -> None:
                nonlocal display_frame_emitted
                display_frame_emitted = True
                if args.display == "codes":
                    display = " ".join(f"{cell:02X}" for cell in frame)
                else:
                    display = "".join(chr(0x2800 | cell) for cell in frame)
                print(f"Display {args.display}: {display}", flush=True)

            bns.display.set_frame_callback(emit_display_frame)

        bns.load_rom(args.rom_file)
        if args.state:
            state_path = Path(args.state)
            if state_path.exists():
                bns.load_state(state_path)
            else:
                print(f"Initializing nonvolatile RAM state: {state_path}")
        elif args.state_dir:
            state_dir = Path(args.state_dir)
            if state_dir.exists() and not state_dir.is_dir():
                parser.error(f"--state-dir is not a directory: {state_dir}")
            if state_dir.exists() and any(state_dir.iterdir()):
                bns.load_state_dir(state_dir)
            else:
                print(f"Initializing nonvolatile state directory: {state_dir}")

        if args.trace:
            bns.trace_boot()
        else:
            bns.run(max_cycles=args.cycles)

        if args.speech:
            if args.speech == "english":
                speech = " ".join(english_chunks)
            else:
                speech = " ".join(
                    _format_phoneme(phoneme, args.speech)
                    for phoneme in bns.ssi263.get_phonemes(include_pauses=False)
                )
            print(f"Speech {args.speech}: {speech}")

        if args.display and not display_frame_emitted:
            emit_display_frame(bytes(bns.display.buffer))

        # Post-run actions
        if args.dump_ram:
            bns.dump_ram(args.dump_ram)

        if args.state:
            bns.save_state(args.state)
        elif args.state_dir:
            bns.save_state_dir(args.state_dir)

        # Dump trace data if any tracing was enabled
        bns.dump_trace_data()

        if args.stats:
            bns.print_stats()

        if stdio_output is not None:
            stdio_output.emit("system", state="exited")


if __name__ == "__main__":
    main()
