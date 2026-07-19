VERSION = 0.1.2

all: core-rules binding-js-build

test: core-lint-rules core-test binding-js-test binding-swift-test

.PHONY: core-rules
core-rules:
	cd core; make rules-data

.PHONY: core-rules
core-lint-rules:
	cd core; make rules-lint

.PHONY: core-test
core-test: core-rules
	cd core; make test

.PHONY: binding-js-test
binding-js-test: binding-js-build
	cd bindings/js; npm run test

.PHONY: binding-js-build
binding-js-build:
	cd bindings/js; npm run build

.PHONY: binding-js-dev
binding-js-dev:
	cd bindings/js; npm run dev

.PHONY: web-dev
web-dev:
	cd examples/web; pnpm dev

.PHONY: binding-swift-test
binding-swift-test:
	swift test

.PHONY: publish
publish:
	@sed -E 's/"version": "[^"]+"/"version": "${VERSION}"/' bindings/js/package.json > bindings/js/package.json.tmp
	@mv bindings/js/package.json.tmp bindings/js/package.json
	@git add \
		Makefile \
		bindings/js/package.json
	@git commit -m "chore: release v$(VERSION) 🔥"
	@git tag v$(VERSION)
	@git-cliff -o CHANGELOG.md
	@git tag -d v$(VERSION)
	@git add CHANGELOG.md
	@git commit --amend --no-edit
	@git tag -a v$(VERSION) -m "release v$(VERSION)"
	@git push
	@git push --tags
