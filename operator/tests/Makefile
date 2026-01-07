# E2E Tests - parallel by default
NPROC := $(shell nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

.PHONY: test test-seq install clean

test: clean
	python -m pytest e2e/ -v -n $(NPROC) --dist loadscope

test-seq: clean
	python -m pytest e2e/ -v

install:
	pip install -e ".[dev]"

clean:
	@echo "Cleaning up test resources..."
	-helm uninstall agentic-e2e -n agentic-e2e-system 2>/dev/null || true
	-kubectl delete namespace agentic-e2e-system --wait=false 2>/dev/null || true
	-kubectl get ns -o name | grep e2e | xargs -I{} kubectl delete {} --wait=false 2>/dev/null || true
	@sleep 3
