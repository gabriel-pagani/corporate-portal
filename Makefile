build-system:
	@cd deploy/ && docker compose up -d --build

start-system:
	@cd deploy/ && docker compose up -d

stop-system:
	@cd deploy/ && docker compose down

restart-system:
	@cd deploy/ && docker compose down && docker compose up -d

reset-system:
	@cd deploy/ && docker compose down -v && sudo rm -rf ../database/ ../deploy/certbot/ && docker compose up -d --build

clean-system:
	@cd deploy/ && docker compose down -v && docker system prune -a --volumes --force && cd .. && sudo rm -rf database/ deploy/certbot/

create-superuser:
	@cd deploy/ && \
	docker compose exec app python manage.py shell -c "from app.models import User; User.objects.filter(username='admin').exists() or User.objects.create_superuser(username='admin', password='1234')"

container-terminal:
	@cd deploy/ && docker compose exec $(container) sh

containers-logs:
	@cd deploy/ && docker compose logs -f $(container)

django-shell:
	@cd deploy/ && docker compose exec app python manage.py shell
