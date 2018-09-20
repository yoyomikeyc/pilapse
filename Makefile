.DEFAULT_GOAL := all

IMAGE_PATH=./media/images/
VIDEO_PATH=./media/videos/
GIF_PATH=./media/gifs/

CP=cp
RM=\rm -rf
PIP=pip3
PYTHON=python3

PYLINT_ARGS= --disable=undefined-variable
#--errors-only 
PYLINT=pylint $(PYLINT_ARGS)

influx:
	sudo apt-get install influxdb

start:
	sudo systemctl start  pilapse-cap.service
	sudo systemctl start  pilapse-api.service

stop:
	sudo systemctl stop pilapse-cap.service
	sudo systemctl stop pilapse-api.service

install:
	sudo $(CP) ./systemd/*.service /etc/systemd/system/
	sudo systemctl enable pilapse-cap.service
	sudo systemctl enable pilapse-api.service

uninstall: stop
	sudo systemctl disable pilapse-cap.service
	sudo systemctl disable pilapse-api.service

api:
	$(PYTHON) pilapse-api.py
cap:
	$(PYTHON) pilapse-cap.py

all: capture


pip:
	$(PIP) install -r requirements.txt

lint:
	$(PYLINT) *.py
clean:
	find . -name '*~' -type f -delete
	$(RM) __pycache__ pilapse-system.log

reset:
	$(RM) $(IMAGE_PATH)/*
	$(RM) $(VIDEO_PATH)/*
	$(RM) $(GIF_PATH)/*
	$(RM) pilapse.db pilapse-sqlite.db
