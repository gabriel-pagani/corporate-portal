build-system:
	@docker compose -f deploy/docker-compose.yml up -d --build

start-system:
	@docker compose -f deploy/docker-compose.yml up -d

stop-system:
	@docker compose -f deploy/docker-compose.yml down

restart-system:
	@docker compose -f deploy/docker-compose.yml down && docker compose -f deploy/docker-compose.yml up -d

reset-system:
	@docker compose -f deploy/docker-compose.yml down -v && docker compose -f deploy/docker-compose.yml up -d --build

clean-system:
	@docker compose -f deploy/docker-compose.yml down -v && docker system prune -a --volumes --force

create-superuser:
	@docker compose -f deploy/docker-compose.yml exec app python manage.py createsuperuser

container-terminal:
	@docker compose -f deploy/docker-compose.yml exec $(container) sh

containers-logs:
	@docker compose -f deploy/docker-compose.yml logs -f $(container)

django-shell:
	@docker compose -f deploy/docker-compose.yml exec app python manage.py shell
