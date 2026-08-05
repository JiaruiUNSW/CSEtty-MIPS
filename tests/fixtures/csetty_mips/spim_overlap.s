.data
separator: .asciiz "|"
newline: .asciiz "\n"
signed_byte: .byte 0x80

.text
.globl main
main:
    li $t0, 0
    li $t1, 1
sum_loop:
    addu $t0, $t0, $t1
    addiu $t1, $t1, 1
    slti $t2, $t1, 6
    bne $t2, $zero, sum_loop
    nop

    move $a0, $t0
    li $v0, 1
    syscall
    la $a0, separator
    li $v0, 4
    syscall

    lb $a0, signed_byte
    li $v0, 1
    syscall
    la $a0, separator
    li $v0, 4
    syscall

    li $a0, 7
    jal twice
    nop
    move $a0, $v0
    li $v0, 1
    syscall
    la $a0, newline
    li $v0, 4
    syscall

    li $v0, 10
    syscall

twice:
    sll $v0, $a0, 1
    jr $ra
    nop
