VERSION = 0.1.0

all: core-rules binding-js-build

test: core-test binding-js-test binding-swift-test

.PHONY: core-rules
core-rules:
	cd core; make rules-data

.PHONY: core-test
core-test: core-rules
	cd core; make test

.PHONY: binding-js-test
binding-js-test: binding-js-build
	cd bindings/js; npm run test

binding-js-build:
	cd bindings/js; npm run build

binding-swift-test:
	swift test
