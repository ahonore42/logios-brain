.PHONY: dev start logs stop test provision clean

# Default target
all: dev

# Start all services in detached mode (local dev)
dev:
	docker compose up -d
	@echo "Logios Brain is starting..."
	@echo "  App:    http://localhost:8000"
	@echo "  Health: http://localhost:8000/health"
	@echo ""
	@echo "Waiting for app to be healthy..."
	@for i in $$(seq 1 30); do \
		if curl -sf http://localhost:8000/health > /dev/null 2>&1; then \
			echo "App is healthy."; \
			exit 0; \
		fi; \
		if [ $$i -eq 30 ]; then \
			echo "ERROR: App did not become healthy in time."; \
			docker compose logs --tail=50 app; \
			exit 1; \
		fi; \
		sleep 2; \
	done

# Start services and rebuild images (production/VPS)
start:
	docker compose up -d --build
	@echo "Waiting for app to be healthy..."
	@for i in $$(seq 1 30); do \
		if curl -sf http://localhost:8000/health > /dev/null 2>&1; then \
			echo "App is healthy."; \
			exit 0; \
		fi; \
		if [ $$i -eq 30 ]; then \
			echo "ERROR: App did not become healthy in time."; \
			docker compose logs --tail=50 app; \
			exit 1; \
		fi; \
		sleep 2; \
	done
	@echo "App is healthy."

# Tail logs from all services
logs:
	docker compose logs -f

# Stop all services
stop:
	docker compose down

# Remove all volumes (full reset)
clean: stop
	docker compose down -v
	@echo "All volumes removed."

# Run the test suite
test:
	uv run pytest tests/ -q

# Provision an agent token (requires LOGIOS_URL and SECRET_KEY env vars)
# Usage: make provision EMAIL=you@example.com PASSWORD=your-password
provision:
	@if [ -z "$(EMAIL)" ] || [ -z "$(PASSWORD)" ]; then \
		echo "Usage: make provision EMAIL=you@example.com PASSWORD=your-password"; \
		exit 1; \
	fi
	python scripts/provision.py --email "$(EMAIL)" --password "$(PASSWORD)"
