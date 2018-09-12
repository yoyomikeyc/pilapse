.DEFAULT_GOAL := all

IMAGE_PATH=./images/
VIDEO_PATH=./videos/
GIF_PATH=./gifs/

CP=cp
RM=\rm -rf
PIP=pip3
PYTHON=python3

PYLINT_ARGS= --disable=undefined-variable
#--errors-only 
PYLINT=pylint $(PYLINT_ARGS)

influx:
	sudo apt-get install influxdb

install:
	sudo $(CP) *.service /etc/systemd/system/
	sudo systemctl start  pilapse-cap.service
	sudo systemctl start  pilapse-api.service
	sudo systemctl enable pilapse-cap.service
	sudo systemctl enable pilapse-api.service

uninstall:
	sudo systemctl stop pilapse-cap.service
	sudo systemctl stop pilapse-api.service
	sudo systemctl disable pilapse-cap.service
	sudo systemctl disable pilapse-api.service

api:
	$(PYTHON) pilapse-api.py
capture:
	$(PYTHON) pilapse-cap.py

all: capture


pip:
	$(PIP) install -r requirements.txt

lint:
	$(PYLINT) *.py
clean:
	$(RM) *.gif *~ series-* __pycache__ pilapse-system.log

reset:
	$(RM) $(IMAGE_PATH)/*
	$(RM) $(VIDEO_PATH)/*
	$(RM) $(GIF_PATH)/*
	$(RM) pilapse.db
