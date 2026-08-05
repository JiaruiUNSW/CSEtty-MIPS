.text
main:
    li   $v0, 1
    syscall
    li   $a0, 124
    li   $v0, 11
    syscall
    lw   $a0, 4($a1)
    li   $v0, 4
    syscall
    li   $v0, 10
    syscall
