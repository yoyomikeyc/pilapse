.DEFAULT_GOAL := all

IMAGE_PATH=./media/images/
VIDEO_PATH=./media/videos/
GIF_PATH=./media/gifs/

CP=cp
RM=\rm -rf
PIP=pip3
PYTHON=python3
CURL=curl

PYLINT_ARGS= --disable=C,R,no-member
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

enc:
	$(PYTHON) encoder-api.py 

all: capture


pip:
	$(PIP) install -r requirements.txt

lint:
	$(PYLINT) *.py

PILAPSE_API_HOST=carpi.local
PILAPSE_API_PORT=5000
ENCODER_API_HOST=carpi.local
ENCODER_API_PORT=5001
test_encoder_api:
	$(CURL) -X GET $(ENCODER_API_HOST):$(ENCODER_API_PORT)/healthcheck
	$(CURL) -X GET $(ENCODER_API_HOST):$(ENCODER_API_PORT)/encode
	$(CURL) -H "Content-Type: application/json" -d '{"starting_image":863, "num":-1, "video_fn":"timelapse.mp4", "preset":"medium", "profile":"baseline", "frame_rate":25 }' -X POST $(ENCODER_API_HOST):$(ENCODER_API_PORT)/encode
	$(CURL) -X GET $(ENCODER_API_HOST):$(ENCODER_API_PORT)/encode

test: test_encoder_api


clean:
	find . -name '*~' -type f -delete
	$(RM) __pycache__ pilapse-system.log

reset:
	$(RM) $(IMAGE_PATH)/*
	$(RM) $(VIDEO_PATH)/*
	$(RM) $(GIF_PATH)/*
	$(RM) pilapse.db pilapse-sqlite.db
