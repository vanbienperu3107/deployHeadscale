# Tiện ích quản lý Headscale deployment.
# Dùng: make up | make logs | make user NAME=alice | make authkey NAME=alice

HS = docker exec headscale headscale

.PHONY: up down restart logs pull health nodes user authkey backup

up:            ## Khởi động stack
	docker compose up -d

down:          ## Dừng stack
	docker compose down

restart:       ## Restart stack
	docker compose restart

logs:          ## Theo dõi log headscale
	docker logs -f headscale

pull:          ## Kéo image mới nhất
	docker compose pull

health:        ## Kiểm tra health endpoint (cần sửa domain)
	@curl -fsS https://hs.yourdomain.com/health || echo "chưa sẵn sàng"

nodes:         ## Liệt kê nodes
	$(HS) nodes list

user:          ## Tạo user: make user NAME=alice
	$(HS) users create $(NAME)

authkey:       ## Tạo pre-auth key (reusable, 24h): make authkey NAME=alice
	$(HS) preauthkeys create --user $(NAME) --reusable --expiration 24h

backup:        ## Backup database
	@mkdir -p backup
	docker cp headscale:/var/lib/headscale/db.sqlite backup/headscale-$$(date +%F).sqlite
	@echo "Đã backup vào backup/"
