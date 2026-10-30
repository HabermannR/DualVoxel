"""The tests as CI runs them on Linux: unittest's discover, then out without Python's shutdown.

    .venv/bin/python tests/ci_run.py

Under Xvfb the interpreter sometimes hung in native code after every test had passed (Qt and VTK tearing
down the windows the tests leave), until the job's time ran out; os._exit leaves before that teardown.
"""
import os
import sys
import unittest

result = unittest.main(module=None, argv=[sys.argv[0], "discover", "-s", os.path.dirname(os.path.abspath(__file__))],
                       exit=False).result
sys.stdout.flush()
sys.stderr.flush()
os._exit(0 if result.wasSuccessful() else 1)
