#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动入口：OpenRF Studio 射频工作台"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.ui.app import main

if __name__ == "__main__":
    main()