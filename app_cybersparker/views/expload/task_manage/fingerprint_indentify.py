#!/usr/bin/env python
# -*- coding: utf-8 -*-
import traceback
from app_cybersparker import models
from app_cybersparker.services.fingerprint_matcher import check_rule, match_condition


class Identifyner():
    def __init__(self):
        self.fingerprints = list(
            models.fingerPrint.objects.values_list('product', 'condition')
        )

    def identify(self, header, body, title, context=None):
        fingers = None
        try:
            fingers = self.handle(header, body, title, context=context)
        except Exception:
            traceback.print_exc()
            pass
        finally:
            return fingers

    def handle(self, header, body, title, context=None):
        finger = []
        for name, key in self.fingerprints:
            if key is None:
                continue
            if match_condition(key, header, body, title, context=context,
                               rule_fn=check_rule):
                finger.append(name)
        return finger