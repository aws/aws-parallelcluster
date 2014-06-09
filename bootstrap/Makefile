SHELL = /bin/sh
PREFIX ?= /opt/cfncluster

install:
	install -d -m 755 $(DESTDIR)
	install -d -m 755 $(DESTDIR)/scripts
	install -d -m 755 $(DESTDIR)/templates
	cp -r src/scripts/* $(DESTDIR)/scripts
	cp -r src/templates/* $(DESTDIR)/templates