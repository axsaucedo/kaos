# E2E Tests - parallel by default (4 workers)
.PHONY: test test-seq clean

test:
	# Running in single line to ensure env var is reflected correctly
	#     This is required as github actions has empty nproc output
	JOBS="$$(nproc --all 2>/dev/null || true)"; JOBS="$${JOBS:-1}"; \
	uv run pytest e2e/ -v -s --log-cli-level=DEBUG -n "$$JOBS" --dist loadscope

test-seq:
	uv run pytest e2e/ -v -s --log-cli-level=DEBUG

clean:
	@echo "Cleaning up test resources..."
	-helm uninstall agentic-e2e -n agentic-e2e-system 2>/dev/null || true
	-kubectl delete namespace agentic-e2e-system --wait=false 2>/dev/null || true
	-kubectl get ns -o name | grep e2e | xargs -I{} kubectl delete {} --wait=false 2>/dev/null || true
	@sleep 3
