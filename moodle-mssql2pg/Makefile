# Makefile cho tool moodle-mssql2pg (phat trien / kiem thu).
# Quy trinh migration day du nam o Makefile thu muc cha.

IMAGE ?= moodle-mssql2pg:local

.DEFAULT_GOAL := help
.PHONY: help build ensure-image test test-local install clean

help: ## Hien thi danh sach lenh
	@echo "moodle-mssql2pg — tool chuyen Moodle tu SQL Server sang PostgreSQL"
	@echo ""
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-11s\033[0m %s\n",$$1,$$2}'

build: ## Build image (Debian bookworm + pgloader + Python 3.11 + FreeTDS UTF-8)
	docker build -t $(IMAGE) .

ensure-image:
	@docker image inspect $(IMAGE) >/dev/null 2>&1 || $(MAKE) --no-print-directory build

test: ensure-image ## Chay test suite trong container (khong can cai gi tren may)
	@docker run --rm -v $(CURDIR):/w -w /w -e PYTHONDONTWRITEBYTECODE=1 \
	  --entrypoint bash $(IMAGE) -c \
	  'pip install -q --break-system-packages pytest >/dev/null 2>&1; \
	   PYTHONPATH=src python3 -m pytest tests/ -q -p no:cacheprovider'

test-local: ## Chay test suite bang Python tren may (can: pip install -r requirements-dev.txt)
	PYTHONPATH=src python3 -m pytest tests/ -q

install: ## Cai tool vao may o che do phat trien
	pip install -e ".[drivers]"

clean: ## Xoa __pycache__, .pytest_cache, *.egg-info
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .pytest_cache src/*.egg-info *.egg-info
	@echo "Da don artifact Python."
