#include<uk/config.h>
#if CONFIG_LIBUKGCOV

#include <string.h>
#include<stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <uk/essentials.h>

void * __memcpy_chk(void *dest, const void *src, size_t len, size_t destlen __unused){
    return memcpy(dest, src, len);
}

int __sprintf_chk(char *str, int flag __unused, size_t slen, const char *format, ...){
    va_list args;
    va_start(args, format);
    int ret = vsnprintf(str, slen, format, args);
    va_end(args);
    return ret;
}

int __fprintf_chk(FILE *stream, int flag __unused, const char *format, ...){
    va_list args;
    va_start(args, format);
    int ret = vfprintf(stream, format, args);
    va_end(args);
    return ret;
}

int __vfprintf_chk(FILE *stream, int flag __unused, const char *format, va_list args){
    return vfprintf(stream, format, args);
}

long __isoc23_strtol(const char *nptr, char **endptr, int base){
    return strtol(nptr, endptr, base);
}

#endif