#!/bin/sh
ps -ef | grep celery | grep -v grep | awk '{print $2}' | xargs -I{} kill -9 {}
