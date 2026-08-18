# Makefile — chuyen database Moodle LMS_PTSC tu SQL Server 2019 sang PostgreSQL 18.
# Chay `make` (hoac `make help`) de xem danh sach lenh.

CFG          ?= config.yml
PG_CONTAINER ?= ptsc-pg18
COMPOSE      ?= docker compose
FORCE        ?=

# Doc thong tin dich tu config.yml de khong lech voi cau hinh that.
# $(1)=ten truong, $(2)=ten khoi. Co gia tri du phong khi chua co config.yml.
cfg = $(shell awk '/^$(2):/{f=1;next} /^[a-zA-Z]/{f=0} f&&/^[[:space:]]+$(1):/{print $$2;exit}' $(CFG) 2>/dev/null)
PG_DB   = $(or $(call cfg,db,target_pgsql),lms_ptsc)
PG_USER = $(or $(call cfg,user,target_pgsql),moodle)

.DEFAULT_GOAL := help
.PHONY: help config check-config build up down ps test-conn dry-run migrate \
        verify report errors psql test clean reset destroy all

help: ## Hien thi danh sach lenh
	@echo "LMS_PTSC: SQL Server 2019 -> PostgreSQL 18"
	@echo "Dich: container $(PG_CONTAINER), database $(PG_DB), user $(PG_USER)"
	@echo ""
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n",$$1,$$2}'
	@echo ""
	@echo "Lan dau chay:  make config  ->  sua $(CFG)  ->  make all"

config: ## Tao config.yml tu config.example.yml neu chua co
	@if [ -f $(CFG) ]; then \
	  echo "$(CFG) da co — khong ghi de."; \
	else \
	  cp config.example.yml $(CFG); \
	  echo "Da tao $(CFG). Mo ra dien host/user/password that."; \
	  echo "Mat khau dien NGUYEN BAN, khong percent-encode, khong chua '@' hay '/'."; \
	fi

check-config:
	@[ -f $(CFG) ] || { echo "Thieu $(CFG). Chay 'make config' roi dien thong tin."; exit 1; }

build: ## Build image migrator
	$(COMPOSE) build migrator

up: ## Bat container PostgreSQL 18 va cho den khi san sang
	@$(COMPOSE) up -d db
	@printf "Cho PostgreSQL san sang"
	@for i in $$(seq 1 60); do \
	  if [ "$$(docker inspect -f '{{.State.Health.Status}}' $(PG_CONTAINER) 2>/dev/null)" = healthy ]; then \
	    echo " — san sang."; exit 0; \
	  fi; \
	  printf "."; sleep 2; \
	done; \
	echo " — QUA THOI GIAN CHO. Xem log: docker logs $(PG_CONTAINER)"; exit 1

down: ## Dung container (du lieu van con trong volume)
	$(COMPOSE) down

ps: ## Trang thai container
	@$(COMPOSE) ps

test-conn: check-config up ## Kiem tra ket noi toi ca MSSQL va PostgreSQL
	$(COMPOSE) run --rm migrator test

dry-run: check-config up ## Sinh file .load de xem truoc, khong nap du lieu
	$(COMPOSE) run --rm migrator run --dry-run

migrate: check-config up ## Chay migration day du (discover -> migrate -> fix -> verify)
	@$(COMPOSE) run --rm migrator run; rc=$$?; \
	if [ $$rc -ne 0 ]; then \
	  echo ""; \
	  echo "Tool bao FAIL (exit $$rc). Luu y: buoc verify lay so dong nguon tu"; \
	  echo "sys.partitions (uoc luong, chup luc bat dau). Neu database nguon dang"; \
	  echo "chay that thi cac bang ghi lien tuc luon bi bao mismatch du ban sao dung."; \
	  echo "Chay 'make verify' de dem chinh xac ca hai phia truoc khi ket luan."; \
	fi; \
	exit $$rc

verify: check-config ## Kiem chung doc lap: dem chinh xac COUNT(*) ca hai phia
	@bash verify_deep.sh $(CFG)

report: ## Tom tat output/report.md
	@[ -f output/report.md ] || { echo "Chua co output/report.md — chay 'make migrate' truoc."; exit 1; }
	@echo "Trang thai tung bang:"
	@awk -F'|' 'NR>6&&NF>=5{gsub(/^ +| +$$/,"",$$5); if($$5!="")c[$$5]++} \
	  END{for(k in c) printf "  %-18s %d\n",k,c[k]}' output/report.md
	@echo ""
	@echo "Cac bang bi bao lech (dung 'make verify' de dem chinh xac):"
	@awk -F'|' 'NR>6&&NF>=5{gsub(/^ +| +$$/,"",$$5);gsub(/^ +| +$$/,"",$$2); \
	  gsub(/ /,"",$$3);gsub(/ /,"",$$4); if($$5=="mismatch"||$$5=="missing") \
	  printf "  %-42s nguon=%-9s dich=%-9s %s\n",$$2,$$3,$$4,$$5}' output/report.md \
	  || echo "  (khong co)"

errors: ## Tim loi trong log pgloader
	@if ls output/*.load.log >/dev/null 2>&1; then \
	  if grep -lE "ERROR|KABOOM" output/*.load.log 2>/dev/null; then \
	    echo "^^^ cac file tren co loi. Xem chi tiet: less <ten-file>"; \
	  else \
	    echo "Khong co loi trong $$(ls output/*.load.log | wc -l) log pgloader."; \
	  fi; \
	else echo "Chua co log — chay 'make migrate' truoc."; fi

psql: ## Mo psql vao database dich
	docker exec -it $(PG_CONTAINER) psql -U $(PG_USER) -d $(PG_DB)

test: ## Chay test suite cua tool
	@$(MAKE) --no-print-directory -C moodle-mssql2pg test

clean: ## Xoa output/ (bat buoc truoc khi chay lai tu dau)
	@rm -f output/*.load output/*.log output/migrate_state.json \
	       output/discovered.json output/report.md
	@echo "Da xoa output/. Luu y: phai xoa migrate_state.json thi tool moi chay lai tu dau."

reset: ## Xoa database dich + output/ de chay lai tu dau  [HOI XAC NHAN]
	@if [ "$(FORCE)" != "1" ]; then \
	  printf "Se XOA toan bo database '$(PG_DB)' va thu muc output/. Go 'yes' de tiep tuc: "; \
	  read ans; [ "$$ans" = "yes" ] || { echo "Da huy — khong co gi bi xoa."; exit 1; }; \
	fi; \
	docker exec $(PG_CONTAINER) psql -U $(PG_USER) -d postgres -q \
	  -c "DROP DATABASE IF EXISTS $(PG_DB) WITH (FORCE);" \
	  -c "CREATE DATABASE $(PG_DB) OWNER $(PG_USER);"
	@$(MAKE) --no-print-directory clean
	@echo "Da reset. Chay 'make migrate' de bat dau lai."

destroy: ## Xoa container VA volume — MAT TOAN BO DU LIEU  [HOI XAC NHAN]
	@if [ "$(FORCE)" != "1" ]; then \
	  printf "Se xoa container VA volume. Toan bo du lieu da migrate se MAT. Go 'DESTROY' de tiep tuc: "; \
	  read ans; [ "$$ans" = "DESTROY" ] || { echo "Da huy — khong co gi bi xoa."; exit 1; }; \
	fi; \
	$(COMPOSE) down -v

all: build test-conn migrate verify ## Chay tron bo: build -> test-conn -> migrate -> verify
