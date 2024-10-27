LOCAL_REPO=/home/bur8787/dev/furby-talks
SERVICE_NAME=furby-talks.service
SERVICE_FILE=/etc/systemd/system/$(SERVICE_NAME)
ENV_FILE=/etc/furby_talks_env_vars
VENV_PATH=$(LOCAL_REPO)/.venv
PYTHON_SCRIPT=$(LOCAL_REPO)/handle.py
PYTHON_EXEC=$(VENV_PATH)/bin/python

ENV_SH=./env.sh

.PHONY: install
install: create_env_file create_service_file enable_service

# env.shの内容をそのままENV_FILEにコピー
.PHONY: create_env_file
create_env_file:
	@echo "Copying env.sh to environment file for systemd..."
	sudo cp $(ENV_SH) $(ENV_FILE)

# systemdサービスファイルの作成
.PHONY: create_service_file
create_service_file:
	@echo "Creating systemd service file..."
	echo "[Unit]" | sudo tee $(SERVICE_FILE)
	echo "Description=Furby Talks Program" | sudo tee -a $(SERVICE_FILE)
	echo "After=network.target" | sudo tee -a $(SERVICE_FILE)
	echo "[Service]" | sudo tee -a $(SERVICE_FILE)
	echo "EnvironmentFile=$(ENV_FILE)" | sudo tee -a $(SERVICE_FILE)
	echo "ExecStart=$(PYTHON_EXEC) $(PYTHON_SCRIPT)" | sudo tee -a $(SERVICE_FILE)
	echo "WorkingDirectory=/home/pi/dev/furby-talks" | sudo tee -a $(SERVICE_FILE)
	echo "StandardOutput=inherit" | sudo tee -a $(SERVICE_FILE)
	echo "StandardError=inherit" | sudo tee -a $(SERVICE_FILE)
	echo "Restart=always" | sudo tee -a $(SERVICE_FILE)
	echo "User=pi" | sudo tee -a $(SERVICE_FILE)
	echo "[Install]" | sudo tee -a $(SERVICE_FILE)
	echo "WantedBy=multi-user.target" | sudo tee -a $(SERVICE_FILE)

# systemdサービスの有効化と開始
.PHONY: enable_service
enable_service:
	sudo systemctl daemon-reload
	sudo systemctl enable $(SERVICE_NAME)
	sudo systemctl start $(SERVICE_NAME)

# クリーンアップ
.PHONY: clean
clean:
	@echo "Cleaning up..."
	sudo systemctl stop $(SERVICE_NAME) || true
	sudo systemctl disable $(SERVICE_NAME) || true
	sudo rm -f $(SERVICE_FILE) $(ENV_FILE)
	sudo systemctl daemon-reload
