public hello_main

section bns_code
hello_main:
ld hl, hello_message
ld a, 2
rst $38
ret

hello_message:
defm "QNS ASSEMBLY DONE"
defb 0
