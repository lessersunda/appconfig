ICU_CFLAGS = `icu-config --cppflags-searchpath`
PG_INCLUDE_DIR = /usr/include/postgresql/{{ pg_version }}/server
PG_PKG_LIB_DIR = `pg_config --pkglibdir`

collkey_icu.so: collkey_icu.o
	ld -shared -o collkey_icu.so collkey_icu.o -ldl -lm -L/usr/lib/x86_64-linux-gnu -licui18n -licuuc -licudata -ldl -lm

collkey_icu.o: collkey_icu.c
	gcc -Wall -fPIC $(ICU_CFLAGS) -I $(PG_INCLUDE_DIR) -o collkey_icu.o -c collkey_icu.c

clean:
	rm -f *.o *.so

install:
	install collkey_icu.so $(PG_PKG_LIB_DIR)
