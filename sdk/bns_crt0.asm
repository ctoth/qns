extern hello_main

public __bns_entry
public __bns_code_end
public __bns_stack_top
public __bns_end_marker

section bns_header
org $1000

jr __bns_entry
defb "BNS", 0
defw 0, 0, 0, 0

section bns_code
__bns_entry:
ld sp, __bns_stack_top
call hello_main
xor a
ld h, a
ld l, a
rst $38

section bns_code_end
__bns_code_end:

section bns_stack
defs 256, 0
__bns_stack_top:

section bns_end
__bns_end_marker:
defb $aa
