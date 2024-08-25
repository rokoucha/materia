BUTANE = podman run -i --rm --volume .:/butane -w /butane quay.io/coreos/butane:release --files-dir /butane --pretty --strict
GZIP = gzip -c9
BASE64 = base64 -w0
YQ_MERGE = yq eval-all '. as $$item ireduce ({}; . *+ $$item )'

BASE_DIR = ./ignition/

CONTROLLERS = boron
WORKERS = carbon

BASE_CONFIG = _base.bu
CONTROLLER_BASE_CONFIG = _controller.bu
WORKER_BASE_CONFIG = _worker.bu

TARGET = .b64

_CONTROLLER_FILES = $(addprefix $(BASE_DIR), $(CONTROLLERS:=.controller$(TARGET)))
_WORKER_FILES = $(addprefix $(BASE_DIR), $(WORKERS:=.worker$(TARGET)))
_BASE_CONFIG = $(addprefix $(BASE_DIR), $(BASE_CONFIG))
_CONTROLLER_BASE_CONFIG = $(addprefix $(BASE_DIR), $(CONTROLLER_BASE_CONFIG))
_WORKER_BASE_CONFIG = $(addprefix $(BASE_DIR), $(WORKER_BASE_CONFIG))

.PHONY: all clean controller worker
.SUFFIXES: .b64 .ign .bu

all: controller worker

clean:
	rm -f $(_CONTROLLER_FILES) $(_WORKER_FILES)

controller: $(_CONTROLLER_FILES)

worker: $(_WORKER_FILES)

.ign.b64:
	$(GZIP) $< | $(BASE64) > $@

.bu.ign:
	$(BUTANE) $< > $@

%.controller.bu: %.bu $(_BASE_CONFIG) $(_CONTROLLER_BASE_CONFIG)
	$(YQ_MERGE) $(_BASE_CONFIG) $(_CONTROLLER_BASE_CONFIG) $< > $@

%.worker.bu: %.bu $(_BASE_CONFIG) $(_WORKER_BASE_CONFIG)
	$(YQ_MERGE) $(_BASE_CONFIG) $(_WORKER_BASE_CONFIG) $< > $@
