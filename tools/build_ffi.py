"""CFFI build script for z180emu wrapper.

This script preprocesses the z180emu headers and generates Python bindings.

Usage:
    python tools/build_ffi.py

The script will:
1. Parse z180emu headers
2. Generate _z180_cffi.c and _z180_cffi.*.pyd
3. Place the compiled extension in qns/
"""

from cffi import FFI
import os
import sys

# Find z180emu source
Z180EMU_PATH = os.environ.get("Z180EMU_PATH", "C:/Users/Q/src/z180emu")

if not os.path.exists(Z180EMU_PATH):
    print(f"Error: z180emu not found at {Z180EMU_PATH}")
    print("Set Z180EMU_PATH environment variable to the z180emu source directory")
    sys.exit(1)

ffi = FFI()

# Simplified C declarations for CFFI
# We expose only what we need - the rest is handled internally
CDEF = """
// Basic types
typedef uint8_t UINT8;
typedef uint16_t UINT16;
typedef uint32_t UINT32;
typedef int8_t INT8;
typedef int32_t INT32;
typedef UINT32 offs_t;
typedef void device_t;

// Memory access callbacks - Python will provide these
typedef UINT8 (*mem_read_callback)(offs_t address);
typedef void (*mem_write_callback)(offs_t address, UINT8 data);
typedef UINT8 (*io_read_callback)(offs_t port);
typedef void (*io_write_callback)(offs_t port, UINT8 data);

// CPU state indices
#define Z180_PC 0x100000
#define Z180_SP ...
#define Z180_AF ...
#define Z180_BC ...
#define Z180_DE ...
#define Z180_HL ...
#define Z180_IX ...
#define Z180_IY ...
#define Z180_A ...
#define Z180_B ...
#define Z180_C ...
#define Z180_D ...
#define Z180_E ...
#define Z180_H ...
#define Z180_L ...

// Line states
#define CLEAR_LINE 0
#define ASSERT_LINE 1

// IRQ lines
#define Z180_IRQ0 0
#define Z180_IRQ1 1
#define Z180_IRQ2 2

// Our simplified wrapper API
typedef struct qns_z180 qns_z180_t;

// Create a Z180 CPU with Python callbacks for memory/IO
qns_z180_t* qns_z180_create(
    UINT32 clock,
    mem_read_callback mem_read,
    mem_write_callback mem_write,
    io_read_callback io_read,
    io_write_callback io_write
);

// Destroy the CPU
void qns_z180_destroy(qns_z180_t* cpu);

// Reset the CPU
void qns_z180_reset(qns_z180_t* cpu);

// Debug counters
unsigned long qns_get_io_read_count(void);
unsigned long qns_get_io_write_count(void);

// Execute for given cycles, return actual cycles executed
int qns_z180_execute(qns_z180_t* cpu, int cycles);

// Get CPU register state
UINT32 qns_z180_get_reg(qns_z180_t* cpu, int reg);

// Set IRQ line
void qns_z180_set_irq(qns_z180_t* cpu, int line, int state);

// Get PC directly (convenience)
UINT16 qns_z180_get_pc(qns_z180_t* cpu);

// Check if halted
int qns_z180_is_halted(qns_z180_t* cpu);

// Get MMU register values (internal z180emu state)
UINT8 qns_z180_get_cbr(qns_z180_t* cpu);
UINT8 qns_z180_get_bbr(qns_z180_t* cpu);
UINT8 qns_z180_get_cbar(qns_z180_t* cpu);
"""

# C source that wraps z180emu
SOURCE = f'''
#include <stdlib.h>
#include <string.h>

// Include z180emu
// z80common.h has tentative definition "int VERBOSE;" - we provide actual definition first
int VERBOSE = 0;
#include "z180/z80common.h"
#include "z180/z80daisy.h"
#include "z180/z80scc.h"
#include "z180/z180asci.h"
#include "z180/z180.h"

// Stub for debugger hook (required by z180emu)
void debugger_instruction_hook(device_t *device, offs_t curpc) {{
    // No-op: debugger not used
}}

// Callback types for Python
typedef UINT8 (*mem_read_callback)(offs_t address);
typedef void (*mem_write_callback)(offs_t address, UINT8 data);
typedef UINT8 (*io_read_callback)(offs_t port);
typedef void (*io_write_callback)(offs_t port, UINT8 data);

// Our wrapper structure
typedef struct qns_z180 {{
    struct z180_device* device;
    struct address_space mem_space;
    struct address_space io_space;
    mem_read_callback py_mem_read;
    mem_write_callback py_mem_write;
    io_read_callback py_io_read;
    io_write_callback py_io_write;
}} qns_z180_t;

// Static pointer for callback routing (single instance for now)
static qns_z180_t* g_cpu = NULL;

// Memory read thunk
static UINT8 mem_read_thunk(offs_t addr) {{
    if (g_cpu && g_cpu->py_mem_read) {{
        return g_cpu->py_mem_read(addr);
    }}
    return 0xFF;
}}

static UINT8 mem_read_raw_thunk(offs_t addr) {{
    return mem_read_thunk(addr);
}}

static void mem_write_thunk(offs_t addr, UINT8 data) {{
    if (g_cpu && g_cpu->py_mem_write) {{
        g_cpu->py_mem_write(addr, data);
    }}
}}

// IO read/write thunks - with debug counters
static unsigned long io_read_count = 0;
static unsigned long io_write_count = 0;

static UINT8 io_read_thunk(offs_t port) {{
    io_read_count++;
    if (g_cpu && g_cpu->py_io_read) {{
        return g_cpu->py_io_read(port);
    }}
    return 0xFF;
}}

static void io_write_thunk(offs_t port, UINT8 data) {{
    io_write_count++;
    if (g_cpu && g_cpu->py_io_write) {{
        g_cpu->py_io_write(port, data);
    }}
}}

unsigned long qns_get_io_read_count(void) {{ return io_read_count; }}
unsigned long qns_get_io_write_count(void) {{ return io_write_count; }}

// IRQ acknowledge callback
static int irq_ack(device_t* device, int irqnum) {{
    return 0xFF;  // No vector for IM1
}}

// Serial callbacks (stubs)
static int serial_rx(device_t* device, int channel) {{
    return -1;  // No data
}}

static void serial_tx(device_t* device, int channel, UINT8 data) {{
    // Discard for now
}}

// Create a Z180 CPU
qns_z180_t* qns_z180_create(
    UINT32 clock,
    mem_read_callback mem_read,
    mem_write_callback mem_write,
    io_read_callback io_read,
    io_write_callback io_write
) {{
    qns_z180_t* cpu = (qns_z180_t*)calloc(1, sizeof(qns_z180_t));
    if (!cpu) return NULL;

    // Store Python callbacks
    cpu->py_mem_read = mem_read;
    cpu->py_mem_write = mem_write;
    cpu->py_io_read = io_read;
    cpu->py_io_write = io_write;

    // Set up address spaces with our thunks
    cpu->mem_space.read_byte = mem_read_thunk;
    cpu->mem_space.write_byte = mem_write_thunk;
    cpu->mem_space.read_raw_byte = mem_read_raw_thunk;

    cpu->io_space.read_byte = io_read_thunk;
    cpu->io_space.write_byte = io_write_thunk;
    cpu->io_space.read_raw_byte = io_read_thunk;

    // Set global pointer for thunks
    g_cpu = cpu;

    // Create the z180 device
    cpu->device = cpu_create_z180(
        "z180",             // tag
        Z180_TYPE_Z180,     // type
        clock,              // clock
        &cpu->mem_space,    // RAM
        NULL,               // ROM (Z182 only)
        &cpu->io_space,     // I/O space
        irq_ack,            // IRQ callback
        NULL,               // daisy chain
        serial_rx,          // ASCI RX
        serial_tx,          // ASCI TX
        NULL,               // SCC RX (Z182 only)
        NULL,               // SCC TX (Z182 only)
        NULL,               // parport read (Z182 only)
        NULL                // parport write (Z182 only)
    );

    if (!cpu->device) {{
        free(cpu);
        return NULL;
    }}

    cpu_reset_z180(cpu->device);
    return cpu;
}}

void qns_z180_destroy(qns_z180_t* cpu) {{
    if (cpu) {{
        if (g_cpu == cpu) g_cpu = NULL;
        // Note: z180emu doesn't have a destroy function, so we just free our wrapper
        free(cpu);
    }}
}}

void qns_z180_reset(qns_z180_t* cpu) {{
    if (cpu && cpu->device) {{
        cpu_reset_z180(cpu->device);
    }}
}}

int qns_z180_execute(qns_z180_t* cpu, int cycles) {{
    if (cpu && cpu->device) {{
        cpu_execute_z180(cpu->device, cycles);
        return cycles;  // z180emu doesn't return actual cycles
    }}
    return 0;
}}

UINT32 qns_z180_get_reg(qns_z180_t* cpu, int reg) {{
    if (cpu && cpu->device) {{
        return (UINT32)cpu_get_state_z180(cpu->device, reg);
    }}
    return 0;
}}

void qns_z180_set_irq(qns_z180_t* cpu, int line, int state) {{
    if (cpu && cpu->device) {{
        z180_set_irq_line(cpu->device, line, state);
    }}
}}

UINT16 qns_z180_get_pc(qns_z180_t* cpu) {{
    return (UINT16)qns_z180_get_reg(cpu, Z180_PC);
}}

int qns_z180_is_halted(qns_z180_t* cpu) {{
    return (int)qns_z180_get_reg(cpu, Z180_HALT);
}}

// MMU register accessors using cpu_get_state_z180
// Z180_CBR/BBR/CBAR are I/O register indices 56/57/58 in the Z180 enum

UINT8 qns_z180_get_cbr(qns_z180_t* cpu) {{
    return (UINT8)qns_z180_get_reg(cpu, 56);  // Z180_CBR
}}

UINT8 qns_z180_get_bbr(qns_z180_t* cpu) {{
    return (UINT8)qns_z180_get_reg(cpu, 57);  // Z180_BBR
}}

UINT8 qns_z180_get_cbar(qns_z180_t* cpu) {{
    return (UINT8)qns_z180_get_reg(cpu, 58);  // Z180_CBAR
}}
'''

# Set up the FFI
ffi.cdef(CDEF)

ffi.set_source(
    "qns._z180_cffi",
    SOURCE,
    include_dirs=[Z180EMU_PATH],
    sources=[
        # z180emu source files
        # Note: z180.c #includes z180op.c, z180cb.c, z180dd.c, z180ed.c, z180fd.c, z180xy.c
        os.path.join(Z180EMU_PATH, "z180/z180.c"),
        os.path.join(Z180EMU_PATH, "z180/z180asci.c"),
        os.path.join(Z180EMU_PATH, "z180/z80daisy.c"),
        os.path.join(Z180EMU_PATH, "z180/z80scc.c"),
    ],
    extra_compile_args=["-O2", "-D_CRT_SECURE_NO_WARNINGS"] if sys.platform != "win32" else ["/O2", "/D_CRT_SECURE_NO_WARNINGS"],
)

if __name__ == "__main__":
    import tempfile
    import shutil
    import glob

    print(f"Building z180 CFFI extension...")
    print(f"z180emu path: {Z180EMU_PATH}")

    # Build in temp directory to avoid setuptools package discovery issues
    tmpdir = tempfile.mkdtemp()
    original_dir = os.getcwd()

    try:
        os.chdir(tmpdir)
        ffi.compile(verbose=True, tmpdir=tmpdir)

        # Find and copy the built extension
        script_dir = os.path.dirname(os.path.abspath(__file__))
        qns_dir = os.path.join(os.path.dirname(script_dir), "qns")

        # Look for pyd files in qns subdirectory of tmpdir
        search_paths = [
            os.path.join(tmpdir, "qns", "_z180_cffi*"),
            os.path.join(tmpdir, "_z180_cffi*"),
        ]

        for pattern in search_paths:
            for ext in glob.glob(pattern):
                dest = os.path.join(qns_dir, os.path.basename(ext))
                print(f"Copying {ext} -> {dest}")
                shutil.copy2(ext, dest)

        print("Done!")
    finally:
        os.chdir(original_dir)
        # Ignore cleanup errors on Windows
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
