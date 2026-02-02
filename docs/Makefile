.PHONY: help install dev build preview clean rebuild-tags rebuild-tag list-tags

# Default target
help:
	@echo "KAOS Documentation Commands"
	@echo ""
	@echo "Local Development:"
	@echo "  make install        - Install npm dependencies"
	@echo "  make dev            - Start development server"
	@echo "  make build          - Build static site"
	@echo "  make preview        - Preview built site locally"
	@echo "  make clean          - Remove build artifacts"
	@echo ""
	@echo "Version Management:"
	@echo "  make list-tags      - List available version tags"
	@echo "  make rebuild-tag TAG=v1.0.0  - Trigger docs rebuild for specific tag"
	@echo "  make rebuild-tags   - Rebuild docs for all version tags (interactive)"
	@echo ""

# Install dependencies
install:
	npm install

# Start development server
dev:
	npm run dev

# Build static site
build:
	npm run build

# Preview built site
preview:
	npm run preview

# Clean build artifacts
clean:
	rm -rf .vitepress/dist .vitepress/cache node_modules/.vite

# List available version tags
list-tags:
	@echo "Available version tags (excluding v0.0.x test tags):"
	@git tag --list "v*" --sort=-v:refname | grep -v '^v0\.0\.' | head -20

# Build the examples into jupyter notebooks
build-examples:
	@for f in examples/*.md; do \
		echo "$$f"; \
		jupytext --to ipynb "$$f" \
			--output "../examples/$$(basename "$${f%.md}.ipynb")"; \
	done


# Rebuild docs for a specific tag by triggering workflow dispatch
# Usage: make rebuild-tag TAG=v1.0.0
rebuild-tag:
ifndef TAG
	$(error TAG is required. Usage: make rebuild-tag TAG=v1.0.0)
endif
	@VERSION=$$(echo $(TAG) | sed 's/^v//'); \
	gh workflow run rebuild-docs.yaml -f version=$$VERSION
	@echo "Triggered rebuild for version: $(TAG)"
	@echo "Check status: gh run list --workflow=rebuild-docs.yaml"

# Interactive rebuild of all version tags
rebuild-tags:
	@echo "=== Rebuild All Version Docs ==="
	@echo ""
	@echo "To rebuild docs for all version tags with current config:"
	@echo "  gh workflow run rebuild-docs.yaml -f version=all"
	@echo ""
	@echo "To rebuild a specific version:"
	@echo "  make rebuild-tag TAG=v0.1.3"
	@echo ""
	@echo "Available versions to rebuild:"
	@git tag --list "v*" --sort=-v:refname | grep -v '^v0\.0\.' | head -10
