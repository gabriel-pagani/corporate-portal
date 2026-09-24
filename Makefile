MAKEFLAGS += --no-print-directory

COMPOSE = docker compose -f deploy/docker-compose.yml

build-system:
	@$(COMPOSE) up -d --build

start-system:
	@$(COMPOSE) up -d

stop-system:
	@$(COMPOSE) down

restart-system:
	@$(COMPOSE) down && $(COMPOSE) up -d

backup-database:
	@mkdir -p -m 700 backups
	@umask 077; FILE="backups/portal-$$(date +%Y%m%d-%H%M%S).sql"; \
	$(COMPOSE) exec -T postgres sh -c 'pg_dump -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" --no-owner --no-privileges' > "$$FILE.tmp" \
		&& mv "$$FILE.tmp" "$$FILE" || { rm -f "$$FILE.tmp"; exit 1; }

restore-database:
	@test -n "$(file)" || { echo "use: make restore-database file=backups/portal-....sql" >&2; exit 1; }
	@$(COMPOSE) exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < "$(file)"

create-superuser:
	@$(COMPOSE) exec django python manage.py createsuperuser
	@$(COMPOSE) exec -T django python manage.py shell < scripts/create_totp.py

create-totp:
	@$(COMPOSE) exec -T -e TOTP_USER="$(user)" django python manage.py shell < scripts/create_totp.py

make-migrations:
	@$(COMPOSE) run --rm --no-deps -v "$(PWD)/app:/app/app" django python manage.py makemigrations $(app)

run-tests:
	@$(COMPOSE) run --rm tests python -m pytest -vv $(args)

django-shell:
	@$(COMPOSE) exec django python manage.py shell

container-terminal:
	@$(COMPOSE) exec $(container) sh

containers-logs:
	@$(COMPOSE) logs -f $(container)
