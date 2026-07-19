CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra
RULES_DIR ?= ./rules
RULES_SRC := $(shell find "$(RULES_DIR)" -name '*.md')
RULES_DATA := src/rules_data.c
TARGET_DIR ?= build
SRC := \
	src/engine.c \
	src/blob.c \
	src/multi.c \
	src/normalize.c \
	$(RULES_DATA)

PYTHON_VERSION := 3.13
PYTHON_VENV_DIR := .venv

all: $(RULES_DATA) test

rules-data: $(RULES_DATA)

.PHONY: test
test: $(TARGET_DIR)/test_rdktr
	"./$(TARGET_DIR)/test_rdktr"

.PHONY: test-asan
test-asan: $(TARGET_DIR)/test_rdktr_asan
	"./$(TARGET_DIR)/test_rdktr_asan"

.PHONY: clean
clean:
	rm -rf "$(TARGET_DIR)"
	rm -rf "$(PYTHON_VENV_DIR)"

.PHONY: rules-lint
rules-lint: $(PYTHON_VENV_DIR)
	uv run scripts/lint_rules.py ./rules

.PHONY: rules-build
rules-build: $(RULES_DATA)

$(RULES_DATA): $(PYTHON_VENV_DIR) $(RULES_SRC)
	uv run scripts/compile_rules.py --rules ./rules  --out-c $@

$(PYTHON_VENV_DIR): requirements.txt
	uv venv --python "$(PYTHON_VERSION)" "$(PYTHON_VENV_DIR)"
	uv pip install -r requirements.txt

$(TARGET_DIR)/test_rdktr: $(SRC) tests/test_rdktr.c include/rdktr.h src/rdktr_internal.h
	@mkdir -p "$(TARGET_DIR)"
	$(CC) $(CFLAGS) -Iinclude $(SRC) tests/test_rdktr.c -o $@

$(TARGET_DIR)/test_rdktr_asan: $(SRC) tests/test_rdktr.c include/rdktr.h src/rdktr_internal.h
	@mkdir -p "$(TARGET_DIR)"
	$(CC) $(CFLAGS) \
	    -g -fsanitize=address,undefined \
		-Iinclude \
		$(SRC) tests/test_rdktr.c \
		-o "$(TARGET_DIR)/test_rdktr_asan"
