"""Command-line interface for the BNS emulator."""

import argparse
import os
import sys
from collections.abc import Callable
from contextlib import nullcontext, redirect_stdout
from pathlib import Path

from .bns import BNS, SYNTH_BACKENDS
from .profiles import PROFILES
from .ssi263 import Phoneme
from .stdio import JSONLOutput

_SPEECH_STYLES = ("codes", "names", "ipa", "examples", "english")
DEFAULT_SYNTH_BACKEND = "pcm"


def settle_audio_backend(argv: list[str]) -> list[str]:
    """Let ``--audio`` stay a bare flag even though it now takes a backend.

    ``--audio`` accepts an optional backend name, and argparse hands an
    optional-valued flag whatever non-dash token follows it.  The long-
    documented invocation puts the ROM there:

        uv run -m qns.bns --audio roms/bspeng.bns

    which would otherwise be read as a backend named ``roms/bspeng.bns``.
    Supplying the default explicitly when the next token is plainly not a
    backend keeps both that form and ``--audio lpc`` working.
    """
    settled = []
    for position, token in enumerate(argv):
        settled.append(token)
        if token != "--audio":
            continue
        following = argv[position + 1] if position + 1 < len(argv) else None
        if following not in SYNTH_BACKENDS:
            settled.append(DEFAULT_SYNTH_BACKEND)
    return settled


def parse_hex_address(value: str) -> int:
    """Parse a hex address like 0xD468 or D468."""
    try:
        return int(value, 16)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid hex address: {value}")


def _bounded_int(minimum: int, maximum: int) -> Callable[[str], int]:
    """Build an argparse integer parser restricted to an inclusive range."""
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"invalid integer: {value}")
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(
                f"must be between {minimum} and {maximum}: {value}"
            )
        return parsed

    return parse


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
    parser.add_argument(
        "--audio",
        nargs="?",
        choices=tuple(SYNTH_BACKENDS),
        const=DEFAULT_SYNTH_BACKEND,
        default=None,
        metavar="BACKEND",
        help=(
            "Enable SSI-263 audio output, optionally naming the backend: "
            "pcm (AppleWin captures, the chip's timbre but one isolated "
            "recording per phoneme), lpc (those captures resynthesized "
            "through one continuous filter), or formant (SC-01 model, "
            f"continuous but a different chip).  Default: {DEFAULT_SYNTH_BACKEND}"
        ),
    )
    parser.add_argument(
        "--audio-log",
        type=Path,
        metavar="FILE",
        help=(
            "Write live PCM producer and sound-callback timing to CSV; "
            "requires --audio pcm"
        ),
    )
    parser.add_argument(
        "--synth",
        choices=tuple(SYNTH_BACKENDS),
        help=argparse.SUPPRESS,  # superseded by --audio BACKEND
    )
    parser.add_argument(
        "--model",
        choices=tuple(PROFILES),
        default="bsp",
        help="Select the hardware profile (default: bsp)",
    )
    parser.add_argument(
        "--core",
        choices=("compat", "direct"),
        default="direct",
        help="Select the z-core API path (default: direct)",
    )
    parser.add_argument("--trace", action="store_true",
                        help="Show boot trace instead of running")
    parser.add_argument("--realtime", action="store_true",
                        help="Hold emulation to wall-clock speed (implied by --audio)")
    parser.add_argument("--no-realtime", dest="realtime", action="store_false",
                        help="Run as fast as possible even with --audio")
    parser.set_defaults(realtime=None)
    parser.add_argument(
        "--input",
        choices=("keyboard", "6-key", "6-key-dvorak", "none", "serial0", "serial1"),
        help="Route standard input to the BNS keyboard, six-key Braille entry "
             "(fdsjkl, or ueohtn for Dvorak), or an ASCI channel",
    )
    parser.add_argument(
        "--reset",
        choices=("warm", "cold"),
        help="Apply the model's physical warm- or cold-reset startup gesture",
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
    parser.add_argument(
        "--trace-speech",
        type=str,
        metavar="FILE",
        help=(
            "Write every SSI-263 phoneme event to a CSV with its cycle "
            "count and full decoded register state"
        ),
    )
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
    speech = parser.add_argument_group(
        "retained speech settings",
        "Values a field unit keeps in battery-backed RAM.  Defaults are "
        "the midpoint of each range documented in BSAPI.H.",
    )
    speech.add_argument("--volume", type=_bounded_int(0, 15), metavar="0-15",
                        help="Speech amplitude (default 8)")
    speech.add_argument("--rate", type=_bounded_int(1, 16), metavar="1-16",
                        help="Speaking rate (default 9)")
    speech.add_argument("--pitch", type=_bounded_int(1, 32), metavar="1-32",
                        help="Filter frequency; the API's \"Pitch\" (default 17)")
    speech.add_argument("--frequency", type=_bounded_int(0, 255), metavar="0-255",
                        help="Inflection; the API's \"Frequency\" (default 128)")
    return parser


# CLI names follow BSAPI.H, whose "Pitch" is the filter-frequency cell
# and whose "Frequency" is the inflection cell.
_SPEECH_SETTING_FIELDS = {
    "volume": "volume",
    "rate": "rate",
    "pitch": "filter_frequency",
    "frequency": "inflection",
}


def _restart_with_same_settings() -> None:
    """Replace this process with the command line that started it.

    Rebuilding the machine in place would leave the previous run's stdin
    reader - a daemon thread blocked in a read on the same descriptor -
    racing the new one for keystrokes.  Re-executing sidesteps that
    entirely and is what "same settings" means most literally:
    `sys.orig_argv` is the original command line, interpreter flags and
    `-m qns.bns` included.  The run loop has already restored the
    terminal and stopped the audio device by this point.
    """
    print("Restarting...", flush=True)
    argv = list(sys.orig_argv)
    try:
        os.execv(argv[0], argv)
    except OSError as error:
        # An exec that fails leaves the process running, so say so rather
        # than carrying on as though the restart had happened.
        print(f"Restart failed ({error}); exiting instead.", flush=True)
        raise SystemExit(1) from error


def speech_settings(args: argparse.Namespace) -> dict[str, int]:
    """Collect the speech settings the user overrode on the command line."""
    return {
        field: getattr(args, option)
        for option, field in _SPEECH_SETTING_FIELDS.items()
        if getattr(args, option, None) is not None
    }


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(
        settle_audio_backend(sys.argv[1:] if argv is None else argv)
    )

    # --synth predates --audio taking a backend.  It still selects one, but
    # only where --audio did not say so itself.
    if args.synth is not None and args.audio == DEFAULT_SYNTH_BACKEND:
        args.audio = args.synth
    if args.synth is not None and args.audio is None:
        parser.error("--synth selects a backend for --audio; pass --audio too")

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

    # Keyboard input costs the per-instruction execution path, but that is
    # affordable at real-time speed: the CPU sleeps between phonemes, so
    # pacing dominates and speech keeps up either way.  --input none exists
    # for offline captures that want the core's full speed.
    if structured_stdio:
        stdin_device = "jsonl"
    elif args.input == "none":
        stdin_device = None
    else:
        stdin_device = args.input or "keyboard"
    audio_enabled = args.audio is not None
    if args.audio_log is not None and args.audio != "pcm":
        parser.error("--audio-log requires --audio pcm")
    realtime = args.realtime if args.realtime is not None else audio_enabled

    with output_context:
        bns = BNS(
            audio=audio_enabled,
            synth_backend=args.audio or DEFAULT_SYNTH_BACKEND,
            audio_log=args.audio_log,
            model=args.model,
            core=args.core,
            trace_io=args.trace_io,
            trace_interrupts=args.trace_interrupts,
            trace_writes=args.trace_writes,
            trace_writes_range=trace_range,
            trace_first_writes=args.trace_first_writes,
            dump_writes_file=args.dump_writes,
            speech_settings=speech_settings(args),
            stdin_device=stdin_device,
            realtime=realtime,
            reset=args.reset,
            serial_output=serial_output,
            serial_output_channel=serial_output_channel,
            pc_disk_dir=pc_disk_dir,
            stdio_output=stdio_output,
            stdio_watch_pc=args.watch_pc,
            english_callback=english_callback,
        )
        speech_observers: list[Callable[[int, str], None]] = []
        speech_trace: list[tuple[int, ...]] = []

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

            speech_observers.append(emit_stdio_speech)
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

            speech_observers.append(emit_speech_phoneme)

        if args.trace_speech:
            # Written and flushed per event: a boot long enough to reach
            # speech runs for minutes, and a trace only readable after the
            # run finishes is a trace nobody can work with.
            speech_trace_file = open(args.trace_speech, "w", encoding="ascii")
            speech_trace_file.write(
                "cycle,code,name,duration_mode,rate,inflection,"
                "articulation,amplitude,filter_freq,playback_duration\n"
            )
            speech_trace_file.flush()

            def record_speech_registers(code: int, name: str) -> None:
                state = bns.ssi263.state()
                speech_trace.append(())
                speech_trace_file.write(
                    f"{bns.ssi263.current_cycle},{code},{name},{state.duration},"
                    f"{state.rate},{state.inflection},{state.articulation},"
                    f"{state.amplitude},{state.filter_freq},"
                    f"{state.playback_duration}\n"
                )
                speech_trace_file.flush()

            speech_observers.append(record_speech_registers)

        if speech_observers:
            def dispatch_speech(code: int, name: str) -> None:
                for observe in speech_observers:
                    observe(code, name)

            bns.ssi263.set_phoneme_callback(dispatch_speech)

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

        if args.trace_speech:
            speech_trace_file.close()
            print(f"Wrote {len(speech_trace)} speech events to {args.trace_speech}")

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

        # Last, so that a restart saves and closes everything a normal exit
        # would.  Restarting before the nonvolatile state was written would
        # discard the session's RAM - the emulated battery-backed memory -
        # which is the opposite of resuming with the same settings.
        if bns.restart_requested:
            _restart_with_same_settings()


if __name__ == "__main__":
    main()
