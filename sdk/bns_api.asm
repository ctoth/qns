public _bns_exit
public _bns_say_wait

section bns_code

_bns_exit:
xor a
ld h, a
ld l, a
rst $38
ret

_bns_say_wait:
pop de
pop hl
push hl
push de
ld a, 2
rst $38
ret
