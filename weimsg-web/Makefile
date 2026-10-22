SHELL := /bin/bash
UV ?= uv
COMPOSE ?= docker compose
WEB_PORT ?= 8080
HOST_API ?= http://127.0.0.1:8769
DATA_DIR ?= $(CURDIR)/web-data
WEB_UI_URL ?= http://127.0.0.1:$(WEB_PORT)
ELECTRON_OUT ?= $(HOME)/Library/Application Support/WeMsgPilot/dist
WECHAT_FILES_HOST_DIR ?= $(HOME)/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files
export WECHAT_FILES_HOST_DIR

.PHONY: help install sync sync-once test build up down restart logs ps \
	electron-install electron-dev electron-build web-data

help:
	@echo "WeMsg Web"
	@echo "  make install          安装 Python 依赖（uv sync）"
	@echo "  make sync             宿主机每 3s 生成 web-data 快照（前台）"
	@echo "  make sync-once        只生成一次快照"
	@echo "  make test             运行单元测试"
	@echo "  make build            构建 Docker 镜像"
	@echo "  make up               启动 Docker 容器（http://127.0.0.1:$(WEB_PORT)）"
	@echo "  make down             停止容器"
	@echo "  make restart          重启容器"
	@echo "  make logs             查看容器日志"
	@echo "  make electron-install 安装 Electron 依赖"
	@echo "  make electron-dev     本地 Electron 加载 $(WEB_UI_URL)"
	@echo "  make electron-build   打包 Electron（WEB_UI_URL=线上地址）"

install:
	$(UV) sync

sync:
	HOST_API_URL=$(HOST_API) DATA_DIR=$(DATA_DIR) \
		$(UV) run python sync_agent.py --interval 3

sync-once:
	HOST_API_URL=$(HOST_API) DATA_DIR=$(DATA_DIR) \
		$(UV) run python sync_agent.py --once

test:
	$(UV) run pytest

web-data:
	mkdir -p "$(DATA_DIR)" "$(CURDIR)/web-outbox"

build: web-data
	$(COMPOSE) build

up: web-data
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart: down up

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

electron-install:
	cd electron && npm install

electron-dev:
	cd electron && WEB_UI_URL=$(WEB_UI_URL) npm start

electron-build:
	cd electron && printf '{"webUiUrl":"%s"}\n' "$(WEB_UI_URL)" > config.json && \
		mkdir -p "$(ELECTRON_OUT)" && \
		WEB_UI_URL=$(WEB_UI_URL) CSC_IDENTITY_AUTO_DISCOVERY=false \
		./node_modules/.bin/electron-builder \
		--config.directories.output="$(ELECTRON_OUT)"
