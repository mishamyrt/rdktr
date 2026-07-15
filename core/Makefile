CC      ?= cc
CFLAGS  ?= -std=c11 -O2 -Wall -Wextra
SRC     := src/engine.c src/blob.c src/multi.c src/normalize.c src/rules_data.c

.PHONY: test test-asan clean src/rules_data.c

src/rules_data.c:
	uv run scripts/compile_rules.py --rules ./rules  --out-c $@

configure: requirements.txt
	uv venv
	uv pip install -r requirements.txt

test: build/test_rdktr
	./build/test_rdktr

test-asan:
	@mkdir -p build
	$(CC) $(CFLAGS) -g -fsanitize=address,undefined -Iinclude $(SRC) tests/test_rdktr.c -o build/test_rdktr_asan
	./build/test_rdktr_asan

build/test_rdktr: $(SRC) tests/test_rdktr.c include/rdktr.h src/rdktr_internal.h
	@mkdir -p build
	$(CC) $(CFLAGS) -Iinclude $(SRC) tests/test_rdktr.c -o $@

clean:
	rm -rf build
