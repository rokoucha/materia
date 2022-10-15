BUTANE = podman run -i --rm --volume .:/butane quay.io/coreos/butane:release --files-dir /butane --pretty --strict
GZIP = gzip -c9
BASE64 = base64 -w0
YQ_MERGE = yq eval-all '. as $$item ireduce ({}; . *+ $$item )'

CONTROLLERS = gracie
WORKERS = ginny

BASE_CONFIG = base.bu
CONTROLLER_BASE_CONFIG = controller.bu
WORKER_BASE_CONFIG = controller.bu

CONTROLLER_FILES = $(addprefix ./nodes/,$(CONTROLLERS:=.controller.b64))
WORKER_FILES = $(addprefix ./nodes/,$(WORKERS:=.worker.b64))

.PHONY: all clean controller worker
.SUFFIXES: .b64 .ign .bu

all: controller worker

clean:
	rm -f $(CONTROLLER_FILES) $(WORKER_FILES)

controller: $(CONTROLLER_FILES)

worker: $(WORKER_FILES)

.ign.b64:
	$(GZIP) $< | $(BASE64) > $@

.bu.ign:
	$(BUTANE) /butane/$< > $@

%.controller.bu: %.bu $(BASE_CONFIG) $(CONTROLLER_BASE_CONFIG)
	$(YQ_MERGE) $(BASE_CONFIG) $(CONTROLLER_BASE_CONFIG) $< > $@

%.worker.bu: %.bu $(BASE_CONFIG) $(WORKER_BASE_CONFIG)
	$(YQ_MERGE) $(BASE_CONFIG) $(WORKER_BASE_CONFIG) $< > $@
