org $1000

public __bns_entry
public __bns_code_end
public __bns_stack_top
public __bns_end_marker

jr __bns_entry
defb "BNS", 0
defw 0, 0, 0, 0

__bns_entry:
nop
__bns_code_end:
defs 4, 0
__bns_stack_top:
__bns_end_marker:
defb $aa
