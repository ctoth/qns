#ifndef BNS_API_H
#define BNS_API_H

typedef char bns_pointer_must_be_16_bits[(sizeof(void *) == 2) ? 1 : -1];
typedef char bns_int_must_be_16_bits[(sizeof(unsigned int) == 2) ? 1 : -1];

extern void bns_exit(void);
extern void bns_say_wait(const char *message) __smallc;

#endif
